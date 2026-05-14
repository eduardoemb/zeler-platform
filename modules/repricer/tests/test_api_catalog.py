from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

NOW = datetime(2026, 5, 13, 19, 0, tzinfo=UTC)


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self._documents = documents

    def sort(self, _sort_spec: list[tuple[str, int]]) -> FakeCursor:
        return self

    def skip(self, count: int) -> FakeCursor:
        self._documents = self._documents[count:]
        return self

    def limit(self, count: int) -> FakeCursor:
        self._documents = self._documents[:count]
        return self

    async def to_list(self, length: int) -> list[dict[str, Any]]:
        return self._documents[:length]


class FakeUpdateResult:
    def __init__(self, matched_count: int) -> None:
        self.matched_count = matched_count


class FakeCollection:
    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        return next(
            (
                document
                for document in self.documents
                if all(document.get(key) == value for key, value in filter_spec.items())
            ),
            None,
        )

    def find(self, filter_spec: dict[str, Any]) -> FakeCursor:
        filtered = [
            document
            for document in self.documents
            if all(document.get(key) == value for key, value in filter_spec.items())
        ]
        return FakeCursor(filtered)

    async def insert_one(self, document: dict[str, Any]) -> None:
        self.documents.append(document)

    async def update_one(
        self, filter_spec: dict[str, Any], update: dict[str, Any]
    ) -> FakeUpdateResult:
        for document in self.documents:
            if all(document.get(key) == value for key, value in filter_spec.items()):
                document.update(update["$set"])
                return FakeUpdateResult(1)
        return FakeUpdateResult(0)

    async def replace_one(
        self, filter_spec: dict[str, Any], document: dict[str, Any], *, upsert: bool
    ) -> None:
        self.documents = [
            existing
            for existing in self.documents
            if not all(existing.get(key) == value for key, value in filter_spec.items())
        ]
        if upsert or self.documents:
            self.documents.append(document)


class FakeDb:
    def __init__(self) -> None:
        self.repricer_catalog_rules = FakeCollection()
        self.repricer_limits = FakeCollection()
        self.repricer_allies = FakeCollection()
        self.repricer_bulk_jobs = FakeCollection()
        self.repricer_bulk_rows = FakeCollection()
        self.repricer_reports = FakeCollection()
        self.repricer_monitoring_snapshots = FakeCollection()
        self.repricer_rules = FakeCollection()
        self.repricer_history = FakeCollection()

    def __getitem__(self, name: str) -> FakeCollection:
        if name == "repricer_catalog_rules":
            return self.repricer_catalog_rules
        if name == "repricer_limits":
            return self.repricer_limits
        if name == "repricer_allies":
            return self.repricer_allies
        if name == "repricer_bulk_jobs":
            return self.repricer_bulk_jobs
        if name == "repricer_bulk_rows":
            return self.repricer_bulk_rows
        if name == "repricer_reports":
            return self.repricer_reports
        if name == "repricer_monitoring_snapshots":
            return self.repricer_monitoring_snapshots
        if name == "repricer_rules":
            return self.repricer_rules
        if name == "repricer_history":
            return self.repricer_history
        raise AssertionError(name)


@pytest.mark.asyncio
async def test_get_catalog_rules_filters_by_seller_account_status_and_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db = _app(monkeypatch)
    db.repricer_catalog_rules.documents.extend(
        [
            _catalog_rule("catalog-1", seller_id="123456789", account_id="acc-1", sku="SKU-ABC"),
            _catalog_rule("catalog-2", seller_id="123456789", account_id="acc-1", sku="OTHER"),
            _catalog_rule("catalog-3", seller_id="123456789", account_id="acc-2", sku="SKU-ABC"),
            _catalog_rule("catalog-4", seller_id="987654321", account_id="acc-1", sku="SKU-ABC"),
            _catalog_rule(
                "catalog-5",
                seller_id="123456789",
                account_id="acc-1",
                sku="SKU-ABC",
                active=False,
            ),
        ]
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/repricer/catalog/rules?seller_id=123456789&account_id=acc-1&status=active&query=sku-abc",
            headers={"Authorization": "Bearer valid"},
        )

    assert response.status_code == 200
    assert [rule["_id"] for rule in response.json()] == ["catalog-1"]


