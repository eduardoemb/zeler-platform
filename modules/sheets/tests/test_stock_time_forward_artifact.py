from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from types import MappingProxyType, SimpleNamespace
from typing import Any

import pytest
from bson import Binary, Code, DBRef, Decimal128, ObjectId, Regex, Timestamp, json_util
from bson.json_util import JSONMode, JSONOptions

from zeler_sheets import _stock_time_forward_artifact as artifact

SELLER = "82453304"
START = datetime(2026, 6, 1, tzinfo=UTC)
END = datetime(2026, 6, 2, tzinfo=UTC)
OPTIONS = JSONOptions(json_mode=JSONMode.CANONICAL, tz_aware=True, tzinfo=UTC)


class _DecimalSubclass(Decimal):
    pass


def payload(**extra: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "read_model": "stock_time_metrics",
        "seller_id": SELLER,
        "date_from": "2026-06-01",
        "date_to_exclusive": "2026-06-02",
        "source_inventory": [
            {"item_id": "not-yet-validated", "revision": "deferred", "nested": ["opaque secret"]}
        ],
        **extra,
    }


def raw(document: dict[str, Any]) -> bytes:
    return (
        json_util.dumps(
            document, json_options=OPTIONS, sort_keys=True, separators=(",", ":")
        ).encode()
        + b"\n"
    )


def load(document: dict[str, Any], **args: Any) -> artifact._StockTimeForwardArtifact:
    encoded = raw(document)
    return artifact._load_stock_time_forward_artifact(
        encoded,
        sha256(encoded).hexdigest(),
        args.get("seller_id", SELLER),
        args.get("date_from", START),
        args.get("date_to_exclusive", END),
    )


def stock_source(item_id: str = "MLM-1", *, projection_id: str | None = None) -> dict[str, Any]:
    return {
        "_id": projection_id or f"projection-{item_id}",
        "seller_id": SELLER,
        "item_id": item_id,
        "title": "Stock item",
        "variations_history": {
            "SKU-1": [{"status2": "active", "changed_at": datetime(2026, 5, 31, tzinfo=UTC)}]
        },
    }


def materialize(document: dict[str, Any], **args: Any) -> artifact._StockTimeForwardMaterialization:
    encoded = raw(document)
    return artifact._load_and_materialize_stock_time_forward_artifact(
        encoded,
        sha256(encoded).hexdigest(),
        args.get("seller_id", SELLER),
        args.get("date_from", START),
        args.get("date_to_exclusive", END),
    )


def test_loads_exact_canonical_envelope_and_deep_freezes_inventory() -> None:
    encoded = raw(payload())
    result = load(payload())

    assert result.sha256 == sha256(encoded).hexdigest()
    assert result.seller_id == SELLER
    assert result.date_from == START and result.date_to_exclusive == END
    assert isinstance(result.source_inventory, tuple)
    assert isinstance(result.source_inventory[0], MappingProxyType)
    assert result.source_inventory[0]["nested"] == ("opaque secret",)
    with pytest.raises(TypeError):
        result.source_inventory[0]["item_id"] = "changed"  # type: ignore[index]
    assert "opaque secret" not in repr(result)
    assert not hasattr(result, "planned_documents")


@pytest.mark.parametrize(
    ("encoded", "expected", "code"),
    [
        (b"", "0" * 64, "INVALID_RAW"),
        (b"\xef\xbb\xbf{}", "0" * 64, "BOM_FORBIDDEN"),
        (b"\xff", "0" * 64, "INVALID_UTF8"),
        (b'{"schema_version":1,"schema_version":1}', "0" * 64, "DUPLICATE_JSON_KEY"),
        (b"{}", "A" * 64, "INVALID_SHA256"),
    ],
)
def test_rejects_raw_boundaries_duplicate_keys_and_non_lowercase_hash(
    encoded: bytes, expected: str, code: str
) -> None:
    with pytest.raises(artifact._StockTimeForwardArtifactError, match=f"^{code}$"):
        artifact._load_stock_time_forward_artifact(encoded, expected, SELLER, START, END)


def test_requires_exact_canonical_ejson_bytes_and_matching_digest() -> None:
    encoded = raw(payload())
    cases = [
        (encoded, "0" * 64, "SHA256_MISMATCH"),
        (encoded[:-1], sha256(encoded[:-1]).hexdigest(), "NONCANONICAL_EJSON"),
        (encoded + b" ", sha256(encoded + b" ").hexdigest(), "NONCANONICAL_EJSON"),
        (b" " * (2 * 1024 * 1024 + 1), "0" * 64, "INVALID_RAW"),
    ]
    for candidate, expected, code in cases:
        with pytest.raises(artifact._StockTimeForwardArtifactError, match=f"^{code}$"):
            artifact._load_stock_time_forward_artifact(candidate, expected, SELLER, START, END)


