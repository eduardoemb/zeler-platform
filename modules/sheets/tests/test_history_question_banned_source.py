"""Known provider BANNED redaction is present-empty, never recovered hidden text."""

from __future__ import annotations

import copy
import importlib.util
import socket
import sys
from importlib.machinery import ModuleSpec, SourceFileLoader
from pathlib import Path
from typing import Any, cast

import pytest

from zeler_sheets.formulas.read_models import FormulaReadModelRepository
from zeler_sheets.history_question_publication import HistoryQuestionPublisher
from zeler_sheets.history_questions import _complete_scan_question
from zeler_sheets.item_projection import item_source_fingerprint

spec = cast(
    ModuleSpec,
    importlib.util.spec_from_file_location(
        "_banned_scan_fixtures",
        Path(__file__).with_name("test_history_question_scan_materialization.py"),
    ),
)
f = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = f
cast(SourceFileLoader, spec.loader).exec_module(f)


def banned(kind: str) -> tuple[Any, Any, Any, Any, Any]:
    db, queue, head, runner, gateway = f.prepared(1)
    for receipt in db["sheets_history_receipts"].docs:
        source = receipt["source_payload"]
        if kind == "question":
            source.update(status="BANNED", text="", answer=None)
        else:
            source["answer"].update(status="BANNED", text="")
        receipt["source_hash"] = item_source_fingerprint(source)
    gateway.resources["1"] = copy.deepcopy(db["sheets_history_receipts"].docs[0]["source_payload"])
    return db, queue, head, runner, gateway


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("banned source tests forbid sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["question", "answer"])
async def test_verified_banned_present_empty_materializes_without_detail_get(kind: str) -> None:
    db, queue, head, runner, gateway = banned(kind)
    result = await runner.fetch_and_hydrate(
        copy.deepcopy(db["sheets_formula_recovery_jobs"].docs[0]), head, gateway
    )
    assert result.fetched_count == 1 and gateway.calls == []
    detail = next(r for r in db["sheets_history_receipts"].docs if r["kind"] == "detail")
    assert detail["source_version"] == "questions.scan.v4.verified"
    if kind == "question":
        assert detail["payload"]["status"] == "BANNED" and detail["payload"]["text"] == ""
    else:
        assert (
            detail["payload"]["answer"]["status"] == "BANNED"
            and detail["payload"]["answer"]["text"] == ""
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["question", "answer"])
async def test_actual_writer_schema_and_reader_preserve_known_empty_without_hidden_text(
    kind: str,
) -> None:
    db, queue, head, runner, gateway = banned(kind)
    head = await runner.fetch_and_hydrate(
        copy.deepcopy(db["sheets_formula_recovery_jobs"].docs[0]), head, gateway
    )
    head = await runner.begin_publication(await f.claimed(queue), head)
    publisher = HistoryQuestionPublisher(runner.continuation)
    head = await publisher.batch(await f.claimed(queue), head)
    head = await publisher.finalize(await f.claimed(queue), head)
    assert head.phase == "completed" and gateway.calls == []
    repo = FormulaReadModelRepository(db=db)
    await repo.require_questions_read_model_productive(
        seller_id=f.f.SELLER, date_from=f.f.START, date_to=f.f.END, formula="ZELERDATA_PREGUNTAS"
    )
    rows = await repo.find_questions(seller_id=f.f.SELLER, date_from=f.f.START, date_to=f.f.END)
    assert len(rows) == 1
    if kind == "question":
        assert (
            rows[0]["status"] == "BANNED"
            and rows[0]["text"] == ""
            and rows[0].get("answer") is None
        )
    else:
        assert rows[0]["answer"]["status"] == "BANNED" and rows[0]["answer"]["text"] == ""


@pytest.mark.parametrize("kind", ["question", "answer"])
@pytest.mark.parametrize("missing", ["none", "absent"])
def test_banned_unknown_text_never_becomes_known_empty(kind: str, missing: str) -> None:
    db, queue, head, runner, gateway = banned(kind)
    source = copy.deepcopy(gateway.resources["1"])
    target = source if kind == "question" else source["answer"]
    if missing == "none":
        target["text"] = None
    else:
        target.pop("text")
    assert _complete_scan_question(source, head) is False


@pytest.mark.parametrize("kind", ["question", "answer"])
def test_non_banned_empty_keeps_existing_incomplete_policy(kind: str) -> None:
    db, queue, head, runner, gateway = f.prepared(1)
    source = copy.deepcopy(gateway.resources["1"])
    if kind == "question":
        source["text"] = ""
    else:
        source["answer"]["text"] = ""
    assert _complete_scan_question(source, head) is False


def test_banned_answer_missing_status_is_not_defaulted_to_active() -> None:
    db, queue, head, runner, gateway = banned("answer")
    source = copy.deepcopy(gateway.resources["1"])
    source["answer"].pop("status")
    assert _complete_scan_question(source, head) is False
