"""Opt-in physical GET budget: offline transport and atomic control-plane fixtures."""

from __future__ import annotations

import asyncio
import copy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from fastapi import FastAPI
from pydantic import ValidationError
from starlette.requests import Request

from zeler_gateway.config import Settings
from zeler_gateway.proxy import router as proxy
from zeler_gateway.proxy.retry import send_with_retry
from zeler_platform_core.auth.jwt import mint_module_jwt, set_kms_client
from zeler_platform_core.runtime.manifest import validate_manifest


def _settings() -> Settings:
    kwargs: dict[str, Any] = {"_env_file": None}
    return Settings(**kwargs)


class FakeJwtKmsClient:
    """Local signing fixture, never calls KMS or transfers credentials."""

    def __init__(self) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())

    def asymmetric_sign(self, request: dict[str, Any]) -> Any:
        signature = self.key.sign(
            request["digest"]["sha256"], ec.ECDSA(utils.Prehashed(hashes.SHA256()))
        )
        return SimpleNamespace(signature=signature)

    def get_public_key(self, request: dict[str, str]) -> Any:
        pem = self.key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return SimpleNamespace(pem=pem.decode("ascii"))


def recording_transport(calls: list[str], status: int = 200) -> httpx.MockTransport:
    def record(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(status)

    return httpx.MockTransport(record)


TEST_ACCESS = "synthetic-offline-only"
ENV = "ZELERDATA_HISTORY_PILOT_GET_BUDGET_SELLERS"


def test_pilot_selector_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV, raising=False)
    assert _settings().history_pilot_get_budget_sellers is None


def test_pilot_selector_explicit_canonical_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV, "82453304, 123456789")
    assert _settings().history_pilot_get_budget_sellers == frozenset({"82453304", "123456789"})


@pytest.mark.parametrize(
    "value", ["", " ", "82453304,", "082453304", "0", "-1", "8x", "８２", "1" * 21, "[82453304]"]
)
def test_malformed_pilot_selector_fails_settings_startup(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(ENV, value)
    with pytest.raises(ValidationError):
        _settings()


@pytest.mark.asyncio
async def test_retry_hook_is_immediately_before_each_physical_send() -> None:
    calls: list[str] = []
    responses = iter([502, 200])

    async def before_attempt() -> None:
        calls.append("cas")

    def transport(request: httpx.Request) -> httpx.Response:
        calls.append("send")
        return httpx.Response(next(responses))

    async def sleep(delay: float) -> None:
        calls.append("sleep")

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        await send_with_retry(
            client,
            client.build_request("GET", "https://provider.test/orders/1"),
            sleep_fn=sleep,
            before_attempt=before_attempt,
        )
    assert calls == ["cas", "send", "sleep", "cas", "send"]


@pytest.mark.asyncio
async def test_retry_hook_denial_is_not_retried_or_transported() -> None:
    calls: list[str] = []

    async def denied() -> None:
        calls.append("denied")
        raise RuntimeError("controlled wait")

    def transport(request: httpx.Request) -> httpx.Response:
        calls.append("send")
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(RuntimeError, match="controlled wait"):
            await send_with_retry(
                client,
                client.build_request("GET", "https://provider.test/orders/1"),
                before_attempt=denied,
            )
    assert calls == ["denied"]


# A small atomic Mongo-shape double. Real default-BSON Mongo verification belongs
# to the root's separately owned isolated target; this fixture cannot open sockets.


NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)
SELLER = "82453304"
EXECUTION = "a" * 32


def plan(**changes: Any) -> dict[str, Any]:
    return {
        "_id": SELLER,
        "seller_id": SELLER,
        "policy_version": "history-on-link-v1",
        "authority": {"kind": "account_link_policy"},
        "state": "active",
        "eligible": True,
        "sources": ["orders", "questions", "shipments", "messages", "claims_returns"],
        "execution_id": EXECUTION,
        "execution_until": (NOW + timedelta(minutes=90)).replace(tzinfo=None),
        "execution_utc_day": NOW.date().isoformat(),
        "execution_attempt_limit": 2500,
        "execution_consumed": 0,
        "execution_sent": 0,
        **changes,
    }


