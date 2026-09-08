from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from zeler_sheets.formulas.registry import FormulaRegistry
from zeler_sheets.scripts.goal_formula_smoke import build_cases, execute_cases, main

TEST_TOKEN = "private-test-credential"  # noqa: S105 - synthetic test credential.


def inputs() -> dict[str, str]:
    return {
        "skus": "PILOT-SKU",
        "id_publicaciones": "MLA123",
        "codigo_ml": "INVENTORY123",
        "id_ordenes": "123456789",
        "fecha_inicial": "2026-08-08",
        "fecha_final": "2026-09-06",
    }


@pytest.mark.asyncio
async def test_smoke_executes_every_registered_formula_without_printing_payloads() -> None:
    seen: list[dict[str, Any]] = []
    token = TEST_TOKEN
    seller = "private-test-seller"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer " + token
        payload = json.loads(request.content)
        seen.append(payload)
        assert payload["cuenta"] == seller
        return httpx.Response(200, json={"ok": True, "values": [["private buyer name"]]})

    cases = build_cases(inputs())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        report = await execute_cases(client, token=token, seller=seller, cases=cases)
    assert len(seen) == 52
    assert {p["formula"] for p in seen} == {
        c.name for c in FormulaRegistry.default().list_contracts()
    }
    assert report["executed"] == 52
    assert report["all_responded"] is True
    assert report["correctness_verified"] is False
    assert report["data_review_required"] == 52
    assert all(p["args"].get("encabezados", False) is False for p in seen)
    serialized = json.dumps(report)
    assert all(
        value not in serialized for value in (token, seller, "private buyer name", "PILOT-SKU")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["missing", "partial", "empty", "auth", "transport", "malformed"]
)
async def test_smoke_does_not_confuse_http_success_with_data_acceptance(failure: str) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if failure == "transport":
            raise httpx.ReadTimeout("sensitive diagnostic", request=request)
        if failure == "auth":
            return httpx.Response(401)
        bodies = {
            "missing": {"ok": False, "error": {"code": "DATA_UNAVAILABLE"}},
            "partial": {"ok": True, "values": [[100]], "meta": {"inventory_rows_complete": False}},
            "empty": {"ok": True, "values": []},
            "malformed": {"ok": True, "values": "private bad payload"},
        }
        return httpx.Response(200, json=bodies[failure])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        report = await execute_cases(
            client, token=TEST_TOKEN, seller="seller", cases=build_cases(inputs())
        )
    assert report["correctness_verified"] is False
    assert report["data_review_required"] == 0
    assert calls == (1 if failure == "auth" else 52)
    assert "private" not in json.dumps(report) and "sensitive" not in json.dumps(report)


def test_smoke_requires_real_case_inputs_and_complete_registry_coverage() -> None:
    with pytest.raises(ValueError):
        build_cases({})
    cases = build_cases(inputs())
    assert cases["ZELERDATA_DEVOLUCIONES"]["fecha_inicio"] == "2026-08-08"
    assert cases["ZELERDATA_PREGUNTAS"]["fecha_final"] == "2026-09-06"


def test_validate_inputs_never_opens_http_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("validation must not instantiate HTTP")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps(inputs()))
    assert main(["--inputs", str(path)]) == 0
    assert json.loads(capsys.readouterr().out) == {"cases_validated": 52, "http_executed": False}


@pytest.mark.asyncio
async def test_each_execution_has_total_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    import zeler_sheets.scripts.goal_formula_smoke as smoke

    monkeypatch.setattr(smoke, "REQUEST_SECONDS", 0.001)

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, json={"ok": True, "values": [[100]]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
        report = await execute_cases(
            client, token=TEST_TOKEN, seller="seller", cases=build_cases(inputs())
        )
    assert report["executed"] == 52
    assert report["all_responded"] is False
    assert all(row["status"] == "transport_failed" for row in report["observations"])
