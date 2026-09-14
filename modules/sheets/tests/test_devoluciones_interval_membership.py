from __future__ import annotations

import json
from collections.abc import AsyncIterator
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
import pytest_asyncio
from infra.operations import zelerdata_read_model_reconcile as canonical
from motor.motor_asyncio import AsyncIOMotorClient

from zeler_sheets.claim_projection import build_claim_projection
from zeler_sheets.devoluciones_reconciliation import collect_devoluciones_snapshot

START = datetime(2025, 5, 14, tzinfo=UTC)
END = START + timedelta(days=1)


class BoundarySource:
    def __init__(self, boundary: str = "2025-05-13T19:04:43-04:00") -> None:
        returns = json.loads(
            (Path(__file__).parent / "fixtures/devoluciones/return_v2.json").read_text()
        )
        self.claims: dict[str, dict[str, Any]] = {}
        self.returns: dict[str, dict[str, Any]] = {}
        self.orders: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, str]] = []
        self.search_params: list[dict[str, Any]] = []
        for index, created in enumerate(
            [boundary, "2025-05-14T00:00:00Z", "2025-05-14T12:00:00Z", "2025-05-14T23:59:59.999Z"]
        ):
            identity = str(100 + index)
            order_id = str(200 + index)
            self.claims[identity] = {
                "id": identity,
                "claim_version": 3,
                "last_updated": "2025-05-16T12:00:00Z",
                "date_created": created,
                "order_id": order_id,
                "item_id": "MLA1",
                "status": "closed",
                "stage": "claim",
                "type": "returns",
                "players": [{"user_id": 82453304, "role": "respondent", "type": "seller"}],
                "related_entities": [{"type": "return", "id": "RETURN-" + identity}],
            }
            detail = deepcopy(returns)
            detail["id"] = "RETURN-" + identity
            detail["orders"][0].update(order_id=order_id, item_id="MLA1")
            self.returns[identity] = detail
            self.orders[order_id] = {
                "id": order_id,
                "seller": {"id": 82453304},
                "items": [
                    {"item": {"id": "MLA1", "seller_sku": "SKU", "title": "Title"}, "quantity": 5}
                ],
            }
        self.inventory = [
            {key: claim[key] for key in ("id", "last_updated", "date_created", "type")}
            for claim in self.claims.values()
        ]

    async def search_claims(self, *, seller_id: str, params: dict[str, Any]) -> dict[str, Any]:
        self.search_params.append(dict(params))
        return {
            "data": deepcopy(self.inventory),
            "paging": {"offset": 0, "limit": 100, "total": len(self.inventory)},
        }

    async def get_claim(self, *, seller_id: str, claim_id: str) -> dict[str, Any]:
        self.calls.append(("claim", claim_id))
        return deepcopy(self.claims[claim_id])

    async def get_returns(self, *, seller_id: str, claim_id: str) -> dict[str, Any]:
        self.calls.append(("returns", claim_id))
        return deepcopy(self.returns[claim_id])

    async def get_order(self, *, seller_id: str, order_id: str) -> dict[str, Any]:
        self.calls.append(("order", order_id))
        return deepcopy(self.orders[order_id])


@pytest.mark.asyncio
async def test_search_extra_before_utc_start_retains_inventory_and_proves_three_claims() -> None:
    source = BoundarySource()
    snapshot = await collect_devoluciones_snapshot(
        source=source, seller_id="82453304", start=START, end=END
    )
    assert snapshot.expected_claim_ids == frozenset({"101", "102", "103"})
    assert {entry.claim_id for entry in snapshot.inventory.entries} == {"100", "101", "102", "103"}
    assert snapshot.counters["inventory_candidates"] == 4
    assert snapshot.counters["productive_claims"] == 3
    assert snapshot.counters["excluded_outside_requested_range"] == 1
    assert [(proof.claim_id, proof.reason.value) for proof in snapshot.exclusions] == [
        ("100", "outside_requested_range")
    ]
    assert ("claim", "100") in source.calls
    assert ("returns", "100") not in source.calls
    assert len(source.search_params) == 2
    assert source.search_params[0] == source.search_params[1]
    assert "after:2025-05-13T23:59:59.999+0000" in str(source.search_params[0]["range"])


