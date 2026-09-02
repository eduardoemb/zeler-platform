"""Pure, private validation of reviewed stock-time artifact envelopes."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from types import MappingProxyType
from typing import Any, TypeVar

from bson import json_util
from bson.json_util import JSONMode, JSONOptions

_MAX_RAW_BYTES = 2 * 1024 * 1024
_MAX_SOURCE_ROWS = 250
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SELLER_ID = re.compile(r"^[0-9]{1,19}$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "read_model",
        "seller_id",
        "date_from",
        "date_to_exclusive",
        "source_inventory",
    }
)
_ERROR_CODES = frozenset(
    {
        "INVALID_SHA256",
        "INVALID_RAW",
        "BOM_FORBIDDEN",
        "INVALID_UTF8",
        "DUPLICATE_JSON_KEY",
        "INVALID_EJSON",
        "NONCANONICAL_EJSON",
        "SHA256_MISMATCH",
        "INVALID_TOP_LEVEL",
        "INVALID_SCHEMA_VERSION",
        "INVALID_READ_MODEL",
        "INVALID_SELLER",
        "SCOPE_MISMATCH",
        "INVALID_DATE",
        "INVALID_INTERVAL",
        "INVALID_SOURCE_COUNT",
        "INVALID_SOURCE_ROW",
    }
)
_JSON_OPTIONS = JSONOptions(json_mode=JSONMode.CANONICAL, tz_aware=True, tzinfo=UTC)
_T = TypeVar("_T")
_IMMUTABLE_SCALAR_TYPES = frozenset({type(None), bool, int, float, str, datetime})


class _StockTimeForwardArtifactError(ValueError):
    def __init__(self, code: str) -> None:
        if code not in _ERROR_CODES:
            raise ValueError("unknown stock-time forward artifact error code")
        self.code = code
        super().__init__(code)


def _bounded_call(callback: Callable[[], _T], code: str) -> _T:
    failed = False
    try:
        result = callback()
    except Exception:  # noqa: BLE001 - parser failures must not retain untrusted input.
        failed = True
    if failed:
        raise _StockTimeForwardArtifactError(code)
    return result


@dataclass(frozen=True)
class _StockTimeForwardArtifact:
    sha256: str
    seller_id: str = field(repr=False)
    date_from: datetime
    date_to_exclusive: datetime
    source_inventory: tuple[Mapping[str, Any], ...] = field(repr=False)


def _load_stock_time_forward_artifact(
    raw: bytes,
    expected_sha256: str,
    seller_id: str,
    date_from: datetime,
    date_to_exclusive: datetime,
) -> _StockTimeForwardArtifact:
    """Bind canonical local evidence without attesting to remote truth."""
    try:
        _validate_expected_sha256(expected_sha256)
        text = _decode_raw(raw)
        _reject_duplicate_keys(text)
        decoded = _decode_ejson(text)
        if _canonical_ejson(decoded) != raw:
            raise _StockTimeForwardArtifactError("NONCANONICAL_EJSON")
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise _StockTimeForwardArtifactError("SHA256_MISMATCH")
        document = _top_level_document(decoded)
        parsed_seller, start, end = _validate_scope(
            document, seller_id, date_from, date_to_exclusive
        )
        inventory = _validate_source_inventory(document["source_inventory"])
        return _StockTimeForwardArtifact(
            expected_sha256,
            parsed_seller,
            start,
            end,
            _freeze_source_inventory(inventory),
        )
    except _StockTimeForwardArtifactError as error:
        code = error.code
    del raw
    raise _StockTimeForwardArtifactError(code)


def _validate_expected_sha256(value: Any) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise _StockTimeForwardArtifactError("INVALID_SHA256")


def _decode_raw(raw: Any) -> str:
    if type(raw) is not bytes or not raw or len(raw) > _MAX_RAW_BYTES:
        raise _StockTimeForwardArtifactError("INVALID_RAW")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise _StockTimeForwardArtifactError("BOM_FORBIDDEN")
    return _bounded_call(lambda: raw.decode("utf-8"), "INVALID_UTF8")


def _reject_duplicate_keys(text: str) -> None:
    duplicate = False

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        nonlocal duplicate
        result: dict[str, Any] = {}
        for key, value in pairs:
            duplicate |= key in result
            result[key] = value
        return result

    invalid_ejson = False
    try:
        json.loads(text, object_pairs_hook=unique_object, parse_constant=_reject_json_constant)
    except (TypeError, ValueError, json.JSONDecodeError):
        invalid_ejson = True
    if duplicate:
        raise _StockTimeForwardArtifactError("DUPLICATE_JSON_KEY")
    if invalid_ejson:
        raise _StockTimeForwardArtifactError("INVALID_EJSON")


def _reject_json_constant(value: str) -> None:
    del value
    raise ValueError("non-finite JSON number")


def _decode_ejson(text: str) -> Any:
    return _bounded_call(lambda: json_util.loads(text, json_options=_JSON_OPTIONS), "INVALID_EJSON")


def _canonical_ejson(value: Any) -> bytes:
    return _bounded_call(
        lambda: (
            json_util.dumps(
                value, json_options=_JSON_OPTIONS, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            + b"\n"
        ),
        "INVALID_EJSON",
    )


def _top_level_document(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _TOP_LEVEL_KEYS:
        raise _StockTimeForwardArtifactError("INVALID_TOP_LEVEL")
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise _StockTimeForwardArtifactError("INVALID_SCHEMA_VERSION")
    if value.get("read_model") != "stock_time_metrics":
        raise _StockTimeForwardArtifactError("INVALID_READ_MODEL")
    return value


def _validate_scope(
    document: Mapping[str, Any], seller_id: Any, date_from: Any, date_to_exclusive: Any
) -> tuple[str, datetime, datetime]:
    seller = document.get("seller_id")
    if type(seller) is not str or _SELLER_ID.fullmatch(seller) is None:
        raise _StockTimeForwardArtifactError("INVALID_SELLER")
    start = _canonical_date(document.get("date_from"))
    end = _canonical_date(document.get("date_to_exclusive"))
    if end <= start or end - start > timedelta(days=31):
        raise _StockTimeForwardArtifactError("INVALID_INTERVAL")
    if (
        seller != seller_id
        or start != _utc_argument(date_from)
        or end != _utc_argument(date_to_exclusive)
    ):
        raise _StockTimeForwardArtifactError("SCOPE_MISMATCH")
    return seller, start, end


def _canonical_date(value: Any) -> datetime:
    if type(value) is not str or _DATE.fullmatch(value) is None:
        raise _StockTimeForwardArtifactError("INVALID_DATE")
    parsed = _bounded_call(lambda: date.fromisoformat(value), "INVALID_DATE")
    return datetime.combine(parsed, datetime.min.time(), tzinfo=UTC)


def _utc_argument(value: Any) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise _StockTimeForwardArtifactError("SCOPE_MISMATCH")
    return value.astimezone(UTC)


def _validate_source_inventory(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= _MAX_SOURCE_ROWS:
        raise _StockTimeForwardArtifactError("INVALID_SOURCE_COUNT")
    if not all(isinstance(row, Mapping) for row in value):
        raise _StockTimeForwardArtifactError("INVALID_SOURCE_ROW")
    return tuple(value)


def _freeze_source_inventory(value: tuple[Mapping[str, Any], ...]) -> tuple[Mapping[str, Any], ...]:
    return _bounded_call(
        lambda: tuple(_artifact_deep_freeze(row) for row in value), "INVALID_SOURCE_ROW"
    )


def _artifact_deep_freeze(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType({key: _artifact_deep_freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_artifact_deep_freeze(item) for item in value)
    if type(value) in _IMMUTABLE_SCALAR_TYPES and (
        type(value) is not datetime or value.tzinfo is UTC
    ):
        return value
    raise TypeError("unsupported artifact value")
