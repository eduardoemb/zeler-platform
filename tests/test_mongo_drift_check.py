from __future__ import annotations

from infra.mongo.drift_check import compare_validators


def test_drift_reports_missing_when_collection_absent() -> None:
    report = compare_validators({"bootstrap_jobs": {"$jsonSchema": {"bsonType": "object"}}}, {})

    assert report["collections"]["bootstrap_jobs"]["status"] == "missing"
    assert report["has_drift"] is True


def test_drift_reports_drifted_when_validator_differs() -> None:
    repo = {"bootstrap_jobs": {"$jsonSchema": {"bsonType": "object"}}}
    live = {"bootstrap_jobs": {"$jsonSchema": {"bsonType": "object", "required": ["_id"]}}}

    report = compare_validators(repo, live)

    assert report["collections"]["bootstrap_jobs"]["status"] == "drifted"
    assert report["has_drift"] is True


def test_drift_reports_applied_when_match() -> None:
    repo = {"bootstrap_jobs": {"$jsonSchema": {"bsonType": "object"}}}
    live = {"bootstrap_jobs": {"$jsonSchema": {"bsonType": "object"}}}

    report = compare_validators(repo, live)

    assert report["collections"]["bootstrap_jobs"]["status"] == "applied"
    assert report["has_drift"] is False