@pytest.mark.parametrize(
    ("boundary", "included"),
    [
        ("2025-05-13T20:00:00-04:00", True),
        ("2025-05-14T20:00:00-04:00", False),
        ("2025-05-14T23:59:59.999Z", True),
    ],
)
@pytest.mark.asyncio
async def test_canonical_membership_uses_exact_half_open_utc_boundary(
    boundary: str, included: bool
) -> None:
    snapshot = await collect_devoluciones_snapshot(
        source=BoundarySource(boundary), seller_id="82453304", start=START, end=END
    )
    assert ("100" in snapshot.expected_claim_ids) is included
    assert len(snapshot.projections) == (4 if included else 3)
    assert snapshot.counters.get("excluded_outside_requested_range", 0) == (0 if included else 1)
    assert len(snapshot.inventory.entries) == 4


@pytest.mark.parametrize(
    "field,value",
    [
        ("date_created", None),
        ("date_created", "not-a-date"),
        ("date_created", "2025-05-13T23:04:43"),
        ("date_created", "2025-05-13T19:05:43-04:00"),
        ("id", "different-claim"),
        ("players", []),
    ],
)
@pytest.mark.asyncio
async def test_unproven_outside_candidate_fails_closed(field: str, value: Any) -> None:
    from zeler_sheets.claim_projection import ClaimProjectionError
    from zeler_sheets.devoluciones_reconciliation import ClaimInventoryError

    source = BoundarySource()
    source.claims["100"][field] = value
    with pytest.raises((ClaimInventoryError, ClaimProjectionError)):
        await collect_devoluciones_snapshot(
            source=source, seller_id="82453304", start=START, end=END
        )
    assert ("claim", "100") in source.calls
    assert not any(kind in {"returns", "order"} for kind, _ in source.calls)


@pytest.mark.asyncio
async def test_excluded_identity_and_date_remain_in_source_fingerprint() -> None:
    first = await collect_devoluciones_snapshot(
        source=BoundarySource(), seller_id="82453304", start=START, end=END
    )
    source = BoundarySource()
    source.claims["999"] = source.claims.pop("100") | {"id": "999"}
    source.inventory[0]["id"] = "999"
    changed = await collect_devoluciones_snapshot(
        source=source, seller_id="82453304", start=START, end=END
    )
    assert (
        first.expected_claim_ids == changed.expected_claim_ids == frozenset({"101", "102", "103"})
    )
    assert first.read_model_fingerprint == changed.read_model_fingerprint
    assert first.inventory.fingerprint != changed.inventory.fingerprint
    assert first.exclusion_fingerprint != changed.exclusion_fingerprint
    assert first.source_fingerprint != changed.source_fingerprint


@pytest.mark.asyncio
async def test_revalidation_rejects_outside_candidate_entering_window() -> None:
    import time

    from zeler_platform_core.devoluciones_readiness import DevolucionesOperationContext
    from zeler_sheets.devoluciones_reconciliation import (
        DevolucionesReadModelVerificationError,
        SourceCallRecorder,
        revalidate_devoluciones_snapshot,
    )

    snapshot = await collect_devoluciones_snapshot(
        source=BoundarySource(), seller_id="82453304", start=START, end=END
    )
    operation = DevolucionesOperationContext(
        seller_id="82453304",
        scope="devoluciones",
        operation_id="test",
        attempt_token=uuid4().hex,
        fence=1,
        owns_lease=True,
        source_fingerprint=snapshot.source_fingerprint,
    )

    async def heartbeat() -> None:
        return None

    with pytest.raises(DevolucionesReadModelVerificationError, match="changed"):
        await revalidate_devoluciones_snapshot(
            source=BoundarySource("2025-05-14T00:00:00Z"),
            snapshot=snapshot,
            operation=operation,
            absolute_deadline=time.monotonic() + 20,
            recorder=SourceCallRecorder(max_total=104),
            heartbeat=heartbeat,
        )


