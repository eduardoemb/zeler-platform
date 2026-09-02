from __future__ import annotations

import hashlib
import inspect
import re
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from pymongo.errors import OperationFailure
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from zeler_platform_core.cli.export_schemas import ENTITY_SCHEMAS, _validator_payload

from .source_gated_read_model_writers import (
    _canonical_bson_bytes,
    _canonical_bson_document,
    _deep_freeze,
    _plan_stock_time_actions,
    _StockTimeAction,
    _StockTimeActionPlan,
    _StockTimeActionPlanError,
)

_READ_MODEL = "stock_time_metrics"
_METRIC_COLLECTION = "sheets_stock_time_metrics"
_MARKER_COLLECTION = "sheets_read_model_freshness"
_OPERATION_COLLECTION = "sheets_stock_time_reconciliation_operations"
_PREIMAGE_COLLECTION = "sheets_stock_time_reconciliation_preimages"
_RECONCILE_SOURCE = "zelerdata_read_model_reconcile"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ATTEMPT_TOKEN = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True)
class _StockTimeIndexDescriptor:
    name: str
    keys: tuple[tuple[str, int], ...]
    unique: bool = False


_STOCK_TIME_WRITE_EXPECTED_INDEXES = (
    (
        _METRIC_COLLECTION,
        (
            _StockTimeIndexDescriptor(
                "idx_sheets_stock_time_metrics_seller_item_range",
                (("seller_id", 1), ("item_id", 1), ("date_from", 1), ("date_to", 1)),
            ),
            _StockTimeIndexDescriptor(
                "idx_sheets_stock_time_metrics_seller_sku_range",
                (("seller_id", 1), ("normalized_sku", 1), ("date_from", 1), ("date_to", 1)),
            ),
        ),
    ),
    (
        _MARKER_COLLECTION,
        (
            _StockTimeIndexDescriptor(
                "uniq_sheets_read_model_freshness_seller_model",
                (("seller_id", 1), ("read_model", 1)),
                True,
            ),
            _StockTimeIndexDescriptor(
                "idx_sheets_read_model_freshness_seller_state_until",
                (("seller_id", 1), ("state", 1), ("fresh_until", -1)),
            ),
            _StockTimeIndexDescriptor(
                "idx_sheets_read_model_freshness_seller_state_valid_until",
                (("seller_id", 1), ("state", 1), ("valid_until", 1)),
            ),
        ),
    ),
    (
        _OPERATION_COLLECTION,
        (
            _StockTimeIndexDescriptor(
                "uniq_sheets_stock_time_reconciliation_operation_binding",
                (
                    ("seller_id", 1),
                    ("read_model", 1),
                    ("date_from", 1),
                    ("date_to", 1),
                    ("source_fingerprint", 1),
                    ("plan_fingerprint", 1),
                ),
                True,
            ),
            _StockTimeIndexDescriptor(
                "idx_sheets_stock_time_reconciliation_operations_state_lease",
                (("state", 1), ("lease_until", 1)),
            ),
        ),
    ),
    (
        _PREIMAGE_COLLECTION,
        (
            _StockTimeIndexDescriptor(
                "uniq_sheets_stock_time_reconciliation_preimages_operation_sequence",
                (("operation_id", 1), ("sequence", 1)),
                True,
            ),
            _StockTimeIndexDescriptor(
                "uniq_sheets_stock_time_reconciliation_preimages_operation_target",
                (("operation_id", 1), ("target_collection", 1), ("target_id", 1)),
                True,
            ),
            _StockTimeIndexDescriptor(
                "idx_sheets_stock_time_reconciliation_preimages_target",
                (("target_collection", 1), ("target_id", 1)),
            ),
        ),
    ),
)


@dataclass(frozen=True)
class _StockTimeRuntimeReadiness:
    ready: bool
    issues: tuple[str, ...]


def _valid_hello(hello: Mapping[str, Any]) -> tuple[str, ...]:
    issues: list[str] = []
    if "msg" in hello:
        issues.append("HELLO_MONGOS")
    if hello.get("isWritablePrimary") is not True:
        issues.append("HELLO_NOT_WRITABLE_PRIMARY")
    if not (
        isinstance(hello.get("setName"), str)
        and bool(hello["setName"].strip())
        and type(hello.get("logicalSessionTimeoutMinutes")) is int
        and hello["logicalSessionTimeoutMinutes"] > 0
        and type(hello.get("maxWireVersion")) is int
        and hello["maxWireVersion"] >= 7
    ):
        issues.append("HELLO_INVALID")
    return tuple(issues)


def _expected_validator(collection: str) -> Mapping[str, Any]:
    payload = _validator_payload(ENTITY_SCHEMAS[collection])
    return {"$jsonSchema": payload["$jsonSchema"]}


def _collection_contract(response: Any, collection: str, validator: Mapping[str, Any]) -> bool:
    if not isinstance(response, Mapping):
        return False
    cursor = response.get("cursor")
    if not isinstance(cursor, Mapping):
        return False
    batch = cursor.get("firstBatch")
    if not isinstance(batch, list) or len(batch) != 1 or not isinstance(batch[0], Mapping):
        return False
    item = batch[0]
    options = item.get("options")
    return (
        item.get("name") == collection
        and item.get("type") == "collection"
        and isinstance(options, Mapping)
        and options.get("validator") == validator
        and options.get("validationLevel") == "strict"
        and options.get("validationAction") == "error"
    )


def _index_contract(observed: Any, descriptors: Sequence[_StockTimeIndexDescriptor]) -> bool:
    if not isinstance(observed, list):
        return False
    expected = (("_id_", (("_id", 1),), False),) + tuple(
        (item.name, item.keys, item.unique) for item in descriptors
    )
    if len(observed) != len(expected):
        return False
    for index, (name, keys, unique) in zip(observed, expected, strict=True):
        if not isinstance(index, Mapping):
            return False
        normalized = {key: value for key, value in index.items() if key not in {"v", "ns"}}
        key_document = normalized.get("key")
        actual_unique = normalized.get("unique", False)
        if (
            set(normalized) - {"name", "key", "unique"}
            or normalized.get("name") != name
            or not isinstance(key_document, Mapping)
            or tuple(key_document.items()) != keys
            or type(actual_unique) is not bool
            or actual_unique is not unique
        ):
            return False
    return True


async def _preflight_stock_time_runtime(db: Any) -> _StockTimeRuntimeReadiness:
    """Read the minimum Mongo runtime contract without starting sessions or mutating state."""
    issues: set[str] = set()
    try:
        hello = await db.command("hello")
    except Exception:  # noqa: BLE001 - the readiness result is intentionally sanitized
        issues.add("HELLO_UNAVAILABLE")
    else:
        if not isinstance(hello, Mapping):
            issues.add("HELLO_INVALID")
        else:
            issues.update(_valid_hello(hello))

    try:
        start_session = db.client.start_session
    except Exception:  # noqa: BLE001 - driver proxies can fail while resolving attributes
        issues.add("SESSION_UNAVAILABLE")
    else:
        if not callable(start_session):
            issues.add("SESSION_UNAVAILABLE")

    validators: dict[str, Mapping[str, Any]] = {}
    for collection, _ in _STOCK_TIME_WRITE_EXPECTED_INDEXES:
        try:
            validators[collection] = _expected_validator(collection)
        except Exception:  # noqa: BLE001 - installed Core contract is unavailable or malformed
            issues.add("VALIDATOR_CONTRACT_UNAVAILABLE")

    for collection, descriptors in _STOCK_TIME_WRITE_EXPECTED_INDEXES:
        validator = validators.get(collection)
        if validator is None:
            continue
        try:
            listed = await db.command("listCollections", filter={"name": collection})
        except Exception:  # noqa: BLE001 - no driver detail may escape the readiness result
            issues.add("COLLECTION_READ_FAILED")
        else:
            if not _collection_contract(listed, collection, validator):
                issues.add("COLLECTION_CONTRACT_INVALID")
        try:
            indexes = await db[collection].list_indexes().to_list(length=None)
        except Exception:  # noqa: BLE001 - no driver detail may escape the readiness result
            issues.add("INDEX_READ_FAILED")
        else:
            if not _index_contract(indexes, descriptors):
                issues.add("INDEX_CONTRACT_INVALID")

    normalized_issues = tuple(sorted(issues))
    return _StockTimeRuntimeReadiness(not normalized_issues, normalized_issues)


_ERROR_CODES = frozenset(
    {
        "INVALID_SELLER",
        "INVALID_UTC_INTERVAL",
        "INVALID_SHA256",
        "INVALID_BSON_INPUT",
        "ACTION_SCOPE_MISMATCH",
        "INVALID_ACTION",
        "INVALID_ATTEMPT_TOKEN",
        "TRANSACTION_REQUIRED",
        "INVALID_OPERATION_SCHEMA",
        "OPERATION_MISMATCH",
        "TAKEOVER_CONFLICT",
        "LEASE_CONFLICT",
        "FENCE_CONFLICT",
        "PREIMAGE_MISMATCH",
        "MARKER_CONFLICT",
        "MARKER_READBACK_MISMATCH",
        "COMMIT_CONFLICT",
        "COMMIT_READBACK_MISMATCH",
        "COMMIT_OUTCOME_UNKNOWN",
        "STATE_BLOCKED",
        "ROLLBACK_BLOCKED",
    }
)


class _ForwardEngineError(RuntimeError):
    def __init__(self, code: str) -> None:
        if code not in _ERROR_CODES:
            raise ValueError("unknown forward-engine error code")
        self.code = code
        super().__init__(code)


class _TargetDriftError(RuntimeError):
    """Private, identifier-free signal that a live forward target changed."""


