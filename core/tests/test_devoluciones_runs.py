from datetime import UTC, datetime, timedelta

import pytest

from zeler_platform_core.devoluciones_runs import (
    RunBinding,
    RunBindingDriftError,
    expires_at,
    is_expired,
    partition_windows,
)


def binding(**changes: object) -> RunBinding:
    values: dict[str, object] = {
        "authorization_id": "authorization-1",
        "cohort_id": "cohort-1",
        "seller_id": "seller-1",
        "scope": "devoluciones",
        "start": datetime(2026, 1, 1, tzinfo=UTC),
        "end": datetime(2026, 1, 26, tzinfo=UTC),
        "partition_version": "v1",
        "release_fingerprints": {"source": "source-v1", "read": "read-v1"},
    }
    values.update(changes)
    return RunBinding(**values)  # type: ignore[arg-type]


def test_binding_id_and_windows_are_deterministic_and_exact() -> None:
    run = binding()
    assert run.run_id == binding().run_id
    assert [(window.index, window.start, window.end) for window in partition_windows(run)] == [
        (0, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 11, tzinfo=UTC)),
        (1, datetime(2026, 1, 11, tzinfo=UTC), datetime(2026, 1, 21, tzinfo=UTC)),
        (2, datetime(2026, 1, 21, tzinfo=UTC), datetime(2026, 1, 26, tzinfo=UTC)),
    ]
    assert partition_windows(run)[0].window_id == partition_windows(binding())[0].window_id


@pytest.mark.parametrize("end, count, seconds", [(11, 1, 1070), (26, 3, 2860)])
def test_expiry_is_proportional_and_fails_closed_at_equality(
    end: int, count: int, seconds: int
) -> None:
    run = binding(end=datetime(2026, 1, end, tzinfo=UTC))
    deadline = expires_at(run, created_at=datetime(2026, 2, 1, tzinfo=UTC))
    assert len(partition_windows(run)) == count
    assert deadline == datetime(2026, 2, 1, tzinfo=UTC) + timedelta(seconds=seconds)
    assert is_expired(deadline, deadline)
    assert not is_expired(deadline - timedelta(microseconds=1), deadline)


@pytest.mark.parametrize(
    "changes",
    [
        {"seller_id": "seller-2"},
        {"start": datetime(2025, 12, 31, tzinfo=UTC)},
        {"release_fingerprints": {"source": "source-v2", "read": "read-v1"}},
    ],
)
def test_binding_rejects_identity_coverage_and_fingerprint_drift(
    changes: dict[str, object],
) -> None:
    with pytest.raises(RunBindingDriftError):
        binding().require_match(binding(**changes))