def lookup(row: dict[str, Any], key: str) -> Any:
    value: Any = row
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def expression(row: dict[str, Any], value: Any) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        return lookup(row, value[1:])
    if not isinstance(value, dict):
        return value
    if "$ifNull" in value:
        first, second = value["$ifNull"]
        evaluated = expression(row, first)
        return second if evaluated is None else evaluated
    if "$and" in value:
        return all(expression(row, part) for part in value["$and"])
    for op in ("$lt", "$lte"):
        if op in value:
            first, second = [expression(row, part) for part in value[op]]
            return first < second if op == "$lt" else first <= second
    raise AssertionError(f"unsupported expression {value}")


def matches(row: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        if key == "$and":
            if not all(matches(row, part) for part in expected):
                return False
        elif key == "$or":
            if not any(matches(row, part) for part in expected):
                return False
        elif key == "$expr":
            if not expression(row, expected):
                return False
        else:
            actual = lookup(row, key)
            if isinstance(expected, dict):
                for op, bound in expected.items():
                    if op == "$exists" and (actual is not None) != bound:
                        return False
                    if op == "$type" and type(actual) is not int:
                        return False
                    if op == "$gte" and (actual is None or actual < bound):
                        return False
                    if op == "$gt":
                        normalized = (
                            actual.replace(tzinfo=UTC)
                            if isinstance(actual, datetime) and actual.tzinfo is None
                            else actual
                        )
                        if normalized is None or normalized <= bound:
                            return False
            elif isinstance(actual, list):
                if expected not in actual:
                    return False
            elif actual != expected:
                return False
    return True


class Plans:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = copy.deepcopy(row)
        self.lock = asyncio.Lock()
        self.updates: list[dict[str, Any]] = []
        self.before_cas: Any = None

    async def find_one(self, query: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        return (
            copy.deepcopy(self.row) if self.row is not None and matches(self.row, query) else None
        )

    async def find_one_and_update(
        self, query: dict[str, Any], update: dict[str, Any], **kwargs: Any
    ) -> Any:
        await asyncio.sleep(0)
        async with self.lock:
            if self.before_cas:
                self.before_cas(self.row)
            if self.row is None or not matches(self.row, query):
                return None
            assert set(update) == {"$inc"}
            for key, count in update["$inc"].items():
                parent = self.row
                parts = key.split(".")
                for part in parts[:-1]:
                    parent = parent.setdefault(part, {})
                parent[parts[-1]] = parent.get(parts[-1], 0) + count
            self.updates.append(copy.deepcopy(update))
            return copy.deepcopy(self.row)


def request(
    plans: Plans,
    *,
    module: str = "sheets",
    seller: str = SELLER,
    method: str = "GET",
    headers: dict[str, str] | None = None,
) -> Request:
    req = Request(
        {
            "type": "http",
            "method": method,
            "path": "/proxy/meli/orders/1",
            "query_string": b"",
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
            "app": SimpleNamespace(
                state=SimpleNamespace(
                    mongo_db={"sheets_history_backfill_plans": plans}, proxy_wait_now=lambda: NOW
                )
            ),
        }
    )
    req.state.history_module_id = module
    req.state.history_seller_id = seller
    return req


@pytest.mark.asyncio
async def test_normal_and_historical_shared_credit_without_double_charge() -> None:
    credit = {EXECUTION: {"orders": {"initial": 1}}}
    plans = Plans(plan(execution_attempt_limit=2, execution_consumed=1, execution_charged=credit))
    normal = request(plans)
    await proxy._reserve_pilot_get_send(normal)
    historical = request(
        plans,
        headers={
            "X-Zeler-History-Trace": f"h1-{EXECUTION}:orders:initial",
            "X-Zeler-Proxy-Retry": "disabled",
        },
    )
    await proxy._reserve_history_send(historical, "orders/1")
    assert plans.row is not None
    assert plans.row["execution_consumed"] == 2 and plans.row["execution_sent"] == 2
    assert plans.row["execution_charged"] == credit
    assert plans.row["execution_sent_by_source"] == {EXECUTION: {"orders": {"initial": 1}}}
    assert plans.updates[0] == {"$inc": {"execution_consumed": 1, "execution_sent": 1}}


@pytest.mark.asyncio
async def test_concurrent_normal_requests_have_only_one_last_credit() -> None:
    plans = Plans(plan(execution_attempt_limit=1))
    results = await asyncio.gather(
        *(proxy._reserve_pilot_get_send(request(plans)) for _ in range(12)), return_exceptions=True
    )
    assert sum(result is None for result in results) == 1
    assert all(
        result is None or isinstance(result, proxy.PilotGetBudgetWaitError) for result in results
    )
    assert (
        plans.row is not None
        and plans.row["execution_consumed"] == 1
        and plans.row["execution_sent"] == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"state": "paused"},
        {"authority": {"kind": "other"}},
        {"policy_version": None},
        {"execution_id": None},
        {"execution_id": "invalid"},
        {"execution_until": NOW.replace(tzinfo=None)},
        {"execution_utc_day": "2026-10-04"},
        {"execution_attempt_limit": None},
        {"execution_attempt_limit": True},
        {"execution_consumed": -1},
        {"execution_consumed": True},
        {"eligible": False},
    ],
)
async def test_unprepared_paused_expired_or_invalid_plans_wait_without_charge(
    changes: dict[str, Any],
) -> None:
    plans = Plans(plan(**changes))
    with pytest.raises(proxy.PilotGetBudgetWaitError) as caught:
        await proxy._reserve_pilot_get_send(request(plans))
    assert caught.value.code == "pilot_execution_unavailable"
    assert plans.updates == []


