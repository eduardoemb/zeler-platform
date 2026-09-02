from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import MappingProxyType
from typing import Any

import pytest
from bson import Binary, Code, DBRef, Decimal128, ObjectId, Regex, Timestamp, json_util
from bson.json_util import JSONMode, JSONOptions

from zeler_sheets import _stock_time_forward_artifact as artifact

SELLER = "82453304"
START = datetime(2026, 6, 1, tzinfo=UTC)
END = datetime(2026, 6, 2, tzinfo=UTC)
OPTIONS = JSONOptions(json_mode=JSONMode.CANONICAL, tz_aware=True, tzinfo=UTC)


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