@dataclass(frozen=True)
class _ForwardBinding:
    _seller_id: str = field(repr=False)
    date_from: datetime
    date_to: datetime
    source_fingerprint: str
    plan_fingerprint: str


@dataclass(frozen=True)
class _ForwardMutation:
    sequence: int
    target_collection: str
    _target_id: str = field(repr=False)
    action: str
    _document: Mapping[str, Any] | None = field(repr=False)
    _preimage: Mapping[str, Any] | None = field(repr=False)
    preimage_kind: str
    preimage_fingerprint: str
    expected_forward_revision: str


@dataclass(frozen=True)
class _ForwardLedgerCounts:
    planned_insert_count: int
    planned_update_count: int
    planned_delete_count: int
    planned_preimage_count: int


@dataclass(frozen=True)
class _ForwardOperationContext:
    operation_id: str
    state: str
    attempt: int
    attempt_token: str = field(repr=False)
    fence: int
    owns_lease: bool


@dataclass(frozen=True)
class _SealedForwardPlan:
    binding: _ForwardBinding
    _action_plan: _StockTimeActionPlan = field(repr=False)
    operation_id: str
    _marker_action: str = field(repr=False)
    _marker_preimage: Mapping[str, Any] | None = field(repr=False)
    _mutations: tuple[_ForwardMutation, ...] = field(repr=False)
    _expected_metric_documents: tuple[Mapping[str, Any], ...] = field(repr=False)
    _desired_marker: Mapping[str, Any] = field(repr=False)
    expected_metric_fingerprint: str
    ledger_counts: _ForwardLedgerCounts


@dataclass(frozen=True)
class _ValidatedRollbackRecordSet:
    operation_id: str
    state: str
    _operation: Mapping[str, Any] = field(repr=False)
    _records: tuple[Mapping[str, Any], ...] = field(repr=False)


@dataclass(frozen=True)
class _RollbackMutation:
    target_collection: str
    _target_id: str = field(repr=False)
    action: str
    expected_forward_revision: str
    forward_sequence: int
    _restoration: Mapping[str, Any] | None = field(repr=False)


@dataclass(frozen=True)
class _ForwardRollbackPlan:
    operation_id: str
    state: str
    _mutations: tuple[_RollbackMutation, ...] = field(repr=False)


def _new_forward_attempt_token() -> str:
    return secrets.token_hex(16)


@asynccontextmanager
async def _required_transaction(db: Any) -> AsyncIterator[Any]:
    session_context: Any = None
    session_entered = False
    try:
        client = getattr(db, "client", None)
        start_session = getattr(client, "start_session", None)
        if not callable(start_session):
            raise TypeError("start_session unavailable")
        session_context = start_session()
        if inspect.isawaitable(session_context):
            session_context = await session_context
        session_enter = getattr(session_context, "__aenter__", None)
        session_exit = getattr(session_context, "__aexit__", None)
        if not callable(session_enter) or not callable(session_exit):
            raise TypeError("async session context unavailable")
        session = await session_enter()
        session_entered = True
        start_transaction = getattr(session, "start_transaction", None)
        if not callable(start_transaction):
            raise TypeError("start_transaction unavailable")
        transaction = start_transaction(
            read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority")
        )
        transaction_enter = getattr(transaction, "__aenter__", None)
        transaction_exit = getattr(transaction, "__aexit__", None)
        if not callable(transaction_enter) or not callable(transaction_exit):
            raise TypeError("async transaction context unavailable")
        await transaction_enter()
    except Exception as exc:
        if session_entered:
            try:
                await session_context.__aexit__(type(exc), exc, exc.__traceback__)
            except Exception as cleanup_exc:
                raise _ForwardEngineError("TRANSACTION_REQUIRED") from cleanup_exc
        raise _ForwardEngineError("TRANSACTION_REQUIRED") from exc
    try:
        yield session
    except BaseException as exc:
        await transaction_exit(type(exc), exc, exc.__traceback__)
        await session_exit(type(exc), exc, exc.__traceback__)
        raise
    else:
        try:
            await transaction_exit(None, None, None)
        except BaseException as exc:
            await session_exit(type(exc), exc, exc.__traceback__)
            raise
        await session_exit(None, None, None)


def _persisted_operation_context(
    operation: Mapping[str, Any], *, owns_lease: bool
) -> _ForwardOperationContext:
    return _ForwardOperationContext(
        operation_id=operation["_id"],
        state=operation["state"],
        attempt=operation["attempt"],
        attempt_token=operation["attempt_token"],
        fence=operation["fence"],
        owns_lease=owns_lease,
    )


def _operation_immutable(sealed_plan: _SealedForwardPlan) -> dict[str, Any]:
    binding, counts = sealed_plan.binding, sealed_plan.ledger_counts
    return {
        "_id": sealed_plan.operation_id,
        "seller_id": binding._seller_id,
        "read_model": _READ_MODEL,
        "date_from": binding.date_from,
        "date_to": binding.date_to,
        "source_fingerprint": binding.source_fingerprint,
        "plan_fingerprint": binding.plan_fingerprint,
        "planned_insert_count": counts.planned_insert_count,
        "planned_update_count": counts.planned_update_count,
        "planned_delete_count": counts.planned_delete_count,
        "planned_preimage_count": counts.planned_preimage_count,
    }


def _validate_persisted_operation(
    operation: Any, immutable: Mapping[str, Any]
) -> Mapping[str, Any]:
    if not isinstance(operation, Mapping):
        raise _ForwardEngineError("INVALID_OPERATION_SCHEMA")
    positive_integers = (operation.get("attempt"), operation.get("fence"))
    counts = tuple(
        operation.get(field)
        for field in (
            "planned_insert_count",
            "planned_update_count",
            "planned_delete_count",
            "planned_preimage_count",
        )
    )
    timestamps = tuple(
        operation.get(field) for field in ("lease_acquired_at", "heartbeat_at", "lease_until")
    )
    schema_valid = (
        operation.get("schema_version") == 1
        and type(operation.get("schema_version")) is int
        and isinstance(operation.get("state"), str)
        and all(type(value) is int and value > 0 for value in positive_integers)
        and all(type(value) is int and value >= 0 for value in counts)
        and isinstance(operation.get("attempt_token"), str)
        and _ATTEMPT_TOKEN.fullmatch(operation["attempt_token"]) is not None
        and all(
            isinstance(value, datetime)
            and value.tzinfo is not None
            and value.utcoffset() == timedelta(0)
            for value in timestamps
        )
    )
    if not schema_valid:
        raise _ForwardEngineError("INVALID_OPERATION_SCHEMA")
    if any(operation.get(field) != expected for field, expected in immutable.items()):
        raise _ForwardEngineError("OPERATION_MISMATCH")
    return operation


async def _acquire_forward_operation(
    db: Any, sealed_plan: _SealedForwardPlan, attempt_token: str
) -> _ForwardOperationContext:
    if not isinstance(attempt_token, str) or _ATTEMPT_TOKEN.fullmatch(attempt_token) is None:
        raise _ForwardEngineError("INVALID_ATTEMPT_TOKEN")
    binding = sealed_plan.binding
    exact_binding = {
        "seller_id": binding._seller_id,
        "read_model": _READ_MODEL,
        "date_from": binding.date_from,
        "date_to": binding.date_to,
        "source_fingerprint": binding.source_fingerprint,
        "plan_fingerprint": binding.plan_fingerprint,
    }
    counts = sealed_plan.ledger_counts
    exact_immutable = {
        "_id": sealed_plan.operation_id,
        **exact_binding,
        "planned_insert_count": counts.planned_insert_count,
        "planned_update_count": counts.planned_update_count,
        "planned_delete_count": counts.planned_delete_count,
        "planned_preimage_count": counts.planned_preimage_count,
    }
    context = _ForwardOperationContext(
        sealed_plan.operation_id, "prepared", 1, attempt_token, 1, True
    )
    async with _required_transaction(db) as session:
        operations = db[_OPERATION_COLLECTION]
        existing = await operations.find_one(
            {"$or": [{"_id": sealed_plan.operation_id}, exact_binding]}, session=session
        )
        if existing is not None:
            persisted = _validate_persisted_operation(existing, exact_immutable)
            if persisted["state"] == "committed":
                return _persisted_operation_context(persisted, owns_lease=False)
            if persisted["state"] != "prepared":
                raise _ForwardEngineError("STATE_BLOCKED")
            identity = {"_id": sealed_plan.operation_id, "state": "prepared"}
            live_owner = await operations.find_one(
                {
                    **identity,
                    "attempt_token": attempt_token,
                    "$expr": {"$gt": ["$lease_until", "$$NOW"]},
                },
                session=session,
            )
            if live_owner is not None:
                return _persisted_operation_context(persisted, owns_lease=True)
            expired = await operations.find_one(
                {**identity, "$expr": {"$lte": ["$lease_until", "$$NOW"]}},
                session=session,
            )
            if expired is None:
                raise _ForwardEngineError("LEASE_CONFLICT")
            takeover = await operations.update_one(
                {
                    **exact_immutable,
                    "state": "prepared",
                    "attempt": persisted["attempt"],
                    "attempt_token": persisted["attempt_token"],
                    "fence": persisted["fence"],
                    "$expr": {"$lte": ["$lease_until", "$$NOW"]},
                },
                [
                    {
                        "$set": {
                            "state": "prepared",
                            "attempt": {"$add": ["$attempt", 1]},
                            "attempt_token": attempt_token,
                            "fence": {"$add": ["$fence", 1]},
                            "lease_acquired_at": "$$NOW",
                            "heartbeat_at": "$$NOW",
                            "lease_until": {
                                "$dateAdd": {
                                    "startDate": "$$NOW",
                                    "unit": "second",
                                    "amount": 120,
                                }
                            },
                            "updated_at": "$$NOW",
                            "committed_at": None,
                            "terminal_at": None,
                            "error_code": None,
                        }
                    }
                ],
                session=session,
            )
            if takeover.matched_count != 1:
                raise _ForwardEngineError("TAKEOVER_CONFLICT")
            return _ForwardOperationContext(
                sealed_plan.operation_id,
                "prepared",
                persisted["attempt"] + 1,
                attempt_token,
                persisted["fence"] + 1,
                True,
            )
        prepared = {
            "_id": sealed_plan.operation_id,
            **exact_binding,
            "state": "prepared",
            "attempt": 1,
            "attempt_token": attempt_token,
            "fence": 1,
            "lease_acquired_at": "$$NOW",
            "heartbeat_at": "$$NOW",
            "lease_until": {"$dateAdd": {"startDate": "$$NOW", "unit": "second", "amount": 120}},
            "planned_insert_count": counts.planned_insert_count,
            "planned_update_count": counts.planned_update_count,
            "planned_delete_count": counts.planned_delete_count,
            "planned_preimage_count": counts.planned_preimage_count,
            "created_at": "$$NOW",
            "updated_at": "$$NOW",
            "committed_at": None,
            "terminal_at": None,
            "error_code": None,
            "schema_version": 1,
        }
        await operations.update_one(
            {"_id": sealed_plan.operation_id},
            [{"$replaceWith": prepared}],
            upsert=True,
            session=session,
        )
    return context