@pytest.mark.parametrize(
    ("changes", "args", "code"),
    [
        ({"extra": True}, {}, "INVALID_TOP_LEVEL"),
        ({"seller_id": "bad"}, {}, "INVALID_SELLER"),
        ({"seller_id": "82453305"}, {}, "SCOPE_MISMATCH"),
        ({"date_from": "2026-06-01T00:00:00Z"}, {}, "INVALID_DATE"),
        ({"date_to_exclusive": "2026-06-01"}, {}, "INVALID_INTERVAL"),
        ({"date_to_exclusive": "2026-07-03"}, {}, "INVALID_INTERVAL"),
        ({}, {"date_from": START + timedelta(days=1)}, "SCOPE_MISMATCH"),
        ({"source_inventory": []}, {}, "INVALID_SOURCE_COUNT"),
        ({"source_inventory": [{}] * 251}, {}, "INVALID_SOURCE_COUNT"),
        ({"source_inventory": ["not-a-mapping"]}, {}, "INVALID_SOURCE_ROW"),
    ],
)
def test_enforces_envelope_scope_and_inventory_shape(
    changes: dict[str, Any], args: dict[str, Any], code: str
) -> None:
    with pytest.raises(artifact._StockTimeForwardArtifactError, match=f"^{code}$"):
        load(payload(**changes), **args)


@pytest.mark.parametrize(
    ("encoded", "code"),
    [
        (b"\xff", "INVALID_UTF8"),
        (b'{"$date":"not-a-date"}\n', "INVALID_EJSON"),
        (raw(payload(date_from="2026-02-30")), "INVALID_DATE"),
        (raw(payload(source_inventory=[{"value": Code("x")}])), "INVALID_SOURCE_ROW"),
        (raw(payload(read_model="other")), "INVALID_READ_MODEL"),
    ],
)
def test_bounded_errors_have_no_graph_or_raw_bytes(encoded: bytes, code: str) -> None:
    with pytest.raises(artifact._StockTimeForwardArtifactError, match=f"^{code}$") as raised:
        artifact._load_stock_time_forward_artifact(
            encoded, sha256(encoded).hexdigest(), SELLER, START, END
        )
    assert raised.value.code in artifact._ERROR_CODES
    assert str(raised.value) == raised.value.code
    assert raised.value.__cause__ is raised.value.__context__ is None
    assert repr(encoded) not in repr(raised.value)
    assert not hasattr(__import__("zeler_sheets"), "load_stock_time_forward_artifact")
    assert not {"Path", "open", "os", "pathlib", "requests", "socket"} & set(vars(artifact))
    traceback = raised.value.__traceback__
    while traceback:
        if traceback.tb_frame.f_code.co_filename == artifact.__file__:
            assert encoded not in traceback.tb_frame.f_locals.values()
        traceback = traceback.tb_next


@pytest.mark.parametrize(
    "value",
    [
        Code("x", {"mutable": []}),
        DBRef("items", "item"),
        Binary(b"item"),
        Regex("^item"),
        ObjectId(),
        Decimal128("1.5"),
        Timestamp(1, 2),
    ],
)
def test_rejects_bson_wrappers_and_unknown_mutable_values(value: Any) -> None:
    with pytest.raises(artifact._StockTimeForwardArtifactError, match="^INVALID_SOURCE_ROW$"):
        load(payload(source_inventory=[{"value": value}]))
    with pytest.raises(artifact._StockTimeForwardArtifactError, match="^INVALID_SOURCE_ROW$"):
        artifact._freeze_source_inventory(({"value": object()},))


def test_freeze_preserves_immutable_json_and_utc_date_scalars() -> None:
    safe = [None, True, 1, 1.5, "safe", START]
    frozen = load(payload(source_inventory=[{"values": safe}])).source_inventory[0]["values"]
    assert frozen == tuple(safe)
    assert tuple(type(value) for value in frozen) == (type(None), bool, int, float, str, datetime)
    for value in frozen:
        assert not hasattr(value, "__dict__"), type(value)
        with pytest.raises(AttributeError):
            value.mutable = True


