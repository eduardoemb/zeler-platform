"""Local transactional fakes for opt-in immutable question readmission; no resources."""

from __future__ import annotations

import copy
import hashlib
import importlib
import socket
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from bson import BSON
from bson.codec_options import CodecOptions
from bson.raw_bson import RawBSONDocument
from pymongo.errors import DuplicateKeyError
from pymongo.results import UpdateResult

from zeler_platform_core.history_onboarding import POLICY_VERSION, SOURCES
from zeler_platform_core.models import SheetsHistoryAcquisition
from zeler_sheets.formulas.recovery import FormulaRecoveryQueue, QuestionScanRecoveryRequest
from zeler_sheets.history_acquisition import HistoryConflictError

NOW = datetime(2026, 10, 6, 9, tzinfo=UTC)
SELLER = "82453304"
EXECUTION = "868b413e20184befb7e8358e0051924f"
END = datetime(2026, 9, 24, 5, 36, 28, tzinfo=UTC)
START = END.replace(year=2025)
MISSING = object()


def normalized(value: dict[str, Any]) -> dict[str, Any]:
    return dict(BSON(BSON.encode(value)).decode(codec_options=CodecOptions(tz_aware=True)))


def sha(value: dict[str, Any]) -> str:
    return hashlib.sha256(BSON.encode(value)).hexdigest()


