from __future__ import annotations

import json
from pathlib import Path

import pytest
from infra.operations.zelerdata_campaign_state import (
    CampaignStateError,
    CampaignStateStore,
    PrivateCampaignSample,
    nearest_rank_p95,
    require_accepted_campaign,
)


def _evidence(
    campaign_id: str,
    *,
    duration: float = 100.0,
    outcome: str = "success",
    disqualified: bool = False,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "event": "zelerdata_devoluciones_scheduled_run",
        "campaign_id": campaign_id,
        "outcome": outcome,
        "reason": "candidate_sample_recorded" if outcome == "success" else "process_failed",
        "duration_seconds": duration,
        "physical_attempts": 16 if outcome == "success" else None,
        "source_fingerprint_hash": "a" * 64 if outcome == "success" else None,
        "read_model_fingerprint_hash": "b" * 64 if outcome == "success" else None,
        "counters": (
            {"P": 4, "R": 8, "O": 4, "T": 16}
            if outcome == "success"
            else {"P": None, "R": None, "O": None, "T": None}
        ),
        "campaign_disqualified": disqualified,
        "reset_required": disqualified,
    }


def _run_sample(campaign_id: str, run_id: str) -> PrivateCampaignSample:
    return PrivateCampaignSample(
        campaign_id=campaign_id,
        run_id=run_id,
        outcome="success",
        campaign_disqualified=False,
        duration_seconds=100.0,
        source_fingerprint_hash="a" * 64,
        read_model_fingerprint_hash="b" * 64,
    )


def test_nearest_rank_p95_uses_actual_eligible_window_size() -> None:
    assert nearest_rank_p95([float(value) for value in range(1, 22)]) == 20.0
    assert nearest_rank_p95([100.0, 149.0, 179.0]) == 179.0


def test_v2_cohort_counts_only_unique_marker_publishing_run_ids(tmp_path: Path) -> None:
    state_path = tmp_path / "campaign.json"
    store = CampaignStateStore(state_path)
    run_ids = [f"{index:064x}" for index in range(20)]
    for run_id in run_ids[:19]:
        store.record(_run_sample("campaign-v2", run_id))

    repeated = store.record(_run_sample("campaign-v2", run_ids[18]))
    assert repeated.campaigns["campaign-v2"]["run_ids"] == run_ids[:19]
    with pytest.raises(CampaignStateError, match="not accepted"):
        require_accepted_campaign(
            state_path,
            expected_campaign_id="campaign-v2",
            expected_source_fingerprint_hash="a" * 64,
            expected_read_model_fingerprint_hash="b" * 64,
        )

    store.record(_run_sample("campaign-v2", run_ids[19]))
    accepted = require_accepted_campaign(
        state_path,
        expected_campaign_id="campaign-v2",
        expected_source_fingerprint_hash="a" * 64,
        expected_read_model_fingerprint_hash="b" * 64,
    )

    assert accepted.sample_count == 20
    assert json.loads(state_path.read_text())["schema_version"] == 2
    accepted_state = state_path.read_bytes()

    repeated_after_acceptance = store.record(_run_sample("campaign-v2", "f" * 64))

    assert repeated_after_acceptance.accepted_campaign_id == "campaign-v2"
    assert repeated_after_acceptance.campaigns["campaign-v2"]["run_ids"] == run_ids
    assert state_path.read_bytes() == accepted_state