@pytest.mark.asyncio
async def test_no_policy_plan_and_exhausted_are_distinct_controlled_waits() -> None:
    with pytest.raises(proxy.PilotGetBudgetWaitError) as unavailable:
        await proxy._reserve_pilot_get_send(request(Plans(None)))
    assert unavailable.value.code == "pilot_execution_unavailable"
    plans = Plans(plan(execution_attempt_limit=0))
    with pytest.raises(proxy.PilotGetBudgetWaitError) as exhausted:
        await proxy._reserve_pilot_get_send(request(plans))
    assert exhausted.value.code == "pilot_budget_exhausted" and plans.updates == []


@pytest.mark.asyncio
async def test_late_cas_execution_drift_prevents_send_and_counter_takeover() -> None:
    plans = Plans(plan())
    plans.before_cas = lambda row: row.update(execution_id="b" * 32)
    with pytest.raises(proxy.PilotGetBudgetWaitError):
        await proxy._reserve_pilot_get_send(request(plans))
    assert plans.updates == []


@pytest.mark.asyncio
async def test_deadline_after_cas_consumes_conservatively_without_send_marker() -> None:
    plans = Plans(plan(execution_until=(NOW + timedelta(seconds=1)).replace(tzinfo=None)))
    req = request(plans)
    times = iter((NOW, NOW + timedelta(seconds=2)))
    req.app.state.proxy_wait_now = lambda: next(times)
    with pytest.raises(proxy.PilotGetBudgetWaitError):
        await proxy._reserve_pilot_get_send(req)
    assert plans.row is not None and plans.row["execution_consumed"] == 1
    assert getattr(req.state, "pilot_upstream_attempts", 0) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "seller", "method", "selector", "charged"),
    [
        ("sheets", SELLER, "GET", None, False),
        ("sheets", "123456789", "GET", SELLER, False),
        ("repricer", SELLER, "GET", SELLER, False),
        ("sheets", SELLER, "POST", SELLER, False),
        ("sheets", SELLER, "GET", SELLER, True),
    ],
)
async def test_forward_opt_in_only_selected_authenticated_sheets_gets(
    monkeypatch: pytest.MonkeyPatch,
    module: str,
    seller: str,
    method: str,
    selector: str | None,
    charged: bool,
) -> None:
    if selector is None:
        monkeypatch.delenv(ENV, raising=False)
    else:
        monkeypatch.setenv(ENV, selector)
    plans = Plans(plan())
    req = request(plans, module=module, seller=seller, method=method)
    req._body = b""
    sent: list[str] = []
    req.app.state.proxy_http_client_factory = lambda: httpx.AsyncClient(
        transport=recording_transport(sent)
    )
    if charged:
        # Seller auth alone no longer permits global-only unallocated traffic.
        with pytest.raises(proxy.PilotGetBudgetWaitError):
            await proxy._forward_to_meli(
                request=req, full_path="items/MLA1", access_token=TEST_ACCESS
            )
        assert sent == [] and plans.updates == []
    else:
        response = await proxy._forward_to_meli(
            request=req, full_path="items/MLA1", access_token=TEST_ACCESS
        )
        assert response.status_code == 200 and sent == ["/items/MLA1"]
        assert plans.updates == []


