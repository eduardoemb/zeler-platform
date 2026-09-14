import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from zeler_sheets.formulas import recovery_worker as module
from zeler_sheets.formulas.recovery import ItemIdsRecoveryRequest


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["acquisition", "lease", "projection", "cancel"])
async def test_written_siblings_are_projected_before_acquisition_error_is_propagated(
    monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    identities = tuple(f"MLM{i:03d}" for i in range(10))
    written: dict[str, str] = {}
    receipts: dict[str, str] = {}
    finished: list[Any] = []
    history: list[str] = []
    first_written = asyncio.Event()

    async def acquire(**kwargs: Any) -> Any:
        ids = kwargs["acquire_item_ids"]
        for identity in ids:
            written[identity] = "fresh source"
        if ids[0] == identities[0]:
            first_written.set()
            return SimpleNamespace(item_details_stale_unavailable=0, diagnostic_reason_counts={})
        await first_written.wait()
        if scenario == "cancel":
            raise asyncio.CancelledError
        raise RuntimeError("synthetic failure after legitimate persisted writes")

    class Collection:
        reads = 0

        async def find_one(self, *args: Any) -> Any:
            self.reads += 1
            return None if scenario == "lease" and self.reads > 1 else {"owned": True}

        def find(self, *args: Any) -> Any:
            return self

        async def to_list(self, **kwargs: Any) -> Any:
            return [{"_id": i} for i in sorted(written)]

    class Queue:
        collection = Collection()

        def now(self) -> datetime:
            return datetime.now(UTC)

        def _owned(self, *args: Any) -> dict[str, Any]:
            return {}

        async def finish(self, *args: Any, **kwargs: Any) -> None:
            finished.append(kwargs)

    class Persistence:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def project_acquired_item_history(self, **kwargs: Any) -> None:
            history.append(kwargs["item_id"])

    async def project(**kwargs: Any) -> None:
        if scenario == "projection":
            raise OSError("synthetic projection failure")
        for identity in kwargs["item_ids"]:
            receipts[identity] = written[identity]

    monkeypatch.setattr(module, "run_item_detail_enrichment", acquire)
    monkeypatch.setattr(module, "SheetsEventPersistence", Persistence)
    monkeypatch.setattr(module, "run_sheetseller_backfill", project)
    worker = module.FormulaRecoveryWorker(
        db={"items": Collection()}, gateway=None, queue=cast("Any", Queue())
    )
    expected = {"lease": ValueError, "cancel": asyncio.CancelledError}.get(scenario, RuntimeError)
    with pytest.raises(expected) as caught:
        await worker._acquire_item_batch({}, ItemIdsRecoveryRequest("123", identities))
    assert set(written) == set(identities)
    assert not finished
    if scenario == "acquisition":
        assert receipts == written, "joined persisted sibling writes must not leave stale receipts"
        assert set(history) == set(written)
    else:
        assert not receipts
    if scenario in {"lease", "cancel"}:
        assert not history
    if scenario == "projection":
        assert isinstance(caught.value.__cause__, OSError)
        assert "synthetic failure" in str(caught.value)
