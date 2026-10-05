"""Characterize real clients/consumers before adding a bounded proxy wait.

Only MockTransport and in-memory control-plane doubles; no real RPC or broker.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from zeler_platform_core.auth.meli_gateway_auth import MeliGatewayAuth
from zeler_platform_core.clients.meli_gateway_client import MeliGatewayClient
from zeler_platform_core.events.claims import ClaimOutcome
from zeler_platform_core.runtime.retry_delay import RETRY_ATTEMPT_HEADER
from zeler_sheets.consumer import SHEETS_CLAIMS_QUEUE, SheetsAmqpConsumerRunner, SheetsEventHandler
from zeler_sheets.sync_jobs_processor import SyncJobsProcessor


class Message:
    def __init__(self) -> None:
        self.body = json.dumps(
            {
                "event_id": "event",
                "event_type": "orders.updated",
                "seller_id": 82453304,
                "resource": "/orders/1",
                "idempotency_key": "event",
            }
        ).encode()
        self.headers: dict[str, Any] = {}
        self.acks = 0
        self.nacks: list[bool] = []

    async def ack(self) -> None:
        self.acks += 1

    async def nack(self, *, requeue: bool) -> None:
        self.nacks.append(requeue)


class Handler:
    def __init__(self, client: MeliGatewayClient) -> None:
        self.client = client

    async def handle(self, event: Any) -> str:
        await self.client.fetch_resource(seller_id=str(event.seller_id), path=event.resource)
        return "appended"


def client(http: httpx.AsyncClient) -> MeliGatewayClient:
    return MeliGatewayClient(
        "https://gateway.test/proxy/meli",
        cast(
            MeliGatewayAuth,
            SimpleNamespace(get_token_for_seller=AsyncMock(return_value="synthetic-test-jwt")),
        ),
        http_client=http,
    )


def wait_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        429,
        json={"error": "history_pilot_get_budget_wait"},
        headers={"Retry-After": "5", "X-Zeler-Upstream-Attempts": "0"},
        request=request,
    )


@pytest.mark.asyncio
async def test_normal_module_client_budget_wait_preserves_original_delivery() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(wait_response)) as http:
        runner = SheetsAmqpConsumerRunner(
            rabbitmq_url="amqp://unit-test", handler=Handler(client(http))
        )
        message = Message()
        await runner.handle_message(message)
    assert message.acks == 0
    assert message.nacks == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("publication_fails", [False, True])
async def test_claim_wait_acks_only_after_confirmed_delayed_copy(publication_fails: bool) -> None:
    publish = AsyncMock(
        side_effect=RuntimeError("fixture") if publication_fails else None, return_value=True
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(wait_response)) as http:
        runner = SheetsAmqpConsumerRunner(
            rabbitmq_url="amqp://unit-test",
            handler=Handler(client(http)),
        )
        message = Message()
        runner._channel = SimpleNamespace(default_exchange=SimpleNamespace(publish=publish))
        await runner.handle_claims_message(message)
    if publication_fails:
        assert message.acks == 0 and message.nacks == [True]
    else:
        assert message.acks == 1 and message.nacks == []
        assert publish.await_args is not None
        sent = publish.await_args.args[0]
        assert sent.body == message.body
        assert publish.await_args.kwargs["mandatory"] is True
        assert publish.await_args.kwargs["routing_key"].startswith(SHEETS_CLAIMS_QUEUE)


@pytest.mark.asyncio
async def test_sync_job_budget_wait_is_terminal_failed_not_resumable_current_contract() -> None:
    now = datetime(2026, 10, 5, 12, tzinfo=UTC)
    jobs = MagicMock()
    jobs.update_one = AsyncMock(return_value=SimpleNamespace(matched_count=1))
    events = MagicMock()
    events.find.return_value.sort.return_value.to_list = AsyncMock(
        return_value=[
            {
                "_id": "event",
                "user_id": 82453304,
                "received_at": now,
                "classification": "orders.updated",
                "resource": "/orders/1",
            }
        ]
    )
    selected = {
        "_id": "job",
        "seller_id": "82453304",
        "requested_at": now - timedelta(minutes=1),
        "delta_through_at": now,
        "attempt_token": "fixture",
        "fence": 1,
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(wait_response)) as http:
        processor = SyncJobsProcessor(
            db={"sheets_sync_jobs": jobs, "webhook_events": events},
            handler=Handler(client(http)),
            activation_cutoff=now - timedelta(days=1),
            clock=lambda: now,
        )
        processor.recover_uncertain_appends = AsyncMock(return_value=0)  # type: ignore[method-assign]
        processor.claim_next = AsyncMock(return_value=selected)  # type: ignore[method-assign]
        result = await processor.process_once()
    assert result == "failed"
    terminal = jobs.update_one.await_args.args[1]["$set"]
    assert terminal["state"] == "failed"
    assert terminal["error_code"] == "sync_job_processing_failed"
    assert "GatewayRateLimitError" in terminal["error_message"]
    assert all(
        call.args[1]["$set"].get("state") != "pending" for call in jobs.update_one.await_args_list
    )
    assert not jobs.delete_one.called and not events.delete_one.called


class Claims:
    def __init__(self) -> None:
        self.completed: set[str] = set()
        self.owners: dict[str, str] = {}

    async def claim(self, idempotency_key: str, *, owner_token: str, **kwargs: Any) -> ClaimOutcome:
        key = idempotency_key
        if key in self.completed:
            return ClaimOutcome.COMPLETED
        assert key not in self.owners
        self.owners[key] = owner_token
        return ClaimOutcome.CLAIMED

    async def complete(self, idempotency_key: str, *, owner_token: str, **kwargs: Any) -> bool:
        key = idempotency_key
        assert self.owners.pop(key) == owner_token
        self.completed.add(key)
        return True

    async def release(self, idempotency_key: str, *, owner_token: str, **kwargs: Any) -> bool:
        key = idempotency_key
        assert self.owners.pop(key) == owner_token
        return True


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["pilot_execution_unavailable", "pilot_budget_exhausted"])
async def test_controlled_pilot_wait_reschedules_and_real_handler_replay_does_not_reappend(
    code: str,
) -> None:
    now = datetime(2026, 10, 5, 12, tzinfo=UTC)
    clock = [now]
    current: dict[str, Any] = {
        "_id": "job",
        "seller_id": "82453304",
        "state": "running",
        "created_at": now - timedelta(hours=1),
        "requested_at": now - timedelta(minutes=10),
        "available_at": None,
        "delta_through_at": now,
        "attempt_token": "fixture",
        "attempt_count": 7,
        "fence": 3,
        "lease_until": now + timedelta(minutes=5),
        "append_started_at": None,
    }
    jobs = MagicMock()

    async def update(query: dict[str, Any], document: dict[str, Any]) -> Any:
        assert query["_id"] == current["_id"] and query["state"] == current["state"]
        assert (
            query["attempt_token"] == current["attempt_token"]
            and query["fence"] == current["fence"]
        )
        current.update(document["$set"])
        return SimpleNamespace(matched_count=1)

    jobs.update_one = AsyncMock(side_effect=update)
    jobs.update_many = AsyncMock(return_value=SimpleNamespace(modified_count=0))
    events = MagicMock()
    events.find.return_value.sort.return_value.to_list = AsyncMock(
        return_value=[
            {
                "_id": "first",
                "user_id": 82453304,
                "received_at": now - timedelta(minutes=2),
                "classification": "items.updated",
                "resource": "/items/first",
            },
            {
                "_id": "second",
                "user_id": 82453304,
                "received_at": now - timedelta(minutes=1),
                "classification": "items.updated",
                "resource": "/items/second",
            },
        ]
    )
    waiting = [True]
    physical_reads: list[str] = []

    def transport(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/second") and waiting[0]:
            return httpx.Response(
                429,
                json={"error": code},
                headers={
                    "Retry-After": "5",
                    "X-Zeler-Pilot-Get-Budget-Status": "wait",
                    "X-Zeler-Upstream-Attempts": "0",
                },
            )
        physical_reads.append(request.url.path)
        return httpx.Response(
            200, json={"id": request.url.path.rsplit("/", 1)[-1], "title": "fixture", "price": 1}
        )

    exports = SimpleNamespace(
        find_one=AsyncMock(return_value={"spreadsheet_id": "synthetic-sheet"})
    )
    sheets = SimpleNamespace(append_row=AsyncMock())
    persistence = SimpleNamespace(persist=AsyncMock())
    claims = Claims()
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        handler = SheetsEventHandler(
            db={"sheets_exports": exports},
            gateway_client=client(http),
            sheets_client=sheets,
            idempotency_store=MagicMock(),
            event_persistence=persistence,
            event_claim_store=claims,
        )
        processor = SyncJobsProcessor(
            db={"sheets_sync_jobs": jobs, "webhook_events": events},
            handler=handler,
            activation_cutoff=now - timedelta(days=1),
            clock=lambda: clock[0],
        )
        processor.claim_next = AsyncMock(return_value=current.copy())  # type: ignore[method-assign]
        assert await processor.process_once() == "pending"
        assert current["state"] == "pending" and current["available_at"] == now + timedelta(
            seconds=5
        )
        assert current["lease_until"] is None and current["append_started_at"] is None
        assert current["requested_at"] == now - timedelta(minutes=10)
        assert (current["attempt_count"], current["fence"], current["attempt_token"]) == (
            7,
            3,
            "fixture",
        )
        assert current["cursor_event_id"] == "first"
        assert sheets.append_row.await_count == 1
        # Resume with the real claim path: existing availability and fenced
        # attempt counters are advanced, never reset or taken over manually.
        del processor.claim_next

        async def candidate(query: dict[str, Any], **kwargs: Any) -> Any:
            assert query["$or"][0]["$or"][1] == {"available_at": {"$lte": clock[0]}}
            return current.copy() if current["available_at"] <= clock[0] else None

        async def claim(query: dict[str, Any], document: dict[str, Any], **kwargs: Any) -> Any:
            assert query["state"] == "pending"
            current.update(document["$set"])
            for field, count in document["$inc"].items():
                current[field] += count
            return current.copy()

        jobs.find_one = AsyncMock(side_effect=candidate)
        jobs.find_one_and_update = AsyncMock(side_effect=claim)
        assert await processor.process_once() == "idle"
        clock[0] += timedelta(seconds=6)
        waiting[0] = False
        assert await processor.process_once() == "succeeded"
    assert physical_reads == ["/proxy/meli/items/first", "/proxy/meli/items/second"]
    assert sheets.append_row.await_count == 2 and persistence.persist.await_count == 2
    assert current["attempt_count"] == 8 and current["fence"] == 4
    assert claims.completed == {"sync-job:job:first", "sync-job:job:second"}
    assert not jobs.delete_one.called and not events.delete_one.called


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("marker", "payload"),
    [
        (None, {"error": "pilot_execution_unavailable"}),
        ("wait", {"error": "provider_error"}),
        ("wait", {"error": {"invalid": True}}),
        ("wait", []),
        ("invalid", {"error": "pilot_budget_exhausted"}),
    ],
)
async def test_unknown_or_unmarked_wait_keeps_other_failure_contract(
    marker: str | None, payload: Any
) -> None:
    now = datetime(2026, 10, 5, 12, tzinfo=UTC)
    jobs = MagicMock()
    jobs.update_one = AsyncMock(return_value=SimpleNamespace(matched_count=1))
    events = MagicMock()
    events.find.return_value.sort.return_value.to_list = AsyncMock(
        return_value=[
            {
                "_id": "event",
                "user_id": 82453304,
                "received_at": now,
                "classification": "items.updated",
                "resource": "/items/1",
            }
        ]
    )
    selected = {
        "_id": "job",
        "seller_id": "82453304",
        "requested_at": now - timedelta(minutes=1),
        "delta_through_at": now,
        "attempt_token": "fixture",
        "fence": 1,
    }

    def response(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json=payload,
            headers={} if marker is None else {"X-Zeler-Pilot-Get-Budget-Status": marker},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
        processor = SyncJobsProcessor(
            db={"sheets_sync_jobs": jobs, "webhook_events": events},
            handler=Handler(client(http)),
            activation_cutoff=now - timedelta(days=1),
            clock=lambda: now,
        )
        processor.recover_uncertain_appends = AsyncMock(return_value=0)  # type: ignore[method-assign]
        processor.claim_next = AsyncMock(return_value=selected)  # type: ignore[method-assign]
        assert await processor.process_once() == "failed"
    assert jobs.update_one.await_args.args[1]["$set"]["state"] == "failed"


@pytest.mark.asyncio
async def test_pilot_pending_write_remains_fenced_on_lease_loss() -> None:
    now = datetime(2026, 10, 5, 12, tzinfo=UTC)
    jobs = MagicMock()
    jobs.update_one = AsyncMock(return_value=SimpleNamespace(matched_count=0))
    selected = {
        "_id": "job",
        "seller_id": "82453304",
        "requested_at": now - timedelta(minutes=1),
        "delta_through_at": now,
        "attempt_token": "fixture",
        "fence": 1,
    }
    from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError

    error = GatewayRateLimitError(
        retry_after_seconds=5,
        response=httpx.Response(
            429,
            json={"error": "pilot_budget_exhausted"},
            headers={"X-Zeler-Pilot-Get-Budget-Status": "wait"},
        ),
    )
    processor = SyncJobsProcessor(
        db={"sheets_sync_jobs": jobs, "webhook_events": MagicMock()},
        handler=MagicMock(),
        activation_cutoff=now - timedelta(days=1),
        clock=lambda: now,
    )
    processor.recover_uncertain_appends = AsyncMock(return_value=0)  # type: ignore[method-assign]
    processor.claim_next = AsyncMock(return_value=selected)  # type: ignore[method-assign]
    processor._process_delta = AsyncMock(side_effect=error)  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="lease lost"):
        await processor.process_once()
    assert jobs.update_one.await_count == 1
    assert jobs.update_one.await_args.args[0] == {
        "_id": "job",
        "state": "running",
        "attempt_token": "fixture",
        "fence": 1,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("claims_queue", [False, True])
async def test_controlled_wait_seven_deliveries_preserve_count_then_provider_still_dlqs(
    claims_queue: bool,
) -> None:
    publish = AsyncMock(return_value=True)
    exchange = SimpleNamespace(publish=publish)
    channel = SimpleNamespace(
        default_exchange=exchange, declare_exchange=AsyncMock(return_value=exchange)
    )
    waiting = [True]
    gateway_requests: list[str] = []

    def response(request: httpx.Request) -> httpx.Response:
        gateway_requests.append(request.url.path)
        if waiting[0]:
            return httpx.Response(
                429,
                json={"error": "pilot_execution_unavailable"},
                headers={
                    "Retry-After": "5",
                    "X-Zeler-Pilot-Get-Budget-Status": "wait",
                    "X-Zeler-Upstream-Attempts": "0",
                },
            )
        return httpx.Response(
            429, json={"error": "provider_rate_limit"}, headers={"Retry-After": "5"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
        runner = SheetsAmqpConsumerRunner(
            rabbitmq_url="amqp://unit-test", handler=Handler(client(http))
        )
        runner._channel = channel
        legacy = SimpleNamespace(publish_delay=AsyncMock())
        runner._retry_delay_publisher = legacy
        delivery = runner.handle_claims_message if claims_queue else runner.handle_message
        for _ in range(7):
            message = Message()
            message.headers = {RETRY_ATTEMPT_HEADER: 4, "idempotency_key": "stable-event"}
            await delivery(message)
            assert message.acks == 1 and message.nacks == []
            assert publish.await_args is not None
            sent = publish.await_args.args[0]
            assert sent.body == message.body
            assert sent.headers[RETRY_ATTEMPT_HEADER] == 4
            assert sent.headers["idempotency_key"] == "stable-event"
            assert publish.await_args.kwargs["mandatory"] is True
            assert int(sent.delivery_mode) == 2
            if not claims_queue:
                assert sent.properties.expiration == "5000"
        assert publish.await_count == 7 and legacy.publish_delay.await_count == 0
        waiting[0] = False
        provider = Message()
        provider.headers = {RETRY_ATTEMPT_HEADER: 4}
        await delivery(provider)
        assert provider.acks == 1
        if claims_queue:
            assert publish.await_args is not None
            provider_copy_headers = publish.await_args.args[0].headers
        else:
            assert legacy.publish_delay.await_args is not None
            provider_copy_headers = legacy.publish_delay.await_args.kwargs["headers"]
        assert provider_copy_headers[RETRY_ATTEMPT_HEADER] == 5
        exhausted = Message()
        exhausted.headers = dict(provider_copy_headers)
        count = len(gateway_requests)
        await delivery(exhausted)
        assert exhausted.acks == 0 and exhausted.nacks == [False]
        assert len(gateway_requests) == count


@pytest.mark.asyncio
@pytest.mark.parametrize("claims_queue", [False, True])
@pytest.mark.parametrize("failure", [False, None, "unroutable"])
async def test_controlled_publication_requires_real_confirmation_or_nacks(
    claims_queue: bool, failure: Any
) -> None:
    publish = AsyncMock(
        return_value=failure,
        side_effect=RuntimeError("unroutable") if failure == "unroutable" else None,
    )
    exchange = SimpleNamespace(publish=publish)
    channel = SimpleNamespace(
        default_exchange=exchange, declare_exchange=AsyncMock(return_value=exchange)
    )

    def response(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error": "pilot_budget_exhausted"},
            headers={
                "Retry-After": "5",
                "X-Zeler-Pilot-Get-Budget-Status": "wait",
                "X-Zeler-Upstream-Attempts": "0",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
        runner = SheetsAmqpConsumerRunner(
            rabbitmq_url="amqp://unit-test", handler=Handler(client(http))
        )
        runner._channel = channel
        message = Message()
        message.headers = {RETRY_ATTEMPT_HEADER: 4}
        await (
            runner.handle_claims_message(message)
            if claims_queue
            else runner.handle_message(message)
        )
    assert message.acks == 0 and message.nacks == [True]