def test_v1_state_remains_readable_without_mutation_and_requires_new_v2_cohort(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "campaign.json"
    legacy = {
        "schema_version": 1,
        "disqualified_campaign_ids": [],
        "accepted_campaign_id": "legacy-campaign",
        "campaigns": {
            "legacy-campaign": {
                "source_fingerprint_hash": "a" * 64,
                "read_model_fingerprint_hash": "b" * 64,
                "durations": [100.0] * 20,
            }
        },
    }
    state_path.write_text(json.dumps(legacy, sort_keys=True, separators=(",", ":")))
    original = state_path.read_bytes()

    accepted = require_accepted_campaign(
        state_path,
        expected_campaign_id="legacy-campaign",
        expected_source_fingerprint_hash="a" * 64,
        expected_read_model_fingerprint_hash="b" * 64,
    )

    assert accepted.sample_count == 20
    assert state_path.read_bytes() == original
    with pytest.raises(CampaignStateError, match="new campaign"):
        CampaignStateStore(state_path).record(_run_sample("legacy-campaign", "1" * 64))


def test_v2_state_rejects_run_id_and_duration_cardinality_drift(tmp_path: Path) -> None:
    state_path = tmp_path / "campaign.json"
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "disqualified_campaign_ids": [],
                "accepted_campaign_id": None,
                "campaigns": {
                    "campaign-v2": {
                        "source_fingerprint_hash": "a" * 64,
                        "read_model_fingerprint_hash": "b" * 64,
                        "durations": [100.0],
                        "run_ids": ["1" * 64, "2" * 64],
                    }
                },
            }
        )
    )

    with pytest.raises(CampaignStateError, match="schema"):
        CampaignStateStore(state_path).load()


