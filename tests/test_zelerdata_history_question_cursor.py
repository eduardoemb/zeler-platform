"""Root operator preflight: wire pins are evidence, never transport authority."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib
import json
import socket
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from bson import BSON
from bson.raw_bson import RawBSONDocument

SELLER = "82453304"
EID = "868b413e20184befb7e8358e0051924f"
NOW = datetime(2026, 10, 6, 9, tzinfo=UTC)
END = datetime(2026, 9, 24, 5, 36, 28, tzinfo=UTC)
START = END.replace(year=2025)
PLAN_ID = "pilot-12m:" + END.isoformat(timespec="milliseconds")
KEY = hashlib.sha256("\0".join((SELLER, "questions", "seller_scan", PLAN_ID)).encode()).hexdigest()


def module() -> Any:
    return importlib.import_module("infra.operations.zelerdata_history_question_cursor")


class Collection:
    def __init__(self, db: DB, name: str) -> None:
        self.db, self.name = db, name

    def with_options(self, **kwargs: Any) -> Collection:
        assert kwargs["codec_options"].document_class is RawBSONDocument
        self.db.raw_options += 1
        return self

    async def find_one(self, selector: dict[str, Any], **kwargs: Any) -> Any:
        assert kwargs["max_time_ms"] == 4000
        self.db.reads += 1
        value = self.db.docs[self.name]
        if value.get("_id") != selector["_id"]:
            return None
        return copy.deepcopy(value) if self.db.dict_result else RawBSONDocument(BSON.encode(value))


class DB:
    def __init__(self) -> None:
        self.reads, self.raw_options = 0, 0
        self.primary, self.dict_result = True, False
        self.client = self
        self.admin = self
        budgets = {
            s: {"physical_attempts": cap, "consumed": used}
            for s, cap, used in (
                ("orders", 800, 53),
                ("questions", 150, 4),
                ("shipments", 250, 0),
                ("messages", 300, 0),
                ("claims_returns", 500, 0),
                ("full_withdrawals", 0, 0),
            )
        }
        self.docs: dict[str, dict[str, Any]] = {
            "sheets_history_backfill_plans": {
                "_id": SELLER,
                "seller_id": SELLER,
                "policy_version": "history-on-link-v1",
                "authority": {"kind": "account_link_policy"},
                "eligible": True,
                "state": "paused",
                "date_from": START,
                "date_to": END,
                "cutoff": END,
                "execution_id": EID,
                "execution_until": NOW + timedelta(hours=1),
                "execution_utc_day": "2026-10-06",
                "execution_attempt_limit": 2500,
                "execution_consumed": 81,
                "execution_sent": 79,
                "total_budget": 2000,
                "total_consumed": 57,
                "incremental_consumed": 24,
                "incremental_policy": {"max_daily_total": 500, "max_daily_source": 300},
                "sources": ["orders", "questions", "shipments", "messages", "claims_returns"],
                "incremental_day": "2026-10-06",
                "incremental_source_consumed": {s: 24 if s == "orders" else 0 for s in budgets},
                "budget": budgets,
            },
            "sheets_history_acquisitions": {
                "_id": KEY,
                "job_id": KEY,
                "seller_id": SELLER,
                "read_model": "questions",
                "plan_id": PLAN_ID,
                "scope_id": "seller_scan",
                "date_from": START,
                "date_to": END,
                "generation": 1,
                "pass_number": 1,
                "checkpoint_revision": 3,
                "published_count": 0,
                "phase": "discover",
                "next_cursor": "PRIVATE_SYNTHETIC_MARKER",
                "observed_until": NOW - timedelta(hours=3),
                "page_sequence": 3,
            },
            "sheets_formula_recovery_jobs": {
                "_id": KEY,
                "seller_id": SELLER,
                "read_model": "questions",
                "state": "failed",
                "failure_reason": "source_rejected",
                "attempts": 1,
                "history_protocol_version": 1,
                "history_plan_id": PLAN_ID,
                "history_acquisition_id": KEY,
                "history_generation": 1,
                "history_pass_number": 1,
                "history_checkpoint_revision": 3,
                "date_from": START,
                "date_to": END,
                "private_extra": "PRIVATE_SYNTHETIC_MARKER",
            },
        }

    def __getitem__(self, name: str) -> Collection:
        return Collection(self, name)

    async def command(self, name: str, **kwargs: Any) -> dict[str, Any]:
        assert name == "hello" and kwargs["maxTimeMS"] == 4000
        self.reads += 1
        return {"isWritablePrimary": self.primary}


@pytest.fixture(autouse=True)
def no_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("operator tests forbid sockets")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)


def inspect(db: DB) -> dict[str, Any]:
    return asyncio.run(module().inspect_question_cursor(db, execution_id=EID, now=NOW))


def test_wire_snapshot_pins_are_exact_and_never_authorize_transport() -> None:
    db = DB()
    before = copy.deepcopy(db.docs)
    result = inspect(db)
    assert db.reads == 4 and db.raw_options == 3 and db.docs == before
    for key, collection in (
        ("plan_bson_sha256", "sheets_history_backfill_plans"),
        ("head_bson_sha256", "sheets_history_acquisitions"),
        ("job_bson_sha256", "sheets_formula_recovery_jobs"),
    ):
        assert result[key] == hashlib.sha256(BSON.encode(db.docs[collection])).hexdigest()
    assert result["hash_format"] == "wire_raw_bson_sha256"
    assert result["transport_authorized"] is False and result["applied"] is False
    assert result["readmission_preconditions_met"] is True
    assert "PRIVATE_SYNTHETIC_MARKER" not in json.dumps(result)


def test_expired_window_can_be_inspected_but_not_used() -> None:
    db = DB()
    db.docs["sheets_history_backfill_plans"]["execution_until"] = NOW - timedelta(seconds=1)
    result = inspect(db)
    assert result["readmission_preconditions_met"] is False
    assert "execution_window_expired" in result["blockers"]
    assert result["charged"] == 81 and result["sent"] == 79


@pytest.mark.parametrize("kind", ["dict_result", "not_primary", "missing_head", "full", "scope"])
def test_unsafe_or_nonwire_read_fails_closed(kind: str) -> None:
    db = DB()
    if kind == "dict_result":
        db.dict_result = True
    if kind == "not_primary":
        db.primary = False
    if kind == "missing_head":
        db.docs["sheets_history_acquisitions"]["_id"] = "other"
    if kind == "full":
        db.docs["sheets_history_backfill_plans"]["budget"]["full_withdrawals"][
            "physical_attempts"
        ] = 1
    if kind == "scope":
        db.docs["sheets_formula_recovery_jobs"]["seller_id"] = "123"
    before = copy.deepcopy(db.docs)
    with pytest.raises(module().CursorControlError):
        inspect(db)
    assert db.docs == before


def test_clock_and_live_lease_blockers_are_not_silently_repaired() -> None:
    db = DB()
    db.docs["sheets_history_acquisitions"]["observed_until"] = NOW + timedelta(seconds=1)
    db.docs["sheets_formula_recovery_jobs"]["lease_until"] = NOW + timedelta(seconds=1)
    result = inspect(db)
    assert {"cursor_clock_invalid", "job_lease_live"} <= set(result["blockers"])
    assert not result["readmission_preconditions_met"]


def test_default_cli_is_noop_without_runtime_factory(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    m = module()
    monkeypatch.setattr(m, "_runtime", lambda: pytest.fail("default must not create runtime"))
    assert m.main([]) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "noop"


def test_inspection_requires_approved_runtime_before_factory(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    m = module()
    monkeypatch.setattr(m, "_runtime", lambda: pytest.fail("unapproved must not create runtime"))
    assert m.main(["--inspect", "--execution-id", EID]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "approved_runtime_required"


@pytest.mark.parametrize("field", ["sources", "incremental_source_consumed"])
def test_unknown_scope_or_source_counters_are_not_free_credit(field: str) -> None:
    db = DB()
    db.docs["sheets_history_backfill_plans"].pop(field)
    with pytest.raises(module().CursorControlError):
        inspect(db)


def test_cleanup_failure_is_closed_not_success_or_raw_error(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    class BadClose:
        def close(self) -> None:
            raise RuntimeError("PRIVATE_SYNTHETIC_MARKER")

    m = module()
    monkeypatch.setattr(m, "_runtime", lambda: SimpleNamespace(db=DB(), client=BadClose()))
    assert m.main(["--inspect", "--approved-runtime", "--execution-id", EID]) == 1
    output = capsys.readouterr().out
    assert "PRIVATE_SYNTHETIC_MARKER" not in output
    assert json.loads(output)["code"] == "runtime_cleanup_failed"
