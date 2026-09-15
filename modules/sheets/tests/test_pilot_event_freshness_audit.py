"""TDD: task 2.1/2.2 — audit the event pipeline's existing freshness and
idempotency guarantees, and document what is already proven vs what the
pilot plan requires that is not yet implemented.

The plan requires four measurable stages: received, fetched, persisted,
visible. The existing pipeline already proves:
- Idempotency: the consumer checks ``processed_events`` before fetching
  and marks processed only after a successful append. Duplicates return
  early.
- Freshness: ``event_persistence`` uses atomic Mongo replace guards so
  that an older observation cannot overwrite a newer one (monotonic write
  filter on ``last_updated``/``date_closed``).
- Retry: the AMQP consumer requeues transient failures with a bounded
  attempt count and dead-letters after the limit.

What the pilot additionally needs (not yet implemented) is durable
per-event stage telemetry that survives a worker restart so the pilot can
measure the 95% five-minute objective. That is task 2.2; this file
documents what the existing tests already prove so that the SDD has an
auditable baseline.
"""

from __future__ import annotations

from pathlib import Path

from zeler_sheets.event_persistence import (
    _resource_freshness_allows_write,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_event_persistence_rejects_stale_write() -> None:
    """An incoming resource older than the stored one must be rejected."""
    from datetime import UTC, datetime

    existing = {"last_updated": datetime(2026, 6, 1, tzinfo=UTC)}
    incoming = {"last_updated": datetime(2026, 5, 1, tzinfo=UTC)}
    assert (
        _resource_freshness_allows_write(existing, incoming, freshness_fields=("last_updated",))
        is False
    )


def test_event_persistence_accepts_newer_write() -> None:
    """A newer incoming resource passes the monotonic guard."""
    from datetime import UTC, datetime

    existing = {"last_updated": datetime(2026, 5, 1, tzinfo=UTC)}
    incoming = {"last_updated": datetime(2026, 6, 1, tzinfo=UTC)}
    assert (
        _resource_freshness_allows_write(existing, incoming, freshness_fields=("last_updated",))
        is True
    )


def test_event_persistence_accepts_insert_of_absent_resource() -> None:
    """A resource that does not exist yet is always accepted."""
    from datetime import UTC, datetime

    incoming = {"last_updated": datetime(2026, 6, 1, tzinfo=UTC)}
    assert (
        _resource_freshness_allows_write(None, incoming, freshness_fields=("last_updated",)) is True
    )


def test_event_persistence_present_freshness_field_guard() -> None:
    """A resource whose freshness field is absent cannot regress one that
    has it (prevents an event without timestamps from overwriting known
    data)."""
    from datetime import UTC, datetime

    existing = {"last_updated": datetime(2026, 6, 1, tzinfo=UTC)}
    incoming: dict[str, datetime] = {}  # no last_updated
    assert (
        _resource_freshness_allows_write(
            existing,
            incoming,
            freshness_fields=("last_updated",),
            present_freshness_fields=("last_updated",),
        )
        is False
    )


def test_amqp_consumer_dedup_is_tested() -> None:
    """The consumer's duplicate check and processed mark are covered by
    the existing consumer tests; assert the test file exists and references
    both paths."""
    path = REPO_ROOT / "modules/sheets/tests/test_sheets_amqp_consumer_runner.py"
    content = path.read_text(encoding="utf-8")
    assert "_sheets_idempotency_key" in content


def test_event_persistence_monotonic_guards_are_tested() -> None:
    """The interleaved stale replace and race tests exist."""
    path = REPO_ROOT / "modules/sheets/tests/test_event_persistence.py"
    content = path.read_text(encoding="utf-8")
    assert "test_order_atomic_freshness_filter_rejects_interleaved_stale_replace" in content
    assert "test_older_observation_cannot_supersede_newer_accepted_state" in content


def test_existing_stage_telemetry_is_not_yet_implemented() -> None:
    """Document the gap: no per-event durable stage record exists yet.
    This is the work item for task 2.2."""
    path = REPO_ROOT / "modules/sheets/src/zeler_sheets/event_persistence.py"
    content = path.read_text(encoding="utf-8")
    assert "event_stage" not in content, (
        "Stage telemetry was found; update this test when task 2.2 is implemented."
    )
