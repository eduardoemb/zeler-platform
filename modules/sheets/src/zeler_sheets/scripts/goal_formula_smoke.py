"""Explicit, env-credential HTTP observations for all 52 Goal formulas.

Separate from the fixed B1 runner. Never mints credentials or certifies business
correctness from an HTTP response. No production execution occurs on import/help.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from zeler_sheets.formulas.registry import FormulaRegistry

EXECUTE_URL = "https://sheets.zeler.ai/sheets/formulas:execute"
REQUEST_SECONDS = 25


def build_cases(inputs: Mapping[str, str]) -> dict[str, dict[str, Any]]:
    required = {
        "skus",
        "id_publicaciones",
        "codigo_ml",
        "id_ordenes",
        "fecha_inicial",
        "fecha_final",
    }
    if (
        not isinstance(inputs, Mapping)
        or set(inputs) != required
        or any(not isinstance(v, str) or not v.strip() for v in inputs.values())
    ):
        raise ValueError("six explicit pilot input fields are required")
    start, end = (
        date.fromisoformat(inputs["fecha_inicial"]),
        date.fromisoformat(inputs["fecha_final"]),
    )
    if not 0 <= (end - start).days < 90:
        raise ValueError("pilot date range must be ordered and at most 90 inclusive days")
    supplied: dict[str, Any] = {
        **inputs,
        "fecha_inicio": inputs["fecha_inicial"],
        "rango_dias": 30,
        "cantidad_top": 10,
        "horario_inicial": "00:00",
        "horario_final": "23:59",
        "encabezados": False,
    }
    cases = {}
    for contract in FormulaRegistry.default().list_contracts():
        args = {}
        for parameter in contract.parameters:
            if parameter.name == "cuenta":
                continue
            if parameter.name in supplied:
                args[parameter.name] = supplied[parameter.name]
            elif parameter.required:
                raise ValueError("unhandled required formula parameter")
        cases[contract.name] = args
    if len(cases) != 52:
        raise ValueError("expected exactly 52 active formula contracts")
    return cases


def _classify(response: httpx.Response) -> tuple[str, int]:
    if response.status_code in {401, 403}:
        return "auth_failed", 0
    if response.status_code != 200:
        return "http_failed", 0
    try:
        body = response.json()
    except ValueError:
        return "malformed", 0
    if not isinstance(body, dict):
        return "malformed", 0
    if body.get("ok") is not True:
        error = body.get("error")
        return (
            "data_unavailable"
            if isinstance(error, dict) and error.get("code") == "DATA_UNAVAILABLE"
            else "formula_failed"
        ), 0
    values, meta = body.get("values"), body.get("meta", {})
    if (
        not isinstance(values, list)
        or not all(isinstance(row, list) for row in values)
        or not isinstance(meta, dict)
    ):
        return "malformed", 0
    if (
        any(cell == "DATA_UNAVAILABLE" for row in values for cell in row)
        or meta.get("inventory_rows_complete") is False
        or meta.get("partial_misses", 0)
    ):
        return "data_unavailable", len(values)
    if not values or not any(values):
        return "empty_needs_review", 0
    return "data_needs_review", len(values)


async def execute_cases(
    client: httpx.AsyncClient,
    *,
    token: str,
    seller: str,
    cases: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    expected = {c.name for c in FormulaRegistry.default().list_contracts()}
    if set(cases) != expected or len(cases) != 52 or not token.strip() or not seller.strip():
        raise ValueError("complete cases and legitimate credentials are required")
    observations = []
    for name, args in cases.items():
        started = time.monotonic()
        status_code = None
        try:
            async with asyncio.timeout(REQUEST_SECONDS):
                response = await client.post(
                    EXECUTE_URL,
                    headers={"Authorization": "Bearer " + token},
                    json={"formula": name, "cuenta": seller, "args": args},
                    follow_redirects=False,
                )
                status_code = response.status_code
                status, rows = _classify(response)
        except (httpx.HTTPError, TimeoutError):
            status, rows = "transport_failed", 0
        observations.append(
            {
                "formula": name,
                "status": status,
                "http_status": status_code,
                "rows": rows,
                "seconds": round(time.monotonic() - started, 4),
            }
        )
        if status == "auth_failed":
            break
    return {
        "executed": len(observations),
        "all_responded": len(observations) == 52
        and all(o["http_status"] == 200 for o in observations),
        "correctness_verified": False,
        "data_review_required": sum(o["status"] == "data_needs_review" for o in observations),
        "observations": observations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inputs", type=Path, required=True, help="JSON with six real pilot input fields"
    )
    parser.add_argument(
        "--execute", action="store_true", help="explicitly run authorized production observations"
    )
    args = parser.parse_args(argv)
    try:
        cases = build_cases(json.loads(args.inputs.read_text()))
        if not args.execute:
            print(json.dumps({"cases_validated": len(cases), "http_executed": False}))
            return 0
        token = os.environ.get("ZELERDATA_SMOKE_TOKEN", "")
        seller = os.environ.get("ZELERDATA_SMOKE_SELLER", "")

        async def run() -> dict[str, Any]:
            async with httpx.AsyncClient(timeout=REQUEST_SECONDS, trust_env=False) as client:
                return await execute_cases(client, token=token, seller=seller, cases=cases)

        report = asyncio.run(run())
        print(json.dumps(report, sort_keys=True))
        return 0 if report["all_responded"] and report["data_review_required"] == 52 else 1
    except (ValueError, TypeError, OSError):
        print(json.dumps({"status": "invalid_smoke_configuration"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