def _digest(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bson_bytes(document)).hexdigest()


def _preimage_record_id(operation_id: str, mutation: _ForwardMutation) -> str:
    return _digest(
        {
            "domain": "zeler.stock-time-forward-preimage-record",
            "version": 1,
            "operation_id": operation_id,
            "sequence": mutation.sequence,
            "target_collection": mutation.target_collection,
            "target_id": mutation._target_id,
        }
    )


def _preimage_records(
    sealed_plan: _SealedForwardPlan, created_at: datetime
) -> list[dict[str, Any]]:
    return [
        {
            "_id": _preimage_record_id(sealed_plan.operation_id, mutation),
            "operation_id": sealed_plan.operation_id,
            "sequence": mutation.sequence,
            "target_collection": mutation.target_collection,
            "target_id": mutation._target_id,
            "action": mutation.action,
            "preimage": (
                _canonical_bson_document(mutation._preimage)
                if mutation._preimage is not None
                else None
            ),
            "preimage_kind": mutation.preimage_kind,
            "preimage_fingerprint": mutation.preimage_fingerprint,
            "expected_forward_revision": mutation.expected_forward_revision,
            "created_at": created_at,
            "schema_version": 1,
        }
        for mutation in sealed_plan._mutations
    ]


def _operation_revision(
    operation_id: str, target_collection: str, target_id: str, action: str
) -> str:
    return _digest(
        {
            "domain": "zeler.stock-time-forward-revision",
            "version": 1,
            "operation_id": operation_id,
            "target_collection": target_collection,
            "target_id": target_id,
            "action": action,
        }
    )


def _preimage_fingerprint(preimage: Mapping[str, Any] | None) -> str:
    return _digest(
        {
            "domain": "zeler.stock-time-forward-preimage",
            "version": 1,
            "preimage_kind": "absent" if preimage is None else "exact_document",
            "preimage": preimage,
        }
    )


def _metric_proof_fingerprint(documents: Sequence[Mapping[str, Any]]) -> str:
    exact = sorted(documents, key=lambda document: str(document.get("_id")))
    return _digest(
        {
            "domain": "zeler.stock-time-forward-metric-proof",
            "version": 1,
            "exact_final_metrics": exact,
        }
    )


def _mutation(
    *,
    operation_id: str,
    sequence: int,
    target_collection: str,
    target_id: str,
    action: str,
    document: Mapping[str, Any] | None,
    preimage: Mapping[str, Any] | None,
) -> _ForwardMutation:
    return _ForwardMutation(
        sequence=sequence,
        target_collection=target_collection,
        _target_id=target_id,
        action=action,
        _document=_deep_freeze(document),
        _preimage=_deep_freeze(preimage),
        preimage_kind="absent" if preimage is None else "exact_document",
        preimage_fingerprint=_preimage_fingerprint(preimage),
        expected_forward_revision=_operation_revision(
            operation_id, target_collection, target_id, action
        ),
    )


def _materialize_forward_plan(
    *,
    binding: _ForwardBinding,
    action_plan: _StockTimeActionPlan,
    operation_id: str,
    marker_action: str,
    marker_preimage: Mapping[str, Any] | None,
) -> _SealedForwardPlan:
    mutations: list[_ForwardMutation] = []
    final_metrics: list[Mapping[str, Any]] = []
    for action in action_plan.actions:
        if action.action == "no-op":
            if action._preimage is None:
                raise _ForwardEngineError("INVALID_ACTION")
            final_metrics.append(action._preimage)
            continue
        revision = _operation_revision(
            operation_id, _METRIC_COLLECTION, action._target_id, action.action
        )
        document = None
        if action.action != "delete":
            if action._document is None:
                raise _ForwardEngineError("INVALID_ACTION")
            document = _canonical_bson_document({**action._document, "revision": revision})
            final_metrics.append(document)
        mutations.append(
            _mutation(
                operation_id=operation_id,
                sequence=len(mutations) + 1,
                target_collection=_METRIC_COLLECTION,
                target_id=action._target_id,
                action=action.action,
                document=document,
                preimage=action._preimage,
            )
        )

    expected_metrics = tuple(_deep_freeze(document) for document in final_metrics)
    proof = _metric_proof_fingerprint(expected_metrics)
    marker_id = f"{binding._seller_id}:{_READ_MODEL}"
    marker_revision = _operation_revision(
        operation_id, _MARKER_COLLECTION, marker_id, marker_action
    )
    marker = _canonical_bson_document(
        {
            "_id": marker_id,
            "seller_id": binding._seller_id,
            "read_model": _READ_MODEL,
            "state": "reconciled",
            "date_from": binding.date_from,
            "fresh_until": binding.date_to,
            "reconciled_until": binding.date_to,
            "last_event_synced_at": binding.date_from,
            "updated_at": binding.date_to,
            "source": _RECONCILE_SOURCE,
            "coverage_basis": "legacy_imported",
            "revision": marker_revision,
            "proof_fingerprint": proof,
            "schema_version": 1,
        }
    )
    mutations.append(
        _mutation(
            operation_id=operation_id,
            sequence=len(mutations) + 1,
            target_collection=_MARKER_COLLECTION,
            target_id=marker_id,
            action=marker_action,
            document=marker,
            preimage=marker_preimage,
        )
    )
    frozen_mutations = tuple(mutations)
    counts = _ForwardLedgerCounts(
        planned_insert_count=sum(item.action == "insert" for item in frozen_mutations),
        planned_update_count=sum(item.action == "replace" for item in frozen_mutations),
        planned_delete_count=sum(item.action == "delete" for item in frozen_mutations),
        planned_preimage_count=len(frozen_mutations),
    )
    return _SealedForwardPlan(
        binding,
        action_plan,
        operation_id,
        marker_action,
        _deep_freeze(marker_preimage),
        frozen_mutations,
        expected_metrics,
        _deep_freeze(marker),
        proof,
        counts,
    )


def _validated_action_plan(
    source_inventory: Sequence[Mapping[str, Any]], supplied: _StockTimeActionPlan
) -> _StockTimeActionPlan:
    try:
        for row in source_inventory:
            _canonical_bson_bytes(row)
        if not all(isinstance(action, _StockTimeAction) for action in supplied.actions):
            raise _ForwardEngineError("INVALID_ACTION")
        planned = [action._document for action in supplied.actions if action._document is not None]
        existing = [action._preimage for action in supplied.actions if action._preimage is not None]
        validated = _plan_stock_time_actions(
            source_inventory=source_inventory,
            planned_documents=planned,
            existing_target_rows=existing,
        )
    except _StockTimeActionPlanError as exc:
        raise _ForwardEngineError("INVALID_ACTION") from exc
    if supplied != validated:
        raise _ForwardEngineError("INVALID_ACTION")
    return validated


