from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol, cast
from urllib.parse import urlencode


class MeliGatewayResourceClient(Protocol):
    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]: ...


class GatewayDevolucionesSource:
    """Read the proven DEVOLUCIONES source contract through the gateway proxy."""

    def __init__(self, client: MeliGatewayResourceClient, *, single_attempt: bool = False) -> None:
        self._client = client
        self._single_attempt = single_attempt

    async def _fetch(self, *, seller_id: str, path: str) -> dict[str, Any]:
        if self._single_attempt:
            fetch_once = getattr(self._client, "fetch_resource_once", None)
            if fetch_once is None:
                raise RuntimeError(
                    "focused gateway client does not enforce single-attempt metadata"
                )
            return cast("dict[str, Any]", await fetch_once(seller_id=seller_id, path=path))
        return await self._client.fetch_resource(seller_id=seller_id, path=path)

    async def search_claims(
        self, *, seller_id: str, params: Mapping[str, str | int]
    ) -> dict[str, Any]:
        limit = params.get("limit", 100)
        offset = params.get("offset", 0)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset < 9999:
            raise ValueError("offset must be an integer between 0 and 9998")
        path = f"/post-purchase/v1/claims/search?{urlencode(params)}"
        return await self._fetch(seller_id=seller_id, path=path)

    async def get_claim(self, *, seller_id: str, claim_id: str) -> dict[str, Any]:
        return await self._fetch(
            seller_id=seller_id,
            path=f"/post-purchase/v1/claims/{_numeric_id(claim_id, field='claim_id')}",
        )

    async def get_returns(self, *, seller_id: str, claim_id: str) -> dict[str, Any]:
        path = f"/post-purchase/v2/claims/{_numeric_id(claim_id, field='claim_id')}/returns"
        try:
            return await self._fetch(seller_id=seller_id, path=path)
        except Exception as exc:
            if self._single_attempt and _is_authoritative_upstream_not_found(exc):
                raise AuthoritativeReturnsNotFoundError from None
            _tag_private_focused_devoluciones_failure(
                exc,
                _private_focused_devoluciones_failure(exc),
            )
            raise

    async def get_order(self, *, seller_id: str, order_id: str) -> dict[str, Any]:
        return await self._fetch(
            seller_id=seller_id,
            path=f"/orders/{_numeric_id(order_id, field='order_id')}",
        )


def _numeric_id(value: str, *, field: str) -> str:
    normalized = str(value).strip()
    if re.fullmatch(r"[0-9]+", normalized) is None:
        raise ValueError(f"{field} must be numeric")
    return normalized


MAX_CLAIM_SEARCH_LIMIT = 100
MAX_CLAIM_SEARCH_OFFSET = 9999
MIN_SPLIT_WINDOW = timedelta(milliseconds=1)
MAX_SOURCE_PHYSICAL_ATTEMPTS = 208
MAX_SNAPSHOT_PHYSICAL_ATTEMPTS = 104
MAX_DETAIL_ATTEMPTS_PER_HYDRATION_CANDIDATE = 3
RETURNS_MIN_START_INTERVAL_SECONDS = 1.75


class _FocusedDevolucionesFailure(StrEnum):
    """Bounded source diagnosis retained only across the private evidence boundary."""

    PARSER = "parser_failure"
    ATTEMPT_METADATA = "attempt_metadata_failure"
    SAFE_404_PRECONDITION = "safe_404_precondition_failure"
    UNSAFE_404 = "unsafe_404_failure"
    ORDER = "order_failure"
    IDENTITY = "identity_failure"
    BUDGET = "budget_failure"
    SOURCE = "source_failure"


class _FocusedSourceStage(StrEnum):
    CLAIM_SEARCH = "claim_search"
    CLAIM_DETAIL = "claim_detail"
    RETURN_DETAIL = "return_detail"
    ORDER_DETAIL = "order_detail"


class _FocusedSourceFamily(StrEnum):
    RATE_LIMIT = "rate_limit"
    SERVER = "server"
    CLIENT_OTHER = "client_other"
    CONNECTION = "connection"
    TIMEOUT = "timeout"
    OTHER = "other"


class ClaimInventoryError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        private_failure: _FocusedDevolucionesFailure | None = None,
    ) -> None:
        super().__init__(message)
        self._focused_devoluciones_private_failure = (
            private_failure or _FocusedDevolucionesFailure.PARSER
        )


class DevolucionesReadModelVerificationError(RuntimeError):
    pass


class SourceCallBudgetError(RuntimeError):
    pass


class AuthoritativeReturnsNotFoundError(RuntimeError):
    """The exact v2 returns resource is authoritatively absent upstream."""


@dataclass(slots=True)
class ReturnsAttemptPacer:
    """Enforce the focused run's code-owned interval between RETURNS sends."""

    INTERVAL = RETURNS_MIN_START_INTERVAL_SECONDS

    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    _last_start: float | None = field(default=None, init=False, repr=False)

    async def wait_until_allowed(self, *, absolute_deadline: float | None) -> None:
        while True:
            current = self.monotonic()
            if absolute_deadline is not None and current >= absolute_deadline:
                raise SourceCallBudgetError(
                    "source process deadline reached before paced physical attempt"
                )
            if self._last_start is None:
                return
            wait = self.INTERVAL - (current - self._last_start)
            if wait <= 0:
                return
            if absolute_deadline is not None and wait >= absolute_deadline - current:
                raise SourceCallBudgetError(
                    "source process deadline lacks margin for paced physical attempt"
                )
            await self.sleep(wait)

    def record_start(self) -> None:
        self._last_start = self.monotonic()


def _tag_private_focused_devoluciones_failure(
    exc: Exception,
    failure: _FocusedDevolucionesFailure,
    *,
    source_stage: _FocusedSourceStage | None = None,
    source_exc: Exception | None = None,
) -> Exception:
    exc.__dict__["_focused_devoluciones_private_failure"] = failure
    if failure is _FocusedDevolucionesFailure.SOURCE and source_stage is not None:
        exc.__dict__["_focused_devoluciones_source_stage"] = source_stage
        exc.__dict__["_focused_devoluciones_source_family"] = _classify_source_family(
            source_exc or exc
        )
    return exc


def _classify_source_family(exc: Exception) -> _FocusedSourceFamily:
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
    if status_code == 429:
        return _FocusedSourceFamily.RATE_LIMIT
    if isinstance(status_code, int) and not isinstance(status_code, bool):
        if 500 <= status_code <= 599:
            return _FocusedSourceFamily.SERVER
        if 400 <= status_code <= 499:
            return _FocusedSourceFamily.CLIENT_OTHER
    if isinstance(exc, ConnectionError):
        return _FocusedSourceFamily.CONNECTION
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return _FocusedSourceFamily.TIMEOUT
    return _FocusedSourceFamily.OTHER


