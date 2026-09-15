"""Bounded staging transactions; these receipts never establish publication coverage."""

from __future__ import annotations

import math
from typing import Any

from bson import BSON
from bson.codec_options import CodecOptions
from bson.errors import InvalidDocument
from pymongo.errors import DuplicateKeyError

from zeler_platform_core.models import (
    SheetsHistoryAcquisition,
    SheetsHistoryOrderRange,
    SheetsHistoryReceipt,
)
from zeler_sheets.formulas.recovery import FormulaRecoveryQueue
from zeler_sheets.item_projection import item_source_fingerprint

IDENTITY = ("acquisition_id", "generation", "pass_number", "kind", "resource_id")
HEAD_IDENTITY = (
    "_id",
    "seller_id",
    "read_model",
    "plan_id",
    "scope_id",
    "job_id",
    "date_from",
    "date_to",
    "generation",
    "pass_number",
    "created_at",
)


class HistoryConflictError(ValueError):
    """Ownership, checkpoint or source evidence changed; callers must reconcile."""


class HistoryLimitError(ValueError):
    """A local staging budget was exceeded, not an upstream retention limit."""


def _safe(value: Any, depth: int = 0) -> None:
    if depth > 64:
        raise HistoryLimitError("receipt nesting exceeds local budget")
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str) or key.startswith("$") or "." in key or "\0" in key:
                raise ValueError("unsafe BSON field name")
            _safe(nested, depth + 1)
    elif isinstance(value, list):
        for nested in value:
            _safe(nested, depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("nonfinite payload number")


def _document(
    model: SheetsHistoryAcquisition | SheetsHistoryReceipt | SheetsHistoryOrderRange, limit: int
) -> dict[str, Any]:
    payload = model.model_dump(by_alias=True)
    _safe(payload)
    try:
        encoded = BSON.encode(payload)
    except (InvalidDocument, OverflowError) as error:
        raise ValueError("receipt is not BSON serializable") from error
    if len(encoded) > limit:
        raise HistoryLimitError("whole document exceeds local byte budget")
    return dict(encoded.decode(codec_options=CodecOptions(tz_aware=True)))


def _head(model: SheetsHistoryAcquisition) -> SheetsHistoryAcquisition:
    validated = SheetsHistoryAcquisition.model_validate(model.model_dump(by_alias=True))
    return SheetsHistoryAcquisition.model_validate(_document(validated, 64 * 1024))


def _same_receipt(left: dict[str, Any], right: dict[str, Any]) -> bool:
    ignored = {"_id", "page_sequence", "observed_at"}
    return {key: value for key, value in left.items() if key not in ignored} == {
        key: value for key, value in right.items() if key not in ignored
    }


class HistoryAcquisitionStore:
    def __init__(self, db: Any, queue: FormulaRecoveryQueue) -> None:
        self.db = db
        self.queue = queue
        self.heads = db["sheets_history_acquisitions"]
        self.receipts = db["sheets_history_receipts"]

    async def _fence(
        self, job: dict[str, Any], head: SheetsHistoryAcquisition, session: Any
    ) -> None:
        if head.read_model not in self.queue.enabled_models or (
            self.queue.allowed_sellers is not None
            and head.seller_id not in self.queue.allowed_sellers
        ):
            raise HistoryConflictError("history recovery is disabled for this seller or resource")
        if job.get("seller_id") != head.seller_id or job.get("read_model") != head.read_model:
            raise HistoryConflictError("job identity does not match acquisition")
        if job.get("_id") != head.job_id:
            raise HistoryConflictError("job does not own acquisition")
        owned = {
            **self.queue._owned(job, self.queue.now()),
            "seller_id": head.seller_id,
            "read_model": head.read_model,
            "date_from": head.date_from,
            "date_to": head.date_to,
        }
        result = await self.queue.collection.update_one(
            owned, {"$inc": {"history_fence_revision": 1}}, session=session
        )
        if result.matched_count != 1:
            raise HistoryConflictError("history recovery lease lost")

    async def initialize(
        self, job: dict[str, Any], initial: SheetsHistoryAcquisition
    ) -> SheetsHistoryAcquisition:
        initial = _head(initial)
        if (
            initial.phase != "discover"
            or initial.checkpoint_revision
            or initial.page_sequence
            or initial.discovered_count
            or initial.fetched_count
            or initial.published_count
            or initial.generation != 1
            or initial.pass_number != 1
            or initial.next_cursor is not None
        ):
            raise HistoryConflictError("initial acquisition must have no staging progress")
        payload = initial.model_dump(by_alias=True)

        async def transaction(session: Any) -> SheetsHistoryAcquisition:
            await self._fence(job, initial, session)
            stored = await self.heads.find_one({"_id": initial.id}, session=session)
            if stored is None:
                try:
                    await self.heads.insert_one(payload, session=session)
                except DuplicateKeyError as error:
                    raise HistoryConflictError(
                        "acquisition scope already has another identity"
                    ) from error
                stored = payload
            if any(
                stored.get(field) != payload[field]
                for field in HEAD_IDENTITY
                if field not in {"generation", "pass_number"}
            ):
                raise HistoryConflictError("acquisition identity changed")
            await self._fence(job, initial, session)
            return SheetsHistoryAcquisition.model_validate(stored)

        async with await self.db.client.start_session() as session:
            return SheetsHistoryAcquisition.model_validate(
                await session.with_transaction(transaction)
            )

    async def checkpoint(
        self,
        job: dict[str, Any],
        expected: SheetsHistoryAcquisition,
        proposed: SheetsHistoryAcquisition,
        receipts: list[SheetsHistoryReceipt],
        *,
        session: Any = None,
    ) -> SheetsHistoryAcquisition:
        expected, proposed = _head(expected), _head(proposed)
        before, after = expected.model_dump(by_alias=True), proposed.model_dump(by_alias=True)
        if any(before[field] != after[field] for field in HEAD_IDENTITY):
            raise HistoryConflictError("checkpoint cannot change acquisition identity")
        if (
            proposed.phase not in {"discover", "hydrate", "verify"}
            or expected.phase not in {"discover", "hydrate", "verify"}
            or proposed.checkpoint_revision != expected.checkpoint_revision + 1
            or proposed.page_sequence != expected.page_sequence + 1
            or proposed.published_count
            or expected.published_count
            or proposed.drift_restarts != expected.drift_restarts
            or proposed.updated_at < expected.updated_at
            or proposed.publish_after is not None
        ):
            raise HistoryConflictError("invalid staging checkpoint transition")
        if len(receipts) > 50 or sum(receipt.kind == "detail" for receipt in receipts) > 20:
            raise HistoryLimitError("staging batch exceeds local record budget")
        documents = []
        for receipt in receipts:
            validated = SheetsHistoryReceipt.model_validate(receipt.model_dump(by_alias=True))
            document = _document(validated, 1024 * 1024)
            if any(
                document[field] != after[head_field]
                for field, head_field in (
                    ("acquisition_id", "_id"),
                    ("seller_id", "seller_id"),
                    ("read_model", "read_model"),
                    ("generation", "generation"),
                    ("pass_number", "pass_number"),
                    ("page_sequence", "page_sequence"),
                )
            ):
                raise HistoryConflictError("receipt does not belong to checkpoint")
            if validated.source_payload is not None and (
                str(validated.source_payload.get("id")) != validated.resource_id
                or item_source_fingerprint(validated.source_payload) != validated.source_hash
            ):
                raise HistoryConflictError("source identity or fingerprint mismatch")
            if validated.source_payload is not None:
                source = validated.source_payload
                seller = source.get("seller")
                seller_ids = [source.get("seller_id")]
                if isinstance(seller, dict):
                    seller_ids.append(seller.get("id"))
                if any(
                    seller_id is not None and str(seller_id) != validated.seller_id
                    for seller_id in seller_ids
                ):
                    raise HistoryConflictError("source seller mismatch")
            if validated.kind == "detail" and (
                str((validated.payload or {}).get("id")) != validated.resource_id
                or item_source_fingerprint(validated.payload or {}) != validated.payload_hash
            ):
                raise HistoryConflictError("detail identity or payload fingerprint mismatch")
            documents.append(document)
        if len({tuple(document[field] for field in IDENTITY) for document in documents}) != len(
            documents
        ):
            raise HistoryConflictError("batch repeats a receipt identity")
        if (
            sum(len(BSON.encode(document)) for document in [before, after, *documents])
            > 4 * 1024 * 1024
        ):
            raise HistoryLimitError("staging transaction exceeds local byte budget")

        async def transaction(session: Any) -> SheetsHistoryAcquisition:
            await self._fence(job, expected, session)
            current = await self.heads.find_one({"_id": expected.id}, session=session)
            if current is not None:
                current = SheetsHistoryAcquisition.model_validate(current).model_dump(by_alias=True)
            replay = current == after
            if current != before and not replay:
                raise HistoryConflictError("stale acquisition checkpoint")
            discovered = fetched = 0
            for document in documents:
                identity = {field: document[field] for field in IDENTITY}
                stored = await self.receipts.find_one(identity, session=session)
                if stored is not None:
                    if not _same_receipt(stored, document):
                        raise HistoryConflictError(
                            "conflicting source receipt requires drift reconciliation"
                        )
                    continue
                if replay:
                    raise HistoryConflictError("checkpoint replay is missing a receipt")
                if document["kind"] == "detail" and not await self.receipts.find_one(
                    {**identity, "kind": "membership"}, session=session
                ):
                    raise HistoryConflictError("detail has no acquired membership")
                try:
                    await self.receipts.insert_one(document, session=session)
                except DuplicateKeyError as error:
                    raise HistoryConflictError("receipt storage identity collision") from error
                discovered += document["kind"] == "membership"
                fetched += document["kind"] == "detail"
            if not replay:
                if (
                    proposed.discovered_count != expected.discovered_count + discovered
                    or proposed.fetched_count != expected.fetched_count + fetched
                ):
                    raise HistoryConflictError("checkpoint counts do not match new receipts")
                result = await self.heads.replace_one(
                    {
                        "_id": expected.id,
                        "generation": expected.generation,
                        "checkpoint_revision": expected.checkpoint_revision,
                    },
                    after,
                    session=session,
                )
                if result.matched_count != 1:
                    raise HistoryConflictError("checkpoint compare-and-swap lost")
            await self._fence(job, proposed, session)
            return proposed

        if session is not None:
            if not session.in_transaction:
                raise ValueError("history checkpoint requires an active transaction")
            return await transaction(session)
        async with await self.db.client.start_session() as owned_session:
            return SheetsHistoryAcquisition.model_validate(
                await owned_session.with_transaction(transaction)
            )
