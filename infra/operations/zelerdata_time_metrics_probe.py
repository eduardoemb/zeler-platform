"""Read-only probe for the four ZelerData time/withdrawal formulas.

Run from the approved VM/VPC runtime context with ``MONGO_URI`` and ``MONGO_DB``
set (neither is printed)::

    python -m infra.operations.zelerdata_time_metrics_probe --seller-id 82453304

It only calls ``list_collection_names``, ``count_documents``, ``find`` with a
limit of one, and small ``aggregate`` pipelines. It never writes. The JSON it
prints holds collection names, counts, field *names*, enum-like values taken from
Mercado Libre (status, type) and the oldest/newest timestamp of a time field, so
the plan in ``docs/sheets/zelerdata-time-metrics-plan.md`` can size forward
accumulation. No document values, identifiers, titles or SKUs are emitted.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import datetime
from typing import Any

MAX_TIME_MS = 30_000

# Sources the legacy importer needs. Expected to be absent in production.
SOURCE_GATED_SOURCES = ("item_history_projection", "meli_item_events", "withdrawal_records")
# Collections the three formulas read today. Expected to hold 0 documents.
TARGET_COLLECTIONS = (
    "sheets_stock_time_metrics",
    "sheets_catalog_time_metrics",
    "sheets_full_withdrawals",
)
# Forward candidates: (collection, time field, enum field or None).
FORWARD_CANDIDATES: tuple[tuple[str, str | None, str | None], ...] = (
    ("item_status_states", "last_observed_at", "current_status"),
    ("item_status_transitions", "observed_at", "to_status"),
    ("sheets_stockout_snapshots", "observed_at", "stock_state"),
    ("sheets_item_availability_transitions", "observed_at", "available"),
    ("sheets_price_history_snapshots", "snapshot_at", None),
    ("sheets_catalog_competition_observations", "observed_at", "status"),
    ("sheets_catalog_buybox_snapshots", "snapshot_at", "buybox_status"),
    ("sheets_full_operations", "date_created", "type"),
)
MARKER_MODELS = (
    "stock_time_metrics",
    "catalog_time_metrics",
    "full_withdrawals",
    "item_status_states",
    "stockout_snapshots",
    "price_history_snapshots",
)


def _seller_filter(seller_id: str) -> dict[str, Any]:
    values: list[Any] = [seller_id]
    if seller_id.isdecimal():
        values.append(int(seller_id))
    return {"seller_id": {"$in": values}}


def _field_names(document: dict[str, Any] | None, *, nested: tuple[str, ...] = ()) -> list[str]:
    """Top-level field names, plus dotted names for the listed sub-documents."""
    if document is None:
        return []
    names = sorted(document)
    for parent in nested:
        child = document.get(parent)
        if isinstance(child, dict):
            names.extend(f"{parent}.{key}" for key in sorted(child))
        elif isinstance(child, list) and child and isinstance(child[0], dict):
            names.extend(f"{parent}[].{key}" for key in sorted(child[0]))
    return names


def _edge(collection: Any, query: dict[str, Any], field: str, direction: int) -> str | None:
    rows = list(
        collection.find(query, {field: 1, "_id": 0})
        .sort(field, direction)
        .limit(1)
        .max_time_ms(MAX_TIME_MS)
    )
    value = rows[0].get(field) if rows else None
    return value.isoformat() if isinstance(value, datetime) else None


def _group_counts(
    collection: Any, query: dict[str, Any], field: str, *, unwind: str | None = None
) -> dict[str, int]:
    pipeline: list[dict[str, Any]] = [{"$match": query}]
    if unwind is not None:
        pipeline.append({"$unwind": f"${unwind}"})
    pipeline += [
        {"$group": {"_id": f"${field}", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
        {"$limit": 20},
    ]
    return {
        str(row["_id"]): int(row["n"])
        for row in collection.aggregate(pipeline, maxTimeMS=MAX_TIME_MS)
    }


def _distinct_items(collection: Any, query: dict[str, Any]) -> int:
    pipeline = [
        {"$match": query},
        {"$group": {"_id": "$item_id"}},
        {"$count": "n"},
    ]
    rows = list(collection.aggregate(pipeline, maxTimeMS=MAX_TIME_MS))
    return int(rows[0]["n"]) if rows else 0


def probe(db: Any, seller_id: str) -> dict[str, Any]:
    names = set(db.list_collection_names())
    scoped = _seller_filter(seller_id)
    report: dict[str, Any] = {"seller_id": seller_id}

    report["sources"] = {
        name: {
            "exists": name in names,
            "count": db[name].count_documents({}, maxTimeMS=MAX_TIME_MS) if name in names else 0,
        }
        for name in SOURCE_GATED_SOURCES
    }
    report["targets"] = {
        name: {
            "exists": name in names,
            "count": db[name].count_documents(scoped, maxTimeMS=MAX_TIME_MS)
            if name in names
            else 0,
        }
        for name in TARGET_COLLECTIONS
    }

    forward: dict[str, Any] = {}
    for name, time_field, enum_field in FORWARD_CANDIDATES:
        if name not in names:
            forward[name] = {"exists": False}
            continue
        collection = db[name]
        sample = collection.find_one(scoped)
        entry: dict[str, Any] = {
            "exists": True,
            "count": collection.count_documents(scoped, maxTimeMS=MAX_TIME_MS),
            "fields": _field_names(sample, nested=("detail", "external_references", "prices")),
        }
        if time_field is not None:
            entry["oldest"] = _edge(collection, scoped, time_field, 1)
            entry["newest"] = _edge(collection, scoped, time_field, -1)
        if enum_field is not None:
            entry["by_" + enum_field] = _group_counts(collection, scoped, enum_field)
        if "item_id" in (sample or {}):
            entry["distinct_items"] = _distinct_items(collection, scoped)
        if name == "sheets_full_operations":
            entry["with_external_references"] = collection.count_documents(
                {**scoped, "external_references.0": {"$exists": True}}, maxTimeMS=MAX_TIME_MS
            )
            entry["external_reference_types"] = _group_counts(
                collection, scoped, "external_references.type", unwind="external_references"
            )
        forward[name] = entry
    report["forward_candidates"] = forward

    items = db["items"]
    report["items"] = {
        "count": items.count_documents(scoped, maxTimeMS=MAX_TIME_MS),
        "fulfillment": items.count_documents(
            {**scoped, "shipping.logistic_type": "fulfillment"}, maxTimeMS=MAX_TIME_MS
        ),
        "with_catalog_product_id": items.count_documents(
            {**scoped, "catalog_product_id": {"$nin": [None, ""]}}, maxTimeMS=MAX_TIME_MS
        ),
        "with_inventory_id": items.count_documents(
            {**scoped, "inventory_id": {"$nin": [None, ""]}}, maxTimeMS=MAX_TIME_MS
        ),
        "with_variations": items.count_documents(
            {**scoped, "variations.0": {"$exists": True}}, maxTimeMS=MAX_TIME_MS
        ),
    }

    markers = db["sheets_read_model_freshness"]
    report["markers"] = {
        model: {
            key: (value.isoformat() if isinstance(value, datetime) else value)
            for key, value in (
                markers.find_one(
                    {"_id": f"{seller_id}:{model}"},
                    {
                        "_id": 0,
                        "state": 1,
                        "coverage_basis": 1,
                        "source": 1,
                        "date_from": 1,
                        "valid_until": 1,
                    },
                )
                or {"state": "missing"}
            ).items()
        }
        for model in MARKER_MODELS
    }
    return report


def create_runtime_db() -> tuple[Any, Any]:
    uri, name = os.environ.get("MONGO_URI"), os.environ.get("MONGO_DB")
    if not uri or not name:
        raise SystemExit("MONGO_URI and MONGO_DB are required")
    from pymongo import MongoClient

    client: Any = MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=10_000)
    return client, client[name]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--seller-id", required=True)
    args = parser.parse_args(argv)
    client, db = create_runtime_db()
    try:
        print(json.dumps(probe(db, args.seller_id), indent=2, sort_keys=True))
    except Exception as exc:  # noqa: BLE001 - sanitized output only
        print(f"probe failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