@pytest.mark.asyncio
async def test_post_catalog_rule_uses_claim_seller_and_stamps_operator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/repricer/catalog/rules",
            headers={"Authorization": "Bearer valid"},
            json={
                "seller_id": "123456789",
                "account_id": "acc-1",
                "item_id": "MLA123",
                "title": "Catalog Item",
                "sku": "SKU-123",
                "strategy": "competitive",
                "min_price": "100.00",
                "max_price": "120.00",
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["_id"] == "catalog-123456789-acc-1-MLA123"
    assert body["seller_id"] == "123456789"
    assert body["created_by"] == "operator-1"
    assert body["execution_state"] == {
        "last_outcome": None,
        "last_event_at": None,
        "last_applied_price": None,
        "last_competitor": None,
        "predominant_variant_id": None,
    }
    assert db.repricer_catalog_rules.documents == [body]


@pytest.mark.asyncio
async def test_post_catalog_rule_rejects_cross_seller_without_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/repricer/catalog/rules",
            headers={"Authorization": "Bearer valid"},
            json={
                "seller_id": "987654321",
                "account_id": "acc-1",
                "item_id": "MLA123",
                "strategy": "competitive",
                "min_price": "100.00",
                "max_price": "120.00",
            },
        )

    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"
    assert db.repricer_catalog_rules.documents == []


