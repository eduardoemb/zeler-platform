from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from zeler_sheets.scripts.authenticated_smoke import (
    ENV_BASE_URL,
    ENV_SELLER,
    ENV_TOKEN,
    EXPECTED_FORMULA_COUNT,
    SMOKE_DATE_FROM,
    SMOKE_DATE_TO,
    SMOKE_FORMULA,
    STAGE,
    SmokeConfig,
    SmokeConfigError,
    SmokeHttpError,
    SmokeRedactionError,
    assert_redacted,
    build_evidence,
    config_from_env,
    exit_code_for,
    fetch_inventory,
    inventory_passes,
    main,
    parse_inventory,
    redact_text,
    run_devoluciones,
)

TOKEN = "zs_ext_smoke_test_secret_token"  # noqa: S105 - test-only placeholder token.
SELLER = "82453304"
BASE_URL = "https://sheets.example"

ENV_OK = {
    ENV_BASE_URL: BASE_URL,
    ENV_TOKEN: TOKEN,
    ENV_SELLER: SELLER,
}


def _inventory_payload(*, implemented: int = 52, total: int = 52) -> dict[str, Any]:
    formulas = [
        {
            "name": f"ZELERDATA_FORMULA_{index:02d}",
            "status": "implemented" if index < implemented else "unsupported",
        }
        for index in range(total - 1)
    ]
    formulas.append(
        {
            "name": SMOKE_FORMULA,
            "status": "implemented" if implemented == total else "unsupported",
        }
    )
    return {"formulas": formulas}


def _devoluciones_error_payload(code: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code}}


class _TransportLog:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []


def _transport(
    log: _TransportLog,
    *,
    inventory_payload: dict[str, Any] | None = None,
    execute_status: int = 200,
    execute_payload: dict[str, Any] | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        log.requests.append(request)
        if request.url.path == "/sheets/formulas/inventory":
            return httpx.Response(200, json=inventory_payload or _inventory_payload())
        if request.url.path == "/sheets/formulas:execute":
            return httpx.Response(
                execute_status,
                json=execute_payload or {"ok": True, "values": [["value"]]},
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _client_factory(
    transport: httpx.MockTransport,
) -> Callable[[], httpx.AsyncClient]:
    return lambda: httpx.AsyncClient(transport=transport, base_url="http://test")


def test_taxonomy_status_classes_and_exit_codes_are_bounded() -> None:
    assert exit_code_for("success") == 0
    for status_class in (
        "config_missing",
        "inventory_mismatch",
        "auth_failed",
        "data_unavailable",
        "formula_failed",
        "transport_failed",
        "redaction_failed",
    ):
        assert exit_code_for(status_class) != 0


def test_build_evidence_emits_zelerdata_smoke_envelope() -> None:
    evidence = build_evidence("success", {"formulas_total": 52, "devoluciones": 1})

    assert set(evidence) == {"stage", "status_class", "counters"}
    assert evidence["stage"] == STAGE
    assert evidence["stage"] == "zelerdata_smoke"
    assert evidence["status_class"] == "success"
    assert evidence["counters"] == {"devoluciones": 1, "formulas_total": 52}


def test_config_from_env_requires_all_three_values_in_normal_mode() -> None:
    with pytest.raises(SmokeConfigError) as exc:
        config_from_env({})
    message = str(exc.value)
    assert ENV_BASE_URL in message
    assert ENV_TOKEN in message
    assert ENV_SELLER in message


@pytest.mark.parametrize("missing", [ENV_BASE_URL, ENV_TOKEN, ENV_SELLER])
def test_config_from_env_fails_closed_on_any_single_missing_value(
    missing: str,
) -> None:
    environment = {key: value for key, value in ENV_OK.items() if key != missing}
    with pytest.raises(SmokeConfigError) as exc:
        config_from_env(environment)
    assert missing in str(exc.value)


def test_config_from_env_dry_run_requires_token_only() -> None:
    config = config_from_env({ENV_TOKEN: TOKEN}, dry_run=True)

    assert config.base_url == ""
    assert config.seller == ""
    assert config.token == TOKEN

    with pytest.raises(SmokeConfigError):
        config_from_env({}, dry_run=True)


def test_config_from_env_strips_whitespace() -> None:
    config = config_from_env(
        {ENV_BASE_URL: f"  {BASE_URL}  ", ENV_TOKEN: f"  {TOKEN}  ", ENV_SELLER: f"  {SELLER}  "}
    )

    assert config == SmokeConfig(base_url=BASE_URL, token=TOKEN, seller=SELLER)


def test_redact_text_replaces_token_and_seller_everywhere() -> None:
    config = config_from_env(ENV_OK)
    text = f"token={TOKEN} seller={SELLER} again {TOKEN} {SELLER}"

    redacted = redact_text(text, config)

    assert TOKEN not in redacted
    assert SELLER not in redacted
    assert redacted.count("[REDACTED_TOKEN]") == 2
    assert redacted.count("[REDACTED_SELLER]") == 2


def test_redact_text_skips_empty_values_for_dry_run_config() -> None:
    config = config_from_env({ENV_TOKEN: TOKEN}, dry_run=True)

    assert redact_text(f"token={TOKEN}", config) == "token=[REDACTED_TOKEN]"
    assert redact_text("plain text", config) == "plain text"


def test_assert_redacted_accepts_clean_output() -> None:
    config = config_from_env(ENV_OK)

    assert_redacted('{"status_class": "success"}', config)


def test_assert_redacted_rejects_leaked_token_or_seller() -> None:
    config = config_from_env(ENV_OK)

    with pytest.raises(SmokeRedactionError) as token_exc:
        assert_redacted(f"leaked {TOKEN}", config)
    assert "token" in str(token_exc.value)
    with pytest.raises(SmokeRedactionError) as seller_exc:
        assert_redacted(f"leaked {SELLER}", config)
    assert "seller" in str(seller_exc.value)


def test_parse_inventory_counts_total_implemented_and_devoluciones() -> None:
    observation = parse_inventory(_inventory_payload())

    assert observation.formulas_total == EXPECTED_FORMULA_COUNT == 52
    assert observation.formulas_implemented == 52
    assert observation.devoluciones_implemented is True


def test_parse_inventory_detects_missing_devoluciones_implementation() -> None:
    observation = parse_inventory(_inventory_payload(implemented=51))

    assert observation.formulas_total == 52
    assert observation.formulas_implemented == 51
    assert observation.devoluciones_implemented is False


def test_parse_inventory_rejects_non_object_formula_contract() -> None:
    with pytest.raises(ValueError, match="formula contract"):
        parse_inventory({"formulas": ["invalid"]})


@pytest.mark.parametrize(
    ("total", "implemented", "devoluciones_implemented", "expected"),
    [
        (52, 52, True, True),
        (52, 51, True, False),
        (52, 52, False, False),
        (53, 53, True, False),
    ],
)
def test_inventory_passes_requires_exact_52_all_implemented(
    total: int, implemented: int, devoluciones_implemented: bool, expected: bool
) -> None:
    from zeler_sheets.scripts.authenticated_smoke import InventoryObservation

    observation = InventoryObservation(total, implemented, devoluciones_implemented)

    assert inventory_passes(observation) is expected


@pytest.mark.asyncio
async def test_fetch_inventory_returns_observation_from_transport() -> None:
    log = _TransportLog()
    async with httpx.AsyncClient(transport=_transport(log)) as client:
        observation = await fetch_inventory(client, BASE_URL)

    assert observation.formulas_total == 52
    assert observation.formulas_implemented == 52
    assert observation.devoluciones_implemented is True
    assert [request.url.path for request in log.requests] == ["/sheets/formulas/inventory"]


@pytest.mark.asyncio
async def test_fetch_inventory_raises_transport_failed_on_http_error() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SmokeHttpError) as exc:
            await fetch_inventory(client, BASE_URL)
    assert exc.value.status_class == "transport_failed"


@pytest.mark.asyncio
async def test_run_devoluciones_classifies_success_data_unavailable_and_auth() -> None:
    log = _TransportLog()
    async with httpx.AsyncClient(transport=_transport(log)) as client:
        assert await run_devoluciones(client, BASE_URL, TOKEN, SELLER) == "success"
    async with httpx.AsyncClient(
        transport=_transport(log, execute_payload=_devoluciones_error_payload("DATA_UNAVAILABLE"))
    ) as client:
        assert await run_devoluciones(client, BASE_URL, TOKEN, SELLER) == "data_unavailable"
    async with httpx.AsyncClient(
        transport=_transport(
            log,
            execute_status=401,
            execute_payload=_devoluciones_error_payload("TOKEN_MISSING"),
        )
    ) as client:
        assert await run_devoluciones(client, BASE_URL, TOKEN, SELLER) == "auth_failed"
    execute_requests = [
        request for request in log.requests if request.url.path == "/sheets/formulas:execute"
    ]
    assert execute_requests[0].headers["Authorization"] == f"Bearer {TOKEN}"
    assert json.loads(execute_requests[0].content) == {
        "formula": SMOKE_FORMULA,
        "cuenta": SELLER,
        "args": {
            "fecha_inicio": "2026-06-01",
            "fecha_final": "2026-06-04",
            "id_publicaciones": "todos",
            "encabezados": "",
        },
    }


def test_main_dry_run_exits_zero_emits_single_redacted_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        ["--inventory-only", "--dry-run"],
        environment={ENV_TOKEN: "zs_ext_dryrun_placeholder"},
    )

    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert exit_code == 0
    assert len(lines) == 1
    envelope = json.loads(lines[0])
    assert envelope["stage"] == "zelerdata_smoke"
    assert envelope["status_class"] == "success"
    assert envelope["counters"] == {"dry_run": 1}
    assert "zs_ext_dryrun_placeholder" not in captured.out
    assert "ZELERDATA_SMOKE_TOKEN" not in captured.out


