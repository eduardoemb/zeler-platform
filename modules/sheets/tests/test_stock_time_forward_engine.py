from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from inspect import signature
from typing import Any

import pytest

import zeler_sheets
from zeler_sheets import _stock_time_forward_engine as engine
from zeler_sheets import source_gated_read_model_writers as planner

START, END = datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC)


def metric(target: str, value: int, **extra: Any) -> dict[str, Any]:
    return {
        "_id": target,
        "seller_id": "82453304",
        "date_from": START,
        "date_to": END,
        "value": value,
        **extra,
    }


def action_plan(*, source: str = "source", value: int = 2) -> Any:
    return planner._plan_stock_time_actions(
        source_inventory=[{"_id": source}],
        planned_documents=[metric("insert", value), metric("same", 1), metric("replace", value)],
        existing_target_rows=[metric("delete", 1), metric("same", 1), metric("replace", 1)],
    )


def marker(**extra: Any) -> dict[str, Any]:
    return {
        "_id": "82453304:stock_time_metrics",
        "seller_id": "82453304",
        "read_model": "stock_time_metrics",
        "state": "stale",
        "fresh_until": START,
        "updated_at": START,
        "schema_version": 1,
        **extra,
    }


def seal(
    *,
    plan: Any | None = None,
    source: str = "source",
    old_marker: dict[str, Any] | None = None,
    seller: str = "82453304",
    start: datetime = START,
    end: datetime = END,
) -> Any:
    return engine._seal_forward_plan(
        seller_id=seller,
        date_from=start,
        date_to=end,
        source_inventory=[{"_id": source}],
        action_plan=plan if plan is not None else action_plan(source=source),
        marker_preimage=old_marker,
    )


EMPTY_PLAN = planner._plan_stock_time_actions(
    source_inventory=[{"_id": "source"}], planned_documents=[], existing_target_rows=[]
)


def test_seal_is_permutation_stable_and_binds_all_material() -> None:
    first = seal()
    base = action_plan()
    permuted = planner._plan_stock_time_actions(
        source_inventory=[{"_id": "source"}],
        planned_documents=[base.actions[i]._document for i in (3, 2, 1)],
        existing_target_rows=[base.actions[i]._preimage for i in (3, 2, 0)],
    )
    assert seal(plan=permuted).operation_id == first.operation_id
    assert first.operation_id == "e0d8a44491f8e18db199c281bb38a2333f470dd19fb9fd3ef795be46466e7a15"
    variants = [
        seal(seller="82453305", plan=EMPTY_PLAN),
        seal(start=START + timedelta(days=1), plan=EMPTY_PLAN),
        seal(source="drift", plan=action_plan(source="drift")),
        seal(plan=action_plan(value=3)),
        seal(old_marker=marker(source="drift")),
    ]
    assert all(item.operation_id != first.operation_id for item in variants)
    assert "82453304" not in repr(first)


def test_seal_canonicalizes_marker_action_and_is_frozen() -> None:
    first = seal()
    assert "marker_document" not in signature(engine._seal_forward_plan).parameters
    assert not hasattr(first, "_marker_document")
    assert first._marker_action == "insert" and first._marker_preimage is None
    replaced = seal(old_marker=marker())
    assert replaced._marker_action == "replace" and replaced._marker_preimage == marker()
    with pytest.raises(FrozenInstanceError):
        first.__setattr__("operation_id", "changed")


@pytest.mark.parametrize(
    ("seller", "start", "end", "code"),
    [
        (" ", START, END, "INVALID_SELLER"),
        ("82453304", START.replace(tzinfo=None), END, "INVALID_UTC_INTERVAL"),
        (
            "82453304",
            START.replace(tzinfo=timezone(timedelta(hours=1))),
            END,
            "INVALID_UTC_INTERVAL",
        ),
        ("82453304", END, END, "INVALID_UTC_INTERVAL"),
        ("82453304", "2026-06-01", END, "INVALID_UTC_INTERVAL"),
        ("82453304", START, object(), "INVALID_UTC_INTERVAL"),
    ],
)
def test_seal_rejects_invalid_seller_and_half_open_utc_bounds(
    seller: str, start: Any, end: Any, code: str
) -> None:
    with pytest.raises(engine._ForwardEngineError, match=code):
        seal(seller=seller, start=start, end=end, plan=EMPTY_PLAN)


@pytest.mark.parametrize(
    "field", ["source_fingerprint", "preimage_fingerprint", "plan_fingerprint"]
)
def test_seal_rejects_invalid_sha256(field: str) -> None:
    with pytest.raises(engine._ForwardEngineError, match="INVALID_SHA256"):
        seal(plan=replace(action_plan(), **{field: "not-a-sha"}))


def test_seal_rejects_action_order_identity_and_marker_drift() -> None:
    plan = action_plan()
    with pytest.raises(engine._ForwardEngineError, match="INVALID_ACTION"):
        seal(plan=replace(plan, actions=tuple(reversed(plan.actions))))
    bad_identity = replace(plan.actions[0], _target_id="other")
    with pytest.raises(engine._ForwardEngineError, match="ACTION_SCOPE_MISMATCH"):
        seal(plan=replace(plan, actions=(bad_identity, *plan.actions[1:])))
    with pytest.raises(engine._ForwardEngineError, match="ACTION_SCOPE_MISMATCH"):
        seal(old_marker=marker(_id="other"))


@pytest.mark.parametrize(
    ("index", "changes"),
    [
        (1, {"_document": metric("insert", 9)}),
        (2, {"action": "no-op"}),
        (2, {"_preimage": metric("replace", 2)}),
    ],
)
def test_seal_rejects_actions_tampered_without_updating_fingerprints(
    index: int, changes: dict[str, Any]
) -> None:
    plan = action_plan()
    actions = list(plan.actions)
    actions[index] = replace(actions[index], **changes)
    with pytest.raises(engine._ForwardEngineError, match="INVALID_ACTION"):
        seal(plan=replace(plan, actions=tuple(actions)))