def _seal_forward_plan(
    *,
    seller_id: str,
    date_from: datetime,
    date_to: datetime,
    source_inventory: Sequence[Mapping[str, Any]],
    action_plan: _StockTimeActionPlan,
    marker_preimage: Mapping[str, Any] | None,
) -> _SealedForwardPlan:
    seller = seller_id.strip() if isinstance(seller_id, str) else ""
    if not seller:
        raise _ForwardEngineError("INVALID_SELLER")
    bounds = (date_from, date_to)
    if (
        not all(isinstance(value, datetime) for value in bounds)
        or any(value.tzinfo is None or value.utcoffset() != timedelta(0) for value in bounds)
        or date_to <= date_from
    ):
        raise _ForwardEngineError("INVALID_UTC_INTERVAL")
    start, end = date_from.astimezone(UTC), date_to.astimezone(UTC)
    if not isinstance(action_plan, _StockTimeActionPlan):
        raise _ForwardEngineError("INVALID_ACTION")
    fingerprints = (
        action_plan.source_fingerprint,
        action_plan.preimage_fingerprint,
        action_plan.plan_fingerprint,
    )
    if not all(isinstance(value, str) and _SHA.fullmatch(value) for value in fingerprints):
        raise _ForwardEngineError("INVALID_SHA256")
    try:
        prior = _canonical_bson_document(marker_preimage) if marker_preimage is not None else None
    except _StockTimeActionPlanError as exc:
        raise _ForwardEngineError("INVALID_BSON_INPUT") from exc
    marker_id = f"{seller}:{_READ_MODEL}"
    if prior is not None and (
        prior.get("_id") != marker_id
        or str(prior.get("seller_id")) != seller
        or prior.get("read_model") != _READ_MODEL
    ):
        raise _ForwardEngineError("ACTION_SCOPE_MISMATCH")
    presence = {
        "insert": (True, False),
        "replace": (True, True),
        "delete": (False, True),
        "no-op": (True, True),
    }
    for action in action_plan.actions:
        if not isinstance(action, _StockTimeAction) or action.action not in presence:
            raise _ForwardEngineError("INVALID_ACTION")
        if (action._document is not None, action._preimage is not None) != presence[action.action]:
            raise _ForwardEngineError("INVALID_ACTION")
        scoped = (
            document for document in (action._document, action._preimage) if document is not None
        )
        if any(
            document.get("_id") != action._target_id
            or str(document.get("seller_id")) != seller
            or document.get("date_from") != start
            or document.get("date_to") != end
            for document in scoped
        ):
            raise _ForwardEngineError("ACTION_SCOPE_MISMATCH")
    validated = _validated_action_plan(source_inventory, action_plan)
    seal_material = {
        "domain": "zeler.stock-time-forward-plan",
        "version": 1,
        "action_plan_fingerprint": validated.plan_fingerprint,
        "marker_preimage": prior,
    }
    sealed_fingerprint = _digest(seal_material)
    binding = _ForwardBinding(seller, start, end, validated.source_fingerprint, sealed_fingerprint)
    operation_id = _digest(
        {
            "domain": "zeler.stock-time-forward-operation",
            "version": 1,
            "seller_id": seller,
            "date_from": start,
            "date_to": end,
            "source_fingerprint": binding.source_fingerprint,
            "plan_fingerprint": binding.plan_fingerprint,
        }
    )
    return _materialize_forward_plan(
        binding=binding,
        action_plan=validated,
        operation_id=operation_id,
        marker_action="replace" if prior is not None else "insert",
        marker_preimage=prior,
    )


def _exact_preimages_match(
    observed: Sequence[Mapping[str, Any]], expected: Sequence[Mapping[str, Any]]
) -> bool:
    try:
        return sorted(_canonical_bson_bytes(row) for row in observed) == sorted(
            _canonical_bson_bytes(row) for row in expected
        )
    except _StockTimeActionPlanError:
        return False


async def _validated_execution_operation(
    db: Any,
    sealed_plan: _SealedForwardPlan,
    context: _ForwardOperationContext,
    session: Any,
) -> Mapping[str, Any]:
    if (
        not isinstance(context, _ForwardOperationContext)
        or context.operation_id != sealed_plan.operation_id
        or context.state != "prepared"
        or not context.owns_lease
    ):
        raise _ForwardEngineError("FENCE_CONFLICT")
    operations = db[_OPERATION_COLLECTION]
    operation = await operations.find_one({"_id": sealed_plan.operation_id}, session=session)
    if operation is None:
        raise _ForwardEngineError("OPERATION_MISMATCH")
    persisted = _validate_persisted_operation(operation, _operation_immutable(sealed_plan))
    if persisted["state"] != "prepared":
        raise _ForwardEngineError("STATE_BLOCKED")
    if any(
        persisted[field] != expected
        for field, expected in {
            "attempt": context.attempt,
            "attempt_token": context.attempt_token,
            "fence": context.fence,
        }.items()
    ):
        raise _ForwardEngineError("FENCE_CONFLICT")
    live = await operations.find_one(
        {
            "_id": sealed_plan.operation_id,
            "state": "prepared",
            "attempt": context.attempt,
            "attempt_token": context.attempt_token,
            "fence": context.fence,
            "$expr": {"$gt": ["$lease_until", "$$NOW"]},
        },
        session=session,
    )
    if live is None:
        raise _ForwardEngineError("LEASE_CONFLICT")
    return persisted


def _metric_interval_query(binding: _ForwardBinding) -> dict[str, Any]:
    seller_values: list[str | int] = [binding._seller_id]
    if re.fullmatch(r"[0-9]+", binding._seller_id):
        seller_values.append(int(binding._seller_id))
    return {
        "seller_id": {"$in": seller_values},
        "date_from": binding.date_from,
        "date_to": binding.date_to,
    }


async def _metric_interval_documents(
    db: Any, sealed_plan: _SealedForwardPlan, session: Any
) -> list[Mapping[str, Any]]:
    cursor = db[_METRIC_COLLECTION].find(
        _metric_interval_query(sealed_plan.binding), session=session
    )
    documents: list[Mapping[str, Any]] = await cursor.to_list(length=None)
    return documents


async def _revalidate_forward_preimages(
    db: Any, sealed_plan: _SealedForwardPlan, session: Any
) -> None:
    binding = sealed_plan.binding
    observed = await _metric_interval_documents(db, sealed_plan, session)
    expected = [
        action._preimage
        for action in sealed_plan._action_plan.actions
        if action._preimage is not None
    ]
    marker = await db[_MARKER_COLLECTION].find_one(
        {"_id": f"{binding._seller_id}:{_READ_MODEL}"}, session=session
    )
    expected_marker = sealed_plan._marker_preimage
    if not _exact_preimages_match(observed, expected) or not _exact_preimages_match(
        [] if marker is None else [marker],
        [] if expected_marker is None else [expected_marker],
    ):
        raise _ForwardEngineError("PREIMAGE_MISMATCH")


async def _persist_forward_preimages(
    db: Any,
    sealed_plan: _SealedForwardPlan,
    context: _ForwardOperationContext,
    transaction_callback: (
        Callable[[Any], Awaitable[None]] | Sequence[Callable[[Any], Awaitable[None]]] | None
    ) = None,
) -> None:
    callbacks = (
        (transaction_callback,)
        if callable(transaction_callback)
        else (() if transaction_callback is None else transaction_callback)
    )
    async with _required_transaction(db) as session:
        operation = await _validated_execution_operation(db, sealed_plan, context, session)
        await _revalidate_forward_preimages(db, sealed_plan, session)
        records = _preimage_records(sealed_plan, operation["lease_acquired_at"])
        await db[_PREIMAGE_COLLECTION].insert_many(records, ordered=True, session=session)
        for callback in callbacks:
            await callback(session)


def _revision_state_guard(document: Mapping[str, Any] | None) -> dict[str, Any]:
    if document is None or "revision" not in document:
        return {"revision": {"$exists": False}}
    return {"revision": {"$exists": True, "$eq": document["revision"]}}


def _metric_cas_selector(
    sealed_plan: _SealedForwardPlan,
    action: _StockTimeAction,
    revision_document: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "_id": action._target_id,
        **_metric_interval_query(sealed_plan.binding),
        **_revision_state_guard(revision_document),
    }


def _exact_write_result(condition: bool) -> None:
    if not condition:
        raise _ForwardEngineError("PREIMAGE_MISMATCH")


async def _insert_metric_cas(
    collection: Any, sealed_plan: _SealedForwardPlan, action: _StockTimeAction, session: Any
) -> None:
    if action._document is None:
        raise _ForwardEngineError("INVALID_ACTION")
    desired = _canonical_bson_document(
        {
            **action._document,
            "revision": _operation_revision(
                sealed_plan.operation_id, _METRIC_COLLECTION, action._target_id, "insert"
            ),
        }
    )
    result = await collection.replace_one(
        _metric_cas_selector(sealed_plan, action, None), desired, upsert=True, session=session
    )
    _exact_write_result(result.matched_count == 0 and result.upserted_id == action._target_id)


async def _replace_metric_cas(
    collection: Any, sealed_plan: _SealedForwardPlan, action: _StockTimeAction, session: Any
) -> None:
    if action._document is None or action._preimage is None:
        raise _ForwardEngineError("INVALID_ACTION")
    desired = _canonical_bson_document(
        {
            **action._document,
            "revision": _operation_revision(
                sealed_plan.operation_id, _METRIC_COLLECTION, action._target_id, "replace"
            ),
        }
    )
    result = await collection.replace_one(
        _metric_cas_selector(sealed_plan, action, action._preimage), desired, session=session
    )
    _exact_write_result(result.matched_count == 1 and result.modified_count == 1)


async def _delete_metric_cas(
    collection: Any, sealed_plan: _SealedForwardPlan, action: _StockTimeAction, session: Any
) -> None:
    if action._preimage is None:
        raise _ForwardEngineError("INVALID_ACTION")
    result = await collection.delete_one(
        _metric_cas_selector(sealed_plan, action, action._preimage), session=session
    )
    _exact_write_result(result.deleted_count == 1)


async def _touch_noop_metric_cas(
    collection: Any, sealed_plan: _SealedForwardPlan, action: _StockTimeAction, session: Any
) -> None:
    if action._preimage is None:
        raise _ForwardEngineError("INVALID_ACTION")
    temporary_revision = _operation_revision(
        sealed_plan.operation_id, _METRIC_COLLECTION, action._target_id, "no-op"
    )
    if action._preimage.get("revision") == temporary_revision:
        temporary_revision = _operation_revision(
            sealed_plan.operation_id, _METRIC_COLLECTION, action._target_id, "no-op-alternate"
        )
    temporary = _canonical_bson_document({**action._preimage, "revision": temporary_revision})
    touched = await collection.replace_one(
        _metric_cas_selector(sealed_plan, action, action._preimage), temporary, session=session
    )
    _exact_write_result(touched.matched_count == 1 and touched.modified_count == 1)
    restored = await collection.replace_one(
        _metric_cas_selector(sealed_plan, action, temporary),
        _canonical_bson_document(action._preimage),
        session=session,
    )
    _exact_write_result(restored.matched_count == 1 and restored.modified_count == 1)


