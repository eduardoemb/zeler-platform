"""Read-only diagnosis of why ZelerData formulas answer PARTIAL for one seller.

Run it from the approved runtime, with the sheets-api container's own
``MONGO_URI``/``MONGO_DB``; nothing is installed and nothing is written::

    docker exec -i zeler-platform-sheets-api-1 /app/.venv/bin/python - \\
        < infra/operations/zelerdata_partial_diagnose.py

The seller defaults to the pilot (``82453304``) and can be overridden with
``ZELERDATA_DIAG_SELLER`` (``docker exec -e``). Every database handle goes
through :class:`ReadOnlyDatabase`, which rejects any write or command. The
report contains counts, buckets and fixed codes only: no item, SKU, order or
seller identifiers, titles, values or secrets. The script replays the real
formula handlers over the real read models, then explains each missing cell by
the condition the reader applies (age windows, source fingerprints, snapshots,
tags and attributes), so a result can be matched to a cause without guessing.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections import Counter
from collections.abc import Awaitable, Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from zeler_sheets.formulas.dispatcher import (
    FormulaDataUnavailableError,
    FormulaExecutionContext,
    FormulaExecutionResult,
)
from zeler_sheets.formulas.handlers_core import build_core_formula_handlers
from zeler_sheets.formulas.handlers_item_shipping_catalog import (
    _is_catalog_link_suggestion,
    build_item_shipping_catalog_formula_handlers,
)
from zeler_sheets.formulas.handlers_orders_questions import (
    _item_id as _order_line_item_id,
)
from zeler_sheets.formulas.handlers_orders_questions import (
    _order_items,
    build_order_question_formula_handlers,
)
from zeler_sheets.formulas.handlers_quality_calculator import (
    build_quality_calculator_formula_handlers,
)
from zeler_sheets.formulas.handlers_remaining_phase4 import (
    CATALOGO_SALES_WINDOWS,
    build_remaining_phase4_formula_handlers,
)
from zeler_sheets.formulas.handlers_returns_histories_withdrawals import (
    build_returns_histories_withdrawals_formula_handlers,
)
from zeler_sheets.formulas.read_models import (
    CATALOG_BUYBOX_CACHE_MAX_AGE,
    FormulaReadModelRepository,
    _read_model_freshness_marker_covers,
    _safe_utc_datetime,
)
from zeler_sheets.formulas.recovery import ItemInventoryRecoveryRequest
from zeler_sheets.formulas.registry import FormulaRegistry
from zeler_sheets.item_projection import item_source_fingerprint

PILOT_SELLER = "82453304"
FRESH = timedelta(minutes=15)
PRODUCT_CACHE = timedelta(hours=4)
CODE = re.compile(r"[a-z][a-z0-9_]{0,59}")
PACKAGE_FAMILIES = {
    "package": ("PACKAGE_LENGTH", "PACKAGE_HEIGHT", "PACKAGE_WIDTH"),
    "seller_package": (
        "SELLER_PACKAGE_LENGTH",
        "SELLER_PACKAGE_HEIGHT",
        "SELLER_PACKAGE_WIDTH",
    ),
}
COST_FIELDS = (
    "seller_shipping_cost",
    "listing_fee_projection",
    "listing_price_fixed_fee",
    "current_promotion",
)
READ_MODELS_FOR_MARKERS = (
    "orders",
    "item_status_states",
    "item_formula_rows",
    "catalog_buybox_snapshots",
    "catalog_product_snapshots",
    "shipments",
)
SNAPSHOT_SOURCES = {"sheets_backfill", "historical_meli_backfill"}
# These two readers load the seller's whole order history on every call, like a
# heavy formula request, so only the most informative populations run them.
FULL_ORDER_HISTORY_FORMULAS = ("ZELERDATA_DIASDESDEULTIMAVENTA", "ZELERDATA_COSTOENVIOVENDEDOR")
FULL_ORDER_POPULATIONS = frozenset({"probe_sorted_by_sku", "spread", "sold_last_30d"})
POPULATION_SIZE = 60
SOLD_SIZE = 40
READ_METHODS = frozenset(
    {"find", "find_one", "count_documents", "estimated_document_count", "distinct", "aggregate"}
)


class ReadOnlyViolationError(RuntimeError):
    """A write, command or administrative call reached the guarded database."""


class ReadOnlyCollection:
    def __init__(self, collection: Any) -> None:
        self._collection = collection

    def __getattr__(self, name: str) -> Any:
        if name not in READ_METHODS:
            raise ReadOnlyViolationError(name)
        if name == "aggregate":
            return self._aggregate
        return getattr(self._collection, name)

    def _aggregate(self, pipeline: Sequence[Mapping[str, Any]], *args: Any, **kwargs: Any) -> Any:
        if any(stage_name in ("$out", "$merge") for stage in pipeline for stage_name in stage):
            raise ReadOnlyViolationError("aggregate_write_stage")
        return self._collection.aggregate(list(pipeline), *args, **kwargs)


class ReadOnlyDatabase:
    def __init__(self, database: Any) -> None:
        self._database = database

    def __getitem__(self, name: str) -> ReadOnlyCollection:
        return ReadOnlyCollection(self._database[name])

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or name in {"command", "client", "drop_collection", "name"}:
            raise ReadOnlyViolationError(name)
        return self[name]


def safe_code(value: Any) -> str:
    return value if isinstance(value, str) and CODE.fullmatch(value) else "other"


def minutes_between(now: datetime, value: Any) -> float | None:
    observed = _safe_utc_datetime(value)
    return None if observed is None else round((now - observed).total_seconds() / 60, 1)


def age_bucket(minutes: float | None) -> str:
    if minutes is None:
        return "none"
    if minutes < 0:
        return "future"
    for limit, label in ((15, "le_15m"), (30, "15_30m"), (60, "30_60m"), (240, "1_4h")):
        if minutes < limit:
            return label
    return "gt_4h"


def _projection_issue(
    source: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], observed: datetime
) -> str | None:
    fingerprint = item_source_fingerprint(dict(source))
    for row in rows:
        snapshot = row.get("source_snapshot")
        if not isinstance(snapshot, dict):
            return "row_without_source_snapshot"
        if snapshot.get("fingerprint") != fingerprint:
            return "fingerprint_mismatch"
        if _safe_utc_datetime(snapshot.get("observed_at")) != observed:
            return "snapshot_observed_at_mismatch"
        if type(snapshot.get("rows_count")) is not int or snapshot["rows_count"] != len(rows):
            return "snapshot_rows_count_mismatch"
    return None


def classify_item_source(
    source: Mapping[str, Any] | None,
    rows: Sequence[Mapping[str, Any]],
    *,
    seller_id: str,
    now: datetime,
) -> str:
    """Why an inventory publication is, or is not, a verified fresh row right now.

    Mirrors ``FormulaReadModelRepository._find_recent_item_rows_with_sources``,
    splitting its single "stale or inconsistent" outcome into separate causes.
    """
    if source is None:
        return "no_item_source"
    if source.get("seller_id") != seller_id:
        return "other_seller"
    if not rows:
        return "no_formula_rows"
    observed = _safe_utc_datetime(source.get("last_meli_sync_at"))
    if observed is None:
        return "no_sync_timestamp"
    if observed > now:
        return "sync_in_future"
    issue = _projection_issue(source, rows, observed)
    if now - FRESH < observed:
        return issue or "ok"
    suffix = "changed" if issue else "consistent"
    return f"sync_older_than_15m_projection_{suffix}"


def _counter(values: Iterable[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _quantiles(values: Sequence[float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)

    def at(quantile: float) -> float:
        return ordered[min(len(ordered) - 1, int(quantile * (len(ordered) - 1) + 0.5))]

    return {
        "min": ordered[0],
        "p10": at(0.1),
        "p50": at(0.5),
        "p90": at(0.9),
        "max": ordered[-1],
    }


def _attribute_ids(resource: Mapping[str, Any]) -> set[str]:
    present: set[str] = set()
    attributes = resource.get("attributes")
    if isinstance(attributes, list):
        for attribute in attributes:
            if not isinstance(attribute, dict):
                continue
            has_value = any(
                str(attribute.get(key) or "").strip() for key in ("value_name", "value_struct")
            ) or bool(attribute.get("values"))
            if has_value:
                present.add(str(attribute.get("id") or "").upper())
    return present


def package_families(source: Mapping[str, Any]) -> list[str]:
    resources: list[Mapping[str, Any]] = [source]
    variations = source.get("variations")
    if isinstance(variations, list):
        resources.extend(entry for entry in variations if isinstance(entry, dict))
    found: set[str] = set()
    for resource in resources:
        attributes = _attribute_ids(resource)
        found.update(family for family, ids in PACKAGE_FAMILIES.items() if set(ids) <= attributes)
    shipping = source.get("shipping")
    if isinstance(shipping, dict) and shipping.get("dimensions"):
        found.add("shipping_dimensions")
    return sorted(found)


def _sold_bucket(now: datetime, last: datetime | None) -> str:
    if last is None:
        return "never"
    days = (now - last).total_seconds() / 86400
    for limit, label in ((7, "le_7d"), (30, "8_30d"), (90, "31_90d")):
        if days <= limit:
            return label
    return "gt_90d"


class _Facts:
    """Everything the sections share, read once with plain queries."""

    def __init__(self, seller_id: str, now: datetime) -> None:
        self.seller_id = seller_id
        self.now = now
        self.job: dict[str, Any] | None = None
        self.enumeration_ids: list[str] | None = None
        self.rows_by_item: dict[str, list[dict[str, Any]]] = {}
        self.row_order: list[dict[str, Any]] = []
        self.sources: dict[str, dict[str, Any]] = {}
        self.package: dict[str, list[str]] = {}
        self.states: dict[str, dict[str, Any]] = {}
        self.sales: dict[str, datetime | None] = {}
        self.orders_seen = 0

    def sold_bucket(self, item_id: str) -> str:
        return _sold_bucket(self.now, self.sales.get(item_id))

    def facts_for(self, item_id: str) -> dict[str, str]:
        source = self.sources.get(item_id) or {}
        state = self.states.get(item_id)
        return {
            "status": safe_code(source.get("status")),
            "state": "no_state" if state is None else safe_code(state.get("current_status")),
            "package": "+".join(self.package.get(item_id, [])) or "none",
            "sold": self.sold_bucket(item_id),
        }


async def _load(db: Any, seller_id: str, now: datetime) -> _Facts:
    facts = _Facts(seller_id, now)
    request = ItemInventoryRecoveryRequest(seller_id)
    facts.job = await db["sheets_formula_recovery_jobs"].find_one(
        {
            "_id": request.key,
            "seller_id": seller_id,
            "read_model": "item_formula_rows",
            "inventory_scope": True,
        }
    )
    identities = facts.job.get("inventory_ids") if facts.job else None
    if isinstance(identities, list):
        facts.enumeration_ids = [str(value) for value in identities]
    async for row in db["sheets_item_formula_rows"].find({"seller_id": seller_id}):
        light = {
            "_id": str(row.get("_id")),
            "item_id": str(row.get("item_id") or ""),
            "sku": row.get("sku") or row.get("normalized_sku") or "",
            "inventory_id": row.get("inventory_id"),
            "source_snapshot": row.get("source_snapshot"),
            "current": row.get("current") if isinstance(row.get("current"), dict) else {},
        }
        facts.rows_by_item.setdefault(light["item_id"], []).append(light)
        facts.row_order.append(light)
    async for source in db["items"].find({"seller_id": seller_id}):
        item_id = str(source["_id"])
        facts.sources[item_id] = source
        facts.package[item_id] = package_families(source)
    async for state in db["item_status_states"].find({"seller_id": seller_id}):
        facts.states[str(state.get("item_id") or "")] = state
    projection = {"items": 1, "date_created": 1}
    async for order in db["orders"].find({"seller_id": seller_id}, projection):
        facts.orders_seen += 1
        created = _safe_utc_datetime(order.get("date_created"))
        for line in _order_items(order):
            identity = _order_line_item_id(line)
            if not identity:
                continue
            previous = facts.sales.get(identity)
            facts.sales[identity] = (
                created if previous is None or (created and created > previous) else previous
            )
    return facts


def _section_enumeration(facts: _Facts) -> dict[str, Any]:
    job = facts.job
    if job is None:
        return {"present": False}
    observed = _safe_utc_datetime(job.get("inventory_observed_at"))
    age = None if observed is None else minutes_between(facts.now, observed)
    identities = facts.enumeration_ids
    return {
        "present": True,
        "state": safe_code(job.get("state")),
        "identities": None if identities is None else len(identities),
        "offset": job.get("inventory_offset")
        if isinstance(job.get("inventory_offset"), int)
        else None,
        "observed_age_min": age,
        "observed_age_bucket": age_bucket(age),
        "current": age is not None and 0 <= age < 15,
        "datetime_fields_age_min": {
            key: minutes_between(facts.now, value)
            for key, value in sorted(job.items())
            if isinstance(value, datetime) and CODE.fullmatch(key)
        },
        "identities_without_item_source": sum(
            1 for value in identities or [] if value not in facts.sources
        ),
        "item_sources_outside_enumeration_by_status": _counter(
            safe_code(source.get("status"))
            for item_id, source in facts.sources.items()
            if identities is not None and item_id not in set(identities)
        ),
    }


def _section_verification(facts: _Facts) -> dict[str, Any]:
    universe = facts.enumeration_ids if facts.enumeration_ids is not None else sorted(facts.sources)
    reasons: Counter[str] = Counter()
    by_status: dict[str, Counter[str]] = {}
    ages: list[float] = []
    buckets: Counter[str] = Counter()
    histogram = [0] * 36
    for item_id in universe:
        source = facts.sources.get(item_id)
        reason = classify_item_source(
            source, facts.rows_by_item.get(item_id, []), seller_id=facts.seller_id, now=facts.now
        )
        reasons[reason] += 1
        status = safe_code((source or {}).get("status")) if source else "unknown"
        by_status.setdefault(status, Counter())[reason] += 1
        if source is None:
            continue
        age = minutes_between(facts.now, source.get("last_meli_sync_at"))
        buckets[age_bucket(age)] += 1
        if age is not None and age >= 0:
            ages.append(age)
            if age < 180:
                histogram[int(age // 5)] += 1
    enumeration = _section_enumeration(facts)
    complete = bool(enumeration.get("current")) and set(reasons) <= {"ok"}
    recent = [age for age in ages if age < 360]
    return {
        "universe": len(universe),
        "universe_source": "enumeration" if facts.enumeration_ids is not None else "items",
        "reasons": dict(sorted(reasons.items())),
        "reasons_by_status": {status: dict(sorted(c.items())) for status, c in by_status.items()},
        "inventory_rows_complete_now": complete,
        "item_sync_ages": {
            "age_minutes": _quantiles(ages),
            "buckets": dict(sorted(buckets.items())),
            "recent_pass_span_minutes": round(max(recent) - min(recent), 1) if recent else None,
            "histogram_5min_last_3h_newest_first": histogram,
        },
    }


def _row_counts(facts: _Facts) -> dict[str, Any]:
    quality: Counter[str] = Counter()
    states: dict[str, Counter[str]] = {field: Counter() for field in COST_FIELDS}
    synced: dict[str, Counter[str]] = {field: Counter() for field in COST_FIELDS}
    dimensions = 0
    for row in facts.row_order:
        current = row["current"]
        projection = current.get("quality_projection")
        enrichment = current.get("enrichment_state")
        enrichment = enrichment if isinstance(enrichment, dict) else {}
        state = enrichment.get("quality_projection")
        label = "absent"
        if isinstance(projection, dict):
            label = "present_" + age_bucket(
                minutes_between(facts.now, projection.get("observed_at"))
            )
        if isinstance(state, dict):
            label += f"|state_{safe_code(state.get('status'))}_{safe_code(state.get('reason'))}"
        quality[label] += 1
        for field in COST_FIELDS:
            entry = enrichment.get(field)
            entry = entry if isinstance(entry, dict) else {}
            states[field]["no_state" if not entry else f"{safe_code(entry.get('status'))}"] += 1
            synced[field][age_bucket(minutes_between(facts.now, entry.get("synced_at")))] += 1
        if any(key in current for key in ("dimensions", "measurement", "measures")):
            dimensions += 1
    return {
        "formula_rows": len(facts.row_order),
        "items_with_rows": len(facts.rows_by_item),
        "quality_projection": dict(sorted(quality.items())),
        "cost_field_state": {field: dict(sorted(c.items())) for field, c in states.items()},
        "cost_field_synced_age": {field: dict(sorted(c.items())) for field, c in synced.items()},
        "rows_with_dimensions_field": dimensions,
    }


def _catalog_rows(facts: _Facts) -> list[dict[str, Any]]:
    return [
        row
        for row in facts.row_order
        if str(row["current"].get("catalog_product_id") or "").strip()
    ]


def _identity_facts(facts: _Facts) -> dict[str, Any]:
    rows = _catalog_rows(facts)
    sales = _counter(facts.sold_bucket(row["item_id"]) for row in rows)
    return {
        "catalog_rows": len(rows),
        "all_rows": len(facts.row_order),
        "status": _counter(facts.facts_for(row["item_id"])["status"] for row in rows),
        "status_state": _counter(facts.facts_for(row["item_id"])["state"] for row in rows),
        "package_dimensions_in_item": _counter(
            facts.facts_for(row["item_id"])["package"] for row in rows
        ),
        "package_dimensions_all_items": _counter(
            "+".join(found) or "none" for found in facts.package.values()
        ),
        "last_sale": sales,
        "with_inventory_id": sum(1 for row in rows if row["inventory_id"]),
        "orders_scanned": facts.orders_seen,
        "items_with_any_order": len(facts.sales),
        "items_with_status_state": len(facts.states),
    }


def _population(facts: _Facts) -> dict[str, list[dict[str, Any]]]:
    rows = _catalog_rows(facts)
    with_sku = [row for row in rows if row["sku"]]
    by_sku = sorted(with_sku, key=lambda row: (str(row["sku"]).lower(), row["item_id"]))
    by_id = sorted(with_sku, key=lambda row: row["_id"])
    step = max(1, len(with_sku) // POPULATION_SIZE)
    sold = [
        row
        for row in facts.row_order
        if row["sku"] and facts.sold_bucket(row["item_id"]) in {"le_7d", "8_30d"}
    ]
    paused = [
        row
        for row in facts.row_order
        if row["sku"] and facts.facts_for(row["item_id"])["status"] == "paused"
    ]
    return {
        "probe_sorted_by_sku": by_sku[:1],
        "probe_first_by_row_id": by_id[:1],
        "probe_first_stored": with_sku[:1],
        "spread": with_sku[::step][:POPULATION_SIZE],
        "sold_last_30d": sold[:SOLD_SIZE],
        "paused": paused[:SOLD_SIZE],
    }


def _cell_kind(value: Any) -> str:
    if value == "NA":
        return "NA"
    if value == "DATA_UNAVAILABLE":
        return "DATA_UNAVAILABLE"
    if value in ("", None):
        return "empty"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "zero" if value == 0 else "number"
    return "text"


def _meta_summary(meta: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key, value in sorted(meta.items()):
        if not CODE.fullmatch(key):
            continue
        if isinstance(value, (bool, int, float)) or value is None:
            summary[key] = value
        elif isinstance(value, str):
            summary[key] = safe_code(value)
        elif isinstance(value, (list, tuple, set, dict)):
            summary[key] = {"len": len(value)}
    return summary


def _recovery_summary(error: FormulaDataUnavailableError | None) -> dict[str, Any] | None:
    if error is None:
        return None
    reason = error.message.partition(": ")[2][:120]
    return {
        "read_model": safe_code(error.read_model),
        "reason": reason,
        "item_ids": len(error.item_ids),
        "catalog_product_ids": len(error.catalog_product_ids),
    }


def _headers(module: Any, *names: str) -> list[str]:
    for name in names:
        value = getattr(module, name, None)
        if isinstance(value, (list, tuple)):
            return [str(entry) for entry in value]
    return []


def _table_summary(result: FormulaExecutionResult, headers: Sequence[str]) -> dict[str, Any]:
    columns: Counter[str] = Counter()
    rows_with_cell = 0
    for row in result.values:
        flagged = False
        for index, cell in enumerate(row):
            if cell == "DATA_UNAVAILABLE":
                flagged = True
                columns[headers[index] if index < len(headers) else f"col_{index}"] += 1
        rows_with_cell += int(flagged)
    return {
        "rows": len(result.values),
        "rows_with_data_unavailable_cell": rows_with_cell,
        "data_unavailable_cells_by_column": dict(sorted(columns.items())),
        "meta": _meta_summary(result.meta),
        "recovery": _recovery_summary(result.recovery),
        "additional_recoveries": len(result.additional_recoveries),
    }


async def _run(
    handlers: Mapping[str, Any],
    name: str,
    seller_id: str,
    args: Mapping[str, Any],
    registry: FormulaRegistry,
) -> tuple[FormulaExecutionResult | None, dict[str, Any]]:
    contract = registry.get(name)
    defaults = {
        parameter.name: parameter.default
        for parameter in contract.parameters
        if parameter.name != "cuenta" and not parameter.required
    }
    context = FormulaExecutionContext(
        contract=contract,
        cuenta="diagnostic",
        seller_id=seller_id,
        seller_nickname="diagnostic",
        token_id="diagnostic",  # noqa: S106 - a label, not a credential
        args={**defaults, **args},
        request_id=None,
    )
    started = time.monotonic()
    try:
        result = await handlers[name](context)
    except FormulaDataUnavailableError as exc:
        return None, {
            "outcome": "formula_unavailable",
            "reason": exc.message.partition(": ")[2][:120],
            "read_model": safe_code(exc.read_model),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    except Exception as exc:  # noqa: BLE001 - one broken replay must not hide the others
        return None, {"outcome": f"error_{type(exc).__name__}"}
    return result, {"outcome": "ok", "elapsed_ms": int((time.monotonic() - started) * 1000)}


def _handlers(repository: FormulaReadModelRepository, now: datetime) -> dict[str, Any]:
    def clock() -> datetime:
        return now

    return {
        **build_core_formula_handlers(repository, now_fn=clock),
        **build_item_shipping_catalog_formula_handlers(repository, now_fn=clock),
        **build_order_question_formula_handlers(repository, now_fn=clock),
        **build_quality_calculator_formula_handlers(repository, now_fn=clock),
        **build_remaining_phase4_formula_handlers(repository, now_fn=clock),
        **build_returns_histories_withdrawals_formula_handlers(repository, now_fn=clock),
    }


async def _section_inventory_replay(
    handlers: Mapping[str, Any], facts: _Facts, registry: FormulaRegistry
) -> dict[str, Any]:
    import zeler_sheets.formulas.handlers_item_shipping_catalog as shipping_module
    import zeler_sheets.formulas.handlers_quality_calculator as quality_module
    import zeler_sheets.formulas.handlers_remaining_phase4 as phase4_module
    import zeler_sheets.formulas.handlers_returns_histories_withdrawals as returns_module
    import zeler_sheets.formulas.matrix_contracts as contracts_module

    plan: dict[str, tuple[dict[str, Any], list[str]]] = {
        "ZELERDATA_CALIDAD": ({}, _headers(quality_module, "CALIDAD_HEADERS")),
        "ZELERDATA_CALCULADORA": (
            {"id_publicaciones": "todos"},
            _headers(quality_module, "CALCULADORA_HEADERS"),
        ),
        "ZELERDATA_PUBLICACIONESDESCUIDADAS": (
            {},
            _headers(returns_module, "PUBLICACIONES_DESCUIDADAS_HEADERS"),
        ),
        "ZELERDATA_CATALOGOSINVINCULAR": (
            {},
            _headers(shipping_module, "CATALOGOS_SIN_VINCULAR_HEADERS"),
        ),
        "ZELERDATA_CATALOGO": ({}, _headers(phase4_module, "CATALOGO_HEADERS")),
        "ZELERDATA_CATALOGOBUYBOX": (
            {},
            _headers(contracts_module, "CATALOGOBUYBOX_VISIBLE_HEADERS"),
        ),
        "ZELERDATA_CATALOGO_COMPLETO": (
            {},
            _headers(contracts_module, "CATALOGO_COMPLETO_VISIBLE_HEADERS"),
        ),
        "ZELERDATA_OBTENER_CATALOGO": (
            {},
            _headers(contracts_module, "OBTENER_CATALOGO_VISIBLE_HEADERS"),
        ),
    }
    report: dict[str, Any] = {}
    for name, (args, headers) in plan.items():
        result, status = await _run(handlers, name, facts.seller_id, args, registry)
        report[name] = {**status, **(_table_summary(result, headers) if result else {})}
    report["catalog_link_suggestion_rows"] = sum(
        1 for row in facts.row_order if _is_catalog_link_suggestion(row)
    )
    return report


def _pairs(rows: Sequence[Mapping[str, Any]]) -> tuple[list[str], list[str]]:
    seen: set[str] = set()
    skus: list[str] = []
    ids: list[str] = []
    for row in rows:
        if row["item_id"] in seen:
            continue
        seen.add(row["item_id"])
        skus.append(str(row["sku"]))
        ids.append(row["item_id"])
    return skus, ids


async def _replay_population(
    handlers: Mapping[str, Any],
    facts: _Facts,
    registry: FormulaRegistry,
    rows: list[dict[str, Any]],
    *,
    full_order_history: bool,
) -> dict[str, Any]:
    skus, ids = _pairs(rows)
    if not ids:
        return {"size": 0}
    today = facts.now.date()
    pair_args = {"skus": skus, "id_publicaciones": ids}
    plan: dict[str, tuple[dict[str, Any], str]] = {
        "ZELERDATA_PAUSADAS": ({"id_publicaciones": ids}, "status"),
        "ZELERDATA_TIEMPOACTIVA": ({"id_publicaciones": ids}, "state"),
        "ZELERDATA_MEDIDAS": (pair_args, "package"),
        "ZELERDATA_UNIDADESVENDIDAS": (
            {
                **pair_args,
                "fecha_inicial": (today - timedelta(days=7)).isoformat(),
                "fecha_final": today.isoformat(),
            },
            "sold",
        ),
        "ZELERDATA_DIASDESDEULTIMAVENTA": (pair_args, "sold"),
        "ZELERDATA_VENTAPORDIAS": ({**pair_args, "rango_dias": 7}, "sold"),
        "ZELERDATA_COSTOENVIOVENDEDOR": (pair_args, "sold"),
        "ZELERDATA_CALCULADORA": ({"id_publicaciones": ids}, "status"),
    }
    if not full_order_history:
        for name in FULL_ORDER_HISTORY_FORMULAS:
            del plan[name]
    codes = [str(row["inventory_id"]) for row in rows if row["inventory_id"]]
    if codes:
        plan["ZELERDATA_CODIGOML2SKUID"] = ({"codigo_ml": codes}, "status")
    population: dict[str, Any] = {
        "size": len(ids),
        "facts": {
            key: _counter(facts.facts_for(item_id)[key] for item_id in ids)
            for key in ("status", "state", "package", "sold")
        },
        "with_inventory_id": len(codes),
        "formulas": {},
    }
    for name, (args, fact_key) in plan.items():
        result, status = await _run(handlers, name, facts.seller_id, args, registry)
        entry: dict[str, Any] = dict(status)
        if result is not None:
            entry["meta"] = _meta_summary(result.meta)
            entry["recovery"] = _recovery_summary(result.recovery)
            if name in {"ZELERDATA_CODIGOML2SKUID", "ZELERDATA_CALCULADORA"}:
                entry["rows"] = len(result.values)
                entry["rows_with_data_unavailable_cell"] = sum(
                    1 for row in result.values if "DATA_UNAVAILABLE" in row
                )
            elif len(result.values) == len(ids):
                kinds = [_cell_kind(row[0] if row else None) for row in result.values]
                entry["outcomes"] = _counter(kinds)
                entry["outcome_by_" + fact_key] = _counter(
                    f"{kind}|{facts.facts_for(item_id)[fact_key]}"
                    for kind, item_id in zip(kinds, ids, strict=True)
                )
            else:
                entry["shape_mismatch_rows"] = len(result.values)
        population["formulas"][name] = entry
    return population


async def _section_single_identity(
    handlers: Mapping[str, Any], facts: _Facts, registry: FormulaRegistry
) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for label, rows in _population(facts).items():
        report[label] = await _replay_population(
            handlers, facts, registry, rows, full_order_history=label in FULL_ORDER_POPULATIONS
        )
    return report


def _classify_product_snapshot(
    snapshot: Mapping[str, Any] | None, *, seller_id: str, identity: str, now: datetime
) -> str:
    if snapshot is None:
        return "absent"
    observed = _safe_utc_datetime(snapshot.get("snapshot_at"))
    if not (
        snapshot.get("_id") == f"{seller_id}:{identity}"
        and observed is not None
        and observed <= now
        and snapshot.get("source") in SNAPSHOT_SOURCES
    ):
        return "invalid_identity_or_source"
    unavailable = snapshot.get("source_unavailable")
    checked = (
        _safe_utc_datetime(unavailable.get("observed_at"))
        if isinstance(unavailable, dict)
        else None
    )
    known_missing = (
        isinstance(unavailable, dict)
        and unavailable.get("reason") == "catalog_product_not_found"
        and checked is not None
        and now - FRESH < checked <= now
        and checked >= observed
    )
    if not now - PRODUCT_CACHE < observed:
        return "older_than_4h"
    if unavailable is not None and not known_missing:
        return "source_unavailable_not_current"
    title = snapshot.get("title")
    if not (isinstance(title, str) and title.strip()):
        return "title_missing"
    if not {"description", "image_url", "attributes"} <= snapshot.keys():
        return "payload_incomplete"
    if known_missing:
        return "ready_product_not_found_in_source"
    return "ready_current" if now - FRESH < observed else "ready_cached_4h"


async def _section_catalog(
    db: Any, facts: _Facts, repository: FormulaReadModelRepository
) -> dict[str, Any]:
    now = facts.now
    seller_id = facts.seller_id
    product_ids: set[str] = set()
    invalid_items = 0
    for source in facts.sources.values():
        for resource in [
            source,
            *[v for v in source.get("variations") or [] if isinstance(v, dict)],
        ]:
            identity = resource.get("catalog_product_id")
            if identity is None:
                continue
            if isinstance(identity, str) and re.fullmatch(r"ML[A-Z][0-9]+", identity):
                product_ids.add(identity)
            else:
                invalid_items += 1
    stored = {
        str(snapshot.get("catalog_product_id")): snapshot
        async for snapshot in db["sheets_catalog_product_snapshots"].find({"seller_id": seller_id})
    }
    products = _counter(
        _classify_product_snapshot(
            stored.get(identity), seller_id=seller_id, identity=identity, now=now
        )
        for identity in product_ids
    )
    product_ages = _counter(
        age_bucket(minutes_between(now, snapshot.get("snapshot_at")))
        for snapshot in stored.values()
    )

    participation: Counter[str] = Counter()
    participating: dict[str, dict[str, Any]] = {}
    for item_id, source in facts.sources.items():
        if source.get("catalog_listing") is False:
            participation["not_catalog_listing"] += 1
            continue
        product = source.get("catalog_product_id")
        quantity = source.get("available_quantity")
        if source.get("catalog_listing") is not True:
            participation["catalog_listing_unknown"] += 1
        elif not isinstance(product, str) or not re.fullmatch(r"ML[A-Z][0-9]+", product):
            participation["catalog_product_id_invalid"] += 1
        elif not (isinstance(source.get("title"), str) and source["title"].strip()):
            participation["title_blank"] += 1
        elif not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 0:
            participation["available_quantity_invalid"] += 1
        else:
            participation["participating"] += 1
            participating[item_id] = source
    buybox_docs = {
        str(snapshot.get("item_id")): snapshot
        async for snapshot in db["sheets_catalog_buybox_snapshots"].find({"seller_id": seller_id})
    }
    states: Counter[str] = Counter()
    ready_fields: Counter[str] = Counter()
    for item_id, source in participating.items():
        snapshot = buybox_docs.get(item_id)
        if snapshot is None:
            states["absent"] += 1
            continue
        observed = _safe_utc_datetime(snapshot.get("snapshot_at"))
        synced = _safe_utc_datetime(source.get("last_meli_sync_at"))
        # Same rules as the reader: its own age and fields, never the re-sync cut.
        if observed is None or synced is None:
            states["no_timestamp"] += 1
        elif not now - CATALOG_BUYBOX_CACHE_MAX_AGE < observed <= now:
            states["snapshot_older_than_cache_limit"] += 1
        elif not (
            snapshot.get("_id") == f"{seller_id}:{item_id}"
            and snapshot.get("source") in SNAPSHOT_SOURCES
            and snapshot.get("catalog_product_id") == source["catalog_product_id"]
            and snapshot.get("title") == source["title"].strip()
            and snapshot.get("available_quantity") == source.get("available_quantity")
        ):
            states["snapshot_does_not_match_item"] += 1
        else:
            states["ready_current" if now - FRESH < observed else "ready_cached"] += 1
            shared = snapshot.get("competitors_sharing_first_place", "key_absent")
            offers_at = snapshot.get("offers_snapshot_at", snapshot.get("snapshot_at"))
            ready_fields[
                f"buybox_status_{'present' if snapshot.get('buybox_status') else 'absent'}"
            ] += 1
            ready_fields[
                f"price_{'present' if snapshot.get('price') is not None else 'absent'}"
            ] += 1
            ready_fields[
                "shared_users_"
                + ("key_absent" if shared == "key_absent" else "null" if shared is None else "int")
            ] += 1
            ready_fields[f"only_competitor_{type(snapshot.get('only_competitor')).__name__}"] += 1
            ready_fields["offers_" + age_bucket(minutes_between(now, offers_at))] += 1
    stored_fields: Counter[str] = Counter()
    for snapshot in buybox_docs.values():
        shared = snapshot.get("competitors_sharing_first_place", "key_absent")
        stored_fields[
            "shared_users_"
            + ("key_absent" if shared == "key_absent" else "null" if shared is None else "int")
        ] += 1
        stored_fields[f"only_competitor_{type(snapshot.get('only_competitor')).__name__}"] += 1
        stored_fields[
            "snapshot_" + age_bucket(minutes_between(now, snapshot.get("snapshot_at")))
        ] += 1
    as_of, covered, recovery = await repository.catalog_sales_coverage(
        seller_id=seller_id,
        formula="ZELERDATA_CATALOGO",
        now=now,
        windows=tuple(CATALOGO_SALES_WINDOWS),
    )
    return {
        "product_ids_in_items": len(product_ids),
        "items_with_invalid_product_id": invalid_items,
        "product_snapshots_by_reader_state": products,
        "product_snapshots_stored_by_age": product_ages,
        "buybox_participation": dict(sorted(participation.items())),
        "buybox_by_reader_state": dict(sorted(states.items())),
        "buybox_ready_field_states": dict(sorted(ready_fields.items())),
        "buybox_stored_field_states": dict(sorted(stored_fields.items())),
        "sales_windows": {
            "as_of_age_bucket": age_bucket(minutes_between(now, as_of)),
            "covered_days": sorted(covered),
            "recovery_needed": recovery is not None,
        },
    }


async def _section_markers(
    db: Any, facts: _Facts, repository: FormulaReadModelRepository
) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for model in READ_MODELS_FOR_MARKERS:
        marker = await db["sheets_read_model_freshness"].find_one(
            {"_id": f"{facts.seller_id}:{model}", "seller_id": facts.seller_id}
        )
        if marker is None:
            report[model] = {"marker": "absent"}
            continue
        report[model] = {
            "marker": "present",
            "state": safe_code(marker.get("state")),
            "productive_now": bool(_read_model_freshness_marker_covers(marker, date_to=facts.now)),
            "valid_until_age_bucket": age_bucket(
                minutes_between(facts.now, marker.get("valid_until"))
            ),
            "reconciled_until_age_bucket": age_bucket(
                minutes_between(facts.now, marker.get("reconciled_until"))
            ),
        }
    return report


async def _section_jobs(db: Any, facts: _Facts) -> dict[str, Any]:
    pipeline = [
        {"$match": {"seller_id": facts.seller_id}},
        {"$group": {"_id": {"m": "$read_model", "s": "$state"}, "n": {"$sum": 1}}},
    ]
    return {
        f"{safe_code(entry['_id'].get('m'))}:{safe_code(entry['_id'].get('s'))}": entry["n"]
        async for entry in db["sheets_formula_recovery_jobs"].aggregate(pipeline)
    }


async def _guard(awaitable: Awaitable[Any]) -> Any:
    try:
        return await awaitable
    except Exception as exc:  # noqa: BLE001 - report the failed section, keep the rest
        return {"error": type(exc).__name__}


async def diagnose(database: Any, *, seller_id: str, now: datetime) -> dict[str, Any]:
    db = ReadOnlyDatabase(database)
    facts = await _load(db, seller_id, now)
    repository = FormulaReadModelRepository(db=db)
    handlers = _handlers(repository, now)
    registry = FormulaRegistry.default()
    verification = _section_verification(facts)
    return {
        "generated_at_utc": now.isoformat(),
        "inventory_enumeration": _section_enumeration(facts),
        "item_verification": verification,
        "item_sync_ages": verification.pop("item_sync_ages"),
        "row_fields": _row_counts(facts),
        "identity_facts": _identity_facts(facts),
        "freshness_markers": await _guard(_section_markers(db, facts, repository)),
        "recovery_jobs_by_model_state": await _guard(_section_jobs(db, facts)),
        "catalog": await _guard(_section_catalog(db, facts, repository)),
        "inventory_replay": await _guard(_section_inventory_replay(handlers, facts, registry)),
        "single_identity_replay": await _guard(_section_single_identity(handlers, facts, registry)),
    }


def main() -> None:
    mongo_uri = os.environ.get("MONGO_URI")
    mongo_db_name = os.environ.get("MONGO_DB")
    if not mongo_uri or not mongo_db_name:
        raise SystemExit("MONGO_URI and MONGO_DB are required")
    from motor.motor_asyncio import AsyncIOMotorClient

    seller_id = os.environ.get("ZELERDATA_DIAG_SELLER") or PILOT_SELLER
    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(mongo_uri)
    try:
        report = asyncio.run(
            diagnose(client[mongo_db_name], seller_id=seller_id, now=datetime.now(UTC))
        )
    finally:
        client.close()
    print(json.dumps(report, indent=2, sort_keys=True, default=str))  # noqa: T201


if __name__ == "__main__":
    main()