@pytest.mark.parametrize(
    "field",
    [
        "source_fingerprint",
        "preimage_fingerprint",
        "plan_fingerprint",
        "action_count",
        "insert_count",
        "replace_count",
        "delete_count",
        "no_op_count",
        "preimage_count",
        "estimated_bson_bytes",
        "estimated_json_bytes",
        "estimated_transaction_payload_bytes",
    ],
)
def test_seal_rejects_tampered_planner_metadata(field: str) -> None:
    plan = action_plan()
    value = "0" * 64 if field.endswith("fingerprint") else getattr(plan, field) + 1
    with pytest.raises(engine._ForwardEngineError, match="INVALID_ACTION"):
        seal(plan=replace(plan, **{field: value}))


def test_seal_rejects_source_that_does_not_match_the_plan() -> None:
    with pytest.raises(engine._ForwardEngineError, match="INVALID_ACTION"):
        seal(source="drift", plan=action_plan())


def test_materializes_metric_actions_with_operation_owned_revisions() -> None:
    sealed = seal()
    mutations = sealed._mutations
    metric_mutations = mutations[:-1]

    assert [(item.sequence, item._target_id, item.action) for item in metric_mutations] == [
        (1, "delete", "delete"),
        (2, "insert", "insert"),
        (3, "replace", "replace"),
    ]
    assert [doc["_id"] for doc in sealed._expected_metric_documents] == [
        "insert",
        "replace",
        "same",
    ]
    final = {doc["_id"]: doc for doc in sealed._expected_metric_documents}
    assert final["same"] == metric("same", 1)
    assert "revision" not in final["same"]
    for target in ("insert", "replace"):
        mutation = next(item for item in metric_mutations if item._target_id == target)
        assert final[target]["revision"] == mutation.expected_forward_revision
        assert mutation._document == final[target]
    overwrite_plan = planner._plan_stock_time_actions(
        source_inventory=[{"_id": "source"}],
        planned_documents=[metric("insert", 2, revision="caller-revision")],
        existing_target_rows=[],
    )
    overwritten = seal(plan=overwrite_plan)._expected_metric_documents[0]
    assert overwritten["revision"] != "caller-revision"
    deleted = metric_mutations[0]
    assert deleted._document is None
    assert (
        engine._operation_revision(
            sealed.operation_id, deleted.target_collection, "delete", "delete"
        )
        == deleted.expected_forward_revision
    )
    assert len({item.expected_forward_revision for item in mutations}) == len(mutations)
    assert seal()._mutations == mutations
    assert (
        len(
            {
                engine._operation_revision(sealed.operation_id, "collection", "id", action)
                for action in ("insert", "replace", "delete")
            }
        )
        == 3
    )


def test_noop_preserves_exact_existing_revision_and_nested_document() -> None:
    same = metric("same", 1, revision="existing", nested={"values": [1, 2]})
    plan = planner._plan_stock_time_actions(
        source_inventory=[{"_id": "source"}],
        planned_documents=[metric("same", 1, nested={"values": [1, 2]})],
        existing_target_rows=[same],
    )
    sealed = seal(plan=plan)

    assert len(sealed._mutations) == 1  # Marker only.
    assert planner._canonical_bson_bytes(sealed._expected_metric_documents[0]) == (
        planner._canonical_bson_bytes(same)
    )
    with pytest.raises(TypeError):
        sealed._expected_metric_documents[0]["nested"]["values"][0] = 9


@pytest.mark.parametrize("old_marker", [None, marker()])
def test_marker_is_canonical_final_mutation_with_exact_counts(
    old_marker: dict[str, Any] | None,
) -> None:
    sealed = seal(old_marker=old_marker)
    desired = sealed._desired_marker
    marker_mutation = sealed._mutations[-1]

    assert set(desired) == {
        "_id",
        "seller_id",
        "read_model",
        "state",
        "date_from",
        "fresh_until",
        "reconciled_until",
        "last_event_synced_at",
        "updated_at",
        "source",
        "coverage_basis",
        "revision",
        "proof_fingerprint",
        "schema_version",
    }
    assert desired == {
        "_id": "82453304:stock_time_metrics",
        "seller_id": "82453304",
        "read_model": "stock_time_metrics",
        "state": "reconciled",
        "date_from": START,
        "fresh_until": END,
        "reconciled_until": END,
        "last_event_synced_at": START,
        "updated_at": END,
        "source": "zelerdata_read_model_reconcile",
        "coverage_basis": "legacy_imported",
        "revision": marker_mutation.expected_forward_revision,
        "proof_fingerprint": sealed.expected_metric_fingerprint,
        "schema_version": 1,
    }
    assert desired["proof_fingerprint"] == engine._metric_proof_fingerprint(
        sealed._expected_metric_documents
    )
    assert desired["proof_fingerprint"] != engine._metric_proof_fingerprint(
        (*sealed._expected_metric_documents, desired)
    )
    assert marker_mutation.sequence == len(sealed._mutations)
    assert marker_mutation._document == desired
    assert marker_mutation.action == ("replace" if old_marker else "insert")
    assert marker_mutation._preimage == old_marker
    assert sealed.ledger_counts == engine._ForwardLedgerCounts(
        planned_insert_count=1 + (old_marker is None),
        planned_update_count=1 + (old_marker is not None),
        planned_delete_count=1,
        planned_preimage_count=4,
    )


def test_mutation_preimages_are_exact_coupled_and_deeply_frozen() -> None:
    sealed = seal(old_marker=marker(nested={"value": [1]}))

    for mutation in sealed._mutations:
        assert mutation.preimage_kind == (
            "absent" if mutation.action == "insert" else "exact_document"
        )
        if mutation.action == "insert":
            assert mutation._preimage is None
        else:
            assert mutation._preimage is not None
        assert mutation.preimage_fingerprint == engine._preimage_fingerprint(mutation._preimage)
    assert planner._canonical_bson_bytes(sealed._mutations[-1]._preimage) == (
        planner._canonical_bson_bytes(marker(nested={"value": [1]}))
    )
    with pytest.raises(TypeError):
        sealed._mutations[-1]._preimage["nested"]["value"][0] = 2
    with pytest.raises(FrozenInstanceError):
        sealed._mutations[0].sequence = 99


