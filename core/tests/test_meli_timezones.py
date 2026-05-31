from __future__ import annotations

from zeler_platform_core.meli_timezones import resolve_meli_timezone


def test_resolve_meli_timezone_maps_mlm_to_mexico_city_without_warning() -> None:
    resolution = resolve_meli_timezone("MLM")

    assert resolution.site_id == "MLM"
    assert resolution.timezone == "America/Mexico_City"
    assert resolution.fallback is False
    assert resolution.reason is None
    assert resolution.warning_fields == {}


def test_resolve_meli_timezone_falls_back_to_utc_for_missing_site_id() -> None:
    resolution = resolve_meli_timezone(None)

    assert resolution.site_id is None
    assert resolution.timezone == "UTC"
    assert resolution.fallback is True
    assert resolution.reason == "missing_site_id"
    assert resolution.warning_fields == {
        "site_id": None,
        "timezone": "UTC",
        "fallback": True,
        "reason": "missing_site_id",
    }


def test_resolve_meli_timezone_falls_back_to_utc_for_unmapped_site_id() -> None:
    resolution = resolve_meli_timezone("MCO")

    assert resolution.site_id == "MCO"
    assert resolution.timezone == "UTC"
    assert resolution.fallback is True
    assert resolution.reason == "unmapped_site_id"
    assert resolution.warning_fields == {
        "site_id": "MCO",
        "timezone": "UTC",
        "fallback": True,
        "reason": "unmapped_site_id",
    }