async def _write_and_verify_forward_metrics(
    db: Any, sealed_plan: _SealedForwardPlan, session: Any
) -> None:
    collection = db[_METRIC_COLLECTION]
    helpers = {
        "insert": _insert_metric_cas,
        "replace": _replace_metric_cas,
        "delete": _delete_metric_cas,
        "no-op": _touch_noop_metric_cas,
    }
    for action in sealed_plan._action_plan.actions:
        helper = helpers.get(action.action)
        if helper is None:
            raise _ForwardEngineError("INVALID_ACTION")
        await helper(collection, sealed_plan, action, session)
    observed = await _metric_interval_documents(db, sealed_plan, session)
    if not _exact_preimages_match(observed, sealed_plan._expected_metric_documents) or (
        _metric_proof_fingerprint(observed) != sealed_plan.expected_metric_fingerprint
    ):
        raise _ForwardEngineError("PREIMAGE_MISMATCH")


async def _persist_forward_metrics(
    db: Any, sealed_plan: _SealedForwardPlan, context: _ForwardOperationContext
) -> None:
    async def persist(session: Any) -> None:
        await _write_and_verify_forward_metrics(db, sealed_plan, session)

    await _persist_forward_preimages(db, sealed_plan, context, persist)


async def _write_and_verify_forward_marker(
    db: Any, sealed_plan: _SealedForwardPlan, session: Any
) -> None:
    desired = _canonical_bson_document(sealed_plan._desired_marker)
    expected = sealed_plan._marker_preimage
    selector = {
        "_id": desired["_id"],
        "seller_id": desired["seller_id"],
        "read_model": desired["read_model"],
        **_revision_state_guard(expected),
    }
    result = await db[_MARKER_COLLECTION].replace_one(
        selector, desired, upsert=expected is None, session=session
    )
    exact_result = (
        result.matched_count == 0 and result.upserted_id == desired["_id"]
        if expected is None
        else result.matched_count == 1 and result.modified_count == 1
    )
    if not exact_result:
        raise _ForwardEngineError("MARKER_CONFLICT")
    observed = await db[_MARKER_COLLECTION].find_one({"_id": desired["_id"]}, session=session)
    if not _exact_preimages_match([] if observed is None else [observed], [desired]):
        raise _ForwardEngineError("MARKER_READBACK_MISMATCH")


def _validated_committed_operation(
    observed: Any, sealed_plan: _SealedForwardPlan, context: _ForwardOperationContext
) -> Mapping[str, Any]:
    try:
        persisted = _validate_persisted_operation(observed, _operation_immutable(sealed_plan))
    except _ForwardEngineError as exc:
        raise _ForwardEngineError("COMMIT_READBACK_MISMATCH") from exc
    committed_at = persisted.get("committed_at")
    exact_fields = set(_operation_immutable(sealed_plan)) | {
        "state",
        "attempt",
        "attempt_token",
        "fence",
        "lease_acquired_at",
        "heartbeat_at",
        "lease_until",
        "created_at",
        "updated_at",
        "committed_at",
        "terminal_at",
        "error_code",
        "schema_version",
    }
    exact_context = {
        "state": "committed",
        "attempt": context.attempt,
        "attempt_token": context.attempt_token,
        "fence": context.fence,
        "error_code": None,
    }
    exact_timestamps = (
        isinstance(committed_at, datetime)
        and committed_at.tzinfo is not None
        and committed_at.utcoffset() == timedelta(0)
        and all(
            persisted.get(field) == committed_at
            for field in ("heartbeat_at", "updated_at", "terminal_at", "lease_until")
        )
    )
    created_at = persisted.get("created_at")
    if (
        set(persisted) != exact_fields
        or not isinstance(created_at, datetime)
        or created_at.tzinfo is None
        or created_at.utcoffset() != timedelta(0)
        or any(persisted.get(field) != value for field, value in exact_context.items())
        or not exact_timestamps
    ):
        raise _ForwardEngineError("COMMIT_READBACK_MISMATCH")
    return persisted


async def _write_and_verify_operation_commit(
    db: Any,
    sealed_plan: _SealedForwardPlan,
    context: _ForwardOperationContext,
    session: Any,
) -> None:
    operations = db[_OPERATION_COLLECTION]
    result = await operations.update_one(
        {
            **_operation_immutable(sealed_plan),
            "state": "prepared",
            "attempt": context.attempt,
            "attempt_token": context.attempt_token,
            "fence": context.fence,
            "$expr": {"$gt": ["$lease_until", "$$NOW"]},
        },
        [
            {
                "$set": {
                    "state": "committed",
                    "heartbeat_at": "$$NOW",
                    "updated_at": "$$NOW",
                    "committed_at": "$$NOW",
                    "terminal_at": "$$NOW",
                    "lease_until": "$$NOW",
                    "error_code": None,
                }
            }
        ],
        session=session,
    )
    if result.matched_count != 1 or result.modified_count != 1:
        raise _ForwardEngineError("COMMIT_CONFLICT")
    observed = await operations.find_one({"_id": sealed_plan.operation_id}, session=session)
    _validated_committed_operation(observed, sealed_plan, context)


async def _commit_transaction_with_retry(session: Any) -> None:
    last_unknown: BaseException | None = None
    for _ in range(3):
        try:
            await session.commit_transaction()
            return
        except Exception as exc:
            has_label = getattr(exc, "has_error_label", None)
            if not callable(has_label) or not has_label("UnknownTransactionCommitResult"):
                raise
            last_unknown = exc
    raise _ForwardEngineError("COMMIT_OUTCOME_UNKNOWN") from last_unknown


async def _majority_commit_readback(
    db: Any, sealed_plan: _SealedForwardPlan, context: _ForwardOperationContext
) -> bool:
    concern = ReadConcern("majority")
    operations = db[_OPERATION_COLLECTION].with_options(read_concern=concern)
    preimages = db[_PREIMAGE_COLLECTION].with_options(read_concern=concern)
    metrics = db[_METRIC_COLLECTION].with_options(read_concern=concern)
    markers = db[_MARKER_COLLECTION].with_options(read_concern=concern)
    operation = await operations.find_one({"_id": sealed_plan.operation_id})
    observed_preimages = await preimages.find({"operation_id": sealed_plan.operation_id}).to_list(
        length=None
    )
    observed_metrics = await metrics.find(_metric_interval_query(sealed_plan.binding)).to_list(
        length=None
    )
    marker = await markers.find_one({"_id": sealed_plan._desired_marker["_id"]})
    try:
        persisted = _validated_committed_operation(operation, sealed_plan, context)
    except _ForwardEngineError:
        return False
    expected_preimages = _preimage_records(sealed_plan, persisted["lease_acquired_at"])
    return (
        _exact_preimages_match(observed_preimages, expected_preimages)
        and _exact_preimages_match(observed_metrics, sealed_plan._expected_metric_documents)
        and _metric_proof_fingerprint(observed_metrics) == sealed_plan.expected_metric_fingerprint
        and _exact_preimages_match(
            [] if marker is None else [marker], [sealed_plan._desired_marker]
        )
    )


async def _commit_forward_operation(
    db: Any, sealed_plan: _SealedForwardPlan, context: _ForwardOperationContext
) -> _ForwardOperationContext:
    async def metrics(session: Any) -> None:
        await _write_and_verify_forward_metrics(db, sealed_plan, session)

    async def marker(session: Any) -> None:
        await _write_and_verify_forward_marker(db, sealed_plan, session)

    async def operation(session: Any) -> None:
        await _write_and_verify_operation_commit(db, sealed_plan, context, session)

    try:
        await _persist_forward_preimages(
            db, sealed_plan, context, (metrics, marker, operation, _commit_transaction_with_retry)
        )
    except _ForwardEngineError as exc:
        if exc.code != "COMMIT_OUTCOME_UNKNOWN":
            raise
        last_unknown = exc.__cause__
        if not await _majority_commit_readback(db, sealed_plan, context):
            raise _ForwardEngineError("COMMIT_OUTCOME_UNKNOWN") from last_unknown
    return _ForwardOperationContext(
        context.operation_id,
        "committed",
        context.attempt,
        context.attempt_token,
        context.fence,
        False,
    )


_ROLLBACK_OPERATION_FIELDS = set(
    "_id seller_id read_model date_from date_to source_fingerprint plan_fingerprint state attempt "  # noqa: SIM905
    "attempt_token fence lease_acquired_at heartbeat_at lease_until planned_insert_count "
    "planned_update_count planned_delete_count planned_preimage_count created_at updated_at "
    "committed_at terminal_at error_code schema_version".split()
)
_ROLLBACK_PREIMAGE_FIELDS = set(
    "_id operation_id sequence target_collection target_id action preimage preimage_kind "  # noqa: SIM905
    "preimage_fingerprint expected_forward_revision created_at schema_version".split()
)


def _utc(value: Any) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and (value.utcoffset() == timedelta(0))
    )