class FakeTransaction:
    def __init__(self, db: FakeDB, session: FakeSession, options: dict[str, Any]) -> None:
        self.db, self.session, self.options = db, session, options

    async def __aenter__(self) -> FakeTransaction:
        assert self.db.staged is None and self.db.active_session is None
        self.db.staged_collections = deepcopy(self.db.collections)
        self.db.staged = self.db.staged_collections.setdefault(
            "sheets_stock_time_reconciliation_operations", {}
        )
        self.db.active_session = self.session
        return self

    async def __aexit__(self, error_type: Any, error: Any, traceback: Any) -> None:
        staged_collections = self.db.staged_collections
        self.db.staged_collections = self.db.staged = self.db.active_session = None
        if error_type is None and self.db.fail_commit:
            raise RuntimeError("commit failed")
        if error_type is None:
            self.db.collections = staged_collections or {}
            self.db.rows = self.db.collections.setdefault(
                "sheets_stock_time_reconciliation_operations", {}
            )


class FakeSession:
    def __init__(self, db: FakeDB, *, transaction: bool = True) -> None:
        self.db, self.transaction = db, transaction

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, error_type: Any, error: Any, traceback: Any) -> None:
        return None

    def start_transaction(self, **options: Any) -> FakeTransaction:
        if not self.transaction:
            raise AttributeError("transaction unavailable")
        self.db.transaction_options.append(options)
        return FakeTransaction(self.db, self, options)


class FakeClient:
    def __init__(self, db: FakeDB, *, awaitable: bool = False, session: Any = None) -> None:
        self.db, self.awaitable, self.session = db, awaitable, session

    def start_session(self) -> Any:
        session = self.session if self.session is not None else FakeSession(self.db)
        if not self.awaitable:
            return session

        async def result() -> Any:
            return session

        return result()


class FakeUpdateResult:
    def __init__(
        self,
        matched_count: int = 0,
        modified_count: int = 0,
        upserted_id: str | None = None,
        deleted_count: int = 0,
    ) -> None:
        self.matched_count = matched_count
        self.modified_count = modified_count
        self.upserted_id = upserted_id
        self.deleted_count = deleted_count


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        return deepcopy(self.rows if length is None else self.rows[:length])


class FakeCollection:
    def __init__(self, db: FakeDB, name: str) -> None:
        self.db, self.name = db, name

    def _session(self, options: dict[str, Any]) -> None:
        assert self.db.staged_collections is not None
        assert options.get("session") is self.db.active_session

    def _rows(self) -> dict[str, dict[str, Any]]:
        assert self.db.staged_collections is not None
        return self.db.staged_collections.setdefault(self.name, {})

    async def find_one(self, query: dict[str, Any], **options: Any) -> Any:
        self._session(options)
        self.db.reads.append((query, options))
        for row in self._rows().values():
            if self._matches(row, query):
                return deepcopy(row)
        return None

    def find(self, query: dict[str, Any], **options: Any) -> FakeCursor:
        self._session(options)
        self.db.reads.append((query, options))
        rows = [row for row in self._rows().values() if self._matches(row, query)]
        if self.name == "sheets_stock_time_metrics":
            self.db.metric_reads += 1
            if self.db.metric_reads == 2 and self.db.metric_readback_hook is not None:
                rows = self.db.metric_readback_hook(deepcopy(rows))
        return FakeCursor(rows)

    def _matches(self, row: dict[str, Any], query: dict[str, Any]) -> bool:
        for key, expected in query.items():
            if key == "$or":
                if not any(self._matches(row, clause) for clause in expected):
                    return False
            elif key == "$expr":
                operation, operands = next(iter(expected.items()))
                left, right = (self._operand(row, operand) for operand in operands)
                if operation == "$gt" and not left > right:
                    return False
                if operation == "$lte" and not left <= right:
                    return False
            elif isinstance(expected, dict) and "$in" in expected:
                if row.get(key) not in expected["$in"]:
                    return False
            elif isinstance(expected, dict) and "$exists" in expected:
                if (key in row) is not expected["$exists"]:
                    return False
                if "$eq" in expected and row.get(key) != expected["$eq"]:
                    return False
            elif row.get(key) != expected:
                return False
        return True

    def _operand(self, row: dict[str, Any], operand: Any) -> Any:
        if operand == "$$NOW":
            return self.db.server_now
        if isinstance(operand, str) and operand.startswith("$"):
            return row.get(operand[1:])
        return operand

    async def update_one(
        self, query: dict[str, Any], pipeline: list[dict[str, Any]], **options: Any
    ) -> FakeUpdateResult:
        self._session(options)
        self.db.writes.append((query, pipeline, options))
        self.db.written_collections.append(self.name)
        assert self.db.staged is not None
        if self.db.pre_match_mutation is not None:
            mutation, self.db.pre_match_mutation = self.db.pre_match_mutation, None
            raced = self.db.rows[query["_id"]]
            raced.update(mutation)
            self.db.staged[query["_id"]] = deepcopy(raced)
        matched = next((row for row in self.db.staged.values() if self._matches(row, query)), None)
        if "$replaceWith" in pipeline[0]:
            if matched is not None or options.get("upsert"):
                updated = self._evaluate(pipeline[0]["$replaceWith"], matched)
                self.db.staged[updated["_id"]] = updated
        elif matched is not None:
            updated = deepcopy(matched)
            updated.update(self._evaluate(pipeline[0]["$set"], matched))
            self.db.staged[updated["_id"]] = updated
        if self.db.fail_body:
            raise RuntimeError("body failed")
        if self.db.fail_write:
            raise RuntimeError("write failed")
        return FakeUpdateResult(int(matched is not None))

    def _metric_race(self) -> None:
        if self.name == "sheets_stock_time_metrics" and self.db.metric_race is not None:
            race, self.db.metric_race = self.db.metric_race, None
            race(self._rows())

    async def replace_one(
        self, query: dict[str, Any], document: dict[str, Any], **options: Any
    ) -> FakeUpdateResult:
        self._session(options)
        self._metric_race()
        self.db.metric_writes.append(("replace", deepcopy(query), deepcopy(document), options))
        rows = self._rows()
        matched = next((row for row in rows.values() if self._matches(row, query)), None)
        if self.db.metric_result_overrides:
            return self.db.metric_result_overrides.pop(0)
        if matched is not None:
            modified = int(matched != document)
            rows[matched["_id"]] = deepcopy(document)
            return FakeUpdateResult(1, modified)
        if options.get("upsert"):
            if document["_id"] in rows:
                raise RuntimeError("duplicate key")
            rows[document["_id"]] = deepcopy(document)
            return FakeUpdateResult(upserted_id=document["_id"])
        return FakeUpdateResult()

    async def delete_one(self, query: dict[str, Any], **options: Any) -> FakeUpdateResult:
        self._session(options)
        self._metric_race()
        self.db.metric_writes.append(("delete", deepcopy(query), None, options))
        rows = self._rows()
        matched = next((row for row in rows.values() if self._matches(row, query)), None)
        if self.db.metric_result_overrides:
            return self.db.metric_result_overrides.pop(0)
        if matched is not None:
            del rows[matched["_id"]]
            return FakeUpdateResult(deleted_count=1)
        return FakeUpdateResult()

    async def insert_many(self, documents: list[dict[str, Any]], **options: Any) -> None:
        self._session(options)
        self.db.written_collections.append(self.name)
        rows = self._rows()
        for document in documents:
            identity = (document["operation_id"], document["sequence"])
            target = (
                document["operation_id"],
                document["target_collection"],
                document["target_id"],
            )
            if document["_id"] in rows or any(
                (row["operation_id"], row["sequence"]) == identity
                or (row["operation_id"], row["target_collection"], row["target_id"]) == target
                for row in rows.values()
            ):
                raise RuntimeError("duplicate insert")
            rows[document["_id"]] = deepcopy(document)
        if self.db.fail_write:
            raise RuntimeError("write failed")

    def _evaluate(self, value: Any, row: dict[str, Any] | None) -> Any:
        if value == "$$NOW":
            return self.db.server_now
        if isinstance(value, str) and value.startswith("$"):
            assert row is not None
            return row[value[1:]]
        if isinstance(value, list):
            return [self._evaluate(item, row) for item in value]
        if not isinstance(value, dict):
            return value
        if "$add" in value:
            return sum(self._evaluate(item, row) for item in value["$add"])
        if "$dateAdd" in value:
            spec = value["$dateAdd"]
            assert spec["unit"] == "second"
            return self._evaluate(spec["startDate"], row) + timedelta(seconds=spec["amount"])
        return {key: self._evaluate(item, row) for key, item in value.items()}