def test_main_full_success_with_fresh_marker_redacts_both_values(
    capsys: pytest.CaptureFixture[str],
) -> None:
    log = _TransportLog()
    transport = _transport(log)
    exit_code = main([], environment=ENV_OK, client_factory=_client_factory(transport))

    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert exit_code == 0
    assert len(lines) == 1
    envelope = json.loads(lines[0])
    assert envelope["stage"] == "zelerdata_smoke"
    assert envelope["status_class"] == "success"
    assert envelope["counters"] == {
        "devoluciones": 1,
        "formulas_implemented": 52,
        "formulas_total": 52,
    }
    assert TOKEN not in captured.out
    assert SELLER not in captured.out


def test_main_data_unavailable_when_marker_stale(capsys: pytest.CaptureFixture[str]) -> None:
    log = _TransportLog()
    transport = _transport(log, execute_payload=_devoluciones_error_payload("DATA_UNAVAILABLE"))
    exit_code = main([], environment=ENV_OK, client_factory=_client_factory(transport))

    envelope = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert exit_code != 0
    assert envelope["status_class"] == "data_unavailable"
    assert envelope["counters"] == {
        "devoluciones": 1,
        "formulas_implemented": 52,
        "formulas_total": 52,
    }


def test_main_auth_failure_exits_nonzero_and_never_leaks_token(
    capsys: pytest.CaptureFixture[str],
) -> None:
    log = _TransportLog()
    transport = _transport(
        log,
        execute_status=401,
        execute_payload=_devoluciones_error_payload("TOKEN_MISSING"),
    )
    exit_code = main([], environment=ENV_OK, client_factory=_client_factory(transport))

    captured = capsys.readouterr()
    envelope = json.loads(captured.out.splitlines()[-1])
    assert exit_code != 0
    assert envelope["status_class"] == "auth_failed"
    assert TOKEN not in captured.out


def test_main_inventory_mismatch_fails_closed_before_execute(
    capsys: pytest.CaptureFixture[str],
) -> None:
    log = _TransportLog()
    transport = _transport(log, inventory_payload=_inventory_payload(implemented=51))
    exit_code = main([], environment=ENV_OK, client_factory=_client_factory(transport))

    envelope = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert exit_code != 0
    assert envelope["status_class"] == "inventory_mismatch"
    assert envelope["counters"] == {"formulas_implemented": 51, "formulas_total": 52}
    assert all(request.url.path != "/sheets/formulas:execute" for request in log.requests)


def test_main_inventory_only_skips_execute_and_reports_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    log = _TransportLog()
    exit_code = main(
        ["--inventory-only"],
        environment=ENV_OK,
        client_factory=_client_factory(_transport(log)),
    )

    envelope = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert exit_code == 0
    assert envelope["status_class"] == "success"
    assert envelope["counters"] == {
        "formulas_implemented": 52,
        "formulas_total": 52,
        "inventory_only": 1,
    }
    assert [request.url.path for request in log.requests] == ["/sheets/formulas/inventory"]


def test_main_never_calls_token_management_endpoints() -> None:
    log = _TransportLog()
    exit_code = main(
        [],
        environment=ENV_OK,
        client_factory=_client_factory(_transport(log)),
    )

    assert exit_code == 0
    paths = [request.url.path for request in log.requests]
    assert "/sheets/formulas/inventory" in paths
    assert "/sheets/formulas:execute" in paths
    assert all("/extension-tokens" not in path for path in paths)
    assert all("rotate" not in path and "reveal" not in path for path in paths)


def test_main_config_missing_fails_closed_with_single_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([], environment={})

    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert exit_code != 0
    assert len(lines) == 1
    envelope = json.loads(lines[0])
    assert envelope["status_class"] == "config_missing"
    assert envelope["counters"] == {}


def test_smoke_date_range_is_inside_documented_accepted_coverage() -> None:
    assert SMOKE_DATE_FROM == "2026-06-01"
    assert SMOKE_DATE_TO == "2026-06-04"
    assert SMOKE_DATE_FROM < SMOKE_DATE_TO
    assert SMOKE_FORMULA == "ZELERDATA_DEVOLUCIONES"