def _validate_rollback_operation(operation: Any, operation_id: str) -> Mapping[str, Any]:
    if not isinstance(operation, Mapping) or set(operation) != _ROLLBACK_OPERATION_FIELDS:
        raise _ForwardEngineError("ROLLBACK_BLOCKED")
    seller = operation["seller_id"]
    dates = (operation["date_from"], operation["date_to"])
    timestamps = tuple(
        operation.get(name)
        for name in ("lease_acquired_at", "heartbeat_at", "lease_until", "created_at", "updated_at")
    )
    terminal, committed = operation["terminal_at"], operation["committed_at"]
    counts = tuple(
        operation.get(name)
        for name in (
            "planned_insert_count",
            "planned_update_count",
            "planned_delete_count",
            "planned_preimage_count",
        )
    )
    expected_id = _digest(
        {
            "domain": "zeler.stock-time-forward-operation",
            "version": 1,
            "seller_id": seller,
            "date_from": dates[0],
            "date_to": dates[1],
            "source_fingerprint": operation.get("source_fingerprint"),
            "plan_fingerprint": operation.get("plan_fingerprint"),
        }
    )
    valid = (
        operation.get("_id") == operation_id == expected_id
        and isinstance(seller, str)
        and bool(seller.strip())
        and operation.get("read_model") == _READ_MODEL
        and all(_utc(value) for value in dates + timestamps + (terminal, committed))
        and dates[1] > dates[0]
        and operation.get("state") in {"committed", "rolled_back", "rollback_blocked"}
        and type(operation.get("attempt")) is int
        and operation["attempt"] > 0
        and type(operation.get("fence")) is int
        and operation["fence"] > 0
        and isinstance(operation.get("attempt_token"), str)
        and _ATTEMPT_TOKEN.fullmatch(operation["attempt_token"]) is not None
        and all(type(value) is int and value >= 0 for value in counts)
        and all(
            isinstance(operation.get(name), str) and _SHA.fullmatch(operation[name])
            for name in ("source_fingerprint", "plan_fingerprint")
        )
        and operation.get("schema_version") == 1
        and (
            (
                operation["state"] in {"committed", "rolled_back"}
                and operation.get("error_code") is None
            )
            or (
                operation["state"] == "rollback_blocked"
                and operation.get("error_code") == "TARGET_DRIFT"
            )
        )
        and operation["heartbeat_at"]
        == operation["updated_at"]
        == terminal
        == operation["lease_until"]
        and operation["created_at"] <= operation["lease_acquired_at"] <= committed <= terminal
        and (operation["state"] != "committed" or committed == terminal)
    )
    if not valid:
        raise _ForwardEngineError("ROLLBACK_BLOCKED")
    return operation


def _rollback_seller_matches(seller: str, value: Any) -> bool:
    return (type(value) is str and value == seller) or (
        bool(re.fullmatch(r"[0-9]+", seller)) and type(value) is int and value == int(seller)
    )


def _validate_rollback_preimages(
    operation: Mapping[str, Any], observed: Sequence[Mapping[str, Any]]
) -> tuple[Mapping[str, Any], ...]:
    operation_id = operation["_id"]
    seller, start, end = operation["seller_id"], operation["date_from"], operation["date_to"]
    expected_sequences = list(range(1, operation["planned_preimage_count"] + 1))
    sequences = [row.get("sequence") if isinstance(row, Mapping) else None for row in observed]
    if len(observed) != len(expected_sequences) or sequences != expected_sequences:
        raise _ForwardEngineError("ROLLBACK_BLOCKED")
    seen: set[tuple[str, str]] = set()
    markers = 0
    action_counts = {"insert": 0, "replace": 0, "delete": 0}
    for row in observed:
        if not isinstance(row, Mapping) or set(row) != _ROLLBACK_PREIMAGE_FIELDS:
            raise _ForwardEngineError("ROLLBACK_BLOCKED")
        target = (row["target_collection"], row["target_id"])
        action, preimage = row["action"], row["preimage"]
        exact = action in {"replace", "delete"}
        valid = (
            row.get("operation_id") == operation_id
            and isinstance(target[1], str)
            and bool(target[1])
            and target[0] in {_METRIC_COLLECTION, _MARKER_COLLECTION}
            and target not in seen
            and action in action_counts
            and row.get("schema_version") == 1
            and row.get("created_at") == operation["lease_acquired_at"]
            and row.get("preimage_kind") == ("exact_document" if exact else "absent")
            and ((isinstance(preimage, Mapping)) if exact else preimage is None)
            and row.get("preimage_fingerprint") == _preimage_fingerprint(preimage)
            and row.get("expected_forward_revision")
            == _operation_revision(operation_id, target[0], target[1], action)
        )
        mutation = _ForwardMutation(
            row["sequence"], target[0], target[1], action, None, None, "", "", ""
        )
        valid = valid and row.get("_id") == _preimage_record_id(operation_id, mutation)
        if exact and target[0] == _METRIC_COLLECTION:
            valid = valid and (
                preimage.get("_id") == target[1]
                and _rollback_seller_matches(seller, preimage.get("seller_id"))
                and preimage.get("date_from") == start
                and preimage.get("date_to") == end
            )
        if target[0] == _MARKER_COLLECTION:
            markers += 1
            valid = (
                valid and target[1] == f"{seller}:{_READ_MODEL}" and action in {"insert", "replace"}
            )
            if exact:
                valid = valid and (
                    preimage.get("_id") == target[1]
                    and preimage.get("seller_id") == seller
                    and preimage.get("read_model") == _READ_MODEL
                )
        if not valid:
            raise _ForwardEngineError("ROLLBACK_BLOCKED")
        seen.add(target)
        action_counts[action] += 1
    expected_counts = dict(
        insert=operation["planned_insert_count"],
        replace=operation["planned_update_count"],
        delete=operation["planned_delete_count"],
    )
    if (
        markers != 1
        or action_counts != expected_counts
        or observed[-1]["target_collection"] != _MARKER_COLLECTION
    ):
        raise _ForwardEngineError("ROLLBACK_BLOCKED")
    return tuple(observed)


async def _load_validated_rollback_record_set(
    db: Any, operation_id: str
) -> _ValidatedRollbackRecordSet:
    if not isinstance(operation_id, str) or _SHA.fullmatch(operation_id) is None:
        raise _ForwardEngineError("ROLLBACK_BLOCKED")
    concern = ReadConcern("majority")
    operation = (
        await db[_OPERATION_COLLECTION]
        .with_options(read_concern=concern)
        .find_one({"_id": operation_id})
    )
    preimages = (
        await db[_PREIMAGE_COLLECTION]
        .with_options(read_concern=concern)
        .find({"operation_id": operation_id})
        .to_list(length=None)
    )
    try:
        persisted = _validate_rollback_operation(operation, operation_id)
        preimages.sort(key=lambda row: row.get("sequence", -1) if isinstance(row, Mapping) else -1)
        records = _validate_rollback_preimages(persisted, preimages)
        return _ValidatedRollbackRecordSet(
            operation_id,
            persisted["state"],
            _deep_freeze(persisted),
            tuple(_deep_freeze(row) for row in records),
        )
    except (
        AttributeError,
        IndexError,
        KeyError,
        OverflowError,
        TypeError,
        ValueError,
        _StockTimeActionPlanError,
    ) as exc:
        raise _ForwardEngineError("ROLLBACK_BLOCKED") from exc


def _validated_rollback_marker(
    operation: Mapping[str, Any], records: Sequence[Mapping[str, Any]], marker: Any
) -> Mapping[str, Any]:
    """Accept only the complete marker written by this committed operation."""
    try:
        marker_record = records[-1]
        expected = {
            "_id": marker_record["target_id"],
            "seller_id": operation["seller_id"],
            "read_model": _READ_MODEL,
            "state": "reconciled",
            "date_from": operation["date_from"],
            "fresh_until": operation["date_to"],
            "reconciled_until": operation["date_to"],
            "last_event_synced_at": operation["date_from"],
            "updated_at": operation["date_to"],
            "source": _RECONCILE_SOURCE,
            "coverage_basis": "legacy_imported",
            "revision": marker_record["expected_forward_revision"],
            "schema_version": 1,
        }
        valid = (
            isinstance(marker, Mapping)
            and set(marker) == set(expected) | {"proof_fingerprint"}
            and all(marker.get(name) == value for name, value in expected.items())
            and isinstance(marker.get("proof_fingerprint"), str)
            and _SHA.fullmatch(marker["proof_fingerprint"]) is not None
        )
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise _TargetDriftError()
    return cast(Mapping[str, Any], marker)


def _validated_rollback_metrics(
    operation: Mapping[str, Any], documents: Sequence[Any]
) -> dict[str, Mapping[str, Any]]:
    seller = operation["seller_id"]
    indexed: dict[str, Mapping[str, Any]] = {}
    try:
        for document in documents:
            if (
                not isinstance(document, Mapping)
                or not isinstance(document.get("_id"), str)
                or not document["_id"]
                or document["_id"] in indexed
                or not _rollback_seller_matches(seller, document.get("seller_id"))
                or document.get("date_from") != operation["date_from"]
                or document.get("date_to") != operation["date_to"]
            ):
                raise _TargetDriftError()
            _canonical_bson_bytes(document)
            indexed[document["_id"]] = document
    except _TargetDriftError:
        raise
    except (AttributeError, KeyError, OverflowError, TypeError, ValueError) as exc:
        raise _TargetDriftError() from exc
    return indexed


def _rollback_mutation(record: Mapping[str, Any]) -> _RollbackMutation:
    actions = {"insert": "delete", "replace": "replace", "delete": "insert"}
    action = actions.get(record["action"])
    if action is None:
        raise _ForwardEngineError("ROLLBACK_BLOCKED")
    restoration = None if action == "delete" else _deep_freeze(record["preimage"])
    return _RollbackMutation(
        record["target_collection"],
        record["target_id"],
        action,
        record["expected_forward_revision"],
        record["sequence"],
        restoration,
    )