class FakeDB:
    def __init__(self, **failures: bool) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.collections: dict[str, dict[str, dict[str, Any]]] = {
            "sheets_stock_time_reconciliation_operations": self.rows
        }
        self.staged: dict[str, dict[str, Any]] | None = None
        self.staged_collections: dict[str, dict[str, dict[str, Any]]] | None = None
        self.active_session: FakeSession | None = None
        self.server_now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
        self.accessed: list[str] = []
        self.reads: list[Any] = []
        self.writes: list[Any] = []
        self.written_collections: list[str] = []
        self.transaction_options: list[dict[str, Any]] = []
        self.fail_body = failures.get("fail_body", False)
        self.fail_write = failures.get("fail_write", False)
        self.fail_commit = failures.get("fail_commit", False)
        self.pre_match_mutation: dict[str, Any] | None = None
        self.metric_race: Any = None
        self.metric_result_overrides: list[FakeUpdateResult] = []
        self.metric_writes: list[Any] = []
        self.metric_readback_hook: Any = None
        self.metric_reads = 0
        self.client: Any = FakeClient(self)

    def __getitem__(self, name: str) -> FakeCollection:
        self.accessed.append(name)
        return FakeCollection(self, name)


@pytest.mark.asyncio
async def test_attempt_tokens_are_fresh_bounded_and_redacted() -> None:
    tokens = {engine._new_forward_attempt_token() for _ in range(8)}
    assert len(tokens) == 8
    assert all(re.fullmatch(r"[0-9a-f]{32}", token) for token in tokens)
    token = tokens.pop()
    context = engine._ForwardOperationContext("operation", "prepared", 1, token, 1, True)
    assert token not in repr(context)
    with pytest.raises(FrozenInstanceError):
        context.__setattr__("fence", 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("token", ["", "a" * 31, "A" * 32, object()])
async def test_invalid_attempt_token_fails_before_database_access(token: Any) -> None:
    class UntouchableDB:
        @property
        def client(self) -> Any:
            raise AssertionError("database accessed")

    with pytest.raises(engine._ForwardEngineError, match="INVALID_ATTEMPT_TOKEN"):
        await engine._acquire_forward_operation(UntouchableDB(), seal(), token)


@pytest.mark.asyncio
async def test_acquire_creates_exact_prepared_operation_with_server_lease() -> None:
    db, sealed, token = FakeDB(), seal(), "a" * 32
    context = await engine._acquire_forward_operation(db, sealed, token)

    assert context == engine._ForwardOperationContext(
        sealed.operation_id, "prepared", 1, token, 1, True
    )
    now = db.server_now
    assert db.rows == {
        sealed.operation_id: {
            "_id": sealed.operation_id,
            "seller_id": "82453304",
            "read_model": "stock_time_metrics",
            "date_from": START,
            "date_to": END,
            "source_fingerprint": sealed.binding.source_fingerprint,
            "plan_fingerprint": sealed.binding.plan_fingerprint,
            "state": "prepared",
            "attempt": 1,
            "attempt_token": token,
            "fence": 1,
            "lease_acquired_at": now,
            "heartbeat_at": now,
            "lease_until": now + timedelta(seconds=120),
            "planned_insert_count": 2,
            "planned_update_count": 1,
            "planned_delete_count": 1,
            "planned_preimage_count": 4,
            "created_at": now,
            "updated_at": now,
            "committed_at": None,
            "terminal_at": None,
            "error_code": None,
            "schema_version": 1,
        }
    }
    options = db.transaction_options[0]
    assert options["read_concern"].level == "snapshot"
    assert options["write_concern"].document == {"w": "majority"}
    assert "$$NOW" in repr(db.writes[0][1]) and "$dateAdd" in repr(db.writes[0][1])
    assert db.writes[0][2]["upsert"] is True
    binding_fields = (
        "seller_id",
        "read_model",
        "date_from",
        "date_to",
        "source_fingerprint",
        "plan_fingerprint",
    )
    assert db.reads[0][0]["$or"] == [
        {"_id": sealed.operation_id},
        {key: db.rows[sealed.operation_id][key] for key in binding_fields},
    ]
    assert db.accessed == ["sheets_stock_time_reconciliation_operations"]


@pytest.mark.asyncio
async def test_acquire_accepts_awaitable_session() -> None:
    db = FakeDB()
    db.client = FakeClient(db, awaitable=True)
    assert (await engine._acquire_forward_operation(db, seal(), "b" * 32)).owns_lease


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing", ["client", "session_context", "transaction", "transaction_failure"]
)
async def test_acquire_requires_all_transaction_capabilities(missing: str) -> None:
    db = FakeDB()
    if missing == "client":
        db.client = object()
    elif missing == "session_context":
        db.client = FakeClient(db, session=object())
    else:
        session: Any = FakeSession(db, transaction=missing != "transaction_failure")
        if missing == "transaction":
            session.start_transaction = None
        db.client = FakeClient(db, session=session)
    with pytest.raises(engine._ForwardEngineError, match="TRANSACTION_REQUIRED"):
        await engine._acquire_forward_operation(db, seal(), "c" * 32)
    assert not db.rows and not db.writes and not db.accessed