def test_materializes_canonical_mlm_history_deterministically_and_deep_freezes() -> None:
    first = materialize(payload(source_inventory=[stock_source("MLM-2"), stock_source("MLM-1")]))
    second = materialize(payload(source_inventory=[stock_source("MLM-1"), stock_source("MLM-2")]))

    assert first.envelope.sha256 != second.envelope.sha256
    assert first.planned_documents == second.planned_documents
    assert tuple(document["_id"] for document in first.planned_documents) == (
        "82453304:MLM-1:SKU-1:2026-06-01:2026-06-02",
        "82453304:MLM-2:SKU-1:2026-06-01:2026-06-02",
    )
    assert first.planned_documents[0] == {
        "_id": "82453304:MLM-1:SKU-1:2026-06-01:2026-06-02",
        "seller_id": SELLER,
        "item_id": "MLM-1",
        "sku": "SKU-1",
        "normalized_sku": "SKU-1",
        "title": "Stock item",
        "url": None,
        "date_from": START,
        "date_to": END,
        "active_stock_hours": Decimal("24"),
        "total_hours": Decimal("24"),
        "active_stock_percent": Decimal("100.0000"),
        "weeks": ({"start_day": 1, "end_day": 1, "has_stock": True},),
        "source": "legacy_history_import",
        "history_basis": "legacy_imported",
        "coverage_basis": "legacy_imported",
        "schema_version": 1,
    }
    assert isinstance(first.planned_documents, tuple)
    assert isinstance(first.planned_documents[0], MappingProxyType)
    assert type(first.planned_documents[0]["total_hours"]) is Decimal
    with pytest.raises(TypeError):
        first.planned_documents[0]["title"] = "changed"
    with pytest.raises(TypeError):
        first.planned_documents[0]["weeks"][0]["has_stock"] = False


def test_one_projection_with_two_complete_variations_yields_two_deterministic_documents() -> None:
    source = stock_source()
    source["variations_history"] = {
        "SKU-2": [{"status2": "active", "changed_at": datetime(2026, 5, 31, tzinfo=UTC)}],
        "SKU-1": [{"status2": "active", "changed_at": datetime(2026, 5, 31, tzinfo=UTC)}],
    }
    reverse_source = stock_source()
    reverse_source["variations_history"] = dict(reversed(source["variations_history"].items()))
    first = materialize(payload(source_inventory=[source]))
    second = materialize(payload(source_inventory=[reverse_source]))

    assert first.planned_documents == second.planned_documents
    assert len(first.planned_documents) == 2
    assert tuple(document["sku"] for document in first.planned_documents) == ("SKU-1", "SKU-2")


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"seller_id": "82453305"}, "SOURCE_SELLER_MISMATCH"),
        ({"item_id": " MLM-1"}, "INVALID_SOURCE_ITEM"),
        ({"_id": " projection"}, "INVALID_PROJECTION_IDENTITY"),
        ({"revision": "forbidden"}, "SOURCE_REVISION_FORBIDDEN"),
    ],
)
def test_materialization_requires_exact_source_scope_identity_item_and_revision(
    change: dict[str, Any], code: str
) -> None:
    source = stock_source()
    source.update(change)
    with pytest.raises(artifact._StockTimeForwardArtifactError, match=f"^{code}$"):
        materialize(payload(source_inventory=[source]))


def test_materialization_rejects_duplicate_source_identity_and_item_id() -> None:
    duplicate_identity = [
        stock_source("MLM-1", projection_id="one"),
        stock_source("MLM-2", projection_id="one"),
    ]
    duplicate_item = [
        stock_source("MLM-1", projection_id="one"),
        stock_source("MLM-1", projection_id="two"),
    ]
    for rows, code in (
        (duplicate_identity, "DUPLICATE_PROJECTION_IDENTITY"),
        (duplicate_item, "DUPLICATE_SOURCE_ITEM_ID"),
    ):
        with pytest.raises(artifact._StockTimeForwardArtifactError, match=f"^{code}$"):
            materialize(payload(source_inventory=rows))


@pytest.mark.parametrize(
    ("source", "code"),
    [
        (stock_source() | {"payload": "x" * (64 * 1024)}, "SOURCE_ROW_TOO_LARGE"),
        (stock_source() | {"variations_history": {}}, "INCOMPLETE_SOURCE_COVERAGE"),
    ],
)
def test_materialization_rejects_source_size_and_incomplete_coverage(
    source: dict[str, Any], code: str
) -> None:
    with pytest.raises(artifact._StockTimeForwardArtifactError, match=f"^{code}$"):
        materialize(payload(source_inventory=[source]))


