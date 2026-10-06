"""Shared question-scan admission identity; no provider cursor interpretation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from zeler_platform_core.models import SheetsHistoryAcquisition, SheetsHistoryReceipt
from zeler_sheets.event_persistence import _canonical_question_document
from zeler_sheets.formulas.pacing import recovery_fetch_resource
from zeler_sheets.formulas.recovery import QuestionScanRecoveryRequest
from zeler_sheets.history_acquisition import HistoryAcquisitionStore, HistoryConflictError, _head
from zeler_sheets.history_continuation import HistoryContinuation
from zeler_sheets.item_projection import item_source_fingerprint
from zeler_sheets.pilot_history import HistoryPlanner


async def initialize_question_scan(
    store: HistoryAcquisitionStore,
    job: dict[str, Any],
    request: QuestionScanRecoveryRequest,
) -> SheetsHistoryAcquisition:
    request.validate_existing(job)
    if job.get("history_protocol_version") != 1 or job.get("history_acquisition_id") != request.key:
        raise HistoryConflictError("question scan requires its history-only admission")
    initial = SheetsHistoryAcquisition(
        _id=request.key,
        seller_id=request.seller_id,
        read_model="questions",
        plan_id=request.plan_id,
        scope_id="seller_scan",
        job_id=request.key,
        date_from=request.date_from,
        date_to=request.date_to,
        created_at=job["created_at"],
        updated_at=job["created_at"],
    )
    return await store.initialize(job, initial)


@dataclass(frozen=True)
class QuestionScanPage:
    """Normalized provider observation; cursor replacement/expiry is adapter authority."""

    rows: list[dict[str, Any]]
    total: int
    next_cursor: str | None
    terminal: bool
    observed_at: datetime


def normalize_question_scan_page(
    raw: dict[str, Any], *, discovered_count: int, observed_at: datetime
) -> QuestionScanPage:
    """Stop at the verified total even when the provider returns another cursor."""
    if not isinstance(raw, dict):
        raise ValueError("question scan response must be an object")
    total, rows, cursor = raw.get("total"), raw.get("questions"), raw.get("scroll_id")
    if (
        type(total) is not int
        or not 0 <= total <= 10000
        or type(discovered_count) is not int
        or not 0 <= discovered_count <= total
        or not isinstance(rows, list)
        or len(rows) > 50
        or any(not isinstance(row, dict) for row in rows)
        or observed_at.tzinfo is None
    ):
        raise ValueError("invalid question scan response or local budget")
    count = discovered_count + len(rows)
    if count > total:
        raise ValueError("question scan exceeded the reported total")
    terminal = count == total
    if not terminal and (not rows or not isinstance(cursor, str) or not cursor):
        raise ValueError("question scan has no usable continuation")
    return QuestionScanPage(rows, total, None if terminal else cursor, terminal, observed_at)


def _question_created_millisecond(value: datetime) -> datetime:
    """Search exposes microseconds; the v4 detail endpoint truncates to milliseconds."""
    utc = value.astimezone(UTC)
    return utc.replace(microsecond=utc.microsecond // 1000 * 1000)


async def fetch_question_scan_page(
    gateway: Any,
    *,
    seller_id: str,
    cursor: str | None,
    discovered_count: int,
    observed_at: datetime | None = None,
) -> QuestionScanPage:
    """Fetch one bounded seller scan page through the configured gateway."""
    if not seller_id.isascii() or not seller_id.isdecimal():
        raise ValueError("question scan requires a numeric seller")
    if cursor is not None and (not isinstance(cursor, str) or not cursor):
        raise ValueError("question scan cursor is invalid")
    params = {"seller_id": seller_id, "api_version": "4", "search_type": "scan"}
    if cursor is None:
        params["limit"] = "50"
    else:
        params["scroll_id"] = cursor
    raw = await recovery_fetch_resource(
        gateway,
        request_timeout=10,
        seller_id=seller_id,
        path="/questions/search?" + urlencode(params),
    )
    return normalize_question_scan_page(
        raw, discovered_count=discovered_count, observed_at=observed_at or datetime.now(UTC)
    )


@dataclass(frozen=True)
class QuestionDetailObservation:
    payload: dict[str, Any]
    observed_at: datetime
    source_version: str | None = None


@dataclass(frozen=True)
class QuestionMonthSubscription:
    """A deterministic acquisition binding, never a publication/coverage proof."""

    acquisition_id: str
    generation: int
    pass_number: int
    chunk_id: str
    date_from: datetime
    date_to: datetime


def question_subscriptions(head: SheetsHistoryAcquisition) -> tuple[QuestionMonthSubscription, ...]:
    head = _head(head)
    if (
        head.read_model != "questions"
        or head.phase != "verify"
        or head.pass_number < 2
        or head.next_cursor is not None
        or head.page_sequence == 0
        or head.source_total != head.discovered_count
        or head.observed_until is None
    ):
        raise ValueError("subscriptions require the finished verification traversal")
    plan = HistoryPlanner(cutoff=head.date_to, months=12).plan_for("questions")
    if plan.chunks[0].start != head.date_from:
        raise ValueError("subscriptions do not match the fixed twelve-month plan")
    return tuple(
        QuestionMonthSubscription(
            head.id, head.generation, head.pass_number, chunk.id, chunk.start, chunk.end
        )
        for chunk in plan.chunks
    )


class QuestionManifestDriftError(HistoryConflictError):
    """A traversal changed its membership or observed source payloads."""


class QuestionCursorExpiredError(HistoryConflictError):
    """A durable page observation no longer permits reusing its provider cursor."""


class QuestionCursorClockError(HistoryConflictError):
    """Missing/future observation cannot establish provider cursor age."""


SCAN_VERSION = "questions.scan.v4.verified"
OUTSIDE = "outside_requested_creation_interval"


def _source_created(source: dict[str, Any]) -> datetime:
    value = source.get("date_created")
    if not isinstance(value, str):
        raise HistoryConflictError("question creation observation unavailable")
    try:
        created = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise HistoryConflictError("question creation observation invalid") from error
    if created.tzinfo is None:
        raise HistoryConflictError("question creation timezone unavailable")
    return _question_created_millisecond(created)


def _complete_scan_question(source: dict[str, Any], head: SheetsHistoryAcquisition) -> bool:
    """Presence is required before canonical validation; never fabricate defaults."""
    missing = False
    status = source.get("status")
    if status is None:
        missing = True
    elif not isinstance(status, str) or not status:
        raise HistoryConflictError("question scan status invalid")
    for value in (source.get("text"),):
        if value is None or value == "":
            missing = True
        elif not isinstance(value, str):
            raise HistoryConflictError("question scan text invalid")
    for key, nested, alternatives in (
        ("item_id", "item", ("id", "item_id")),
        ("from_user_id", "from", ("id", "user_id")),
    ):
        value = source.get(key)
        if value is None and nested in source:
            container = source[nested]
            if not isinstance(container, dict):
                raise HistoryConflictError("question scan identity field invalid")
            value = next((container[k] for k in alternatives if container.get(k) is not None), None)
        if key == "from_user_id" and value is None:
            value = source.get("user_id")
        if value is None or value == "":
            missing = True
        elif isinstance(value, bool) or not isinstance(value, (str, int)):
            raise HistoryConflictError("question scan identity field invalid")
    if status == "ANSWERED":
        answer = source.get("answer")
        if answer is None:
            missing = True
        elif not isinstance(answer, dict):
            raise HistoryConflictError("question scan answer invalid")
        else:
            text = answer.get("text")
            answer_status = answer.get("status")
            if answer_status is None:
                missing = True
            elif not isinstance(answer_status, str) or not answer_status:
                raise HistoryConflictError("question scan answer status invalid")
            date = (
                answer.get("date_created") or answer.get("answered_at") or answer.get("created_at")
            )
            if text is None or text == "" or date is None:
                missing = True
            elif not isinstance(text, str) or not isinstance(date, str):
                raise HistoryConflictError("question scan answer invalid")
            else:
                try:
                    answered = datetime.fromisoformat(date.replace("Z", "+00:00"))
                except ValueError as error:
                    raise HistoryConflictError("question scan answer clock invalid") from error
                if answered.tzinfo is None or answered.astimezone(UTC) < _source_created(source):
                    raise HistoryConflictError("question scan answer clock invalid")
    if missing:
        return False
    try:
        _canonical_question_document(
            source, seller_id=head.seller_id, observed_at=head.observed_until or head.updated_at
        )
    except (ValueError, TypeError) as error:
        raise HistoryConflictError("question scan canonical fields invalid") from error
    return True


async def verified_question_members(
    store: HistoryAcquisitionStore,
    head: SheetsHistoryAcquisition,
    *,
    session: Any = None,
) -> list[SheetsHistoryReceipt]:
    """Two exhaustive concordant current passes, not an inherited partial manifest."""
    if (
        head.read_model != "questions"
        or head.phase not in {"verify", "publish", "completed"}
        or head.pass_number < 2
        or head.next_cursor is not None
        or head.observed_until is None
        or head.observed_from is None
        or head.source_total != head.discovered_count
    ):
        raise HistoryConflictError("question complete manifests unavailable")
    scope = {
        "acquisition_id": head.id,
        "generation": head.generation,
        "read_model": "questions",
        "seller_id": head.seller_id,
        "kind": "membership",
    }
    current = await store.receipts.find(
        {**scope, "pass_number": head.pass_number}, session=session
    ).to_list(length=10001)
    previous = await store.receipts.find(
        {**scope, "pass_number": head.pass_number - 1}, session=session
    ).to_list(length=10001)
    if (
        len(current) != head.source_total
        or len(previous) != head.source_total
        or len(current) > 10000
    ):
        raise HistoryConflictError("question manifests are incomplete")
    old: dict[str, SheetsHistoryReceipt] = {}
    for raw in previous:
        receipt = SheetsHistoryReceipt.model_validate(raw)
        if receipt.resource_id in old:
            raise HistoryConflictError("question previous manifest duplicated")
        if (
            receipt.source_payload is None
            or item_source_fingerprint(receipt.source_payload) != receipt.source_hash
        ):
            raise HistoryConflictError("question previous manifest fingerprint invalid")
        old[receipt.resource_id] = receipt
    members: list[SheetsHistoryReceipt] = []
    identities: set[str] = set()
    for raw in current:
        receipt = SheetsHistoryReceipt.model_validate(raw)
        source = receipt.source_payload
        if (
            source is None
            or item_source_fingerprint(source) != receipt.source_hash
            or receipt.resource_id in identities
            or receipt.resource_id not in old
            or old[receipt.resource_id].source_hash != receipt.source_hash
        ):
            raise HistoryConflictError("question verified manifests disagree")
        identity = str(source.get("id", ""))
        if (
            not identity.isascii()
            or not identity.isdecimal()
            or identity != receipt.resource_id
            or str(source.get("seller_id")) != head.seller_id
        ):
            raise HistoryConflictError("question verified membership scope invalid")
        if head.date_from <= _source_created(source) < head.date_to:
            _complete_scan_question(source, head)
        if (
            not head.observed_from <= receipt.observed_at <= head.observed_until
            or old[receipt.resource_id].observed_at > receipt.observed_at
        ):
            raise HistoryConflictError("question verified observation clock invalid")
        identities.add(receipt.resource_id)
        members.append(receipt)
    if identities != set(old):
        raise HistoryConflictError("question verified membership differs")
    return sorted(members, key=lambda r: r.resource_id)


async def question_target_members(
    store: HistoryAcquisitionStore, head: SheetsHistoryAcquisition, *, session: Any = None
) -> list[SheetsHistoryReceipt]:
    return [
        r
        for r in await verified_question_members(store, head, session=session)
        if head.date_from <= _source_created(r.source_payload or {}) < head.date_to
    ]


class QuestionScanStaging:
    def __init__(self, continuation: HistoryContinuation) -> None:
        self.continuation = continuation
        self.store = continuation.store

    async def fetch_and_stage(
        self,
        job: dict[str, Any],
        expected: SheetsHistoryAcquisition,
        gateway: Any,
        *,
        observed_at: datetime | None = None,
    ) -> SheetsHistoryAcquisition:
        head = _head(expected)
        if head.phase not in {"discover", "verify"} or (
            head.phase == "verify" and head.observed_until is not None and head.next_cursor is None
        ):
            raise ValueError("question traversal is finished or not active")
        cursor = head.next_cursor
        if cursor is not None:
            now = self.store.queue.now()
            observed = head.observed_until
            if observed is None or observed.tzinfo is None or now.tzinfo is None or observed > now:
                raise QuestionCursorClockError("question cursor observation clock unavailable")
            if (now - observed).total_seconds() >= 300:
                raise QuestionCursorExpiredError("question source cursor expired")
        if cursor is not None and not isinstance(cursor, str):
            raise ValueError("question scan cursor is invalid")
        page = await fetch_question_scan_page(
            gateway,
            seller_id=head.seller_id,
            cursor=cursor,
            discovered_count=head.discovered_count,
            observed_at=observed_at,
        )
        return await self.page(job, head, page)

    async def fetch_and_hydrate(
        self,
        job: dict[str, Any],
        expected: SheetsHistoryAcquisition,
        detail_gateway: Any,
    ) -> SheetsHistoryAcquisition:
        """Acquire one bounded set of verified members, then fence their receipts."""
        head = _head(expected)
        question_subscriptions(head)
        scope = {
            "acquisition_id": head.id,
            "generation": head.generation,
            "pass_number": head.pass_number,
        }
        async with (
            await self.store.db.client.start_session() as session,
            session.start_transaction(),
        ):
            await self.continuation._current(job, head, session)
            members = await self.store.receipts.find(
                {**scope, "kind": "membership"},
                {"resource_id": 1},
                session=session,
            ).to_list(length=10001)
            details = await self.store.receipts.find(
                {**scope, "kind": "detail"},
                {"resource_id": 1},
                session=session,
            ).to_list(length=10001)
        member_ids = {row["resource_id"] for row in members}
        detail_ids = {row["resource_id"] for row in details}
        if (
            len(member_ids) != len(members)
            or len(member_ids) != head.discovered_count
            or len(detail_ids) != len(details)
            or len(detail_ids) != head.fetched_count
            or not detail_ids <= member_ids
        ):
            raise HistoryConflictError("question detail membership is incomplete")
        verified = await verified_question_members(self.store, head)
        exclusions = await self.store.receipts.find(
            {**scope, "kind": "exclusion", "exclusion_reason": OUTSIDE}, session=None
        ).to_list(length=10001)
        excluded_ids = {r["resource_id"] for r in exclusions}
        missing = [r for r in verified if r.resource_id not in detail_ids | excluded_ids][:20]
        if not missing:
            return head
        observations: list[QuestionDetailObservation] = []
        outside: list[SheetsHistoryReceipt] = []
        # Classify the entire pending batch before any fallback transport.
        fallback: list[SheetsHistoryReceipt] = []
        for member in missing:
            source = member.source_payload or {}
            if not head.date_from <= _source_created(source) < head.date_to:
                outside.append(member)
            elif _complete_scan_question(source, head):
                observations.append(
                    QuestionDetailObservation(source, member.observed_at, SCAN_VERSION)
                )
            else:
                fallback.append(member)
        for member in fallback:
            resource = await recovery_fetch_resource(
                detail_gateway,
                request_timeout=10,
                seller_id=head.seller_id,
                path=f"/questions/{member.resource_id}?api_version=4",
            )
            if not isinstance(resource, dict):
                raise HistoryConflictError("question detail response invalid")
            if not _complete_scan_question(resource, head):
                raise HistoryConflictError("question required fields remain unavailable")
            observations.append(QuestionDetailObservation(resource, self.store.queue.now()))
        return await self.hydrate(job, head, observations, outside=outside)

    async def materialization_complete(
        self, job: dict[str, Any], expected: SheetsHistoryAcquisition
    ) -> bool:
        head = _head(expected)
        targets = await question_target_members(self.store, head)
        return head.fetched_count == len(targets)

    async def hydrate(
        self,
        job: dict[str, Any],
        expected: SheetsHistoryAcquisition,
        observations: list[QuestionDetailObservation],
        *,
        outside: list[SheetsHistoryReceipt] | None = None,
    ) -> SheetsHistoryAcquisition:
        head = _head(expected)
        subscriptions = question_subscriptions(head)
        outside = outside or []
        if not 1 <= len(observations) + len(outside) <= 20:
            raise ValueError("question hydration requires one to twenty details")

        async def transaction(session: Any) -> SheetsHistoryAcquisition:
            await self.continuation._current(job, head, session)
            scope = {
                "acquisition_id": head.id,
                "generation": head.generation,
                "pass_number": head.pass_number,
            }
            receipts: list[SheetsHistoryReceipt] = []
            if outside or any(o.source_version is not None for o in observations):
                verified = {
                    r.resource_id: r
                    for r in await verified_question_members(self.store, head, session=session)
                }
            else:
                verified = {}
            for member in outside:
                trusted = verified.get(member.resource_id)
                if (
                    trusted is None
                    or trusted.model_dump() != member.model_dump()
                    or head.date_from
                    <= _source_created(trusted.source_payload or {})
                    < head.date_to
                ):
                    raise HistoryConflictError("question exclusion is not verified outside scope")
                receipts.append(
                    SheetsHistoryReceipt(
                        _id=f"{head.id}:{head.generation}:{head.pass_number}:exclusion:{member.resource_id}",
                        acquisition_id=head.id,
                        seller_id=head.seller_id,
                        read_model="questions",
                        generation=head.generation,
                        pass_number=head.pass_number,
                        page_sequence=head.page_sequence + 1,
                        kind="exclusion",
                        resource_id=member.resource_id,
                        observed_at=member.observed_at,
                        source_version=SCAN_VERSION,
                        source_payload=member.source_payload,
                        source_hash=member.source_hash,
                        exclusion_reason=OUTSIDE,
                    )
                )
            seen: set[str] = set()
            for observation in observations:
                payload = observation.payload
                if observation.source_version is not None:
                    trusted = verified.get(str(payload.get("id", "")))
                    if (
                        observation.source_version != SCAN_VERSION
                        or trusted is None
                        or trusted.source_payload != payload
                        or trusted.observed_at != observation.observed_at
                        or not _complete_scan_question(payload, head)
                    ):
                        raise HistoryConflictError("question scan provenance is not verified")
                identity = str(payload.get("id", ""))
                created = datetime.fromisoformat(
                    str(payload.get("date_created", "")).replace("Z", "+00:00")
                )
                if (
                    not identity.isascii()
                    or not identity.isdecimal()
                    or identity in seen
                    or str(payload.get("seller_id")) != head.seller_id
                    or created.tzinfo is None
                    or observation.observed_at.tzinfo is None
                    or not any(sub.date_from <= created < sub.date_to for sub in subscriptions)
                    or (
                        payload.get("status") == "ANSWERED"
                        and not isinstance(payload.get("answer"), dict)
                    )
                ):
                    raise ValueError(
                        "question detail identity, interval or required answer is invalid"
                    )
                seen.add(identity)
                member = await self.store.receipts.find_one(
                    {**scope, "kind": "membership", "resource_id": identity},
                    session=session,
                )
                if member is None:
                    raise HistoryConflictError("question detail has no verified membership")
                receipt = SheetsHistoryReceipt.model_validate(member)
                source = receipt.source_payload or {}
                source_created = datetime.fromisoformat(
                    str(source.get("date_created", "")).replace("Z", "+00:00")
                )
                if (
                    item_source_fingerprint(source) != receipt.source_hash
                    or str(source.get("id")) != identity
                    or str(source.get("seller_id")) != head.seller_id
                    or _question_created_millisecond(source_created)
                    != _question_created_millisecond(created)
                    or any(
                        key in source and source[key] != payload.get(key)
                        for key in ("status", "item_id")
                    )
                ):
                    raise QuestionManifestDriftError(
                        "question detail contradicts verified membership"
                    )
                if await self.store.receipts.find_one(
                    {**scope, "kind": "detail", "resource_id": identity},
                    session=session,
                ):
                    raise HistoryConflictError("question detail already staged")
                fingerprint = item_source_fingerprint(payload)
                receipts.append(
                    SheetsHistoryReceipt(
                        _id=f"{head.id}:{head.generation}:{head.pass_number}:detail:{identity}",
                        acquisition_id=head.id,
                        seller_id=head.seller_id,
                        read_model="questions",
                        generation=head.generation,
                        pass_number=head.pass_number,
                        page_sequence=head.page_sequence + 1,
                        kind="detail",
                        resource_id=identity,
                        observed_at=observation.observed_at,
                        source_version=observation.source_version,
                        source_payload=payload,
                        source_hash=fingerprint,
                        payload=payload,
                        payload_hash=fingerprint,
                    )
                )
            proposed = _head(
                SheetsHistoryAcquisition.model_validate(
                    {
                        **head.model_dump(by_alias=True),
                        "fetched_count": head.fetched_count + len(observations),
                        "page_sequence": head.page_sequence + 1,
                        "checkpoint_revision": head.checkpoint_revision + 1,
                        "updated_at": self.store.queue.now(),
                    }
                )
            )
            saved = await self.store.checkpoint(job, head, proposed, receipts, session=session)
            await self.continuation._pending(job, saved, 0, timedelta(0), session)
            return saved

        async with await self.store.db.client.start_session() as session:
            return SheetsHistoryAcquisition.model_validate(
                await session.with_transaction(transaction)
            )

    async def begin_publication(
        self, job: dict[str, Any], expected: SheetsHistoryAcquisition
    ) -> SheetsHistoryAcquisition:
        """Hand off only a fully hydrated verified scan; this publishes no proof."""
        head = _head(expected)
        question_subscriptions(head)
        if (
            head.fetched_count != len(await question_target_members(self.store, head))
            or head.published_count
        ):
            raise HistoryConflictError("question publication requires every verified detail")

        async def transaction(session: Any) -> SheetsHistoryAcquisition:
            await self.continuation._current(job, head, session)
            scope = {
                "acquisition_id": head.id,
                "generation": head.generation,
                "pass_number": head.pass_number,
            }
            members = await self.store.receipts.count_documents(
                {**scope, "kind": "membership"}, session=session
            )
            details = await self.store.receipts.count_documents(
                {**scope, "kind": "detail"}, session=session
            )
            if members != head.source_total or details != head.fetched_count:
                raise HistoryConflictError("question publication receipt count changed")
            missing = await self.store.receipts.aggregate(
                [
                    {
                        "$match": {
                            **scope,
                            "kind": "membership",
                            "resource_id": {
                                "$in": [
                                    r.resource_id
                                    for r in await question_target_members(
                                        self.store, head, session=session
                                    )
                                ]
                            },
                        }
                    },
                    {
                        "$lookup": {
                            "from": "sheets_history_receipts",
                            "let": {"identity": "$resource_id"},
                            "pipeline": [
                                {
                                    "$match": {
                                        **scope,
                                        "kind": "detail",
                                        "$expr": {"$eq": ["$resource_id", "$$identity"]},
                                    }
                                },
                                {"$limit": 1},
                            ],
                            "as": "details",
                        }
                    },
                    {"$match": {"details": {"$size": 0}}},
                    {"$limit": 1},
                ],
                session=session,
            ).to_list(length=1)
            if missing:
                raise HistoryConflictError("verified question detail is missing")
            saved = _head(
                SheetsHistoryAcquisition.model_validate(
                    {
                        **head.model_dump(by_alias=True),
                        "phase": "publish",
                        "checkpoint_revision": head.checkpoint_revision + 1,
                        "updated_at": self.store.queue.now(),
                    }
                )
            )
            result = await self.store.heads.replace_one(
                {
                    "_id": head.id,
                    "generation": head.generation,
                    "checkpoint_revision": head.checkpoint_revision,
                },
                saved.model_dump(by_alias=True),
                session=session,
            )
            if result.matched_count != 1:
                raise HistoryConflictError("question publication handoff lost its checkpoint")
            await self.continuation._pending(job, saved, 0, timedelta(0), session)
            return saved

        async with await self.store.db.client.start_session() as session:
            return SheetsHistoryAcquisition.model_validate(
                await session.with_transaction(transaction)
            )

    async def cursor_expired(
        self, job: dict[str, Any], head: SheetsHistoryAcquisition
    ) -> SheetsHistoryAcquisition:
        if head.read_model != "questions" or head.next_cursor is None:
            raise ValueError("expiry requires an active question cursor")
        return await self.continuation.release(job, head, reason="cursor_expired")

    async def begin_verification(
        self, job: dict[str, Any], expected: SheetsHistoryAcquisition
    ) -> SheetsHistoryAcquisition:
        head = _head(expected)
        if (
            head.read_model != "questions"
            or head.phase != "hydrate"
            or head.next_cursor is not None
            or head.fetched_count
        ):
            raise ValueError("verification requires a completed membership traversal")

        async def transaction(session: Any) -> SheetsHistoryAcquisition:
            await self.continuation._current(job, head, session)
            count = await self.store.receipts.count_documents(
                {
                    "acquisition_id": head.id,
                    "generation": head.generation,
                    "pass_number": head.pass_number,
                    "kind": "membership",
                },
                session=session,
            )
            if (
                count != head.discovered_count
                or count != head.source_total
                or head.observed_until is None
            ):
                raise HistoryConflictError("verification baseline is incomplete")
            saved = _head(
                SheetsHistoryAcquisition.model_validate(
                    {
                        **head.model_dump(by_alias=True),
                        "phase": "verify",
                        "pass_number": head.pass_number + 1,
                        "page_sequence": head.page_sequence,
                        "checkpoint_revision": head.checkpoint_revision + 1,
                        "discovered_count": 0,
                        "observed_from": None,
                        "observed_until": None,
                        "updated_at": self.store.queue.now(),
                    }
                )
            )
            replaced = await self.store.heads.replace_one(
                {
                    "_id": head.id,
                    "generation": head.generation,
                    "checkpoint_revision": head.checkpoint_revision,
                },
                saved.model_dump(by_alias=True),
                session=session,
            )
            if replaced.matched_count != 1:
                raise HistoryConflictError("question verification lost its checkpoint")
            await self.continuation._pending(job, saved, 0, timedelta(0), session)
            return saved

        async with await self.store.db.client.start_session() as session:
            return SheetsHistoryAcquisition.model_validate(
                await session.with_transaction(transaction)
            )

    async def page(
        self, job: dict[str, Any], expected: SheetsHistoryAcquisition, page: QuestionScanPage
    ) -> SheetsHistoryAcquisition:
        head = _head(expected)
        if (
            head.read_model != "questions"
            or head.phase not in {"discover", "verify"}
            or (
                head.phase == "verify"
                and head.observed_until is not None
                and head.next_cursor is None
            )
        ):
            raise ValueError("question traversal is finished or not active")
        if (
            type(page.total) is not int
            or not 0 <= page.total <= 10000
            or type(page.terminal) is not bool
            or not isinstance(page.rows, list)
            or len(page.rows) > 50
            or page.observed_at.tzinfo is None
            or (page.terminal and page.next_cursor is not None)
            or (
                not page.terminal
                and (not isinstance(page.next_cursor, str) or not page.next_cursor or not page.rows)
            )
        ):
            raise ValueError("invalid normalized question page or local scan budget")
        receipts = []
        for row in page.rows:
            identity = str(row.get("id", ""))
            created = datetime.fromisoformat(
                str(row.get("date_created", "")).replace("Z", "+00:00")
            )
            if (
                not identity.isascii()
                or not identity.isdecimal()
                or str(row.get("seller_id")) != head.seller_id
                or created.tzinfo is None
            ):
                raise ValueError("question membership scope is invalid")
            receipts.append(
                SheetsHistoryReceipt(
                    _id=f"{head.id}:{head.generation}:{head.pass_number}:membership:{identity}",
                    acquisition_id=head.id,
                    seller_id=head.seller_id,
                    read_model="questions",
                    generation=head.generation,
                    pass_number=head.pass_number,
                    page_sequence=head.page_sequence + 1,
                    kind="membership",
                    resource_id=identity,
                    observed_at=page.observed_at,
                    source_payload=row,
                    source_hash=item_source_fingerprint(row),
                )
            )

        async def transaction(session: Any) -> SheetsHistoryAcquisition:
            await self.continuation._current(job, head, session)
            if head.source_total is not None and head.source_total != page.total:
                raise QuestionManifestDriftError("question source total changed")
            identities = [receipt.resource_id for receipt in receipts]
            scope = {"acquisition_id": head.id, "generation": head.generation, "kind": "membership"}
            if len(set(identities)) != len(identities) or await self.store.receipts.find_one(
                {
                    **scope,
                    "pass_number": head.pass_number,
                    "resource_id": {"$in": identities},
                },
                session=session,
            ):
                raise QuestionManifestDriftError("question traversal repeated membership")
            if head.phase == "verify":
                for receipt in receipts:
                    previous = await self.store.receipts.find_one(
                        {
                            **scope,
                            "pass_number": head.pass_number - 1,
                            "resource_id": receipt.resource_id,
                        },
                        session=session,
                    )
                    if previous is None or previous.get("source_hash") != receipt.source_hash:
                        raise QuestionManifestDriftError("question manifests diverged")
            count = head.discovered_count + len(receipts)
            if count > page.total or (page.terminal and count != page.total):
                raise QuestionManifestDriftError("question terminal manifest is incomplete")
            proposed = _head(
                SheetsHistoryAcquisition.model_validate(
                    {
                        **head.model_dump(by_alias=True),
                        "source_total": page.total,
                        "discovered_count": count,
                        "page_sequence": head.page_sequence + 1,
                        "checkpoint_revision": head.checkpoint_revision + 1,
                        "next_cursor": page.next_cursor,
                        "phase": "hydrate"
                        if page.terminal and head.phase == "discover"
                        else head.phase,
                        "observed_from": head.observed_from or page.observed_at,
                        "observed_until": page.observed_at,
                        "updated_at": self.store.queue.now(),
                    }
                )
            )
            saved = await self.store.checkpoint(job, head, proposed, receipts, session=session)
            await self.continuation._pending(job, saved, 0, timedelta(0), session)
            return saved

        try:
            async with await self.store.db.client.start_session() as session:
                return SheetsHistoryAcquisition.model_validate(
                    await session.with_transaction(transaction)
                )
        except QuestionManifestDriftError:
            return await self.continuation.release(job, head, reason="source_drift")