@pytest.mark.asyncio
async def test_patch_catalog_rule_updates_owned_rule_and_denies_cross_seller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db = _app(monkeypatch)
    db.repricer_catalog_rules.documents.append(
        _catalog_rule("catalog-1", seller_id="123456789", account_id="acc-1")
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        updated = await client.patch(
            "/repricer/catalog/rules/catalog-1",
            headers={"Authorization": "Bearer valid"},
            json={"seller_id": "123456789", "account_id": "acc-1", "active": False},
        )
        denied = await client.patch(
            "/repricer/catalog/rules/catalog-1",
            headers={"Authorization": "Bearer valid"},
            json={"seller_id": "987654321", "account_id": "acc-1", "active": True},
        )

    assert updated.status_code == 200
    assert updated.json()["active"] is False
    assert db.repricer_catalog_rules.documents[0]["active"] is False
    assert denied.status_code == 403
    assert db.repricer_catalog_rules.documents[0]["active"] is False


@pytest.mark.asyncio
async def test_patch_catalog_rules_collection_route_accepts_rule_id_in_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db = _app(monkeypatch)
    db.repricer_catalog_rules.documents.append(
        _catalog_rule("catalog-1", seller_id="123456789", account_id="acc-1")
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.patch(
            "/repricer/catalog/rules",
            headers={"Authorization": "Bearer valid"},
            json={
                "_id": "catalog-1",
                "seller_id": "123456789",
                "account_id": "acc-1",
                "min_price": "101.00",
            },
        )

    assert response.status_code == 200
    assert response.json()["_id"] == "catalog-1"
    assert response.json()["min_price"] == "101.00"
    assert db.repricer_catalog_rules.documents[0]["min_price"] == "101.00"


@pytest.mark.asyncio
async def test_post_catalog_rules_refresh_is_seller_and_account_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db = _app(monkeypatch)
    db.repricer_catalog_rules.documents.extend(
        [
            _catalog_rule("catalog-1", seller_id="123456789", account_id="acc-1"),
            _catalog_rule("catalog-2", seller_id="123456789", account_id="acc-2"),
            _catalog_rule("catalog-3", seller_id="987654321", account_id="acc-1"),
        ]
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/repricer/catalog/rules/refresh",
            headers={"Authorization": "Bearer valid"},
            json={"seller_id": "123456789", "account_id": "acc-1"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "refreshed", "matched_rules": 1}


@pytest.mark.asyncio
async def test_put_and_get_limits_are_seller_account_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        put_response = await client.put(
            "/repricer/limits?seller_id=123456789&account_id=acc-1",
            headers={"Authorization": "Bearer valid"},
            json={
                "enabled": True,
                "min_price_limit": "100.00",
                "max_price_limit": "150.00",
                "undercut_delta": "2.00",
                "pause_competition": False,
                "escalate_to_manual_review": True,
            },
        )
        get_response = await client.get(
            "/repricer/limits?seller_id=123456789&account_id=acc-1",
            headers={"Authorization": "Bearer valid"},
        )

    assert put_response.status_code == 200
    assert put_response.json()["_id"] == "limits-123456789-acc-1"
    assert put_response.json()["escalate_to_manual_review"] is True
    assert get_response.status_code == 200
    assert get_response.json() == put_response.json()
    assert db.repricer_limits.documents == [put_response.json()]


@pytest.mark.asyncio
async def test_put_limits_rejects_cross_seller_without_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(
            "/repricer/limits?seller_id=987654321&account_id=acc-1",
            headers={"Authorization": "Bearer valid"},
            json={
                "enabled": True,
                "min_price_limit": "100.00",
                "max_price_limit": "150.00",
                "undercut_delta": "2.00",
                "pause_competition": False,
                "escalate_to_manual_review": False,
            },
        )

    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"
    assert db.repricer_limits.documents == []


@pytest.mark.asyncio
async def test_put_and_get_allies_are_seller_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        put_response = await client.put(
            "/repricer/allies?seller_id=123456789",
            headers={"Authorization": "Bearer valid"},
            json={"allies": [{"account_id": "ally-1", "nickname": "ALLY SHOP"}]},
        )
        get_response = await client.get(
            "/repricer/allies?seller_id=123456789",
            headers={"Authorization": "Bearer valid"},
        )

    assert put_response.status_code == 200
    assert put_response.json()["_id"] == "allies-123456789"
    assert put_response.json()["allies"] == [
        {"account_id": "ally-1", "nickname": "ALLY SHOP", "item_id": None}
    ]
    assert get_response.status_code == 200
    assert get_response.json() == put_response.json()
    assert db.repricer_allies.documents == [put_response.json()]


@pytest.mark.asyncio
async def test_put_allies_rejects_cross_seller_without_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(
            "/repricer/allies?seller_id=987654321",
            headers={"Authorization": "Bearer valid"},
            json={"allies": [{"account_id": "ally-1", "nickname": "ALLY SHOP"}]},
        )

    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"
    assert db.repricer_allies.documents == []


@pytest.mark.asyncio
async def test_bulk_validate_persists_job_and_row_level_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db = _app(monkeypatch)
    db.repricer_limits.documents.append(
        _limits_doc(
            seller_id="123456789",
            account_id="acc-1",
            min_price="90.00",
            max_price="130.00",
        )
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/repricer/bulk-jobs/validate",
            headers={"Authorization": "Bearer valid"},
            json={
                "seller_id": "123456789",
                "account_id": "acc-1",
                "source_filename": "catalog-upload.csv",
                "content": (
                    "item_id,title,sku,strategy,min_price,max_price,active\n"
                    "MLA1,Valid Item,SKU-1,competitive,100.00,120.00,true\n"
                    "MLA2,Below Guard,SKU-2,competitive,80.00,100.00,true\n"
                ),
            },
        )

    body = response.json()
    assert response.status_code == 201
    assert body["job"]["status"] == "validated"
    assert body["job"]["total_rows"] == 2
    assert body["job"]["success_rows"] == 1
    assert body["job"]["failed_rows"] == 1
    assert [row["status"] for row in body["rows"]] == ["validated", "failed"]
    assert body["rows"][1]["error"] == {
        "code": "min_price_below_limit",
        "message": "Row 3 min_price is below the configured limit",
        "retryable": False,
    }
    assert db.repricer_bulk_jobs.documents == [body["job"]]
    assert len(db.repricer_bulk_rows.documents) == 2


@pytest.mark.asyncio
async def test_bulk_process_status_and_errors_are_seller_scoped_and_retry_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        validation = await client.post(
            "/repricer/bulk-jobs/validate",
            headers={"Authorization": "Bearer valid"},
            json={
                "seller_id": "123456789",
                "account_id": "acc-1",
                "source_filename": "catalog-upload.csv",
                "content": (
                    "item_id,title,sku,strategy,min_price,max_price,active\n"
                    "MLA1,Valid Item,SKU-1,competitive,100.00,120.00,true\n"
                    "MLA2,Bad Bounds,SKU-2,competitive,150.00,120.00,true\n"
                ),
            },
        )
        job_id = validation.json()["job"]["_id"]
        processed = await client.post(
            "/repricer/bulk-jobs",
            headers={"Authorization": "Bearer valid"},
            json={"seller_id": "123456789", "job_id": job_id},
        )
        retried = await client.post(
            "/repricer/bulk-jobs",
            headers={"Authorization": "Bearer valid"},
            json={"seller_id": "123456789", "job_id": job_id},
        )
        status = await client.get(
            f"/repricer/bulk-jobs/{job_id}?seller_id=123456789",
            headers={"Authorization": "Bearer valid"},
        )
        errors = await client.get(
            f"/repricer/bulk-jobs/{job_id}/errors?seller_id=123456789",
            headers={"Authorization": "Bearer valid"},
        )
        denied = await client.get(
            f"/repricer/bulk-jobs/{job_id}?seller_id=987654321",
            headers={"Authorization": "Bearer valid"},
        )

    assert processed.status_code == 200
    assert processed.json()["status"] == "completed_with_errors"
    assert retried.json() == processed.json()
    assert status.json()["job"] == processed.json()
    assert [row["error"]["code"] for row in errors.json()["rows"]] == [
        "min_price_above_max_price"
    ]
    assert denied.status_code == 403
    assert [doc["_id"] for doc in db.repricer_catalog_rules.documents] == [
        "catalog-123456789-acc-1-MLA1"
    ]


@pytest.mark.asyncio
async def test_get_history_filters_catalog_outcomes_without_breaking_seller_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db = _app(monkeypatch)
    db.repricer_history.documents.extend(
        [
            _history_doc(
                "history-applied",
                seller_id="123456789",
                account_id="acc-1",
                item_id="MLA1",
                reason="track_buybox",
                gateway_status=202,
                applied_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC).isoformat(),
            ),
            _history_doc(
                "history-guard",
                seller_id="123456789",
                account_id="acc-1",
                item_id="MLA2",
                reason="below_floor",
                gateway_status=None,
                applied_at=datetime(2026, 5, 13, 12, 5, tzinfo=UTC).isoformat(),
                job_id="job-1",
            ),
            _history_doc(
                "history-paused",
                seller_id="123456789",
                account_id="acc-1",
                item_id="MLA3",
                reason="competition_paused",
                gateway_status=None,
                applied_at=datetime(2026, 5, 13, 12, 10, tzinfo=UTC).isoformat(),
            ),
            _history_doc(
                "history-no-action",
                seller_id="123456789",
                account_id="acc-1",
                item_id="MLA4",
                reason="ally_competitor",
                gateway_status=None,
                applied_at=datetime(2026, 5, 13, 12, 15, tzinfo=UTC).isoformat(),
                report_id="report-1",
            ),
            _history_doc(
                "history-other-seller",
                seller_id="987654321",
                account_id="acc-1",
                item_id="MLA1",
                reason="track_buybox",
                gateway_status=202,
                applied_at=datetime(2026, 5, 13, 12, 20, tzinfo=UTC).isoformat(),
            ),
        ]
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        guard_response = await client.get(
            "/repricer/history?seller_id=123456789&account_id=acc-1&outcome=guard_blocked&job_id=job-1",
            headers={"Authorization": "Bearer valid"},
        )
        paused_response = await client.get(
            "/repricer/history?seller_id=123456789&status=paused",
            headers={"Authorization": "Bearer valid"},
        )
        no_action_response = await client.get(
            "/repricer/history?seller_id=123456789&item_id=MLA4&report_id=report-1",
            headers={"Authorization": "Bearer valid"},
        )
        denied = await client.get(
            "/repricer/history?seller_id=987654321",
            headers={"Authorization": "Bearer valid"},
        )

    assert guard_response.status_code == 200
    assert [entry["_id"] for entry in guard_response.json()] == ["history-guard"]
    assert guard_response.json()[0]["outcome"] == "guard_blocked"
    assert paused_response.json()[0]["outcome"] == "paused"
    assert no_action_response.json()[0]["outcome"] == "no_action"
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_report_rules_export_lifecycle_uses_canonical_catalog_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db = _app(monkeypatch)
    db.repricer_catalog_rules.documents.extend(
        [
            _catalog_rule("catalog-1", seller_id="123456789", account_id="acc-1", sku="SKU-1"),
            _catalog_rule("catalog-2", seller_id="123456789", account_id="acc-2", sku="SKU-2"),
            _catalog_rule("catalog-3", seller_id="987654321", account_id="acc-1", sku="SKU-3"),
        ]
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/repricer/reports/rules-export",
            headers={"Authorization": "Bearer valid"},
            json={"seller_id": "123456789", "account_id": "acc-1", "format": "csv"},
        )
        report_id = created.json()["_id"]
        listed = await client.get(
            "/repricer/reports?seller_id=123456789&account_id=acc-1&status=ready&report_type=rules_export",
            headers={"Authorization": "Bearer valid"},
        )
        downloaded = await client.get(
            f"/repricer/reports/{report_id}/download?seller_id=123456789",
            headers={"Authorization": "Bearer valid"},
        )
        denied = await client.post(
            "/repricer/reports/rules-export",
            headers={"Authorization": "Bearer valid"},
            json={"seller_id": "987654321", "account_id": "acc-1", "format": "csv"},
        )

    assert created.status_code == 201
    assert created.json()["status"] == "ready"
    assert created.json()["row_count"] == 1
    assert created.json()["storage_path"].startswith("inline://repricer/reports/")
    assert listed.status_code == 200
    assert listed.json() == [created.json()]
    assert downloaded.status_code == 200
    assert downloaded.json()["report"] == created.json()
    assert downloaded.json()["content"].splitlines() == [
        "item_id,title,sku,strategy,min_price,max_price,active,last_outcome",
        "MLA123,Catalog Item,SKU-1,competitive,100.00,120.00,true,",
    ]
    assert denied.status_code == 403
    assert len(db.repricer_reports.documents) == 1


@pytest.mark.asyncio
async def test_get_monitoring_returns_seller_scoped_snapshot_and_scheduler_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db = _app(monkeypatch)
    db.repricer_catalog_rules.documents.extend(
        [
            _catalog_rule("catalog-active", seller_id="123456789", account_id="acc-1"),
            _catalog_rule(
                "catalog-paused",
                seller_id="123456789",
                account_id="acc-1",
                active=False,
            ),
            _catalog_rule("catalog-other-seller", seller_id="987654321", account_id="acc-1"),
        ]
    )
    db.repricer_history.documents.extend(
        [
            _history_doc(
                "history-applied",
                seller_id="123456789",
                account_id="acc-1",
                item_id="MLA1",
                reason="track_buybox",
                gateway_status=202,
                applied_at=datetime(2026, 5, 13, 18, 55, tzinfo=UTC).isoformat(),
            ),
            _history_doc(
                "history-guard",
                seller_id="123456789",
                account_id="acc-1",
                item_id="MLA2",
                reason="below_floor",
                gateway_status=None,
                applied_at=datetime(2026, 5, 13, 18, 56, tzinfo=UTC).isoformat(),
            ),
        ]
    )
    db.repricer_bulk_jobs.documents.append(
        _bulk_job_doc("bulk-active", seller_id="123456789", account_id="acc-1", status="processing")
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/repricer/monitoring?seller_id=123456789&account_id=acc-1",
            headers={"Authorization": "Bearer valid"},
        )
        denied = await client.get(
            "/repricer/monitoring?seller_id=987654321&account_id=acc-1",
            headers={"Authorization": "Bearer valid"},
        )

    body = response.json()
    assert response.status_code == 200
    assert body["snapshot"]["seller_id"] == "123456789"
    assert body["snapshot"]["account_id"] == "acc-1"
    assert body["snapshot"]["active_bulk_job_ids"] == ["bulk-active"]
    assert body["metrics"] == {"active_rules": 1, "paused_rules": 1, "active_bulk_jobs": 1}
    assert body["scheduler"]["processed_count"] == 2
    assert body["scheduler"]["applied_count"] == 1
    assert body["scheduler"]["blocked_count"] == 1
    assert body["health"]["checks"]["catalog_rules"] == "ok"
    assert denied.status_code == 403
    persisted_snapshot = db.repricer_monitoring_snapshots.documents[0]
    assert isinstance(persisted_snapshot["generated_at"], datetime)
    assert persisted_snapshot["worker_heartbeat_at"] is None
    assert body["snapshot"]["generated_at"] == persisted_snapshot["generated_at"].astimezone(
        UTC
    ).isoformat().replace("+00:00", "Z")


def _app(monkeypatch: pytest.MonkeyPatch) -> tuple[FastAPI, FakeDb]:
    import zeler_repricer.api as api
    from zeler_repricer.api import build_router

    db = FakeDb()
    app = FastAPI()
    app.state.mongo_db = db
    app.include_router(build_router())

    monkeypatch.setattr(api, "verify_module_jwt", lambda _token: _claims())
    return app, db


def _claims(**overrides: Any) -> object:
    from zeler_platform_core.auth.jwt import ModuleClaims

    module_id = str(overrides.pop("module_id", "repricer"))
    seller_id = int(overrides.pop("seller_id", 123456789))
    return ModuleClaims(
        module_id=module_id,
        seller_id=seller_id,
        iss=f"module:{module_id}",
        aud="gateway",
        iat=1,
        exp=2,
        token_type=str(overrides.pop("token_type", "module_admin")),
        scopes=list(overrides.pop("scopes", ["admin:repricer"])),
        issued_by=str(overrides.pop("issued_by", "operator-1")),
    )


def _catalog_rule(
    rule_id: str,
    *,
    seller_id: str,
    account_id: str,
    sku: str = "SKU-1",
    active: bool = True,
) -> dict[str, Any]:
    return {
        "_id": rule_id,
        "seller_id": seller_id,
        "account_id": account_id,
        "item_id": "MLA123",
        "title": "Catalog Item",
        "sku": sku,
        "strategy": "competitive",
        "min_price": "100.00",
        "max_price": "120.00",
        "active": active,
        "execution_state": {},
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
        "created_by": "operator-1",
        "updated_by": "operator-1",
        "schema_version": 1,
    }


def _history_doc(
    history_id: str,
    *,
    seller_id: str,
    account_id: str,
    item_id: str,
    reason: str,
    gateway_status: int | None,
    applied_at: str,
    job_id: str | None = None,
    report_id: str | None = None,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "_id": history_id,
        "seller_id": seller_id,
        "account_id": account_id,
        "rule_id": f"catalog-{item_id}",
        "item_id": item_id,
        "old_price": "150.00",
        "new_price": "149.00",
        "reason": reason,
        "applied_at": applied_at,
        "gateway_status": gateway_status,
        "gateway_latency_ms": 11 if gateway_status is not None else None,
        "event_id": f"event-{history_id}",
        "schema_version": 1,
    }
    if job_id is not None:
        document["job_id"] = job_id
    if report_id is not None:
        document["report_id"] = report_id
    return document


def _bulk_job_doc(job_id: str, *, seller_id: str, account_id: str, status: str) -> dict[str, Any]:
    return {
        "_id": job_id,
        "seller_id": seller_id,
        "account_id": account_id,
        "status": status,
        "source_filename": "catalog-upload.csv",
        "total_rows": 2,
        "processed_rows": 1,
        "success_rows": 1,
        "failed_rows": 0,
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
        "created_by": "operator-1",
        "schema_version": 1,
    }


def _limits_doc(
    *, seller_id: str, account_id: str, min_price: str, max_price: str
) -> dict[str, Any]:
    return {
        "_id": f"limits-{seller_id}-{account_id}",
        "seller_id": seller_id,
        "account_id": account_id,
        "enabled": True,
        "min_price_limit": min_price,
        "max_price_limit": max_price,
        "undercut_delta": "1.00",
        "pause_competition": False,
        "escalate_to_manual_review": False,
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
        "schema_version": 1,
    }