@pytest.mark.asyncio
async def test_may14_real_mongo_readback_keeps_outside_claim_and_reports_membership(
    default_mongo_uri: str,
) -> None:
    from urllib.parse import urlsplit
    from uuid import uuid4

    from infra.operations import zelerdata_read_model_reconcile as canonical
    from motor.motor_asyncio import AsyncIOMotorClient

    from zeler_platform_core.devoluciones_readiness import DevolucionesOperationContext
    from zeler_sheets.claim_projection import build_claim_projection

    parsed = urlsplit(default_mongo_uri)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        pytest.skip("requires an explicitly selected loopback test Mongo target")
    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(
        default_mongo_uri, serverSelectionTimeoutMS=3000
    )
    db = client["test_return_boundary_" + uuid4().hex]
    try:
        hello = await client.admin.command("hello")
        assert hello.get("isWritablePrimary") is True
        source = BoundarySource()
        rows = [
            build_claim_projection(
                seller_id="82453304",
                claim=claim,
                returns=source.returns[identity],
                order=source.orders[claim["order_id"]],
            )
            for identity, claim in source.claims.items()
        ]
        await db.claims.insert_many(rows)
        args = canonical.build_arg_parser().parse_args(
            [
                "--seller-id",
                "82453304",
                "--date-from",
                "2025-05-14",
                "--date-to",
                "2025-05-14",
                "--read-model",
                "devoluciones",
                "--dry-run",
                "--confirm-approved-runtime",
            ]
        )
        request = canonical.build_reconciliation_request(args)
        summary = await canonical.run_focused_devoluciones_reconciliation(
            db=db, request=request, source=source
        )
        evidence = summary.to_focused_evidence(stage="dry_run")
        assert {
            key: evidence["counters"][key]
            for key in ("expected", "persisted", "complete", "missing")
        } == {"expected": 3, "persisted": 3, "complete": 3, "missing": 0}
        assert evidence["counters"]["excluded_outside_requested_range"] == 1
        assert await db.claims.count_documents({}) == 4
        assert await db.claims.count_documents({"_id": "100", "date_created": {"$lt": START}}) == 1
        snapshot = await collect_devoluciones_snapshot(
            source=BoundarySource(), seller_id="82453304", start=START, end=END
        )
        operation = DevolucionesOperationContext(
            seller_id="82453304",
            scope="devoluciones",
            operation_id="readback-only",
            attempt_token=uuid4().hex,
            fence=0,
            owns_lease=False,
            source_fingerprint=snapshot.source_fingerprint,
        )
        expected_ids, fingerprint = canonical._validated_devoluciones_marker_inputs(
            expected=canonical._focused_expected_counts(snapshot),
            aggregate=summary.aggregates[0],
            operation=operation,
        )
        assert expected_ids == frozenset({"101", "102", "103"})
        assert fingerprint == snapshot.read_model_fingerprint
        assert await db.sheets_read_model_freshness.count_documents({}) == 0
        assert await db.sheets_devoluciones_operations.count_documents({}) == 0
    finally:
        await client.drop_database(db.name)
        client.close()


@pytest_asyncio.fixture
async def claims_db(default_mongo_uri: str) -> AsyncIterator[Any]:
    if urlsplit(default_mongo_uri).hostname not in {"127.0.0.1", "localhost"}:
        pytest.skip("requires an explicitly selected loopback test Mongo target")
    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(
        default_mongo_uri, serverSelectionTimeoutMS=3000
    )
    db = client["test_chunk_readback_" + uuid4().hex]
    try:
        hello = await client.admin.command("hello")
        assert hello.get("isWritablePrimary") is True
        yield db
    finally:
        await client.drop_database(db.name)
        client.close()


class MovingClaimSource(BoundarySource):
    async def search_claims(self, *, seller_id: str, params: dict[str, Any]) -> dict[str, Any]:
        created = (
            datetime.fromisoformat(str(params["date_created"])) + timedelta(hours=1)
        ).isoformat()
        for claim, entry in zip(self.claims.values(), self.inventory, strict=True):
            claim["date_created"] = entry["date_created"] = created
        return await super().search_claims(seller_id=seller_id, params=params)