@pytest.mark.parametrize(
    ("documents", "source_count", "code"),
    [
        ([], 0, "INVALID_PLANNED_COUNT"),
        (["duplicate", "duplicate"], 2, "DUPLICATE_PLANNED_ID"),
        (["revision"], 1, "PLANNED_REVISION_FORBIDDEN"),
        (["oversized"], 1, "PLANNED_DOCUMENT_TOO_LARGE"),
    ],
)
def test_materialization_enforces_generated_count_identity_revision_and_size(
    monkeypatch: pytest.MonkeyPatch, documents: list[str], source_count: int, code: str
) -> None:
    document = dict(materialize(payload(source_inventory=[stock_source()])).planned_documents[0])
    generated: list[dict[str, Any]] = []
    for case in documents:
        candidate = dict(document)
        if case == "revision":
            candidate["revision"] = "forbidden"
        elif case == "oversized":
            candidate["payload"] = "x" * (32 * 1024)
        generated.append(candidate)
    monkeypatch.setattr(
        artifact,
        "_stock_time_metric_documents",
        lambda *_args, **_kwargs: SimpleNamespace(
            documents=generated, source_inventory_count=source_count, coverage_complete=True
        ),
    )
    with pytest.raises(artifact._StockTimeForwardArtifactError, match=f"^{code}$"):
        materialize(payload(source_inventory=[stock_source()]))


def test_materialization_rejects_valid_looking_arbitrary_generated_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = dict(materialize(payload(source_inventory=[stock_source()])).planned_documents[0])
    document["_id"] = "82453304:MLM-999:SKU-1:2026-06-01:2026-06-02"
    monkeypatch.setattr(
        artifact,
        "_stock_time_metric_documents",
        lambda *_args, **_kwargs: SimpleNamespace(
            documents=[document], source_inventory_count=1, coverage_complete=True
        ),
    )

    with pytest.raises(artifact._StockTimeForwardArtifactError, match="^INVALID_PLANNED_ID$"):
        materialize(payload(source_inventory=[stock_source()]))


@pytest.mark.parametrize("value", [Decimal("24"), _DecimalSubclass("24")])
def test_materialization_freezes_only_exact_generated_decimal(
    monkeypatch: pytest.MonkeyPatch, value: Decimal
) -> None:
    document = dict(materialize(payload(source_inventory=[stock_source()])).planned_documents[0])
    document["total_hours"] = value
    monkeypatch.setattr(
        artifact,
        "_stock_time_metric_documents",
        lambda *_args, **_kwargs: SimpleNamespace(
            documents=[document], source_inventory_count=1, coverage_complete=True
        ),
    )

    if type(value) is Decimal:
        result = materialize(payload(source_inventory=[stock_source()]))
        assert type(result.planned_documents[0]["total_hours"]) is Decimal
    else:
        with pytest.raises(
            artifact._StockTimeForwardArtifactError, match="^INVALID_PLANNED_DOCUMENT$"
        ):
            materialize(payload(source_inventory=[stock_source()]))


def test_materialization_rejects_unknown_helper_output(monkeypatch: pytest.MonkeyPatch) -> None:
    document = dict(materialize(payload(source_inventory=[stock_source()])).planned_documents[0])
    document["opaque"] = object()
    monkeypatch.setattr(
        artifact,
        "_stock_time_metric_documents",
        lambda *_args, **_kwargs: SimpleNamespace(
            documents=[document], source_inventory_count=1, coverage_complete=True
        ),
    )

    with pytest.raises(artifact._StockTimeForwardArtifactError, match="^INVALID_PLANNED_DOCUMENT$"):
        materialize(payload(source_inventory=[stock_source()]))


def test_materialization_errors_are_bounded_and_private(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_helper(*_args: Any, **_kwargs: Any) -> None:
        try:
            raise ValueError("Stock item")
        except ValueError as error:
            raise RuntimeError("opaque helper failure") from error

    monkeypatch.setattr(artifact, "_stock_time_metric_documents", broken_helper)
    with pytest.raises(
        artifact._StockTimeForwardArtifactError, match="^INVALID_PLANNED_DOCUMENT$"
    ) as raised:
        materialize(payload(source_inventory=[stock_source()]))
    assert raised.value.__cause__ is raised.value.__context__ is None
    assert "Stock item" not in repr(raised.value)
    assert not hasattr(__import__("zeler_sheets"), "materialize_stock_time_forward_artifact")
    assert not {"Path", "open", "os", "pathlib", "requests", "socket"} & set(vars(artifact))