async def _prepare_rollback_record_set(
    db: Any, record_set: _ValidatedRollbackRecordSet, session: Any | None = None
) -> tuple[_ForwardRollbackPlan, Mapping[str, Any] | None, dict[str, Mapping[str, Any]]]:
    """Validate the complete forward state from one read view and derive its inverse."""
    if record_set.state in {"rolled_back", "rollback_blocked"}:
        return _ForwardRollbackPlan(record_set.operation_id, record_set.state, ()), None, {}
    try:
        operation, records = record_set._operation, record_set._records
        options = {"session": session} if session is not None else {}
        marker_collection, metric_collection = db[_MARKER_COLLECTION], db[_METRIC_COLLECTION]
        if session is None:
            concern = ReadConcern("majority")
            marker_collection = marker_collection.with_options(read_concern=concern)
            metric_collection = metric_collection.with_options(read_concern=concern)
        marker = await marker_collection.find_one(
            {"_id": f"{operation['seller_id']}:{_READ_MODEL}"}, **options
        )
        binding = _ForwardBinding(
            operation["seller_id"],
            operation["date_from"],
            operation["date_to"],
            operation["source_fingerprint"],
            operation["plan_fingerprint"],
        )
        documents = await metric_collection.find(
            _metric_interval_query(binding), **options
        ).to_list(length=None)
        current_marker = _validated_rollback_marker(operation, records, marker)
        current_metrics = _validated_rollback_metrics(operation, documents)
        if (
            _metric_proof_fingerprint(tuple(current_metrics.values()))
            != current_marker["proof_fingerprint"]
        ):
            raise _TargetDriftError()
        for record in records:
            if record["target_collection"] != _METRIC_COLLECTION:
                continue
            current = current_metrics.get(record["target_id"])
            if record["action"] in {"insert", "replace"}:
                if (
                    current is None
                    or current.get("revision") != record["expected_forward_revision"]
                ):
                    raise _TargetDriftError()
            elif current is not None:
                raise _TargetDriftError()
        marker_record = records[-1]
        metrics = tuple(
            _rollback_mutation(record)
            for record in reversed(records[:-1])
            if record["target_collection"] == _METRIC_COLLECTION
        )
        return (
            _ForwardRollbackPlan(
                record_set.operation_id,
                record_set.state,
                (_rollback_mutation(marker_record), *metrics),
            ),
            current_marker,
            current_metrics,
        )
    except (_ForwardEngineError, _TargetDriftError):
        raise
    except (
        AttributeError,
        IndexError,
        KeyError,
        OverflowError,
        TypeError,
        ValueError,
        _StockTimeActionPlanError,
    ) as exc:
        raise _ForwardEngineError("ROLLBACK_BLOCKED") from exc


async def _prepare_forward_rollback(db: Any, operation_id: str) -> _ForwardRollbackPlan:
    """Prepare only; R2 applies inverses atomically, so ordering is an audit/readback convention."""
    record_set = await _load_validated_rollback_record_set(db, operation_id)
    try:
        plan, _, _ = await _prepare_rollback_record_set(db, record_set)
        return plan
    except _TargetDriftError as exc:
        raise _ForwardEngineError("ROLLBACK_BLOCKED") from exc


async def _transaction_rollback_record_set(
    db: Any, operation_id: str, session: Any
) -> _ValidatedRollbackRecordSet:
    operation = await db[_OPERATION_COLLECTION].find_one({"_id": operation_id}, session=session)
    preimages = (
        await db[_PREIMAGE_COLLECTION]
        .find({"operation_id": operation_id}, session=session)
        .to_list(length=None)
    )
    try:
        persisted = _validate_rollback_operation(operation, operation_id)
        preimages.sort(key=lambda row: row.get("sequence", -1) if isinstance(row, Mapping) else -1)
        records = _validate_rollback_preimages(persisted, preimages)
        return _ValidatedRollbackRecordSet(
            operation_id,
            persisted["state"],
            _deep_freeze(persisted),
            tuple(_deep_freeze(row) for row in records),
        )
    except _ForwardEngineError:
        raise
    except (AttributeError, IndexError, KeyError, OverflowError, TypeError, ValueError) as exc:
        raise _ForwardEngineError("ROLLBACK_BLOCKED") from exc


def _rollback_operation_identity(operation: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: operation[key]
        for key in (
            "_id",
            "seller_id",
            "read_model",
            "date_from",
            "date_to",
            "source_fingerprint",
            "plan_fingerprint",
            "planned_insert_count",
            "planned_update_count",
            "planned_delete_count",
            "planned_preimage_count",
            "schema_version",
        )
    }


def _rollback_binding(operation: Mapping[str, Any]) -> _ForwardBinding:
    return _ForwardBinding(
        operation["seller_id"],
        operation["date_from"],
        operation["date_to"],
        operation["source_fingerprint"],
        operation["plan_fingerprint"],
    )


def _rollback_selector(operation: Mapping[str, Any], mutation: _RollbackMutation) -> dict[str, Any]:
    if mutation.target_collection == _MARKER_COLLECTION:
        return {
            "_id": mutation._target_id,
            "seller_id": operation["seller_id"],
            "read_model": _READ_MODEL,
            "revision": mutation.expected_forward_revision,
        }
    return {
        "_id": mutation._target_id,
        **_metric_interval_query(_rollback_binding(operation)),
        "revision": mutation.expected_forward_revision,
    }


async def _apply_rollback_mutation(
    db: Any, operation: Mapping[str, Any], mutation: _RollbackMutation, session: Any
) -> None:
    collection = db[mutation.target_collection]
    if mutation.action == "delete":
        result = await collection.delete_one(
            _rollback_selector(operation, mutation), session=session
        )
        exact = result.deleted_count == 1
    elif mutation.action == "replace":
        if mutation._restoration is None:
            raise _ForwardEngineError("ROLLBACK_BLOCKED")
        result = await collection.replace_one(
            _rollback_selector(operation, mutation),
            _canonical_bson_document(mutation._restoration),
            session=session,
        )
        exact = result.matched_count == 1 and result.modified_count == 1
    elif mutation.action == "insert":
        if mutation._restoration is None:
            raise _ForwardEngineError("ROLLBACK_BLOCKED")
        selector = {
            key: value
            for key, value in _rollback_selector(operation, mutation).items()
            if key != "revision"
        }
        try:
            result = await collection.replace_one(
                selector,
                _canonical_bson_document(mutation._restoration),
                upsert=True,
                session=session,
            )
        except OperationFailure as exc:
            if exc.code == 11000:
                raise _TargetDriftError() from None
            raise
        exact = result.matched_count == 0 and result.upserted_id == mutation._target_id
    else:
        raise _ForwardEngineError("ROLLBACK_BLOCKED")
    if not exact:
        raise _TargetDriftError()


def _rollback_baseline(
    current_metrics: Mapping[str, Mapping[str, Any]], plan: _ForwardRollbackPlan
) -> tuple[Mapping[str, Any], ...]:
    baseline = dict(current_metrics)
    for mutation in plan._mutations[1:]:
        if mutation.action == "delete":
            baseline.pop(mutation._target_id, None)
        elif mutation._restoration is not None:
            baseline[mutation._target_id] = mutation._restoration
    return tuple(baseline.values())


async def _majority_rollback_readback(
    db: Any,
    record_set: _ValidatedRollbackRecordSet,
    baseline: Sequence[Mapping[str, Any]],
    expected_marker: Mapping[str, Any] | None,
) -> bool:
    """Accept an unknown rollback commit only when its entire durable result is exact."""
    try:
        concern = ReadConcern("majority")
        operation = (
            await db[_OPERATION_COLLECTION]
            .with_options(read_concern=concern)
            .find_one({"_id": record_set.operation_id})
        )
        preimages = (
            await db[_PREIMAGE_COLLECTION]
            .with_options(read_concern=concern)
            .find({"operation_id": record_set.operation_id})
            .to_list(length=None)
        )
        metrics = (
            await db[_METRIC_COLLECTION]
            .with_options(read_concern=concern)
            .find(_metric_interval_query(_rollback_binding(record_set._operation)))
            .to_list(length=None)
        )
        marker = (
            await db[_MARKER_COLLECTION]
            .with_options(read_concern=concern)
            .find_one({"_id": f"{record_set._operation['seller_id']}:{_READ_MODEL}"})
        )
        observed = _validate_rollback_operation(operation, record_set.operation_id)
        mutable = {
            "state",
            "heartbeat_at",
            "updated_at",
            "terminal_at",
            "lease_until",
            "error_code",
        }
        if observed["state"] != "rolled_back" or any(
            observed.get(field) != record_set._operation.get(field)
            for field in set(record_set._operation) - mutable
        ):
            return False
        return (
            _exact_preimages_match(preimages, record_set._records)
            and _exact_preimages_match(metrics, baseline)
            and _exact_preimages_match(
                [] if marker is None else [marker],
                [] if expected_marker is None else [expected_marker],
            )
        )
    except Exception:  # noqa: BLE001 - unavailable readback is an unknown commit outcome
        return False


def _full_document_selector(document: Mapping[str, Any]) -> dict[str, Any]:
    """Bind a CAS to every field of the observed document, not just its identity."""
    return dict(document)


def _rollback_mutable_fields() -> set[str]:
    return {"state", "heartbeat_at", "updated_at", "terminal_at", "lease_until", "error_code"}


def _validated_blocked_operation(
    observed: Any, original: Mapping[str, Any], operation_id: str
) -> Mapping[str, Any]:
    operation = _validate_rollback_operation(observed, operation_id)
    if (
        operation["state"] != "rollback_blocked"
        or operation["error_code"] != "TARGET_DRIFT"
        or any(
            operation.get(key) != original.get(key)
            for key in set(original) - _rollback_mutable_fields()
        )
    ):
        raise _ForwardEngineError("ROLLBACK_BLOCKED")
    return operation


