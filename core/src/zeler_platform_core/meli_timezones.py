from __future__ import annotations

from dataclasses import dataclass

MELI_SITE_TIMEZONES: dict[str, str] = {
    "MLM": "America/Mexico_City",
}

UTC_TIMEZONE = "UTC"


@dataclass(frozen=True)
class TimezoneResolution:
    site_id: str | None
    timezone: str
    fallback: bool
    reason: str | None

    @property
    def warning_fields(self) -> dict[str, str | bool | None]:
        if not self.fallback:
            return {}
        return {
            "site_id": self.site_id,
            "timezone": self.timezone,
            "fallback": self.fallback,
            "reason": self.reason,
        }


def resolve_meli_timezone(site_id: str | None) -> TimezoneResolution:
    normalized_site_id = site_id.strip().upper() if site_id else None
    if not normalized_site_id:
        return TimezoneResolution(
            site_id=None,
            timezone=UTC_TIMEZONE,
            fallback=True,
            reason="missing_site_id",
        )

    timezone = MELI_SITE_TIMEZONES.get(normalized_site_id)
    if timezone is None:
        return TimezoneResolution(
            site_id=normalized_site_id,
            timezone=UTC_TIMEZONE,
            fallback=True,
            reason="unmapped_site_id",
        )

    return TimezoneResolution(
        site_id=normalized_site_id,
        timezone=timezone,
        fallback=False,
        reason=None,
    )
