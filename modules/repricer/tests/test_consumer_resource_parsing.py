from __future__ import annotations

import pytest

from zeler_repricer.consumer import _item_id_from_resource


def test_parses_legacy_items_path() -> None:
    assert _item_id_from_resource("/items/MLA123") == "MLA123"


def test_parses_price_suggestion_format_a() -> None:
    assert _item_id_from_resource("suggestions/items/MLA123/details") == "MLA123"


def test_parses_price_suggestion_format_b() -> None:
    assert _item_id_from_resource("/marketplace/benchmarks/items/MLA123/details") == "MLA123"


def test_unknown_format_raises_value_error() -> None:
    with pytest.raises(ValueError, match="unsupported repricer resource"):
        _item_id_from_resource("/foo/bar/baz")