def _private_focused_devoluciones_failure(exc: Exception) -> _FocusedDevolucionesFailure:
    retained = getattr(exc, "_focused_devoluciones_private_failure", None)
    if isinstance(retained, _FocusedDevolucionesFailure):
        return retained
    if isinstance(exc, SourceCallBudgetError):
        return _FocusedDevolucionesFailure.BUDGET
    if type(exc).__name__ == "ClaimProjectionError":
        return _FocusedDevolucionesFailure.PARSER
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code == 404:
        headers = getattr(response, "headers", None)
        if isinstance(headers, Mapping) and "X-Zeler-Upstream-Attempts" in headers:
            return _FocusedDevolucionesFailure.ATTEMPT_METADATA
        return _FocusedDevolucionesFailure.UNSAFE_404
    if status_code is not None or isinstance(exc, (ConnectionError, TimeoutError)):
        return _FocusedDevolucionesFailure.SOURCE
    if isinstance(exc, ClaimInventoryError):
        return _FocusedDevolucionesFailure.PARSER
    return _FocusedDevolucionesFailure.SOURCE


def _private_focused_devoluciones_diagnostic(exc: Exception) -> dict[str, str]:
    failure = _private_focused_devoluciones_failure(exc)
    diagnostic = {"failure_class": failure.value}
    if failure is _FocusedDevolucionesFailure.SOURCE:
        stage = getattr(exc, "_focused_devoluciones_source_stage", None)
        family = getattr(exc, "_focused_devoluciones_source_family", None)
        if isinstance(stage, _FocusedSourceStage) and isinstance(family, _FocusedSourceFamily):
            diagnostic["source_stage"] = stage.value
            diagnostic["source_family"] = family.value
        return diagnostic
    if (
        failure is not _FocusedDevolucionesFailure.PARSER
        or type(exc).__name__ != "ClaimProjectionError"
    ):
        return diagnostic
    from zeler_sheets.claim_projection import ClaimProjectionReason

    reason = getattr(exc, "projection_reason", None)
    diagnostic["projection_reason"] = (
        reason.value if isinstance(reason, ClaimProjectionReason) else "projection_unknown"
    )
    return diagnostic


