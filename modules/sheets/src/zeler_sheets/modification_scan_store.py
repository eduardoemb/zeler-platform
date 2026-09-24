"""Durable modification-page evidence; no read-model coverage claim."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from bson import BSON
from pymongo.errors import DuplicateKeyError

from zeler_platform_core.models import SheetsHistoryReceipt
from zeler_sheets.formulas.recovery import FormulaRecoveryQueue, ModifiedOrderIdsRecoveryRequest
from zeler_sheets.history_acquisition import HistoryLimitError, _document
from zeler_sheets.item_projection import item_source_fingerprint
from zeler_sheets.modification_recovery import (
    ModificationEnumerationDriftError,
    ModificationSearchPage,
    admit_modifications,
    modification_window,
)

PLAN_COLLECTION = "sheets_history_backfill_plans"
RECEIPT_COLLECTION = "sheets_history_receipts"
MAX_MODIFICATION_RESULTS = 10000
SCAN_INTERVAL = timedelta(minutes=15)
MAX_SCAN_GENERATION = 4


class ModificationScanBlockedError(ValueError):
    """A terminal ID recovery failed, so this scan cannot certify completion."""


@dataclass(frozen=True)
class ModificationScan:
    seller_id: str
    scan_id: str
    watermark: datetime
    cutoff: datetime
    phase: Literal["discover", "verify", "completed", "failed"]
    next_offset: int
    source_total: int | None
    page_sequence: int
    revision: int
    generation: int = 1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.seller_id, str)
            or not self.seller_id.isascii()
            or not self.seller_id.isdecimal()
            or not isinstance(self.scan_id, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.scan_id) is None
            or not isinstance(self.watermark, datetime)
            or not isinstance(self.cutoff, datetime)
            or self.watermark.tzinfo is None
            or self.cutoff.tzinfo is None
            or self.watermark > self.cutoff
            or self.phase not in {"discover", "verify", "completed", "failed"}
            or type(self.next_offset) is not int
            or self.next_offset < 0
            or (
                self.source_total is not None
                and (
                    type(self.source_total) is not int
                    or not 0 <= self.source_total <= MAX_MODIFICATION_RESULTS
                    or self.next_offset > self.source_total
                )
            )
            or (self.source_total is None and self.next_offset != 0)
            or (self.phase not in {"discover", "failed"} and self.source_total is None)
            or (self.phase == "failed" and (self.next_offset != 0 or self.source_total is not None))
            or (self.phase == "completed" and self.next_offset != self.source_total)
            or type(self.page_sequence) is not int
            or self.page_sequence < 0
            or type(self.revision) is not int
            or self.revision < 0
            or type(self.generation) is not int
            or self.generation < 1
        ):
            raise ValueError("modification scan state is invalid")
        object.__setattr__(self, "watermark", self.watermark.astimezone(UTC))
        object.__setattr__(self, "cutoff", self.cutoff.astimezone(UTC))

    def document(self) -> dict[str, Any]:
        return {
            "seller_id": self.seller_id,
            "scan_id": self.scan_id,
            "watermark": self.watermark,
            "cutoff": self.cutoff,
            "phase": self.phase,
            "next_offset": self.next_offset,
            "source_total": self.source_total,
            "page_sequence": self.page_sequence,
            "revision": self.revision,
            "generation": self.generation,
        }


def _scan_from(document: dict[str, Any]) -> ModificationScan:
    return ModificationScan(**document)


class ModificationScanStore:
    def __init__(self, db: Any, queue: FormulaRecoveryQueue, *, now: Any) -> None:
        self.db = db
        self.queue = queue
        self.now = now
        self.plans = db[PLAN_COLLECTION]
        self.receipts = db[RECEIPT_COLLECTION]

    async def begin(self, seller_id: str, *, cutoff: datetime) -> ModificationScan:
        if not seller_id.isascii() or not seller_id.isdecimal() or cutoff.tzinfo is None:
            raise ValueError("modification scan requires a seller and UTC cutoff")
        cutoff = cutoff.astimezone(UTC)
        plan = await self.plans.find_one({"_id": seller_id, "seller_id": seller_id})
        if not isinstance(plan, dict) or not isinstance(plan.get("cutoff"), datetime):
            raise ValueError("modification scan requires a fixed pilot plan")
        current = plan.get("modification_scan")
        if isinstance(current, dict):
            previous = _scan_from(current)
            if previous.phase != "completed" or cutoff < previous.cutoff + SCAN_INTERVAL:
                return previous
        watermark = plan.get("modification_watermark") or plan["cutoff"]
        if not isinstance(watermark, datetime) or watermark.tzinfo is None:
            raise ValueError("modification watermark is invalid")
        watermark = watermark.astimezone(UTC)
        modification_window(watermark, cutoff)
        identity = hashlib.sha256(
            "\0".join(
                (seller_id, watermark.isoformat(), cutoff.isoformat(), "modifications")
            ).encode()
        ).hexdigest()
        scan = ModificationScan(
            seller_id=seller_id,
            scan_id=identity,
            watermark=watermark,
            cutoff=cutoff,
            phase="discover",
            next_offset=0,
            source_total=None,
            page_sequence=0,
            revision=0,
        )
        filter_spec: dict[str, Any] = {"_id": seller_id, "seller_id": seller_id}
        if isinstance(current, dict):
            filter_spec["modification_scan.scan_id"] = current.get("scan_id")
            filter_spec["modification_scan.phase"] = "completed"
            filter_spec["modification_scan.revision"] = current.get("revision")
        else:
            filter_spec["modification_scan"] = {"$exists": False}
        await self.plans.update_one(filter_spec, {"$set": {"modification_scan": scan.document()}})
        stored = await self.plans.find_one({"_id": seller_id, "seller_id": seller_id})
        if not isinstance(stored, dict) or not isinstance(stored.get("modification_scan"), dict):
            raise ModificationEnumerationDriftError("modification scan admission lost")
        return _scan_from(stored["modification_scan"])

    async def advance(
        self, scan: ModificationScan, page: ModificationSearchPage
    ) -> ModificationScan:
        if scan.phase in {"completed", "failed"}:
            raise ValueError("terminal modification scan cannot advance")
        if (
            page.page.seller_id != scan.seller_id
            or page.page.watermark != scan.watermark
            or page.page.cutoff != scan.cutoff
            or type(page.source_total) is not int
            or not 0 <= page.source_total <= MAX_MODIFICATION_RESULTS
            or (scan.source_total is not None and page.source_total != scan.source_total)
            or len(page.page.rows) > 50
        ):
            raise ModificationEnumerationDriftError("modification page binding changed")
        next_offset = scan.next_offset + len(page.page.rows)
        if (
            next_offset > page.source_total
            or page.next_offset != (None if next_offset == page.source_total else next_offset)
            or (not page.page.rows and scan.next_offset != page.source_total)
        ):
            raise ModificationEnumerationDriftError("modification page cursor changed")
        receipts = [self._receipt(scan, row) for row in page.page.rows]
        if scan.phase == "discover":
            outcome = (await admit_modifications(self.queue, [page.page]))[0]
            if outcome.state == "deferred":
                return scan
            if outcome.state != "admitted":
                raise ModificationEnumerationDriftError("modification page could not be admitted")
        else:
            for receipt in receipts:
                baseline = await self.receipts.find_one(
                    {
                        "acquisition_id": scan.scan_id,
                        "generation": scan.generation,
                        "pass_number": 1,
                        "resource_id": receipt.resource_id,
                    },
                    {"kind": 1, "source_version": 1, "source_hash": 1},
                )
                if baseline is None or any(
                    baseline.get(field) != getattr(receipt, field)
                    for field in ("kind", "source_version", "source_hash")
                ):
                    raise ModificationEnumerationDriftError(
                        "modification verification manifest changed"
                    )
                if receipt.kind != "membership":
                    continue
                request = ModifiedOrderIdsRecoveryRequest(
                    scan.seller_id,
                    (receipt.resource_id,),
                    modified_version=receipt.source_version or "",
                    source_hash=receipt.source_hash or "",
                )
                job = await self.queue.collection.find_one(
                    {"_id": request.key, "seller_id": scan.seller_id}, {"state": 1}
                )
                if not job or job.get("state") in {"pending", "running"}:
                    return scan
                if job.get("state") != "completed":
                    raise ModificationScanBlockedError("modified order recovery did not complete")
        return await self._checkpoint(scan, page, receipts)

    async def restart(self, scan: ModificationScan) -> ModificationScan:
        """Restart a drifting traversal without advancing its watermark."""
        if scan.phase in {"completed", "failed"}:
            raise ValueError("terminal modification scan cannot restart")
        generation = scan.generation + 1
        proposed = ModificationScan(
            seller_id=scan.seller_id,
            scan_id=scan.scan_id,
            watermark=scan.watermark,
            cutoff=scan.cutoff,
            phase="failed" if generation > MAX_SCAN_GENERATION else "discover",
            next_offset=0,
            source_total=None,
            page_sequence=0,
            revision=scan.revision + 1,
            generation=generation,
        )
        result = await self.plans.update_one(
            {
                "_id": scan.seller_id,
                "seller_id": scan.seller_id,
                "modification_scan": scan.document(),
            },
            {"$set": {"modification_scan": proposed.document()}},
        )
        if result.matched_count != 1:
            raise ModificationEnumerationDriftError("modification restart lost its revision")
        return proposed

    def _receipt(self, scan: ModificationScan, row: dict[str, Any]) -> SheetsHistoryReceipt:
        identity = str(row.get("id", ""))
        try:
            modified = datetime.fromisoformat(str(row["date_last_updated"]).replace("Z", "+00:00"))
        except (KeyError, ValueError) as error:
            raise ModificationEnumerationDriftError(
                "modification receipt time is invalid"
            ) from error
        if (
            not identity.isascii()
            or not identity.isdecimal()
            or modified.tzinfo is None
            or not isinstance(row.get("seller"), dict)
            or str(row["seller"].get("id")) != scan.seller_id
        ):
            raise ModificationEnumerationDriftError("modification receipt scope is invalid")
        start, end = modification_window(scan.watermark, scan.cutoff)
        inside = start <= modified.astimezone(UTC) < end
        kind = "membership" if inside else "exclusion"
        receipt_id = hashlib.sha256(
            "\0".join(
                (
                    scan.scan_id,
                    str(scan.generation),
                    str(1 if scan.phase == "discover" else 2),
                    kind,
                    identity,
                )
            ).encode()
        ).hexdigest()
        return SheetsHistoryReceipt.model_validate(
            {
                "_id": receipt_id,
                "acquisition_id": scan.scan_id,
                "seller_id": scan.seller_id,
                "read_model": "orders",
                "generation": scan.generation,
                "pass_number": 1 if scan.phase == "discover" else 2,
                "page_sequence": scan.page_sequence + 1,
                "kind": kind,
                "resource_id": identity,
                "observed_at": self.now(),
                "source_version": modified.astimezone(UTC).isoformat(),
                "source_hash": item_source_fingerprint(row),
                "source_payload": row,
                "exclusion_reason": None if inside else "outside_requested_modification_interval",
            }
        )

    async def _checkpoint(
        self,
        scan: ModificationScan,
        page: ModificationSearchPage,
        receipts: list[SheetsHistoryReceipt],
    ) -> ModificationScan:
        documents = [_document(receipt, 1024 * 1024) for receipt in receipts]
        if sum(len(BSON.encode(document)) for document in documents) > 4 * 1024 * 1024:
            raise HistoryLimitError("modification page exceeds local transaction byte budget")
        final_page = page.next_offset is None
        next_phase: Literal["discover", "verify", "completed"] = cast(
            Literal["discover", "verify"], scan.phase
        )
        if final_page:
            next_phase = "verify" if scan.phase == "discover" else "completed"
        cursor = (
            (0 if scan.phase == "discover" else page.source_total)
            if final_page
            else page.next_offset
        )
        if cursor is None:
            raise ModificationEnumerationDriftError("modification cursor disappeared")
        proposed = ModificationScan(
            seller_id=scan.seller_id,
            scan_id=scan.scan_id,
            watermark=scan.watermark,
            cutoff=scan.cutoff,
            phase=next_phase,
            next_offset=cursor,
            source_total=page.source_total,
            page_sequence=scan.page_sequence + 1,
            revision=scan.revision + 1,
            generation=scan.generation,
        )

        async def transaction(session: Any) -> ModificationScan:
            plan = await self.plans.find_one(
                {"_id": scan.seller_id, "seller_id": scan.seller_id}, session=session
            )
            if not isinstance(plan, dict) or plan.get("modification_scan") != scan.document():
                raise ModificationEnumerationDriftError("modification checkpoint owner changed")
            scope = {"acquisition_id": scan.scan_id, "generation": scan.generation}
            for document in documents:
                if scan.phase == "verify":
                    baseline = await self.receipts.find_one(
                        {
                            **scope,
                            "pass_number": 1,
                            "resource_id": document["resource_id"],
                        },
                        session=session,
                    )
                    if baseline is None or any(
                        baseline.get(field) != document.get(field)
                        for field in ("kind", "source_version", "source_hash")
                    ):
                        raise ModificationEnumerationDriftError(
                            "modification verification manifest changed"
                        )
                if await self.receipts.find_one(
                    {
                        **scope,
                        "pass_number": document["pass_number"],
                        "resource_id": document["resource_id"],
                    },
                    session=session,
                ):
                    raise ModificationEnumerationDriftError(
                        "modification scan repeated a source identity"
                    )
                try:
                    await self.receipts.insert_one(document, session=session)
                except DuplicateKeyError as error:
                    raise ModificationEnumerationDriftError(
                        "modification receipt identity collided"
                    ) from error
            if final_page:
                count = await self.receipts.count_documents(
                    {**scope, "pass_number": 1 if scan.phase == "discover" else 2},
                    session=session,
                )
                if count != page.source_total:
                    raise ModificationEnumerationDriftError(
                        "modification manifest count differs from source total"
                    )
            update: dict[str, Any] = {"modification_scan": proposed.document()}
            if next_phase == "completed":
                update["modification_watermark"] = scan.cutoff
            result = await self.plans.update_one(
                {
                    "_id": scan.seller_id,
                    "seller_id": scan.seller_id,
                    "modification_scan.scan_id": scan.scan_id,
                    "modification_scan.revision": scan.revision,
                },
                {"$set": update},
                session=session,
            )
            if result.matched_count != 1:
                raise ModificationEnumerationDriftError("modification checkpoint lost its revision")
            return proposed

        async with await self.db.client.start_session() as session:
            return cast(ModificationScan, await session.with_transaction(transaction))