@pytest.mark.parametrize("mode", ["missing", "complete", "unavailable", "overlap"])
@pytest.mark.asyncio
async def test_chunked_return_counts_are_measured_readback(
    claims_db: Any, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    source = MovingClaimSource() if mode == "overlap" else BoundarySource()
    documents = [
        build_claim_projection(
            seller_id="82453304",
            claim=claim,
            returns=source.returns[identity],
            order=source.orders[claim["order_id"]],
        )
        for identity, claim in source.claims.items()
    ]
    await claims_db.claims.insert_many(documents[1:] if mode == "missing" else documents)
    if mode == "unavailable":
        original = canonical.collect_reconciliation_counts

        async def unavailable(**kwargs: Any) -> canonical.ReconciliationSummary:
            summary = await original(**kwargs)
            if kwargs["request"].date_range.date_from == "2025-05-11":
                aggregate = replace(
                    summary.aggregates[0],
                    persisted_count=None,
                    complete_count=None,
                    missing_count=None,
                    error_count=1,
                    issues=(
                        canonical.ReadModelIssue(
                            read_model="claims",
                            code="query_anomaly",
                            message="local readback unavailable",
                        ),
                    ),
                )
                return replace(summary, aggregates=(aggregate,))
            return summary

        monkeypatch.setattr(canonical, "collect_reconciliation_counts", unavailable)
    args = canonical.build_arg_parser().parse_args(
        [
            "--seller-id",
            "82453304",
            "--date-from",
            "2025-05-01",
            "--date-to",
            "2025-05-28",
            "--read-model",
            "devoluciones",
            "--dry-run",
            "--confirm-approved-runtime",
        ]
    )
    clock = [0.0]

    async def sleep(seconds: float) -> None:
        clock[0] += seconds

    summary = await canonical.run_focused_devoluciones_reconciliation(
        db=claims_db,
        request=canonical.build_reconciliation_request(args),
        source=source,
        monotonic=lambda: clock[0],
        sleep=sleep,
    )
    evidence = summary.to_focused_evidence(stage="dry_run")
    if mode == "overlap":
        assert summary.mandatory_source_gate is not None
        assert summary.mandatory_source_gate.authoritative is False
        assert evidence["status_class"] != "success"
    elif mode == "unavailable":
        assert summary.aggregates[0].persisted_count is None
        assert summary.aggregates[0].complete_count is None
        assert summary.aggregates[0].missing_count is None
        assert evidence["status_class"] == "query_anomaly"
    else:
        count = 3 if mode == "missing" else 4
        assert {
            key: evidence["counters"][key]
            for key in ("expected", "persisted", "complete", "missing")
        } == {"expected": 4, "persisted": count, "complete": count, "missing": 4 - count}
        assert evidence["counters"]["excluded_outside_requested_range"] == 8
        assert summary.runtime_evidence is not None
        assert (
            sum(snapshot["T"] for snapshot in summary.runtime_evidence.snapshot_calls)
            == evidence["counters"]["T"]
        )
    assert await claims_db.sheets_read_model_freshness.count_documents({}) == 0
    assert await claims_db.sheets_devoluciones_operations.count_documents({}) == 0


@pytest.mark.asyncio
async def test_chunk_fingerprints_preserve_independent_evidence_and_utc_scopes(
    claims_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zeler_sheets.devoluciones_reconciliation as acquisition

    original = acquisition.collect_devoluciones_snapshot
    source_hash = "source-proof"
    read_hash = "read-proof"

    async def snapshot(**kwargs: Any) -> acquisition.CollectedDevolucionesSnapshot:
        result = await original(**kwargs)
        return replace(result, source_fingerprint=source_hash, read_model_fingerprint=read_hash)

    monkeypatch.setattr(acquisition, "collect_devoluciones_snapshot", snapshot)

    async def run(start: str = "2025-05-01") -> canonical.FocusedRuntimeEvidence:
        args = canonical.build_arg_parser().parse_args(
            [
                "--seller-id",
                "82453304",
                "--date-from",
                start,
                "--date-to",
                "2025-05-28",
                "--read-model",
                "devoluciones",
                "--dry-run",
                "--confirm-approved-runtime",
            ]
        )
        clock = [0.0]

        async def sleep(seconds: float) -> None:
            clock[0] += seconds

        result = await canonical.run_focused_devoluciones_reconciliation(
            db=claims_db,
            request=canonical.build_reconciliation_request(args),
            source=BoundarySource(),
            monotonic=lambda: clock[0],
            sleep=sleep,
        )
        assert result.runtime_evidence is not None
        return result.runtime_evidence

    first = await run()
    read_hash = "different-read-proof"
    changed_read = await run()
    assert first.source_fingerprint == changed_read.source_fingerprint
    assert first.read_model_fingerprint != changed_read.read_model_fingerprint
    source_hash = "different-source-proof"
    changed_source = await run()
    assert changed_read.source_fingerprint != changed_source.source_fingerprint
    assert changed_read.read_model_fingerprint == changed_source.read_model_fingerprint
    changed_scope = await run("2025-05-02")
    assert changed_source.source_fingerprint != changed_scope.source_fingerprint
    assert changed_source.read_model_fingerprint != changed_scope.read_model_fingerprint