@pytest.mark.asyncio
@pytest.mark.parametrize("disabled", [True, False])
async def test_selected_h1_is_not_charged_twice_and_invalid_trace_never_sends(
    monkeypatch: pytest.MonkeyPatch, disabled: bool
) -> None:
    monkeypatch.setenv(ENV, SELLER)
    credit = {EXECUTION: {"orders": {"initial": 1}}}
    plans = Plans(plan(execution_consumed=1, execution_attempt_limit=1, execution_charged=credit))
    req = request(
        plans,
        headers={
            "X-Zeler-History-Trace": f"h1-{EXECUTION}:orders:initial",
            **({"X-Zeler-Proxy-Retry": "disabled"} if disabled else {}),
        },
    )
    req._body = b""
    sends: list[str] = []
    req.app.state.proxy_http_client_factory = lambda: httpx.AsyncClient(
        transport=recording_transport(sends)
    )
    if disabled:
        await proxy._forward_to_meli(request=req, full_path="orders/1", access_token=TEST_ACCESS)
        assert sends == ["/orders/1"]
        assert (
            plans.row is not None
            and plans.row["execution_consumed"] == 1
            and plans.row["execution_sent"] == 1
        )
    else:
        with pytest.raises(proxy.PilotGetBudgetWaitError):
            await proxy._forward_to_meli(
                request=req, full_path="orders/1", access_token=TEST_ACCESS
            )
        assert sends == [] and plans.updates == []


@pytest.mark.asyncio
@pytest.mark.parametrize("during_backoff", ["paused", "expired", "day", "execution", "exhausted"])
async def test_global_cas_kernel_rechecks_policy_on_each_retry_after_backoff(
    monkeypatch: pytest.MonkeyPatch, during_backoff: str
) -> None:
    monkeypatch.setenv(ENV, SELLER)
    plans = Plans(plan(execution_attempt_limit=2))
    req = request(plans)
    req._body = b""
    sends: list[str] = []
    req.app.state.proxy_http_client_factory = lambda: httpx.AsyncClient(
        transport=recording_transport(sends, 502)
    )

    async def backoff(delay: float) -> None:
        assert plans.row is not None
        if during_backoff == "paused":
            plans.row["state"] = "paused"
        elif during_backoff == "expired":
            req.app.state.proxy_wait_now = lambda: NOW + timedelta(hours=2)
        elif during_backoff == "day":
            plans.row["execution_utc_day"] = "2026-10-04"
        elif during_backoff == "execution":
            plans.row["execution_id"] = "b" * 32
        else:
            plans.row["execution_consumed"] = 2

    req.app.state.proxy_retry_sleep = backoff
    # Low-level kernel regression, not permission for unallocated pilot traffic.
    async with req.app.state.proxy_http_client_factory() as client:
        with pytest.raises(proxy.PilotGetBudgetWaitError):
            await send_with_retry(
                client,
                httpx.Request("GET", "https://offline.test/orders/1"),
                before_attempt=lambda: proxy._reserve_pilot_get_send(req),
                sleep_fn=backoff,
            )
    assert sends == ["/orders/1"] and len(plans.updates) == 1


@pytest.mark.asyncio
async def test_global_cas_kernel_retries_and_transport_failures_remain_consumed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV, SELLER)
    plans = Plans(plan())
    req = request(plans)
    req._body = b""

    async def no_sleep(delay: float) -> None:
        pass

    req.app.state.proxy_retry_sleep = no_sleep

    def fail_transport(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=r)

    req.app.state.proxy_http_client_factory = lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(fail_transport)
    )
    # Keep conservative CAS/transport evidence without bypassing allocation gate.
    async with req.app.state.proxy_http_client_factory() as client:
        with pytest.raises(httpx.ConnectError):
            await send_with_retry(
                client,
                httpx.Request("GET", "https://offline.test/orders/1"),
                before_attempt=lambda: proxy._reserve_pilot_get_send(req),
                sleep_fn=no_sleep,
            )
    assert len(plans.updates) == 3
    assert (
        plans.row is not None
        and plans.row["execution_consumed"] == 3
        and plans.row["execution_sent"] == 3
    )