async def _majority_target_drift_finalizer_readback(
    db: Any,
    record_set: _ValidatedRollbackRecordSet,
    expected_operation: Mapping[str, Any],
    expected_marker: Mapping[str, Any] | None,
) -> bool:
    """Accept an unknown finalizer commit only when its bounded durable result is exact.

    Metrics are intentionally excluded: the finalizer cannot mutate metrics and the
    compensation transaction that detected drift was aborted before this transaction.
    """
    try:
        concern = ReadConcern("majority")
        operation = (
            await db[_OPERATION_COLLECTION]
            .with_options(read_concern=concern)
            .find_one({"_id": record_set.operation_id})
        )
        preimages = (
            await db[_PREIMAGE_COLLECTION]
            .with_options(read_concern=concern)
            .find({"operation_id": record_set.operation_id})
            .to_list(length=None)
        )
        marker = (
            await db[_MARKER_COLLECTION]
            .with_options(read_concern=concern)
            .find_one({"_id": f"{record_set._operation['seller_id']}:{_READ_MODEL}"})
        )
        _validated_blocked_operation(operation, record_set._operation, record_set.operation_id)
        return (
            _exact_preimages_match([operation], [expected_operation])
            and _exact_preimages_match(preimages, record_set._records)
            and _exact_preimages_match(
                [] if marker is None else [marker],
                [] if expected_marker is None else [expected_marker],
            )
        )
    except Exception:  # noqa: BLE001 - unavailable/corrupt readback is an unknown outcome
        return False


async def _finalize_target_drift(db: Any, majority_records: _ValidatedRollbackRecordSet) -> None:
    """Atomically quarantine an owned marker and make confirmed target drift terminal."""
    recovery_record_set: _ValidatedRollbackRecordSet | None = None
    recovery_operation: Mapping[str, Any] | None = None
    recovery_marker: Mapping[str, Any] | None = None
    try:
        async with _required_transaction(db) as session:
            record_set = await _transaction_rollback_record_set(
                db, majority_records.operation_id, session
            )
            if (
                record_set.state != "committed"
                or record_set._operation != majority_records._operation
                or record_set._records != majority_records._records
            ):
                raise _ForwardEngineError("ROLLBACK_BLOCKED")
            operation, records = record_set._operation, record_set._records
            result = await db[_OPERATION_COLLECTION].update_one(
                _full_document_selector(operation),
                [
                    {
                        "$set": {
                            "state": "rollback_blocked",
                            "error_code": "TARGET_DRIFT",
                            "heartbeat_at": "$$NOW",
                            "updated_at": "$$NOW",
                            "terminal_at": "$$NOW",
                            "lease_until": "$$NOW",
                        }
                    }
                ],
                session=session,
            )
            if result.matched_count != 1 or result.modified_count != 1:
                raise _ForwardEngineError("ROLLBACK_BLOCKED")
            observed_operation = await db[_OPERATION_COLLECTION].find_one(
                {"_id": operation["_id"]}, session=session
            )
            blocked = _validated_blocked_operation(observed_operation, operation, operation["_id"])
            marker_collection = db[_MARKER_COLLECTION]
            observed_marker = await marker_collection.find_one(
                {"_id": f"{operation['seller_id']}:{_READ_MODEL}"}, session=session
            )
            try:
                owned_marker = _validated_rollback_marker(operation, records, observed_marker)
            except _TargetDriftError:
                owned_marker = None
            expected_marker = observed_marker
            if owned_marker is not None:
                result = await marker_collection.update_one(
                    _full_document_selector(owned_marker),
                    [{"$set": {"state": "stale", "updated_at": blocked["updated_at"]}}],
                    session=session,
                )
                if result.matched_count != 1 or result.modified_count != 1:
                    raise _ForwardEngineError("ROLLBACK_BLOCKED")
                expected_marker = {
                    **owned_marker,
                    "state": "stale",
                    "updated_at": blocked["updated_at"],
                }
            readback_marker = await marker_collection.find_one(
                {"_id": f"{operation['seller_id']}:{_READ_MODEL}"}, session=session
            )
            if not _exact_preimages_match(
                [] if readback_marker is None else [readback_marker],
                [] if expected_marker is None else [expected_marker],
            ):
                raise _ForwardEngineError("ROLLBACK_BLOCKED")
            preimages = (
                await db[_PREIMAGE_COLLECTION]
                .find({"operation_id": operation["_id"]}, session=session)
                .to_list(length=None)
            )
            if not _exact_preimages_match(preimages, records):
                raise _ForwardEngineError("ROLLBACK_BLOCKED")
            recovery_record_set = record_set
            recovery_operation = _deep_freeze(blocked)
            recovery_marker = expected_marker
            await _commit_transaction_with_retry(session)
    except _ForwardEngineError as exc:
        if exc.code != "COMMIT_OUTCOME_UNKNOWN":
            raise
        last_unknown = exc.__cause__
        if (
            recovery_record_set is None
            or recovery_operation is None
            or not await _majority_target_drift_finalizer_readback(
                db, recovery_record_set, recovery_operation, recovery_marker
            )
        ):
            raise _ForwardEngineError("COMMIT_OUTCOME_UNKNOWN") from last_unknown


async def _rollback_forward_operation(db: Any, operation_id: str) -> _ForwardRollbackPlan:
    """Restore a forward operation or terminalize confirmed live target drift."""
    majority_records = await _load_validated_rollback_record_set(db, operation_id)
    if majority_records.state == "rolled_back":
        return _ForwardRollbackPlan(operation_id, "rolled_back", ())
    if majority_records.state == "rollback_blocked":
        raise _ForwardEngineError("ROLLBACK_BLOCKED")
    recovery_record_set: _ValidatedRollbackRecordSet | None = None
    recovery_baseline: tuple[Mapping[str, Any], ...] | None = None
    recovery_marker: Mapping[str, Any] | None = None
    try:
        async with _required_transaction(db) as session:
            record_set = await _transaction_rollback_record_set(db, operation_id, session)
            if (
                record_set.state != "committed"
                or record_set._operation != majority_records._operation
                or record_set._records != majority_records._records
            ):
                raise _ForwardEngineError("ROLLBACK_BLOCKED")
            local_plan, _, metrics = await _prepare_rollback_record_set(db, record_set, session)
            baseline = _rollback_baseline(metrics, local_plan)
            expected_marker = local_plan._mutations[0]._restoration
            recovery_record_set = record_set
            recovery_baseline = baseline
            recovery_marker = expected_marker
            for mutation in local_plan._mutations:
                await _apply_rollback_mutation(db, record_set._operation, mutation, session)
            observed_metrics = (
                await db[_METRIC_COLLECTION]
                .find(
                    _metric_interval_query(_rollback_binding(record_set._operation)),
                    session=session,
                )
                .to_list(length=None)
            )
            if not _exact_preimages_match(observed_metrics, baseline):
                raise _TargetDriftError()
            observed_marker = await db[_MARKER_COLLECTION].find_one(
                {"_id": f"{record_set._operation['seller_id']}:{_READ_MODEL}"}, session=session
            )
            if not _exact_preimages_match(
                [] if observed_marker is None else [observed_marker],
                [] if expected_marker is None else [expected_marker],
            ):
                raise _TargetDriftError()
            preimages = (
                await db[_PREIMAGE_COLLECTION]
                .find({"operation_id": operation_id}, session=session)
                .to_list(length=None)
            )
            if not _exact_preimages_match(preimages, record_set._records):
                raise _ForwardEngineError("ROLLBACK_BLOCKED")
            operation = record_set._operation
            result = await db[_OPERATION_COLLECTION].update_one(
                {
                    **_rollback_operation_identity(operation),
                    "state": "committed",
                    "attempt": operation["attempt"],
                    "attempt_token": operation["attempt_token"],
                    "fence": operation["fence"],
                    "committed_at": operation["committed_at"],
                },
                [
                    {
                        "$set": {
                            "state": "rolled_back",
                            "heartbeat_at": "$$NOW",
                            "updated_at": "$$NOW",
                            "terminal_at": "$$NOW",
                            "lease_until": "$$NOW",
                            "error_code": None,
                        }
                    }
                ],
                session=session,
            )
            if result.matched_count != 1 or result.modified_count != 1:
                raise _ForwardEngineError("ROLLBACK_BLOCKED")
            observed_operation = await db[_OPERATION_COLLECTION].find_one(
                {"_id": operation_id}, session=session
            )
            _validate_rollback_operation(observed_operation, operation_id)
            if any(
                observed_operation.get(key) != operation.get(key)
                for key in set(operation) - _rollback_mutable_fields()
            ):
                raise _ForwardEngineError("ROLLBACK_BLOCKED")
            await _commit_transaction_with_retry(session)
    except _TargetDriftError:
        await _finalize_target_drift(db, majority_records)
        raise _ForwardEngineError("ROLLBACK_BLOCKED") from None
    except _ForwardEngineError as exc:
        if exc.code != "COMMIT_OUTCOME_UNKNOWN":
            raise
        last_unknown = exc.__cause__
        if (
            recovery_record_set is None
            or recovery_baseline is None
            or not await _majority_rollback_readback(
                db, recovery_record_set, recovery_baseline, recovery_marker
            )
        ):
            raise _ForwardEngineError("COMMIT_OUTCOME_UNKNOWN") from last_unknown
    return _ForwardRollbackPlan(operation_id, "rolled_back", ())