class FrozenDict(dict[str, Any]):
    def _immutable(self, *_: Any, **__: Any) -> None:
        raise TypeError("snapshot mappings are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable  # type: ignore[assignment]
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable  # type: ignore[assignment]

    def __deepcopy__(self, memo: dict[int, Any]) -> dict[str, Any]:
        return {key: deepcopy(value, memo) for key, value in self.items()}


class FrozenList(list[Any]):
    def _immutable(self, *_: Any, **__: Any) -> None:
        raise TypeError("snapshot sequences are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable
    __iadd__ = _immutable  # type: ignore[assignment]
    __imul__ = _immutable  # type: ignore[assignment]

    def __deepcopy__(self, memo: dict[int, Any]) -> list[Any]:
        return [deepcopy(value, memo) for value in self]


@dataclass(slots=True)
class SourceRunLedger:
    max_total: int = MAX_SOURCE_PHYSICAL_ATTEMPTS
    claim_pages: int = 0
    claim_and_return_details: int = 0
    order_details: int = 0

    def __post_init__(self) -> None:
        if self.max_total < 1:
            raise ValueError("source call budget must be positive")

    @property
    def total(self) -> int:
        return self.claim_pages + self.claim_and_return_details + self.order_details

    @property
    def counts(self) -> dict[str, int]:
        return {
            "P": self.claim_pages,
            "R": self.claim_and_return_details,
            "O": self.order_details,
            "T": self.total,
        }

    def ensure_capacity(self) -> None:
        if self.total >= self.max_total:
            raise SourceCallBudgetError("source physical-attempt run budget exceeded")

    def record(self, call_kind: str) -> None:
        _increment_source_counter(self, call_kind)


@dataclass(slots=True)
class SourceCallRecorder:
    max_total: int = MAX_SNAPSHOT_PHYSICAL_ATTEMPTS
    run_ledger: SourceRunLedger | None = None
    claim_pages: int = 0
    claim_and_return_details: int = 0
    order_details: int = 0
    required_capacity: int = 0

    def __post_init__(self) -> None:
        if self.max_total < 1:
            raise ValueError("source call budget must be positive")

    @property
    def total(self) -> int:
        return self.claim_pages + self.claim_and_return_details + self.order_details

    @property
    def counts(self) -> dict[str, int]:
        return {
            "P": self.claim_pages,
            "R": self.claim_and_return_details,
            "O": self.order_details,
            "T": self.total,
        }

    def charge(self, call_kind: str) -> None:
        _validate_source_call_kind(call_kind)
        if self.total >= self.max_total:
            raise SourceCallBudgetError("source physical-attempt budget exceeded")
        if self.run_ledger is not None:
            self.run_ledger.ensure_capacity()
        _increment_source_counter(self, call_kind)
        if self.run_ledger is not None:
            self.run_ledger.record(call_kind)

    def require_hydration_capacity(self, candidate_count: int) -> None:
        if isinstance(candidate_count, bool) or not isinstance(candidate_count, int):
            raise TypeError("hydration candidate count must be an integer")
        if candidate_count < 0:
            raise ValueError("hydration candidate count must not be negative")
        required_capacity = (
            self.total + candidate_count * MAX_DETAIL_ATTEMPTS_PER_HYDRATION_CANDIDATE
        )
        self.required_capacity = max(self.required_capacity, required_capacity)
        if required_capacity > self.max_total:
            raise SourceCallBudgetError("inventory-derived source attempt budget exceeds hard cap")


def _validate_source_call_kind(call_kind: str) -> None:
    if call_kind not in {"claim_search", "claim_detail", "return_detail", "order_detail"}:
        raise ValueError("unknown source call kind")


def _increment_source_counter(
    recorder: SourceRunLedger | SourceCallRecorder, call_kind: str
) -> None:
    if call_kind == "claim_search":
        recorder.claim_pages += 1
    elif call_kind in {"claim_detail", "return_detail"}:
        recorder.claim_and_return_details += 1
    else:
        recorder.order_details += 1


class InventoryRelevance(StrEnum):
    EXCLUDED_TERMINAL_CANCELLATION = "excluded_terminal_cancellation"
    HYDRATE_CANDIDATE = "hydrate_candidate"


class ClaimInventorySource(Protocol):
    async def search_claims(
        self, *, seller_id: str, params: dict[str, str | int]
    ) -> dict[str, Any]: ...


class DevolucionesSource(ClaimInventorySource, Protocol):
    async def get_claim(self, *, seller_id: str, claim_id: str) -> dict[str, Any]: ...

    async def get_returns(self, *, seller_id: str, claim_id: str) -> dict[str, Any]: ...

    async def get_order(self, *, seller_id: str, order_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ClaimInventoryEntry:
    claim_id: str
    last_updated: str
    date_created: str | None
    source: Mapping[str, Any]
    trusted_type: str = field(init=False)
    trusted_status: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "trusted_type",
            _normalized_relevance_value(self.source.get("type")),
        )
        object.__setattr__(
            self,
            "trusted_status",
            _normalized_relevance_value(self.source.get("status")),
        )


@dataclass(frozen=True, slots=True)
class VerifiedClaimInventory:
    entries: tuple[ClaimInventoryEntry, ...]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class InventoryExclusionEvidence:
    claim_id: str
    last_updated: str
    reason: str


@dataclass(frozen=True, slots=True)
class CollectedDevolucionesSnapshot:
    seller_id: str
    start: datetime
    end: datetime
    captured_at: datetime
    projections: tuple[Mapping[str, Any], ...]
    orders: tuple[Mapping[str, Any], ...]
    inventory: VerifiedClaimInventory
    expected_claim_ids: frozenset[str]
    source_fingerprint: str
    read_model_fingerprint: str
    exclusions: tuple[InventoryExclusionEvidence, ...] = ()
    exclusion_fingerprint: str = ""
    counters: Mapping[str, int] = field(default_factory=FrozenDict)

    def claim_documents(self) -> list[dict[str, Any]]:
        return [cast("dict[str, Any]", _deep_thaw(row)) for row in self.projections]

    def order_documents(self) -> list[dict[str, Any]]:
        return [cast("dict[str, Any]", _deep_thaw(row)) for row in self.orders]


@dataclass(frozen=True, slots=True)
class VerifiedDevolucionesReadModel:
    expected_claims: int
    persisted_claims: int
    complete_claims: int
    missing_claims: int
    productive_claims: int
    non_productive_claims: int
    verified_orders: int


async def read_devoluciones_claims_keyset(
    *,
    db: Any,
    seller_id: str,
    date_from: datetime,
    date_to: datetime,
    page_size: int = 500,
    session: Any = None,
) -> list[dict[str, Any]]:
    if page_size < 1:
        raise ValueError("page_size must be positive")
    date_from, date_to = _validated_utc_range(date_from, date_to)
    session_kwargs = {"session": session} if session is not None else {}
    documents: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    last_date: datetime | None = None
    last_id: str | None = None
    while True:
        filter_spec: dict[str, Any] = {
            "seller_id": str(seller_id),
            "type": "returns",
            "date_created": {"$gte": date_from, "$lt": date_to},
        }
        if last_date is not None and last_id is not None:
            filter_spec["$or"] = [
                {"date_created": {"$gt": last_date, "$lt": date_to}},
                {"date_created": last_date, "_id": {"$gt": last_id}},
            ]
        cursor = (
            db["claims"].find(filter_spec, **session_kwargs).sort([("date_created", 1), ("_id", 1)])
        )
        page = cast("list[dict[str, Any]]", await cursor.to_list(length=page_size))
        if not page:
            return documents
        for document in page:
            claim_id = str(document.get("_id") or "").strip()
            created_at = _utc_datetime(document.get("date_created"), field="claim date_created")
            if not claim_id or claim_id in seen_ids:
                raise DevolucionesReadModelVerificationError(
                    "claim keyset contains a missing or duplicate identity"
                )
            if (
                last_date is not None
                and last_id is not None
                and (created_at < last_date or (created_at == last_date and claim_id <= last_id))
            ):
                raise DevolucionesReadModelVerificationError("claim keyset did not advance")
            seen_ids.add(claim_id)
            documents.append(dict(document))
            last_date = created_at
            last_id = claim_id
        if len(page) < page_size:
            return documents


async def read_devoluciones_orders_by_id_keyset(
    *,
    db: Any,
    seller_id: str,
    order_ids: frozenset[str] | set[str] | Sequence[str],
    chunk_size: int = 500,
    session: Any = None,
) -> list[dict[str, Any]]:
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    normalized_ids = sorted(
        {str(order_id).strip() for order_id in order_ids if str(order_id).strip()}
    )
    session_kwargs = {"session": session} if session is not None else {}
    documents: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index in range(0, len(normalized_ids), chunk_size):
        chunk = normalized_ids[index : index + chunk_size]
        cursor = (
            db["orders"]
            .find(
                {"seller_id": str(seller_id), "_id": {"$in": chunk}},
                **session_kwargs,
            )
            .sort([("_id", 1)])
        )
        page = cast("list[dict[str, Any]]", await cursor.to_list(length=None))
        for document in page:
            order_id = str(document.get("_id") or "").strip()
            if not order_id or order_id in seen_ids or order_id not in chunk:
                raise DevolucionesReadModelVerificationError(
                    "order keyset contains an unexpected or duplicate identity"
                )
            seen_ids.add(order_id)
            documents.append(dict(document))
    return documents


async def verify_devoluciones_read_model(
    *,
    db: Any,
    seller_id: str,
    date_from: datetime,
    date_to: datetime,
    expected_claim_ids: frozenset[str] | set[str] | Sequence[str],
    expected_read_model_fingerprint: str | None = None,
    page_size: int = 500,
    order_chunk_size: int = 500,
    session: Any = None,
) -> VerifiedDevolucionesReadModel:
    expected_ids = frozenset(
        str(claim_id).strip() for claim_id in expected_claim_ids if str(claim_id).strip()
    )
    claims = await read_devoluciones_claims_keyset(
        db=db,
        seller_id=seller_id,
        date_from=date_from,
        date_to=date_to,
        page_size=page_size,
        session=session,
    )
    persisted_ids = frozenset(str(claim.get("_id") or "").strip() for claim in claims)
    if persisted_ids != expected_ids:
        raise DevolucionesReadModelVerificationError(
            "persisted claim identities do not match authoritative inventory"
        )

    productive_claims = 0
    non_productive_claims = 0
    required_orders: dict[str, list[str]] = {}
    for claim in claims:
        claim_id = str(claim.get("_id") or "").strip()
        order_id = _required_text(claim.get("order_id"), field="claim order_id")
        item_id = _required_text(claim.get("item_id"), field="claim item_id")
        _required_text(claim.get("status"), field="claim status")
        claim_version = claim.get("claim_version")
        if isinstance(claim_version, bool) or not isinstance(claim_version, int):
            raise DevolucionesReadModelVerificationError("claim source version is required")
        _utc_datetime(claim.get("last_updated"), field="claim last_updated")
        _utc_datetime(claim.get("return_last_updated"), field="claim return_last_updated")
        if str(claim.get("seller_id")) != str(seller_id) or claim.get("type") != "returns":
            raise DevolucionesReadModelVerificationError("claim scope is not canonical")
        productive = claim.get("productive")
        if productive is True:
            quantity = claim.get("returned_quantity")
            if (
                isinstance(quantity, bool)
                or not isinstance(quantity, int)
                or quantity < 1
                or claim.get("return_quantity_basis") != "v2_return_order"
            ):
                raise DevolucionesReadModelVerificationError(
                    "productive claim lacks exact v2 return quantity"
                )
            productive_claims += 1
        else:
            raise DevolucionesReadModelVerificationError(
                "only positive integral v2 return proof is complete"
            )
        required_orders.setdefault(order_id, []).append(item_id)
        if not claim_id:
            raise DevolucionesReadModelVerificationError("claim identity is required")

    orders = await read_devoluciones_orders_by_id_keyset(
        db=db,
        seller_id=seller_id,
        order_ids=frozenset(required_orders),
        chunk_size=order_chunk_size,
        session=session,
    )
    orders_by_id = {str(order.get("_id") or "").strip(): order for order in orders}
    if set(orders_by_id) != set(required_orders):
        raise DevolucionesReadModelVerificationError("required canonical orders are missing")
    for order_id, claim_item_ids in required_orders.items():
        order = orders_by_id[order_id]
        if str(order.get("seller_id")) != str(seller_id):
            raise DevolucionesReadModelVerificationError("order seller does not match claim seller")
        items = order.get("items")
        if not isinstance(items, list):
            raise DevolucionesReadModelVerificationError("canonical order items are missing")
        for item_id in claim_item_ids:
            matches = [
                item
                for item in items
                if isinstance(item, Mapping) and str(item.get("item_id") or "").strip() == item_id
            ]
            if len(matches) != 1:
                raise DevolucionesReadModelVerificationError(
                    "claim item does not have one unique canonical order line"
                )

    if expected_read_model_fingerprint is not None:
        persisted_fingerprint = devoluciones_read_model_fingerprint(
            seller_id=seller_id,
            claims=claims,
            orders=orders,
        )
        if persisted_fingerprint != expected_read_model_fingerprint:
            raise DevolucionesReadModelVerificationError(
                "persisted DEVOLUCIONES facts differ from hydrated source facts"
            )

    return VerifiedDevolucionesReadModel(
        expected_claims=len(expected_ids),
        persisted_claims=len(claims),
        complete_claims=len(claims),
        missing_claims=0,
        productive_claims=productive_claims,
        non_productive_claims=non_productive_claims,
        verified_orders=len(orders),
    )


def claim_inventory_search_params(
    *, seller_id: str, start: datetime, end: datetime, offset: int, limit: int
) -> dict[str, str | int]:
    start, end = _validated_utc_range(start, end)
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset < 9999:
        raise ClaimInventoryError("offset must be an integer below 9999")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ClaimInventoryError("limit must be an integer no greater than 100")
    return {
        "players.user_id": str(seller_id),
        "players.role": "respondent",
        "date_created": _format_meli_datetime(start),
        "range": (
            f"date_created:after:{_format_meli_datetime(start - MIN_SPLIT_WINDOW)},"
            f"before:{_format_meli_datetime(end)}"
        ),
        "sort": "date_created:asc",
        "offset": offset,
        "limit": limit,
    }


async def verify_claim_inventory(
    *,
    source: ClaimInventorySource,
    seller_id: str,
    start: datetime,
    end: datetime,
    limit: int = MAX_CLAIM_SEARCH_LIMIT,
    recorder: SourceCallRecorder | None = None,
    absolute_deadline: float | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    heartbeat: Callable[[], Awaitable[None]] | None = None,
) -> VerifiedClaimInventory:
    start, end = _validated_utc_range(start, end)
    first = await _inventory_pass(
        source=source,
        seller_id=str(seller_id),
        start=start,
        end=end,
        limit=limit,
        recorder=recorder,
        absolute_deadline=absolute_deadline,
        monotonic=monotonic,
        heartbeat=heartbeat,
    )
    second = await _inventory_pass(
        source=source,
        seller_id=str(seller_id),
        start=start,
        end=end,
        limit=limit,
        recorder=recorder,
        absolute_deadline=absolute_deadline,
        monotonic=monotonic,
        heartbeat=heartbeat,
    )
    first_fingerprint = _inventory_fingerprint(first)
    second_fingerprint = _inventory_fingerprint(second)
    if first_fingerprint != second_fingerprint:
        raise ClaimInventoryError("claim inventory fingerprint changed between passes")
    return VerifiedClaimInventory(entries=tuple(first), fingerprint=first_fingerprint)


async def collect_devoluciones_projections(
    *,
    source: DevolucionesSource,
    seller_id: str,
    start: datetime,
    end: datetime,
) -> tuple[list[dict[str, Any]], VerifiedClaimInventory]:
    snapshot = await collect_devoluciones_snapshot(
        source=source,
        seller_id=seller_id,
        start=start,
        end=end,
    )
    return snapshot.claim_documents(), snapshot.inventory


async def collect_devoluciones_snapshot(
    *,
    source: DevolucionesSource,
    seller_id: str,
    start: datetime,
    end: datetime,
    captured_at: datetime | None = None,
    recorder: SourceCallRecorder | None = None,
    absolute_deadline: float | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    returns_pacer: ReturnsAttemptPacer | None = None,
    heartbeat: Callable[[], Awaitable[None]] | None = None,
) -> CollectedDevolucionesSnapshot:
    from zeler_sheets.claim_projection import build_claim_projection

    normalized_start, normalized_end = _validated_utc_range(start, end)
    resolved_returns_pacer = returns_pacer
    if resolved_returns_pacer is None and sleep is not None:
        resolved_returns_pacer = ReturnsAttemptPacer(monotonic=monotonic, sleep=sleep)
    inventory = await verify_claim_inventory(
        source=source,
        seller_id=seller_id,
        start=normalized_start,
        end=normalized_end,
        recorder=recorder,
        absolute_deadline=absolute_deadline,
        monotonic=monotonic,
        heartbeat=heartbeat,
    )
    hydration_entries = tuple(
        entry
        for entry in inventory.entries
        if classify_inventory_relevance(entry) is InventoryRelevance.HYDRATE_CANDIDATE
    )
    if recorder is not None:
        recorder.require_hydration_capacity(len(hydration_entries))
    projections: list[dict[str, Any]] = []
    orders_by_id: dict[str, dict[str, Any]] = {}
    exclusions: list[InventoryExclusionEvidence] = []
    for entry in inventory.entries:
        if classify_inventory_relevance(entry) is InventoryRelevance.EXCLUDED_TERMINAL_CANCELLATION:
            exclusions.append(
                InventoryExclusionEvidence(
                    claim_id=entry.claim_id,
                    last_updated=entry.last_updated,
                    reason="terminal_cancellation",
                )
            )
            continue
        await _before_source_attempt(
            "claim_detail",
            recorder=recorder,
            absolute_deadline=absolute_deadline,
            monotonic=monotonic,
            heartbeat=heartbeat,
        )
        try:
            claim = await _bounded_source_call(
                source.get_claim(seller_id=seller_id, claim_id=entry.claim_id),
                absolute_deadline=absolute_deadline,
                monotonic=monotonic,
            )
        except SourceCallBudgetError:
            raise
        except Exception as exc:
            failure = _private_focused_devoluciones_failure(exc)
            _tag_private_focused_devoluciones_failure(
                exc,
                failure,
                source_stage=_FocusedSourceStage.CLAIM_DETAIL,
            )
            raise
        if not _is_return_candidate(claim):
            raise ClaimInventoryError(
                "hydrated claim candidate is unresolved and cannot be excluded"
            )
        await _before_source_attempt(
            "return_detail",
            recorder=recorder,
            absolute_deadline=absolute_deadline,
            monotonic=monotonic,
            heartbeat=heartbeat,
            returns_pacer=resolved_returns_pacer,
        )
        try:
            returns = await _bounded_source_call(
                source.get_returns(seller_id=seller_id, claim_id=entry.claim_id),
                absolute_deadline=absolute_deadline,
                monotonic=monotonic,
            )
        except SourceCallBudgetError:
            raise
        except AuthoritativeReturnsNotFoundError:
            if _is_authoritative_no_return_mediation(
                entry=entry,
                claim=claim,
                seller_id=seller_id,
            ):
                exclusions.append(
                    InventoryExclusionEvidence(
                        claim_id=entry.claim_id,
                        last_updated=entry.last_updated,
                        reason="authoritative_no_return_mediation",
                    )
                )
                continue
            raise ClaimInventoryError(
                "v2 returns source_issue",
                private_failure=_FocusedDevolucionesFailure.SAFE_404_PRECONDITION,
            ) from None
        except Exception as exc:  # noqa: BLE001 - source exception text is unsafe evidence.
            failure = _private_focused_devoluciones_failure(exc)
            error = ClaimInventoryError(
                "v2 returns source_issue",
                private_failure=failure,
            )
            _tag_private_focused_devoluciones_failure(
                error,
                failure,
                source_stage=_FocusedSourceStage.RETURN_DETAIL,
                source_exc=exc,
            )
            raise error from None
        order_id = str(claim.get("order_id") or claim.get("resource_id") or "").strip()
        if not order_id:
            raise ClaimInventoryError(
                "return claim is missing order identity",
                private_failure=_FocusedDevolucionesFailure.IDENTITY,
            )
        order = orders_by_id.get(order_id)
        if order is None:
            await _before_source_attempt(
                "order_detail",
                recorder=recorder,
                absolute_deadline=absolute_deadline,
                monotonic=monotonic,
                heartbeat=heartbeat,
            )
            try:
                order = await _bounded_source_call(
                    source.get_order(seller_id=seller_id, order_id=order_id),
                    absolute_deadline=absolute_deadline,
                    monotonic=monotonic,
                )
            except SourceCallBudgetError:
                raise
            except Exception as exc:
                source_failure = _private_focused_devoluciones_failure(exc)
                _tag_private_focused_devoluciones_failure(
                    exc,
                    (
                        _FocusedDevolucionesFailure.SOURCE
                        if source_failure is _FocusedDevolucionesFailure.SOURCE
                        else _FocusedDevolucionesFailure.ORDER
                    ),
                    source_stage=_FocusedSourceStage.ORDER_DETAIL,
                )
                raise
            orders_by_id[order_id] = dict(order)
        projections.append(
            build_claim_projection(
                seller_id=seller_id,
                claim=claim,
                returns=returns,
                order=order,
            )
        )
    read_model_fingerprint = devoluciones_read_model_fingerprint(
        seller_id=seller_id,
        claims=projections,
        orders=tuple(orders_by_id.values()),
    )
    exclusion_fingerprint = _exclusion_fingerprint(exclusions)
    captured = _utc_datetime(captured_at or datetime.now(UTC), field="snapshot captured_at")
    frozen_projections = tuple(cast("Mapping[str, Any]", _deep_freeze(row)) for row in projections)
    frozen_orders = tuple(
        cast("Mapping[str, Any]", _deep_freeze(row)) for row in orders_by_id.values()
    )
    terminal_cancellation_exclusions = sum(
        exclusion.reason == "terminal_cancellation" for exclusion in exclusions
    )
    authoritative_no_return_exclusions = sum(
        exclusion.reason == "authoritative_no_return_mediation" for exclusion in exclusions
    )
    return CollectedDevolucionesSnapshot(
        seller_id=str(seller_id),
        start=normalized_start,
        end=normalized_end,
        captured_at=captured,
        projections=frozen_projections,
        orders=frozen_orders,
        inventory=inventory,
        expected_claim_ids=frozenset(
            _required_text(projection.get("_id"), field="claim identity")
            for projection in projections
        ),
        source_fingerprint=_hydrated_source_fingerprint(
            inventory_fingerprint=inventory.fingerprint,
            read_model_fingerprint=read_model_fingerprint,
            exclusion_fingerprint=exclusion_fingerprint if exclusions else None,
        ),
        read_model_fingerprint=read_model_fingerprint,
        exclusions=tuple(exclusions),
        exclusion_fingerprint=exclusion_fingerprint,
        counters=FrozenDict(
            {
                "inventory_candidates": len(inventory.entries),
                "hydrated_candidates": len(hydration_entries),
                "excluded_terminal_cancellations": terminal_cancellation_exclusions,
                **(
                    {
                        "excluded_authoritative_no_return_mediations": (
                            authoritative_no_return_exclusions
                        )
                    }
                    if authoritative_no_return_exclusions
                    else {}
                ),
                "productive_claims": sum(
                    projection.get("productive") is True for projection in projections
                ),
                "non_productive_claims": sum(
                    projection.get("productive") is False for projection in projections
                ),
                **(recorder.counts if recorder is not None else {}),
            }
        ),
    )


async def revalidate_devoluciones_snapshot(
    *,
    source: DevolucionesSource,
    snapshot: CollectedDevolucionesSnapshot,
    operation: Any,
    absolute_deadline: float,
    recorder: SourceCallRecorder,
    heartbeat: Callable[[], Awaitable[None]],
    monotonic: Callable[[], float] = time.monotonic,
    returns_pacer: ReturnsAttemptPacer | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> CollectedDevolucionesSnapshot:
    if recorder.total != 0:
        raise SourceCallBudgetError("publication revalidation requires a fresh snapshot ledger")
    invalid_owner = (
        operation.seller_id != snapshot.seller_id
        or not operation.owns_lease
        or operation.lease_lost
    )
    if invalid_owner:
        raise DevolucionesReadModelVerificationError("root operation does not own snapshot scope")
    if operation.source_fingerprint != snapshot.source_fingerprint:
        raise DevolucionesReadModelVerificationError("root operation source fingerprint changed")
    require_snapshot_publication_age(snapshot=snapshot, current_time=now())

    current = await collect_devoluciones_snapshot(
        source=source,
        seller_id=snapshot.seller_id,
        start=snapshot.start,
        end=snapshot.end,
        captured_at=now(),
        recorder=recorder,
        absolute_deadline=absolute_deadline,
        monotonic=monotonic,
        returns_pacer=returns_pacer,
        heartbeat=heartbeat,
    )
    if (
        current.source_fingerprint != snapshot.source_fingerprint
        or current.read_model_fingerprint != snapshot.read_model_fingerprint
        or current.inventory.fingerprint != snapshot.inventory.fingerprint
        or current.exclusion_fingerprint != snapshot.exclusion_fingerprint
        or current.expected_claim_ids != snapshot.expected_claim_ids
    ):
        raise DevolucionesReadModelVerificationError(
            "DEVOLUCIONES source or read-model fingerprint changed during targeted revalidation"
        )
    require_snapshot_publication_age(snapshot=snapshot, current_time=now())
    await heartbeat()
    return current


def require_snapshot_publication_age(
    *, snapshot: CollectedDevolucionesSnapshot, current_time: datetime
) -> None:
    publication_age = _utc_datetime(current_time, field="publication time") - snapshot.captured_at
    if publication_age < timedelta(0) or publication_age > timedelta(seconds=150):
        raise DevolucionesReadModelVerificationError("snapshot publication age is invalid")


async def write_devoluciones_snapshot(
    *,
    db: Any,
    snapshot: CollectedDevolucionesSnapshot,
    operation: Any,
) -> dict[str, int]:
    if operation.seller_id != snapshot.seller_id or not operation.owns_lease:
        raise DevolucionesReadModelVerificationError("root operation does not own snapshot scope")
    if operation.source_fingerprint != snapshot.source_fingerprint:
        raise DevolucionesReadModelVerificationError("root operation source fingerprint changed")

    from zeler_sheets.claim_projection import persist_claim_projection
    from zeler_sheets.event_persistence import SheetsEventPersistence

    persistence = SheetsEventPersistence(db=db)
    for frozen_order in snapshot.orders:
        await persistence.persist(
            event_type="orders.updated",
            seller_id=snapshot.seller_id,
            resource=cast("dict[str, Any]", _deep_thaw(frozen_order)),
            operation=operation,
        )
    for frozen_claim in snapshot.projections:
        await persist_claim_projection(
            db=db,
            document=cast("dict[str, Any]", _deep_thaw(frozen_claim)),
            operation=operation,
        )
    return {
        "written_orders": len(snapshot.orders),
        "written_claims": len(snapshot.projections),
    }


async def _inventory_pass(
    *,
    source: ClaimInventorySource,
    seller_id: str,
    start: datetime,
    end: datetime,
    limit: int,
    recorder: SourceCallRecorder | None,
    absolute_deadline: float | None,
    monotonic: Callable[[], float],
    heartbeat: Callable[[], Awaitable[None]] | None,
) -> list[ClaimInventoryEntry]:
    entries = await _inventory_window(
        source=source,
        seller_id=seller_id,
        start=start,
        end=end,
        limit=limit,
        recorder=recorder,
        absolute_deadline=absolute_deadline,
        monotonic=monotonic,
        heartbeat=heartbeat,
    )
    claim_ids = [entry.claim_id for entry in entries]
    if len(claim_ids) != len(set(claim_ids)):
        raise ClaimInventoryError("duplicate claim id across inventory windows")
    return entries


async def _inventory_window(
    *,
    source: ClaimInventorySource,
    seller_id: str,
    start: datetime,
    end: datetime,
    limit: int,
    recorder: SourceCallRecorder | None,
    absolute_deadline: float | None,
    monotonic: Callable[[], float],
    heartbeat: Callable[[], Awaitable[None]] | None,
) -> list[ClaimInventoryEntry]:
    offset = 0
    stable_total: int | None = None
    entries: list[ClaimInventoryEntry] = []
    seen_ids: set[str] = set()
    while True:
        params = claim_inventory_search_params(
            seller_id=seller_id,
            start=start,
            end=end,
            offset=offset,
            limit=limit,
        )
        await _before_source_attempt(
            "claim_search",
            recorder=recorder,
            absolute_deadline=absolute_deadline,
            monotonic=monotonic,
            heartbeat=heartbeat,
        )
        try:
            payload = await _bounded_source_call(
                source.search_claims(seller_id=seller_id, params=params),
                absolute_deadline=absolute_deadline,
                monotonic=monotonic,
            )
        except Exception as exc:
            failure = _private_focused_devoluciones_failure(exc)
            error = ClaimInventoryError(
                "claim inventory source request failed",
                private_failure=failure,
            )
            _tag_private_focused_devoluciones_failure(
                error,
                failure,
                source_stage=_FocusedSourceStage.CLAIM_SEARCH,
                source_exc=exc,
            )
            raise error from exc
        data, response_offset, _, total = _validated_page(payload, requested_offset=offset)
        if stable_total is None:
            stable_total = total
        elif stable_total != total:
            raise ClaimInventoryError("claim inventory total changed during paging")
        if total >= MAX_CLAIM_SEARCH_OFFSET + 1:
            if end - start <= MIN_SPLIT_WINDOW:
                raise ClaimInventoryError("claim inventory offset cap is unsplittable")
            midpoint = start + (end - start) / 2
            left = await _inventory_window(
                source=source,
                seller_id=seller_id,
                start=start,
                end=midpoint,
                limit=limit,
                recorder=recorder,
                absolute_deadline=absolute_deadline,
                monotonic=monotonic,
                heartbeat=heartbeat,
            )
            right = await _inventory_window(
                source=source,
                seller_id=seller_id,
                start=midpoint,
                end=end,
                limit=limit,
                recorder=recorder,
                absolute_deadline=absolute_deadline,
                monotonic=monotonic,
                heartbeat=heartbeat,
            )
            return [*left, *right]
        for raw_entry in data:
            entry = _inventory_entry(raw_entry)
            if entry.claim_id in seen_ids:
                raise ClaimInventoryError("duplicate claim id in inventory page")
            seen_ids.add(entry.claim_id)
            entries.append(entry)
        next_offset = response_offset + len(data)
        if next_offset == total:
            if heartbeat is not None:
                await heartbeat()
            return entries
        if next_offset > total:
            raise ClaimInventoryError("claim inventory page exceeds stable total")
        if not data or next_offset <= offset:
            raise ClaimInventoryError("claim inventory nonterminal page did not advance")
        if next_offset >= MAX_CLAIM_SEARCH_OFFSET:
            raise ClaimInventoryError("claim inventory offset cap reached before terminal page")
        offset = next_offset


async def _before_source_attempt(
    call_kind: str,
    *,
    recorder: SourceCallRecorder | None,
    absolute_deadline: float | None,
    monotonic: Callable[[], float],
    heartbeat: Callable[[], Awaitable[None]] | None,
    returns_pacer: ReturnsAttemptPacer | None = None,
) -> None:
    if call_kind == "return_detail" and returns_pacer is not None:
        await returns_pacer.wait_until_allowed(absolute_deadline=absolute_deadline)
    if heartbeat is not None:
        await heartbeat()
    if absolute_deadline is not None and monotonic() >= absolute_deadline:
        raise SourceCallBudgetError("source process deadline reached before physical attempt")
    if recorder is not None:
        recorder.charge(call_kind)
    if call_kind == "return_detail" and returns_pacer is not None:
        returns_pacer.record_start()


async def _bounded_source_call(
    awaitable: Awaitable[dict[str, Any]],
    *,
    absolute_deadline: float | None,
    monotonic: Callable[[], float],
) -> dict[str, Any]:
    if absolute_deadline is None:
        return await awaitable
    remaining = absolute_deadline - monotonic()
    if remaining <= 0:
        if hasattr(awaitable, "close"):
            cast(Any, awaitable).close()
        raise SourceCallBudgetError("source process deadline reached before physical attempt")
    try:
        async with asyncio.timeout(remaining):
            return await awaitable
    except TimeoutError as exc:
        raise SourceCallBudgetError(
            "source process deadline expired during physical attempt"
        ) from exc


def _validated_page(
    payload: Mapping[str, Any], *, requested_offset: int
) -> tuple[list[dict[str, Any]], int, int, int]:
    paging = payload.get("paging")
    data = payload.get("data")
    if not isinstance(paging, Mapping) or not isinstance(data, list):
        raise ClaimInventoryError("claim inventory response is missing data or paging")
    values = (paging.get("offset"), paging.get("limit"), paging.get("total"))
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise ClaimInventoryError("claim inventory paging values must be integers")
    offset = cast(int, values[0])
    limit = cast(int, values[1])
    total = cast(int, values[2])
    if offset != requested_offset:
        raise ClaimInventoryError("claim inventory response offset did not echo request")
    if not 1 <= limit <= MAX_CLAIM_SEARCH_LIMIT:
        raise ClaimInventoryError("claim inventory response limit is invalid")
    if total < 0:
        raise ClaimInventoryError("claim inventory total is invalid")
    if not all(isinstance(entry, dict) for entry in data):
        raise ClaimInventoryError("claim inventory data rows must be objects")
    return data, offset, limit, total


def _inventory_entry(raw_entry: Mapping[str, Any]) -> ClaimInventoryEntry:
    claim_id = str(raw_entry.get("id") or "").strip()
    last_updated = str(raw_entry.get("last_updated") or "").strip()
    if not claim_id or not last_updated:
        raise ClaimInventoryError("claim inventory row is missing id or last_updated")
    date_created = raw_entry.get("date_created")
    return ClaimInventoryEntry(
        claim_id=claim_id,
        last_updated=last_updated,
        date_created=str(date_created) if date_created is not None else None,
        source=cast("Mapping[str, Any]", _deep_freeze(raw_entry)),
    )


def _inventory_fingerprint(entries: Sequence[ClaimInventoryEntry]) -> str:
    rows = [
        (
            entry.claim_id,
            entry.last_updated,
            entry.date_created,
            entry.trusted_type,
            entry.trusted_status,
        )
        for entry in entries
    ]
    encoded = json.dumps(rows, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def classify_inventory_relevance(entry: ClaimInventoryEntry) -> InventoryRelevance:
    if entry.trusted_type == "cancel_purchase" and entry.trusted_status == "closed":
        return InventoryRelevance.EXCLUDED_TERMINAL_CANCELLATION
    return InventoryRelevance.HYDRATE_CANDIDATE


def _normalized_relevance_value(value: Any) -> str:
    return str(value or "").strip().lower()


def _exclusion_fingerprint(exclusions: Sequence[InventoryExclusionEvidence]) -> str:
    return _fingerprint_payload(
        [
            {
                "claim_id": exclusion.claim_id,
                "last_updated": exclusion.last_updated,
                "reason": exclusion.reason,
            }
            for exclusion in exclusions
        ]
    )


def devoluciones_read_model_fingerprint(
    *,
    seller_id: str,
    claims: Sequence[Mapping[str, Any]],
    orders: Sequence[Mapping[str, Any]],
) -> str:
    normalized_seller_id = _required_text(seller_id, field="seller_id")
    orders_by_id: dict[str, Mapping[str, Any]] = {}
    for source_order in orders:
        order_id = _required_text(
            source_order.get("_id") or source_order.get("id"), field="order identity"
        )
        if order_id in orders_by_id:
            raise DevolucionesReadModelVerificationError(
                "hydrated source proof contains duplicate orders"
            )
        orders_by_id[order_id] = source_order

    rows: list[dict[str, Any]] = []
    for claim in claims:
        claim_id = _required_text(claim.get("_id") or claim.get("id"), field="claim identity")
        claim_seller_id = _required_text(claim.get("seller_id"), field="claim seller_id")
        if claim_seller_id != normalized_seller_id:
            raise DevolucionesReadModelVerificationError(
                "claim seller does not match hydrated source proof scope"
            )
        order_id = _required_text(claim.get("order_id"), field="claim order_id")
        item_id = _required_text(claim.get("item_id"), field="claim item_id")
        matched_order = orders_by_id.get(order_id)
        if matched_order is None:
            raise DevolucionesReadModelVerificationError(
                "hydrated source proof is missing a required order"
            )
        order_seller_id = _order_seller_id(matched_order)
        if order_seller_id != normalized_seller_id:
            raise DevolucionesReadModelVerificationError(
                "order seller does not match hydrated source proof scope"
            )
        order_line = _unique_order_line(matched_order, item_id=item_id)
        claim_version = claim.get("claim_version")
        if isinstance(claim_version, bool) or not isinstance(claim_version, int):
            raise DevolucionesReadModelVerificationError(
                "claim source version is required for hydrated source proof"
            )
        productive = claim.get("productive")
        if not isinstance(productive, bool):
            raise DevolucionesReadModelVerificationError(
                "claim productive classification is required for hydrated source proof"
            )
        returned_quantity = claim.get("returned_quantity")
        if productive:
            if (
                isinstance(returned_quantity, bool)
                or not isinstance(returned_quantity, int)
                or returned_quantity < 1
            ):
                raise DevolucionesReadModelVerificationError(
                    "productive claim quantity is required for hydrated source proof"
                )
        elif returned_quantity is not None:
            raise DevolucionesReadModelVerificationError(
                "non-productive claim quantity must be absent from hydrated source proof"
            )

        rows.append(
            {
                "claim": {
                    "id": claim_id,
                    "seller_id": claim_seller_id,
                    "buyer_id": _optional_fingerprint_text(claim.get("buyer_id")),
                    "order_id": order_id,
                    "item_id": item_id,
                    "claim_version": claim_version,
                    "date_created": _fingerprint_datetime(
                        claim.get("date_created"), field="claim date_created"
                    ),
                    "last_updated": _fingerprint_datetime(
                        claim.get("last_updated"), field="claim last_updated"
                    ),
                    "status": _required_text(claim.get("status"), field="claim status"),
                    "stage": _required_text(claim.get("stage"), field="claim stage"),
                    "type": _required_text(claim.get("type"), field="claim type"),
                },
                "return": {
                    "id": _required_text(claim.get("return_id"), field="return identity"),
                    "status": _required_text(claim.get("return_status"), field="return status"),
                    "subtype": _required_text(claim.get("return_subtype"), field="return subtype"),
                    "last_updated": _fingerprint_datetime(
                        claim.get("return_last_updated"), field="return last_updated"
                    ),
                },
                "return_order_row": {
                    "order_id": order_id,
                    "item_id": item_id,
                    "return_quantity": returned_quantity,
                    "context_type": _optional_fingerprint_text(claim.get("return_context_type")),
                    "quantity_basis": _required_text(
                        claim.get("return_quantity_basis"), field="return quantity basis"
                    ),
                    "productive": productive,
                },
                "order": {
                    "id": order_id,
                    "seller_id": order_seller_id,
                    "item_id": item_id,
                    "variation_id": _order_line_variation_id(order_line),
                    "sku": _order_line_formula_sku(order_line),
                    "title": _order_line_formula_title(order_line),
                    "quantity": _order_line_quantity(order_line),
                },
            }
        )
    rows.sort(key=lambda row: str(row["claim"]["id"]))
    return _fingerprint_payload(rows)


def _hydrated_source_fingerprint(
    *,
    inventory_fingerprint: str,
    read_model_fingerprint: str,
    exclusion_fingerprint: str | None = None,
) -> str:
    payload = {
        "inventory_fingerprint": inventory_fingerprint,
        "read_model_fingerprint": read_model_fingerprint,
    }
    if exclusion_fingerprint is not None:
        payload["exclusion_fingerprint"] = exclusion_fingerprint
    return _fingerprint_payload(payload)


def _fingerprint_payload(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return FrozenDict({str(key): _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return FrozenList(_deep_freeze(item) for item in value)
    return value


def _deep_thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_deep_thaw(item) for item in value]
    return value


def _fingerprint_datetime(value: Any, *, field: str) -> str:
    return (
        _utc_datetime(value, field=field).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _optional_fingerprint_text(value: Any) -> str | None:
    normalized = str(value).strip() if value is not None else ""
    return normalized or None


def _order_seller_id(order: Mapping[str, Any]) -> str:
    seller = order.get("seller")
    value = seller.get("id") if isinstance(seller, Mapping) else order.get("seller_id")
    return _required_text(value, field="order seller_id")


def _unique_order_line(order: Mapping[str, Any], *, item_id: str) -> Mapping[str, Any]:
    raw_items = order.get("items") or order.get("order_items")
    if not isinstance(raw_items, list):
        raise DevolucionesReadModelVerificationError(
            "hydrated source proof order items are missing"
        )
    matches = [
        row for row in raw_items if isinstance(row, Mapping) and _order_line_item_id(row) == item_id
    ]
    if len(matches) != 1:
        raise DevolucionesReadModelVerificationError(
            "hydrated source proof requires one unique order line"
        )
    return matches[0]


def _order_line_item_id(row: Mapping[str, Any]) -> str:
    nested_item = row.get("item")
    value = nested_item.get("id") if isinstance(nested_item, Mapping) else row.get("item_id")
    return str(value or "").strip()


def _order_line_variation_id(row: Mapping[str, Any]) -> str | None:
    nested_item = row.get("item")
    value = (
        nested_item.get("variation_id")
        if isinstance(nested_item, Mapping)
        else row.get("variation_id")
    )
    return _optional_fingerprint_text(value)


def _order_line_formula_sku(row: Mapping[str, Any]) -> str | None:
    nested_item = row.get("item")
    nested = nested_item if isinstance(nested_item, Mapping) else {}
    value = (
        row.get("sku")
        or row.get("seller_sku")
        or row.get("seller_custom_field")
        or nested.get("seller_sku")
        or nested.get("seller_custom_field")
    )
    normalized = str(value).strip().upper() if value is not None else ""
    return normalized or None


def _order_line_formula_title(row: Mapping[str, Any]) -> str | None:
    nested_item = row.get("item")
    nested = nested_item if isinstance(nested_item, Mapping) else {}
    return _optional_fingerprint_text(row.get("title") or nested.get("title"))


def _order_line_quantity(row: Mapping[str, Any]) -> int:
    value = row.get("qty", row.get("quantity"))
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DevolucionesReadModelVerificationError(
            "hydrated source proof order line quantity is invalid"
        )
    return cast(int, value)


def _required_text(value: Any, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise DevolucionesReadModelVerificationError(f"{field} is required")
    return normalized


def _utc_datetime(value: Any, *, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise DevolucionesReadModelVerificationError(f"{field} must be a datetime")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _is_return_candidate(claim: Mapping[str, Any]) -> bool:
    claim_type = str(claim.get("type") or "")
    if claim_type in {"return", "returns"}:
        return True
    return claim_type == "mediations"


def _is_authoritative_upstream_not_found(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    return bool(
        getattr(response, "status_code", None) == 404
        and isinstance(headers, Mapping)
        and headers.get("X-Zeler-Upstream-Attempts") == "1"
    )


def _is_authoritative_no_return_mediation(
    *,
    entry: ClaimInventoryEntry,
    claim: Mapping[str, Any],
    seller_id: str,
) -> bool:
    claim_id = str(claim.get("id") or claim.get("_id") or "").strip()
    last_updated = str(claim.get("last_updated") or "").strip()
    direct_order_id = str(claim.get("order_id") or "").strip()
    resource_order_id = str(claim.get("resource_id") or "").strip()
    order_id = direct_order_id or resource_order_id
    order_identities = {
        identity
        for identity in (
            direct_order_id,
            resource_order_id,
            str(entry.source.get("order_id") or "").strip(),
            str(entry.source.get("resource_id") or "").strip(),
        )
        if identity
    }
    order_identity_agrees = len(order_identities) == 1 and all(
        re.fullmatch(r"[0-9]+", identity) for identity in order_identities
    )
    item_id = claim.get("item_id")
    item_identity_absent = item_id is None or (isinstance(item_id, str) and not item_id.strip())
    related_entities = claim.get("related_entities")
    related_return_absent = related_entities is None or (
        isinstance(related_entities, list)
        and all(isinstance(entity, Mapping) for entity in related_entities)
        and not any(
            str(entity.get("type") or "").strip().lower() in {"return", "returns"}
            for entity in related_entities
        )
    )
    players = claim.get("players")
    seller_respondents = (
        [
            player
            for player in players
            if isinstance(player, Mapping)
            and player.get("role") == "respondent"
            and player.get("type") == "seller"
        ]
        if isinstance(players, list)
        else []
    )
    seller_respondent_agrees = bool(
        len(seller_respondents) == 1 and str(seller_respondents[0].get("user_id")) == str(seller_id)
    )
    contradictory_return_evidence = any(
        claim.get(field_name) not in (None, "", [], {})
        for field_name in (
            "return_id",
            "return_quantity",
            "returned_quantity",
            "return",
            "returns",
        )
    )
    return bool(
        entry.trusted_type == "mediations"
        and entry.trusted_status in {"", "closed"}
        and claim_id == entry.claim_id
        and last_updated == entry.last_updated
        and str(claim.get("type") or "").strip().lower() == "mediations"
        and str(claim.get("status") or "").strip().lower() == "closed"
        and re.fullmatch(r"[0-9]+", order_id)
        and order_identity_agrees
        and item_identity_absent
        and related_return_absent
        and seller_respondent_agrees
        and not contradictory_return_evidence
    )


def _validated_utc_range(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    if start.tzinfo is None or end.tzinfo is None:
        raise ClaimInventoryError("claim inventory bounds must be timezone-aware")
    normalized_start = start.astimezone(UTC)
    normalized_end = end.astimezone(UTC)
    if normalized_end <= normalized_start:
        raise ClaimInventoryError("claim inventory end must be after start")
    return normalized_start, normalized_end


def _format_meli_datetime(value: datetime) -> str:
    utc_value = value.astimezone(UTC)
    milliseconds = utc_value.microsecond // 1000
    return f"{utc_value:%Y-%m-%dT%H:%M:%S}.{milliseconds:03d}+0000"