def get(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return MISSING
        current = current[part]
    return current


def expression(value: Any, row: dict[str, Any], variables: dict[str, Any] | None = None) -> Any:
    variables = variables or {}
    if isinstance(value, str) and value == "$$ROOT":
        return row
    if isinstance(value, str) and value.startswith("$$"):
        return variables.get(value[2:], MISSING)
    if isinstance(value, str) and value.startswith("$"):
        return get(row, value[1:])
    if isinstance(value, list):
        return [expression(v, row, variables) for v in value]
    if not isinstance(value, dict):
        return value
    if "$literal" in value:
        return value["$literal"]
    if "$toString" in value:
        return str(expression(value["$toString"], row, variables))
    for op in ("$eq", "$ne", "$gt", "$gte", "$lt", "$lte"):
        if op in value:
            a, b = expression(value[op], row, variables)
            if op == "$eq":
                return a == b
            if op == "$ne":
                return a != b
            if a is MISSING or b is MISSING:
                return False
            if op == "$gt":
                return a > b
            if op == "$gte":
                return a >= b
            if op == "$lt":
                return a < b
            return a <= b

    if "$and" in value:
        return all(expression(v, row, variables) for v in value["$and"])
    raise AssertionError("unsupported fake expression")


def matches(row: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, wanted in query.items():
        if key == "$and":
            if not all(matches(row, v) for v in wanted):
                return False
            continue
        if key == "$or":
            if not any(matches(row, v) for v in wanted):
                return False
            continue
        if key == "$expr":
            if not expression(wanted, row):
                return False
            continue
        actual = get(row, key)
        if isinstance(wanted, dict):
            for op, b in wanted.items():
                if op == "$exists":
                    yes = (actual is not MISSING) is b
                elif op == "$in":
                    yes = actual in b
                elif op == "$nin":
                    yes = actual not in b
                elif op == "$ne":
                    yes = actual != b
                elif op == "$size":
                    yes = isinstance(actual, list) and len(actual) == b
                elif actual is MISSING:
                    yes = False
                elif op == "$gt":
                    yes = actual > b
                elif op == "$gte":
                    yes = actual >= b
                elif op == "$lt":
                    yes = actual < b
                elif op == "$lte":
                    yes = actual <= b
                else:
                    raise AssertionError("unsupported fake query")
                if not yes:
                    return False
        elif actual != wanted:
            return False
    return True


class Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = copy.deepcopy(rows)

    def sort(self, key: str | list[tuple[str, int]], direction: int = 1) -> Cursor:
        entries = [(key, direction)] if isinstance(key, str) else key
        for field, order in reversed(entries):
            self.rows.sort(key=lambda r: str(get(r, field)), reverse=order < 0)
        return self

    def limit(self, n: int) -> Cursor:
        self.rows = self.rows[:n]
        return self

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        return copy.deepcopy(self.rows if length is None else self.rows[:length])

    def __aiter__(self) -> Cursor:
        self.index = 0
        return self

    async def __anext__(self) -> dict[str, Any]:
        if self.index == len(self.rows):
            raise StopAsyncIteration
        value = copy.deepcopy(self.rows[self.index])
        self.index += 1
        return value


class Collection:
    def __init__(self, db: DB, name: str) -> None:
        self.database = db
        self.name = name
        self.docs: list[dict[str, Any]] = []

    def with_options(self, **kwargs: Any) -> Any:
        collection = self
        raw = kwargs["codec_options"].document_class is RawBSONDocument

        class RawView:
            def __getattr__(self, name: str) -> Any:
                return getattr(collection, name)

            async def find_one(self, query: dict[str, Any], **options: Any) -> Any:
                row = await collection.find_one(query, **options)
                if row is None or not raw:
                    return row
                return RawBSONDocument(
                    BSON.encode(row), CodecOptions(document_class=RawBSONDocument, tz_aware=True)
                )

        return RawView()

    async def find_one(
        self, query: dict[str, Any], projection: Any = None, **kwargs: Any
    ) -> dict[str, Any] | None:
        return next((copy.deepcopy(r) for r in self.docs if matches(r, query)), None)

    def find(self, query: dict[str, Any], projection: Any = None, **kwargs: Any) -> Cursor:
        return Cursor([r for r in self.docs if matches(r, query)])

    async def count_documents(self, query: dict[str, Any], limit: int = 0, **kwargs: Any) -> int:
        rows = [r for r in self.docs if matches(r, query)]
        return min(len(rows), limit) if limit else len(rows)

    async def insert_one(self, row: dict[str, Any], **kwargs: Any) -> Any:
        if any(r["_id"] == row["_id"] for r in self.docs):
            raise DuplicateKeyError("synthetic duplicate")
        self.docs.append(normalized(row))
        return None

    async def update_one(
        self, query: dict[str, Any], update: dict[str, Any], upsert: bool = False, **kwargs: Any
    ) -> UpdateResult:
        self.database.writes.append((self.name, copy.deepcopy(query), copy.deepcopy(update)))
        if (
            self.database.before_cas is not None
            and self.database.before_cas[0] == self.name
            and "$expr" in query
        ):
            name, field, value = self.database.before_cas
            self.docs[0][field] = value
            self.database.external_changes.append((name, field, value))
            self.database.before_cas = None
        if self.database.fail_collection == self.name:
            raise RuntimeError("synthetic transaction failure")
        row = next((r for r in self.docs if matches(r, query)), None)
        inserted = row is None and upsert
        if inserted:
            row = {k: v for k, v in query.items() if not k.startswith("$")}
            self.docs.append(row)
        if row is None:
            return UpdateResult({"n": 0, "nModified": 0}, True)
        for op, values in update.items():
            for key, value in values.items():
                target = row
                parts = key.split(".")
                for part in parts[:-1]:
                    target = target.setdefault(part, {})
                field = parts[-1]
                if op == "$set" or op == "$setOnInsert" and field not in target:
                    target[field] = copy.deepcopy(value)
                elif op == "$inc":
                    target[field] = target.get(field, 0) + value
                elif op == "$unset":
                    target.pop(field, None)
                elif op != "$setOnInsert":
                    raise AssertionError("unsupported fake update")
        return UpdateResult(
            {"n": 1, "nModified": 0, "upserted": row["_id"]}
            if inserted
            else {"n": 1, "nModified": 1},
            True,
        )

    async def replace_one(
        self, query: dict[str, Any], row: dict[str, Any], upsert: bool = False, **kwargs: Any
    ) -> UpdateResult:
        if self.database.fail_collection == self.name:
            raise RuntimeError("synthetic transaction failure")
        index = next((i for i, r in enumerate(self.docs) if matches(r, query)), None)
        if index is None:
            if not upsert:
                return UpdateResult({"n": 0, "nModified": 0}, True)
            await self.insert_one(row)
            return UpdateResult({"n": 1, "nModified": 1}, True)
        self.docs[index] = normalized(row)
        return UpdateResult({"n": 1, "nModified": 1}, True)

    async def find_one_and_update(
        self, query: dict[str, Any], update: dict[str, Any], sort: Any = None, **kwargs: Any
    ) -> dict[str, Any] | None:
        rows = self.find(query)
        if sort:
            rows.sort(sort)
        selected = await rows.to_list(length=1)
        if not selected:
            return None
        await self.update_one({"_id": selected[0]["_id"]}, update)
        return await self.find_one({"_id": selected[0]["_id"]})

    async def update_many(
        self, query: dict[str, Any], update: dict[str, Any], **kwargs: Any
    ) -> Any:
        for row in list(self.docs):
            if matches(row, query):
                await self.update_one({"_id": row["_id"]}, update)
        return None

    def aggregate(self, pipeline: list[dict[str, Any]], **kwargs: Any) -> Cursor:
        rows = copy.deepcopy(self.docs)
        for step in pipeline:
            if "$match" in step:
                rows = [r for r in rows if matches(r, step["$match"])]
            elif "$limit" in step:
                rows = rows[: step["$limit"]]
            elif "$lookup" in step:
                lookup = step["$lookup"]
                for row in rows:
                    variables = {k: expression(v, row) for k, v in lookup.get("let", {}).items()}
                    found = copy.deepcopy(self.database[lookup["from"]].docs)
                    for sub in lookup["pipeline"]:
                        if "$match" in sub:
                            q = sub["$match"]
                            found = [
                                r
                                for r in found
                                if (expression(q["$expr"], r, variables) if "$expr" in q else True)
                                and matches(r, {k: v for k, v in q.items() if k != "$expr"})
                            ]
                        elif "$limit" in sub:
                            found = found[: sub["$limit"]]
                        else:
                            raise AssertionError("unsupported fake lookup")
                    row[lookup["as"]] = found
            else:
                raise AssertionError("unsupported fake aggregate")
        return Cursor(rows)


class Session:
    def __init__(self, db: DB) -> None:
        self.db = db
        self.in_transaction = False

    async def __aenter__(self) -> Session:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    def start_transaction(self) -> Any:
        session = self

        class Transaction:
            async def __aenter__(self) -> Any:
                session.in_transaction = True
                self.before = {k: copy.deepcopy(v.docs) for k, v in session.db.collections.items()}
                return self

            async def __aexit__(self, kind: Any, error: Any, trace: Any) -> None:
                if error is not None:
                    for k in set(session.db.collections) | set(self.before):
                        session.db[k].docs = copy.deepcopy(self.before.get(k, []))
                session.in_transaction = False

        return Transaction()

    async def with_transaction(self, callback: Any, **kwargs: Any) -> Any:
        self.db.tx_options.append(kwargs)
        self.in_transaction = True
        before = {k: copy.deepcopy(v.docs) for k, v in self.db.collections.items()}
        try:
            return await callback(self)
        except BaseException:
            for k in set(self.db.collections) | set(before):
                self.db[k].docs = copy.deepcopy(before.get(k, []))
            for name, field, value in self.db.external_changes:
                self.db[name].docs[0][field] = value
            raise
        finally:
            self.in_transaction = False


class DB:
    def __init__(self) -> None:
        self.collections: dict[str, Collection] = {}
        self.client = self
        self.writes: list[Any] = []
        self.tx_options: list[Any] = []
        self.fail_collection: str | None = None
        self.before_cas: tuple[str, str, Any] | None = None
        self.external_changes: list[tuple[str, str, Any]] = []

    def __getitem__(self, name: str) -> Collection:
        if name not in self.collections:
            self.collections[name] = Collection(self, name)
        return self.collections[name]

    def __getattr__(self, name: str) -> Collection:
        return self[name]

    async def start_session(self) -> Session:
        return Session(self)


def seeded() -> tuple[DB, FormulaRecoveryQueue, QuestionScanRecoveryRequest]:
    db = DB()
    request = QuestionScanRecoveryRequest(SELLER, "fixed-pilot-plan", START, END)
    head = SheetsHistoryAcquisition(
        _id=request.key,
        seller_id=SELLER,
        read_model="questions",
        plan_id=request.plan_id,
        scope_id="seller_scan",
        job_id=request.key,
        date_from=START,
        date_to=END,
        generation=1,
        pass_number=1,
        checkpoint_revision=3,
        page_sequence=3,
        next_cursor="synthetic-old-cursor",
        source_total=210,
        discovered_count=150,
        created_at=NOW - timedelta(hours=4),
        updated_at=NOW - timedelta(hours=3),
        observed_from=NOW - timedelta(hours=4),
        observed_until=NOW - timedelta(hours=3),
    )
    job = {
        "_id": request.key,
        "seller_id": SELLER,
        "read_model": "questions",
        "state": "failed",
        "failure_reason": "source_rejected",
        "attempts": 1,
        "history_protocol_version": 1,
        "history_plan_id": request.plan_id,
        "history_acquisition_id": request.key,
        "history_generation": 1,
        "history_pass_number": 1,
        "history_checkpoint_revision": 3,
        "date_from": START,
        "date_to": END,
        "policy_authority": POLICY_VERSION,
        "created_at": head.created_at,
        "updated_at": NOW - timedelta(hours=1),
        "available_at": NOW - timedelta(minutes=30),
        "unknown_original": {"retained": 9},
    }
    plan = {
        "_id": SELLER,
        "seller_id": SELLER,
        "policy_version": POLICY_VERSION,
        "authority": {"kind": "account_link_policy"},
        "eligible": True,
        "sources": list(SOURCES[:-1]),
        "state": "paused",
        "execution_id": EXECUTION,
        "execution_utc_day": NOW.date().isoformat(),
        "execution_until": NOW + timedelta(minutes=20),
        "execution_attempt_limit": 2500,
        "execution_consumed": 81,
        "execution_sent": 79,
        "total_budget": 2000,
        "total_consumed": 57,
        "incremental_policy": {"max_daily_total": 500, "max_daily_source": 300},
        "incremental_day": NOW.date().isoformat(),
        "incremental_consumed": 24,
        "incremental_source_consumed": dict.fromkeys(SOURCES, 0),
        "date_from": START,
        "date_to": END,
        "cutoff": END,
        "budget": {
            s: {"physical_attempts": cap, "consumed": 4 if s == "questions" else 0}
            for s, cap in zip(SOURCES, (800, 150, 250, 300, 500, 0), strict=True)
        },
    }
    db["sheets_history_acquisitions"].docs = [normalized(head.model_dump(by_alias=True))]
    db["sheets_formula_recovery_jobs"].docs = [normalized(job)]
    db["sheets_history_backfill_plans"].docs = [normalized(plan)]
    db["sheets_formula_recovery_admission"].docs = [{"_id": SELLER, "revision": 0}]
    queue = FormulaRecoveryQueue(
        db,
        now=lambda: NOW,
        enabled_models=frozenset({"questions"}),
        allowed_sellers=frozenset({SELLER}),
        policy_authority=POLICY_VERSION,
    )
    return db, queue, request


def pins(db: DB) -> dict[str, Any]:
    return {
        "execution_id": EXECUTION,
        "expected_head_sha256": sha(db["sheets_history_acquisitions"].docs[0]),
        "expected_job_sha256": sha(db["sheets_formula_recovery_jobs"].docs[0]),
        "expected_plan_bson_sha256": sha(db["sheets_history_backfill_plans"].docs[0]),
    }


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("sockets forbidden")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)


@pytest.mark.asyncio
async def test_readmission_archives_full_bytes_and_preserves_plan_attempts_old_receipts() -> None:
    db, queue, request = seeded()
    before = copy.deepcopy({k: v.docs for k, v in db.collections.items()})
    bound = pins(db)
    result = await queue.readmit_question_cursor(request, opt_in=True, **bound)
    assert result["state"] == "pending"
    assert db["sheets_history_backfill_plans"].docs == [
        {**before["sheets_history_backfill_plans"][0], "history_readmission_revision": 1}
    ]
    archive = db["sheets_history_checkpoint_versions"].docs[0]
    assert archive["head_bson"] == BSON.encode(before["sheets_history_acquisitions"][0])
    assert archive["job_bson"] == BSON.encode(before["sheets_formula_recovery_jobs"][0])
    head = db["sheets_history_acquisitions"].docs[0]
    job = db["sheets_formula_recovery_jobs"].docs[0]
    assert (
        head["pass_number"] == 2 and head["checkpoint_revision"] == 4 and head["page_sequence"] == 3
    )
    assert head["next_cursor"] is None and head["discovered_count"] == 0
    assert head["generation"] == 1 and head["date_from"] == START and head["date_to"] == END
    assert job["attempts"] == 1 and job["unknown_original"] == {"retained": 9}
    assert db.tx_options[-1]["read_concern"].level == "snapshot"
    assert db.tx_options[-1]["write_concern"].document == {"w": "majority"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "guard",
    [
        "no_optin",
        "head_pin",
        "job_pin",
        "plan_pin",
        "expired",
        "day",
        "live_lease",
        "source_scope",
        "seller_scope",
        "quota",
        "drift_limit",
        "attempts_limit",
        "revision_bool",
        "revision_negative",
        "revision_overflow",
    ],
)
async def test_invalid_readmission_has_no_partial_writes(guard: str) -> None:
    db, queue, request = seeded()
    if guard == "expired":
        db["sheets_history_backfill_plans"].docs[0]["execution_until"] = datetime(
            2026, 10, 6, 8, 17, 23, tzinfo=UTC
        )
    elif guard == "day":
        db["sheets_history_backfill_plans"].docs[0]["execution_utc_day"] = "2026-10-05"
    elif guard == "live_lease":
        db["sheets_formula_recovery_jobs"].docs[0]["lease_until"] = NOW + timedelta(seconds=1)
    elif guard == "source_scope":
        queue.enabled_models = frozenset({"orders"})
    elif guard == "seller_scope":
        queue.allowed_sellers = None
    elif guard == "quota":
        db["sheets_history_backfill_plans"].docs[0]["budget"]["questions"]["consumed"] = 150
    elif guard == "drift_limit":
        db["sheets_history_acquisitions"].docs[0]["drift_restarts"] = 3
    elif guard == "attempts_limit":
        db["sheets_formula_recovery_jobs"].docs[0]["attempts"] = 3
    if guard.startswith("revision_"):
        db["sheets_history_backfill_plans"].docs[0]["history_readmission_revision"] = {
            "revision_bool": True,
            "revision_negative": -1,
            "revision_overflow": 2**63 - 1,
        }[guard]
    bound = pins(db)
    if guard.endswith("_pin"):
        bound[
            "expected_plan_bson_sha256"
            if guard == "plan_pin"
            else "expected_" + guard.replace("_pin", "") + "_sha256"
        ] = "0" * 64
    before = copy.deepcopy({k: v.docs for k, v in db.collections.items()})
    with pytest.raises(HistoryConflictError):
        await queue.readmit_question_cursor(request, opt_in=guard != "no_optin", **bound)
    assert all(v.docs == before.get(k, []) for k, v in db.collections.items())


@pytest.mark.asyncio
async def test_transaction_failure_rolls_back_archive_and_both_documents() -> None:
    db, queue, request = seeded()
    before = copy.deepcopy({k: v.docs for k, v in db.collections.items()})
    bound = pins(db)
    db.fail_collection = "sheets_formula_recovery_jobs"
    with pytest.raises(RuntimeError):
        await queue.readmit_question_cursor(request, opt_in=True, **bound)
    assert all(v.docs == before.get(k, []) for k, v in db.collections.items())


@pytest.mark.asyncio
async def test_archive_duplicate_is_append_only_and_conflict_rejects() -> None:
    db, queue, request = seeded()
    m = importlib.import_module("zeler_sheets.history_checkpoint_versions")
    bound = pins(db)
    head = db["sheets_history_acquisitions"].docs[0]
    job = db["sheets_formula_recovery_jobs"].docs[0]
    async with await db.start_session() as session:

        async def insert(s: Any) -> Any:
            return await m.archive_question_checkpoint(
                db,
                head=RawBSONDocument(
                    BSON.encode(head), CodecOptions(document_class=RawBSONDocument, tz_aware=True)
                ),
                job=RawBSONDocument(
                    BSON.encode(job), CodecOptions(document_class=RawBSONDocument, tz_aware=True)
                ),
                execution_id=EXECUTION,
                expected_head_sha256=bound["expected_head_sha256"],
                expected_job_sha256=bound["expected_job_sha256"],
                now=NOW,
                session=s,
            )

        first = await session.with_transaction(insert)
        before = copy.deepcopy(db["sheets_history_checkpoint_versions"].docs)
        await session.with_transaction(insert)
        assert db["sheets_history_checkpoint_versions"].docs == before
        db["sheets_history_checkpoint_versions"].docs[0]["job_sha256"] = "0" * 64
        with pytest.raises(HistoryConflictError):
            await session.with_transaction(insert)
        assert first.id == before[0]["_id"]


@pytest.mark.asyncio
async def test_default_enqueue_still_never_reopens_terminal_question_scan() -> None:
    db, queue, request = seeded()
    before = copy.deepcopy(db["sheets_formula_recovery_jobs"].docs)
    await queue.enqueue(request, reopen_terminal=True)
    assert db["sheets_formula_recovery_jobs"].docs == before


@pytest.mark.asyncio
async def test_archive_rejects_reconstructed_dict_and_preserves_wire_extras() -> None:
    from bson.int64 import Int64

    db, queue, request = seeded()
    m = importlib.import_module("zeler_sheets.history_checkpoint_versions")
    head = db["sheets_history_acquisitions"].docs[0]
    head["wire_extra"] = {"long": Int64(4), "double": 4.0}
    job = db["sheets_formula_recovery_jobs"].docs[0]
    head_raw = RawBSONDocument(
        BSON.encode(head), CodecOptions(document_class=RawBSONDocument, tz_aware=True)
    )
    job_raw = RawBSONDocument(
        BSON.encode(job), CodecOptions(document_class=RawBSONDocument, tz_aware=True)
    )
    async with await db.start_session() as session:

        async def call(s: Any, raw: bool = True) -> Any:
            return await m.archive_question_checkpoint(
                db,
                head=head_raw if raw else head,
                job=job_raw,
                execution_id=EXECUTION,
                expected_head_sha256=hashlib.sha256(head_raw.raw).hexdigest(),
                expected_job_sha256=hashlib.sha256(job_raw.raw).hexdigest(),
                now=NOW,
                session=s,
            )

        result = await session.with_transaction(call)
        assert result.head_bson == head_raw.raw and result.job_bson == job_raw.raw

        async def reconstructed(s: Any) -> Any:
            return await call(s, False)

        with pytest.raises(HistoryConflictError):
            await session.with_transaction(reconstructed)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "collection,field,value",
    [
        ("sheets_history_backfill_plans", "execution_consumed", 82),
        ("sheets_formula_recovery_jobs", "attempts", 2),
    ],
)
async def test_concurrent_full_snapshot_change_aborts_all_owned_writes(
    collection: str, field: str, value: Any
) -> None:
    db, queue, request = seeded()
    bound = pins(db)
    before = copy.deepcopy({k: v.docs for k, v in db.collections.items()})
    db.before_cas = (collection, field, value)
    with pytest.raises(HistoryConflictError):
        await queue.readmit_question_cursor(request, opt_in=True, **bound)
    assert db["sheets_history_checkpoint_versions"].docs == []
    for name in (
        "sheets_history_acquisitions",
        "sheets_formula_recovery_jobs",
        "sheets_history_backfill_plans",
    ):
        expected = copy.deepcopy(before[name])
        if name == collection:
            expected[0][field] = value
        assert db[name].docs == expected
