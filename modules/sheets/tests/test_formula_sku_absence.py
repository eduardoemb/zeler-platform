import pytest

from zeler_sheets.formulas.read_models import normalize_sku


@pytest.mark.parametrize(
    "raw, expected", [(None, ""), ("", ""), (0, "0"), ("None", "NONE"), (" sku ", "SKU")]
)
def test_normalize_sku_preserves_real_values_and_absence(raw: object, expected: str) -> None:
    assert normalize_sku(raw) == expected