def persisted_operation(
    sealed: Any,
    *,
    state: Any = "prepared",
    token: str = "a" * 32,
    lease_until: datetime | None = None,
) -> dict[str, Any]:
    now, counts = datetime(2026, 8, 1, 12, 0, tzinfo=UTC), sealed.ledger_counts
    return {
        "_id": sealed.operation_id,
        "seller_id": sealed.binding._seller_id,
        "read_model": "stock_time_metrics",
        "date_from": sealed.binding.date_from,
        "date_to": sealed.binding.date_to,
        "source_fingerprint": sealed.binding.source_fingerprint,
        "plan_fingerprint": sealed.binding.plan_fingerprint,
        "state": state,
        "attempt": 3,
        "attempt_token": token,
        "fence": 5,
        "lease_acquired_at": now - timedelta(minutes=1),
        "heartbeat_at": now,
        "lease_until": lease_until or now + timedelta(minutes=1),
        "planned_insert_count": counts.planned_insert_count,
        "planned_update_count": counts.planned_update_count,
        "planned_delete_count": counts.planned_delete_count,
        "planned_preimage_count": counts.planned_preimage_count,
        "created_at": now - timedelta(minutes=2),
        "updated_at": now,
        "committed_at": None,
        "terminal_at": None,
        "error_code": None,
        "schema_version": 1,
    }


def install(db: FakeDB, row: dict[str, Any]) -> None:
    db.rows[row["_id"]] = row


def execution_setup(sealed: Any | None = None) -> tuple[FakeDB, Any, Any]:
    db, plan, token = FakeDB(), sealed or seal(old_marker=marker()), "9" * 32
    operation = persisted_operation(plan, token=token)
    install(db, operation)
    metrics = db.collections.setdefault("sheets_stock_time_metrics", {})
    for action in plan._action_plan.actions:
        if action._preimage is not None:
            metrics[action._target_id] = planner._canonical_bson_document(action._preimage)
    if plan._marker_preimage is not None:
        db.collections["sheets_read_model_freshness"] = {
            plan._marker_preimage["_id"]: planner._canonical_bson_document(plan._marker_preimage)
        }
    context = engine._ForwardOperationContext(
        plan.operation_id, "prepared", operation["attempt"], token, operation["fence"], True
    )
    return db, plan, context


@pytest.mark.asyncio
async def test_same_token_live_prepared_returns_persisted_owner_using_server_time() -> None:
    db, sealed, token = FakeDB(), seal(), "d" * 32
    install(db, persisted_operation(sealed, token=token))

    context = await engine._acquire_forward_operation(db, sealed, token)

    assert context == engine._ForwardOperationContext(
        sealed.operation_id, "prepared", 3, token, 5, True
    )
    assert db.reads[1][0] == {
        "_id": sealed.operation_id,
        "state": "prepared",
        "attempt_token": token,
        "$expr": {"$gt": ["$lease_until", "$$NOW"]},
    }
    assert not db.writes