def test_provider_cannot_spoof_controlled_wait_marker() -> None:
    response = httpx.Response(
        429,
        headers={"X-Zeler-Pilot-Get-Budget-Status": "wait", "X-Zeler-Upstream-Attempts": "1"},
        json={"error": "pilot_budget_exhausted"},
    )
    assert "X-Zeler-Pilot-Get-Budget-Status" not in proxy._response_headers(response)


# Authentic API path using a locally signed JWT and injected offline dependencies.


class Static:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any]:
        return self.row


class Audit:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def insert_one(self, row: dict[str, Any]) -> None:
        self.rows.append(row)


class RateCounter:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def check_and_increment(self, **kwargs: Any) -> None:
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "expected"), [("orders/1", 429), ("stock/fulfillment/operations/search", 403)]
)
async def test_authenticated_normal_proxy_wait_and_existing_full_scope_denial(
    monkeypatch: pytest.MonkeyPatch, path: str, expected: int
) -> None:
    monkeypatch.setenv(ENV, SELLER)
    monkeypatch.setattr(proxy, "RateLimitCounter", RateCounter)

    async def decrypt(*args: Any, **kwargs: Any) -> str:
        return "synthetic-upstream-token"

    monkeypatch.setattr(proxy, "decrypt_token", decrypt)
    set_kms_client(FakeJwtKmsClient())
    try:
        app = FastAPI()
        app.include_router(proxy.router, prefix="/proxy/meli")
        plans = Plans(plan(state="paused"))
        account = {
            "status": "active",
            "access_token_ciphertext": b"test",
            "token_nonce": b"test",
            "access_token_dek_wrapped": b"test",
            "kms_key_version": "test",
        }
        app.state.mongo_db = {
            "module_registry": Static(
                {
                    "_id": "sheets",
                    "status": "enabled",
                    "allowed_meli_scopes": validate_manifest(
                        Path(__file__).resolve().parents[2] / "modules/sheets/manifest.yaml"
                    ).allowed_meli_scopes,
                }
            ),
            "meli_accounts": Static(account),
            "sheets_history_backfill_plans": plans,
            "audit_log": Audit(),
        }
        app.state.proxy_wait_now = lambda: NOW
        calls: list[str] = []
        app.state.proxy_http_client_factory = lambda: httpx.AsyncClient(
            transport=recording_transport(calls)
        )
        jwt = mint_module_jwt("sheets", seller_id=int(SELLER))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
        ) as client:
            response = await client.get(
                "/proxy/meli/" + path, headers={"Authorization": "Bearer " + jwt}
            )
            unauthorized = await client.get(
                "/proxy/meli/orders/1", headers={"Authorization": "Bearer invalid"}
            )
        assert response.status_code == expected
        assert unauthorized.status_code == 401
        assert calls == [] and plans.updates == []
        if expected == 429:
            assert response.json()["error"] == "pilot_execution_unavailable"
            assert response.headers["X-Zeler-Pilot-Get-Budget-Status"] == "wait"
            assert response.headers["X-Zeler-Upstream-Attempts"] == "0"
    finally:
        set_kms_client(None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing",
    [
        "execution_id",
        "execution_until",
        "execution_utc_day",
        "execution_attempt_limit",
        "execution_consumed",
    ],
)
async def test_missing_execution_control_is_not_ordinary_unlimited_policy(missing: str) -> None:
    value = plan()
    del value[missing]
    plans = Plans(value)
    with pytest.raises(proxy.PilotGetBudgetWaitError):
        await proxy._reserve_pilot_get_send(request(plans))
    assert plans.updates == []


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["invalid", None, [], 1])
async def test_invalid_authority_fails_controlled_without_rpc(invalid: Any) -> None:
    plans = Plans(plan(authority=invalid))
    with pytest.raises(proxy.PilotGetBudgetWaitError):
        await proxy._reserve_pilot_get_send(request(plans))
    assert plans.updates == []


@pytest.mark.asyncio
async def test_late_sent_corruption_is_not_repaired_or_charged() -> None:
    plans = Plans(plan())
    plans.before_cas = lambda row: row.update(execution_sent=99)
    with pytest.raises(proxy.PilotGetBudgetWaitError):
        await proxy._reserve_pilot_get_send(request(plans))
    assert plans.updates == []
    assert plans.row is not None and plans.row["execution_sent"] == 99