def test_disqualified_campaign_id_cannot_be_reused_after_another_campaign_accepts(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "campaign.json"
    store = CampaignStateStore(state_path)
    store.record(_evidence("campaign-a", outcome="failure", disqualified=True))
    for _ in range(20):
        store.record(_evidence("campaign-b"))

    accepted = require_accepted_campaign(
        state_path,
        expected_campaign_id="campaign-b",
        expected_source_fingerprint_hash="a" * 64,
        expected_read_model_fingerprint_hash="b" * 64,
    )
    assert accepted.campaign_id == "campaign-b"
    assert accepted.sample_count == 20
    assert accepted.p95_seconds == 100.0

    with pytest.raises(CampaignStateError, match="disqualified"):
        store.record(_evidence("campaign-a"))
    reloaded = CampaignStateStore(state_path).load()
    assert "campaign-a" in reloaded.disqualified_campaign_ids
    assert reloaded.accepted_campaign_id == "campaign-b"


def test_fingerprint_drift_is_durably_disqualified_before_failure_returns(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "campaign.json"
    store = CampaignStateStore(state_path)
    store.record(_evidence("campaign-a"))
    drifted = _evidence("campaign-a")
    drifted["source_fingerprint_hash"] = "c" * 64

    with pytest.raises(CampaignStateError, match="drift"):
        store.record(drifted)

    state = CampaignStateStore(state_path).load()
    assert "campaign-a" in state.disqualified_campaign_ids
    assert "campaign-a" not in state.campaigns


def test_timer_preflight_rejects_incomplete_or_budget_failing_campaign(tmp_path: Path) -> None:
    state_path = tmp_path / "campaign.json"
    store = CampaignStateStore(state_path)
    for _ in range(18):
        store.record(_evidence("campaign-a"))
    with pytest.raises(CampaignStateError, match="not accepted"):
        require_accepted_campaign(
            state_path,
            expected_campaign_id="campaign-a",
            expected_source_fingerprint_hash="a" * 64,
            expected_read_model_fingerprint_hash="b" * 64,
        )

    store.record(_evidence("campaign-a", duration=150.0))
    store.record(_evidence("campaign-a", duration=150.0))
    with pytest.raises(CampaignStateError, match="not accepted"):
        require_accepted_campaign(
            state_path,
            expected_campaign_id="campaign-a",
            expected_source_fingerprint_hash="a" * 64,
            expected_read_model_fingerprint_hash="b" * 64,
        )


@pytest.mark.parametrize(
    ("campaign_id", "source_hash", "read_hash"),
    [
        ("campaign-b", "a" * 64, "b" * 64),
        ("campaign-a", "c" * 64, "b" * 64),
        ("campaign-a", "a" * 64, "d" * 64),
    ],
)
def test_accepted_campaign_cannot_authorize_different_service_release(
    tmp_path: Path,
    campaign_id: str,
    source_hash: str,
    read_hash: str,
) -> None:
    state_path = tmp_path / "campaign.json"
    store = CampaignStateStore(state_path)
    for _ in range(20):
        store.record(_evidence("campaign-a"))

    with pytest.raises(CampaignStateError, match="service|release|match"):
        require_accepted_campaign(
            state_path,
            expected_campaign_id=campaign_id,
            expected_source_fingerprint_hash=source_hash,
            expected_read_model_fingerprint_hash=read_hash,
        )


def test_campaign_state_replace_is_atomic_and_leaves_no_temporary_file(tmp_path: Path) -> None:
    state_path = tmp_path / "campaign.json"
    CampaignStateStore(state_path).record(_evidence("campaign-a"))

    assert state_path.exists()
    assert [path for path in tmp_path.iterdir() if path.name != state_path.name] == []


def test_typed_private_sample_appends_to_legacy_v1_state_after_restart(tmp_path: Path) -> None:
    state_path = tmp_path / "campaign.json"
    legacy_store = CampaignStateStore(state_path)
    legacy_store.record(_evidence("campaign-a", duration=91.0))

    restarted_store = CampaignStateStore(state_path)
    restarted_store.record(
        PrivateCampaignSample(
            campaign_id="campaign-a",
            outcome="success",
            campaign_disqualified=False,
            duration_seconds=92.0,
            source_fingerprint_hash="a" * 64,
            read_model_fingerprint_hash="b" * 64,
        )
    )

    state = CampaignStateStore(state_path).load()
    assert state.campaigns["campaign-a"]["durations"] == [91.0, 92.0]
    assert state.campaigns["campaign-a"]["source_fingerprint_hash"] == "a" * 64
    assert state.campaigns["campaign-a"]["read_model_fingerprint_hash"] == "b" * 64


def test_private_failure_rejects_fingerprint_hashes_and_disqualifies_without_them(
    tmp_path: Path,
) -> None:
    with pytest.raises(CampaignStateError, match="success-only"):
        PrivateCampaignSample.from_mapping(
            {
                "campaign_id": "campaign-a",
                "outcome": "failure",
                "campaign_disqualified": True,
                "duration_seconds": 10.0,
                "source_fingerprint_hash": "a" * 64,
                "read_model_fingerprint_hash": "b" * 64,
            }
        )

    store = CampaignStateStore(tmp_path / "campaign.json")
    store.record(
        PrivateCampaignSample(
            campaign_id="campaign-a",
            outcome="failure",
            campaign_disqualified=True,
            duration_seconds=10.0,
        )
    )
    assert store.load().disqualified_campaign_ids == frozenset({"campaign-a"})


def test_repeated_private_failure_is_idempotent_for_an_already_disqualified_campaign(
    tmp_path: Path,
) -> None:
    store = CampaignStateStore(tmp_path / "campaign.json")
    failed = PrivateCampaignSample(
        campaign_id="campaign-a",
        outcome="failure",
        campaign_disqualified=True,
        duration_seconds=10.0,
    )

    store.record(failed)
    repeated = store.record(failed)

    assert repeated.disqualified_campaign_ids == frozenset({"campaign-a"})
    assert "campaign-a" not in repeated.campaigns


@pytest.mark.parametrize(
    ("drift_key", "drift_value"),
    [
        ("source_fingerprint_hash", "c" * 64),
        ("read_model_fingerprint_hash", "c" * 64),
    ],
)
def test_fingerprint_drift_on_accepted_campaign_is_refused_without_state_update(
    tmp_path: Path,
    drift_key: str,
    drift_value: str,
) -> None:
    state_path = tmp_path / "campaign.json"
    store = CampaignStateStore(state_path)
    for _ in range(20):
        store.record(_evidence("campaign-a"))
    assert store.load().accepted_campaign_id == "campaign-a"

    drifted = _evidence("campaign-a")
    drifted[drift_key] = drift_value
    with pytest.raises(CampaignStateError, match="drift"):
        store.record(drifted)

    state = CampaignStateStore(state_path).load()
    assert state.accepted_campaign_id == "campaign-a"
    assert "campaign-a" not in state.disqualified_campaign_ids
    assert state.campaigns["campaign-a"]["durations"] == [100.0] * 20
    assert state.campaigns["campaign-a"]["source_fingerprint_hash"] == "a" * 64
    assert state.campaigns["campaign-a"]["read_model_fingerprint_hash"] == "b" * 64