@pytest.mark.asyncio
async def test_other_live_prepared_is_lease_conflict_with_server_predicates() -> None:
    db, sealed = FakeDB(), seal()
    install(db, persisted_operation(sealed, token="d" * 32))

    with pytest.raises(engine._ForwardEngineError, match="LEASE_CONFLICT"):
        await engine._acquire_forward_operation(db, sealed, "e" * 32)

    assert [read[0].get("$expr") for read in db.reads[1:]] == [
        {"$gt": ["$lease_until", "$$NOW"]},
        {"$lte": ["$lease_until", "$$NOW"]},
    ]
    assert not db.writes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("persisted_token", "requested_token", "delta"),
    [("f" * 32, "f" * 32, timedelta(0)), ("f" * 32, "0" * 32, timedelta(seconds=-1))],
)
async def test_expired_prepared_either_token_cas_takes_over_exact_row(
    persisted_token: str, requested_token: str, delta: timedelta
) -> None:
    db, sealed = FakeDB(), seal()
    original = persisted_operation(sealed, token=persisted_token, lease_until=db.server_now + delta)
    original.update(
        committed_at=START, terminal_at=START, error_code="stale", preserved={"nested": 1}
    )
    install(db, original)

    context = await engine._acquire_forward_operation(db, sealed, requested_token)

    assert context == engine._ForwardOperationContext(
        sealed.operation_id, "prepared", 4, requested_token, 6, True
    )
    query, pipeline, options = db.writes[0]
    assert query == {
        "_id": sealed.operation_id,
        "seller_id": sealed.binding._seller_id,
        "read_model": "stock_time_metrics",
        "date_from": sealed.binding.date_from,
        "date_to": sealed.binding.date_to,
        "source_fingerprint": sealed.binding.source_fingerprint,
        "plan_fingerprint": sealed.binding.plan_fingerprint,
        "planned_insert_count": 2,
        "planned_update_count": 1,
        "planned_delete_count": 1,
        "planned_preimage_count": 4,
        "state": "prepared",
        "attempt": 3,
        "attempt_token": persisted_token,
        "fence": 5,
        "$expr": {"$lte": ["$lease_until", "$$NOW"]},
    }
    assert pipeline == [
        {
            "$set": {
                "state": "prepared",
                "attempt": {"$add": ["$attempt", 1]},
                "attempt_token": requested_token,
                "fence": {"$add": ["$fence", 1]},
                "lease_acquired_at": "$$NOW",
                "heartbeat_at": "$$NOW",
                "lease_until": {
                    "$dateAdd": {"startDate": "$$NOW", "unit": "second", "amount": 120}
                },
                "updated_at": "$$NOW",
                "committed_at": None,
                "terminal_at": None,
                "error_code": None,
            }
        }
    ]
    assert options == {"session": options["session"]}
    expected = deepcopy(original)
    expected.update(
        state="prepared",
        attempt=4,
        attempt_token=requested_token,
        fence=6,
        lease_acquired_at=db.server_now,
        heartbeat_at=db.server_now,
        lease_until=db.server_now + timedelta(seconds=120),
        updated_at=db.server_now,
        committed_at=None,
        terminal_at=None,
        error_code=None,
    )
    assert db.rows[sealed.operation_id] == expected
    assert len(db.writes) == 1
    assert db.accessed == ["sheets_stock_time_reconciliation_operations"]


@pytest.mark.asyncio
async def test_expired_takeover_race_loser_is_bounded_without_fallback() -> None:
    db, sealed = FakeDB(), seal()
    install(db, persisted_operation(sealed, token="1" * 32, lease_until=db.server_now))
    db.pre_match_mutation = {
        "attempt": 4,
        "attempt_token": "2" * 32,
        "fence": 6,
        "lease_until": db.server_now + timedelta(seconds=120),
    }

    with pytest.raises(engine._ForwardEngineError, match="TAKEOVER_CONFLICT"):
        await engine._acquire_forward_operation(db, sealed, "3" * 32)

    assert len(db.writes) == 1
    assert len(db.reads) == 3
    assert db.rows[sealed.operation_id]["attempt_token"] == "2" * 32


@pytest.mark.asyncio
@pytest.mark.parametrize("requested", ["a" * 32, "b" * 32])
async def test_committed_exact_row_returns_persisted_non_owner(requested: str) -> None:
    db, sealed, persisted = FakeDB(), seal(), "a" * 32
    install(db, persisted_operation(sealed, state="committed", token=persisted))
    assert await engine._acquire_forward_operation(db, sealed, requested) == (
        engine._ForwardOperationContext(sealed.operation_id, "committed", 3, persisted, 5, False)
    )
    assert len(db.reads) == 1 and not db.writes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state", ["failed", "expired", "rolled_back", "rollback_blocked", "future_state"]
)
async def test_terminal_and_unknown_states_are_blocked_without_write(state: str) -> None:
    db, sealed = FakeDB(), seal()
    install(db, persisted_operation(sealed, state=state))
    with pytest.raises(engine._ForwardEngineError, match="STATE_BLOCKED"):
        await engine._acquire_forward_operation(db, sealed, "a" * 32)
    assert not db.writes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("_id", "other"),
        ("seller_id", "other"),
        ("read_model", "other"),
        ("date_from", START + timedelta(days=1)),
        ("date_to", END + timedelta(days=1)),
        ("source_fingerprint", "0" * 64),
        ("plan_fingerprint", "0" * 64),
        ("planned_insert_count", 99),
        ("planned_update_count", 99),
        ("planned_delete_count", 99),
        ("planned_preimage_count", 99),
    ],
)
async def test_existing_immutable_mismatch_precedes_state(field: str, value: Any) -> None:
    db, sealed = FakeDB(), seal()
    row = persisted_operation(sealed, state="committed")
    row[field] = value
    install(db, row)
    with pytest.raises(engine._ForwardEngineError, match="OPERATION_MISMATCH"):
        await engine._acquire_forward_operation(db, sealed, "a" * 32)
    assert not db.writes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("state", None),
        ("attempt", 0),
        ("attempt", True),
        ("fence", 0),
        ("fence", True),
        ("attempt_token", "bad"),
        ("planned_update_count", True),
        ("lease_acquired_at", START.replace(tzinfo=None)),
        ("heartbeat_at", START.replace(tzinfo=None)),
        ("lease_until", START.replace(tzinfo=None)),
    ],
)
async def test_existing_malformed_schema_precedes_state(field: str, value: Any) -> None:
    db, sealed = FakeDB(), seal()
    row = persisted_operation(sealed, state="committed")
    row[field] = value
    install(db, row)
    with pytest.raises(engine._ForwardEngineError, match="INVALID_OPERATION_SCHEMA"):
        await engine._acquire_forward_operation(db, sealed, "a" * 32)
    assert not db.writes


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["fail_body", "fail_write", "fail_commit"])
@pytest.mark.parametrize("existing", [False, True], ids=["create", "takeover"])
async def test_acquire_failure_rolls_back_and_never_becomes_success(
    failure: str, existing: bool
) -> None:
    db, sealed = FakeDB(**{failure: True}), seal()
    if existing:
        install(db, persisted_operation(sealed, token="d" * 32, lease_until=db.server_now))
    original = deepcopy(db.rows)
    with pytest.raises(RuntimeError, match=failure.removeprefix("fail_") + " failed"):
        await engine._acquire_forward_operation(db, sealed, "e" * 32)
    assert db.rows == original and db.staged is None


@pytest.mark.asyncio
async def test_execution_revalidates_owner_and_persists_deterministic_exact_preimages() -> None:
    db, sealed, context = execution_setup()
    await engine._persist_forward_preimages(db, sealed, context)
    rows = list(db.collections["sheets_stock_time_reconciliation_preimages"].values())

    assert [row["sequence"] for row in rows] == [1, 2, 3, 4]
    assert [row["target_id"] for row in rows] == ["delete", "insert", "replace", marker()["_id"]]
    assert "same" not in {row["target_id"] for row in rows}
    operation = db.rows[sealed.operation_id]
    for row, mutation in zip(rows, sealed._mutations, strict=True):
        assert row == {
            "_id": engine._preimage_record_id(sealed.operation_id, mutation),
            "operation_id": sealed.operation_id,
            "sequence": mutation.sequence,
            "target_collection": mutation.target_collection,
            "target_id": mutation._target_id,
            "action": mutation.action,
            "preimage": mutation._preimage,
            "preimage_kind": mutation.preimage_kind,
            "preimage_fingerprint": mutation.preimage_fingerprint,
            "expected_forward_revision": mutation.expected_forward_revision,
            "created_at": operation["lease_acquired_at"],
            "schema_version": 1,
        }
    assert db.written_collections == ["sheets_stock_time_reconciliation_preimages"]

    other, _, other_context = execution_setup(sealed)
    await engine._persist_forward_preimages(other, sealed, other_context)
    assert (
        other.collections["sheets_stock_time_reconciliation_preimages"]
        == (db.collections["sheets_stock_time_reconciliation_preimages"])
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "code"),
    [
        ("token", "FENCE_CONFLICT"),
        ("fence", "FENCE_CONFLICT"),
        ("state", "STATE_BLOCKED"),
        ("lease", "LEASE_CONFLICT"),
        ("binding", "OPERATION_MISMATCH"),
    ],
)
async def test_execution_rejects_stale_owner_state_lease_and_binding(kind: str, code: str) -> None:
    db, sealed, context = execution_setup()
    if kind == "token":
        context = replace(context, attempt_token="8" * 32)
    elif kind == "fence":
        context = replace(context, fence=context.fence + 1)
    elif kind == "state":
        db.rows[sealed.operation_id]["state"] = "committed"
    elif kind == "lease":
        db.rows[sealed.operation_id]["lease_until"] = db.server_now
    else:
        db.rows[sealed.operation_id]["planned_preimage_count"] += 1
    with pytest.raises(engine._ForwardEngineError, match=code):
        await engine._persist_forward_preimages(db, sealed, context)
    assert "sheets_stock_time_reconciliation_preimages" not in db.collections


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["replace", "same", "marker"])
async def test_execution_rejects_metric_marker_and_noop_drift(target: str) -> None:
    db, sealed, context = execution_setup()
    collection = (
        "sheets_read_model_freshness" if target == "marker" else "sheets_stock_time_metrics"
    )
    target_id = marker()["_id"] if target == "marker" else target
    db.collections[collection][target_id]["revision"] = None
    with pytest.raises(engine._ForwardEngineError, match="PREIMAGE_MISMATCH"):
        await engine._persist_forward_preimages(db, sealed, context)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["missing", "extra", "duplicate"])
async def test_execution_rejects_incomplete_or_duplicate_exact_interval(mode: str) -> None:
    db, sealed, context = execution_setup()
    metrics = db.collections["sheets_stock_time_metrics"]
    if mode == "missing":
        del metrics["delete"]
    elif mode == "extra":
        metrics["extra"] = metric("extra", 1)
    else:
        metrics["duplicate"] = deepcopy(metrics["same"])
    with pytest.raises(engine._ForwardEngineError, match="PREIMAGE_MISMATCH"):
        await engine._persist_forward_preimages(db, sealed, context)


@pytest.mark.asyncio
@pytest.mark.parametrize("revision", ["missing", None, "7" * 64])
async def test_execution_preserves_exact_legacy_revision_state(revision: Any) -> None:
    existing = metric("same", 1)
    if revision != "missing":
        existing["revision"] = revision
    plan = planner._plan_stock_time_actions(
        source_inventory=[{"_id": "source"}],
        planned_documents=[metric("same", 1)],
        existing_target_rows=[existing],
    )
    db, sealed, context = execution_setup(seal(plan=plan, old_marker=marker()))
    await engine._persist_forward_preimages(db, sealed, context)
    assert len(db.collections["sheets_stock_time_reconciliation_preimages"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["fail_write", "fail_commit"])
async def test_preimage_transaction_failure_rolls_back_and_next_transaction_is_fresh(
    failure: str,
) -> None:
    db, sealed, context = execution_setup()
    setattr(db, failure, True)
    with pytest.raises(RuntimeError, match=failure.removeprefix("fail_") + " failed"):
        await engine._persist_forward_preimages(db, sealed, context)
    assert "sheets_stock_time_reconciliation_preimages" not in db.collections
    assert db.staged_collections is None and db.active_session is None
    setattr(db, failure, False)
    await engine._persist_forward_preimages(db, sealed, context)
    assert len(db.collections["sheets_stock_time_reconciliation_preimages"]) == 4


@pytest.mark.asyncio
async def test_duplicate_preimage_insert_rolls_back_partial_batch() -> None:
    source, sealed, source_context = execution_setup()
    await engine._persist_forward_preimages(source, sealed, source_context)
    records = list(source.collections["sheets_stock_time_reconciliation_preimages"].values())
    db, _, context = execution_setup(sealed)
    db.collections["sheets_stock_time_reconciliation_preimages"] = {
        records[1]["_id"]: deepcopy(records[1])
    }
    with pytest.raises(RuntimeError, match="duplicate insert"):
        await engine._persist_forward_preimages(db, sealed, context)
    assert db.collections["sheets_stock_time_reconciliation_preimages"] == {
        records[1]["_id"]: records[1]
    }


@pytest.mark.asyncio
async def test_preimage_callback_runs_after_insert_inside_the_same_transaction() -> None:
    db, sealed, context = execution_setup()
    called: list[Any] = []

    async def callback(session: Any) -> None:
        called.append(session)
        assert db.active_session is session
        assert db.staged_collections is not None
        assert len(db.staged_collections["sheets_stock_time_reconciliation_preimages"]) == 4

    await engine._persist_forward_preimages(db, sealed, context, callback)
    assert called and len(db.transaction_options) == 1


@pytest.mark.asyncio
async def test_metric_cas_mixed_plan_has_exact_sequence_noop_touch_and_readback() -> None:
    db, sealed, context = execution_setup()
    original_operation, original_marker = (
        deepcopy(db.rows),
        deepcopy(db.collections["sheets_read_model_freshness"]),
    )

    await engine._persist_forward_metrics(db, sealed, context)

    assert db.collections["sheets_stock_time_metrics"] == {
        row["_id"]: row for row in sealed._expected_metric_documents
    }
    assert [(method, query["_id"]) for method, query, _, _ in db.metric_writes] == [
        ("delete", "delete"),
        ("replace", "insert"),
        ("replace", "replace"),
        ("replace", "same"),
        ("replace", "same"),
    ]
    for _, query, _, _ in db.metric_writes:
        assert query["seller_id"] == {"$in": ["82453304", 82453304]}
        assert (query["date_from"], query["date_to"]) == (START, END)
    assert db.metric_writes[1][3]["upsert"] is True
    assert db.metric_writes[1][2] == next(
        row for row in sealed._expected_metric_documents if row["_id"] == "insert"
    )
    noop_writes = db.metric_writes[-2:]
    assert noop_writes[0][2]["revision"] == engine._operation_revision(
        sealed.operation_id, "sheets_stock_time_metrics", "same", "no-op"
    )
    assert noop_writes[1][2] == metric("same", 1)
    assert len(db.collections["sheets_stock_time_reconciliation_preimages"]) == 4
    assert db.rows == original_operation
    assert db.collections["sheets_read_model_freshness"] == original_marker
    assert len(db.transaction_options) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("revision", ["missing", None, "7" * 64])
async def test_noop_cas_distinguishes_and_restores_legacy_revision_state(revision: Any) -> None:
    existing = metric("same", 1)
    if revision != "missing":
        existing["revision"] = revision
    plan = planner._plan_stock_time_actions(
        source_inventory=[{"_id": "source"}],
        planned_documents=[metric("same", 1)],
        existing_target_rows=[existing],
    )
    db, sealed, context = execution_setup(seal(plan=plan, old_marker=marker()))

    await engine._persist_forward_metrics(db, sealed, context)

    assert db.collections["sheets_stock_time_metrics"]["same"] == existing
    first_guard = db.metric_writes[0][1]["revision"]
    assert first_guard == (
        {"$exists": False} if revision == "missing" else {"$exists": True, "$eq": revision}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["insert", "replace", "delete", "no-op"])
async def test_metric_cas_rejects_each_non_exact_write_result(action: str) -> None:
    planned = [] if action == "delete" else [metric("target", 1 if action == "no-op" else 2)]
    existing = [] if action == "insert" else [metric("target", 1)]
    plan = planner._plan_stock_time_actions(
        source_inventory=[{"_id": "source"}],
        planned_documents=planned,
        existing_target_rows=existing,
    )
    db, sealed, context = execution_setup(seal(plan=plan, old_marker=marker()))
    db.metric_result_overrides = [
        FakeUpdateResult(matched_count=1)
        if action in {"insert", "no-op"}
        else FakeUpdateResult(matched_count=1, modified_count=0)
        if action == "replace"
        else FakeUpdateResult(deleted_count=0)
    ]
    original = deepcopy(db.collections)

    with pytest.raises(engine._ForwardEngineError, match="PREIMAGE_MISMATCH"):
        await engine._persist_forward_metrics(db, sealed, context)
    assert db.collections == original


@pytest.mark.asyncio
async def test_metric_concurrent_write_conflict_rolls_back_preimages_and_metrics() -> None:
    plan = planner._plan_stock_time_actions(
        source_inventory=[{"_id": "source"}],
        planned_documents=[metric("replace", 2)],
        existing_target_rows=[metric("replace", 1)],
    )
    db, sealed, context = execution_setup(seal(plan=plan, old_marker=marker()))
    original = deepcopy(db.collections)

    def race(_: Any) -> None:
        raise RuntimeError("write conflict")

    db.metric_race = race
    with pytest.raises(RuntimeError, match="write conflict"):
        await engine._persist_forward_metrics(db, sealed, context)
    assert db.collections == original


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["missing", "extra", "altered", "fingerprint"])
async def test_metric_exact_readback_mismatch_rolls_back(mode: str) -> None:
    db, sealed, context = execution_setup()
    original = deepcopy(db.collections)
    if mode == "fingerprint":
        sealed = replace(sealed, expected_metric_fingerprint="0" * 64)
    else:

        def hook(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            if mode == "missing":
                return rows[:-1]
            if mode == "extra":
                return [*rows, metric("extra", 1)]
            rows[0]["value"] = 999
            return rows

        db.metric_readback_hook = hook

    with pytest.raises(engine._ForwardEngineError, match="PREIMAGE_MISMATCH"):
        await engine._persist_forward_metrics(db, sealed, context)
    assert db.collections == original


@pytest.mark.asyncio
async def test_metric_commit_failure_rolls_back_preimages_and_all_metric_writes() -> None:
    db, sealed, context = execution_setup()
    original = deepcopy(db.collections)
    db.fail_commit = True
    with pytest.raises(RuntimeError, match="commit failed"):
        await engine._persist_forward_metrics(db, sealed, context)
    assert db.collections == original


def test_forward_contract_remains_private_with_bounded_errors() -> None:
    assert not hasattr(zeler_sheets, "_seal_forward_plan")
    assert not hasattr(zeler_sheets, "_ForwardMutation")
    assert not hasattr(zeler_sheets, "_acquire_forward_operation")
    assert not hasattr(engine, "_acquire_new_forward_operation")
    assert not hasattr(zeler_sheets, "_ForwardOperationContext")
    assert not hasattr(zeler_sheets, "_persist_forward_preimages")
    assert not hasattr(zeler_sheets, "_persist_forward_metrics")
    with pytest.raises(ValueError, match="unknown forward-engine error code"):
        engine._ForwardEngineError("NOT_A_SEALING_ERROR")
