from __future__ import annotations

import json
from pathlib import Path

import pytest
from infra.operations.devoluciones_timer_status import main
from infra.operations.zelerdata_campaign_state import CampaignStateStore

VALID_CAMPAIGN_ID = "campaign-a"
SOURCE_HASH = "a" * 64
READ_HASH = "b" * 64
STATUS_KEYS = {
    "timer_active",
    "accepted_through",
    "has_accepted_campaign",
    "accepted_campaign_id",
    "p95_seconds",
    "sample_count",
}


def _campaign_evidence(
    campaign_id: str = VALID_CAMPAIGN_ID,
    *,
    duration: float = 100.0,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "event": "zelerdata_devoluciones_scheduled_run",
        "campaign_id": campaign_id,
        "outcome": "success",
        "reason": "candidate_sample_recorded",
        "duration_seconds": duration,
        "physical_attempts": 16,
        "source_fingerprint_hash": SOURCE_HASH,
        "read_model_fingerprint_hash": READ_HASH,
        "counters": {"P": 4, "R": 8, "O": 4, "T": 16},
        "campaign_disqualified": False,
        "reset_required": False,
    }


def _service_environment(
    *,
    campaign_id: str = VALID_CAMPAIGN_ID,
    source_hash: str = SOURCE_HASH,
    read_hash: str = READ_HASH,
    accepted_through: str = "2026-07-09",
) -> str:
    return (
        f"ZELERDATA_DEVOLUCIONES_CAMPAIGN_ID={campaign_id}\n"
        f"ZELERDATA_DEVOLUCIONES_SOURCE_FINGERPRINT_HASH={source_hash}\n"
        f"ZELERDATA_DEVOLUCIONES_READ_MODEL_FINGERPRINT_HASH={read_hash}\n"
        f"ZELERDATA_DEVOLUCIONES_ACCEPTED_THROUGH={accepted_through}\n"
    )


def _run_status(
    state_path: Path,
    env_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> dict[str, object]:
    exit_code = main(
        [
            "--state-file",
            str(state_path),
            "--service-environment-file",
            str(env_path),
        ]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert isinstance(payload, dict)
    return payload


def test_no_accepted_campaign_reports_disabled_and_redacts_private_payload(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_path = tmp_path / "campaign.json"
    store = CampaignStateStore(state_path)
    store.record(_campaign_evidence("candidate-x", duration=42.0))
    env_path = tmp_path / "service.env"
    env_path.write_text(
        _service_environment(campaign_id="candidate-x"),
        encoding="utf-8",
    )

    payload = _run_status(state_path, env_path, capsys)
    output = capsys.readouterr().out

    assert set(payload) == STATUS_KEYS
    assert payload["timer_active"] is False
    assert payload["has_accepted_campaign"] is False
    assert payload["accepted_campaign_id"] is None
    assert payload["p95_seconds"] is None
    assert payload["sample_count"] == 0
    assert payload["accepted_through"] == "2026-07-09"
    assert SOURCE_HASH not in output
    assert READ_HASH not in output


def test_accepted_campaign_reports_active_gate_and_aggregates_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_path = tmp_path / "campaign.json"
    store = CampaignStateStore(state_path)
    for _ in range(20):
        store.record(_campaign_evidence())
    env_path = tmp_path / "service.env"
    env_path.write_text(
        _service_environment(accepted_through="2026-07-15"),
        encoding="utf-8",
    )

    payload = _run_status(state_path, env_path, capsys)
    output = capsys.readouterr().out

    assert set(payload) == STATUS_KEYS
    assert payload["timer_active"] is True
    assert payload["has_accepted_campaign"] is True
    assert payload["accepted_campaign_id"] == VALID_CAMPAIGN_ID
    assert payload["p95_seconds"] == 100.0
    assert payload["sample_count"] == 20
    assert payload["accepted_through"] == "2026-07-15"
    assert SOURCE_HASH not in output
    assert READ_HASH not in output


def test_release_fingerprint_drift_reports_disabled_without_exit_64(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_path = tmp_path / "campaign.json"
    store = CampaignStateStore(state_path)
    for _ in range(20):
        store.record(_campaign_evidence())
    env_path = tmp_path / "service.env"
    env_path.write_text(
        _service_environment(source_hash="c" * 64, read_hash="d" * 64),
        encoding="utf-8",
    )

    payload = _run_status(state_path, env_path, capsys)

    assert set(payload) == STATUS_KEYS
    assert payload["timer_active"] is False
    assert payload["has_accepted_campaign"] is False
    assert payload["accepted_campaign_id"] is None
    assert payload["p95_seconds"] is None
    assert payload["sample_count"] == 0


def test_missing_fingerprint_hash_exits_64_runtime_config_invalid(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_path = tmp_path / "campaign.json"
    env_path = tmp_path / "service.env"
    env_path.write_text(
        "ZELERDATA_DEVOLUCIONES_CAMPAIGN_ID=campaign-a\n"
        f"ZELERDATA_DEVOLUCIONES_SOURCE_FINGERPRINT_HASH={SOURCE_HASH}\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--state-file",
                str(state_path),
                "--service-environment-file",
                str(env_path),
            ]
        )
    assert exc_info.value.code == 64
    assert "runtime_config_invalid" in capsys.readouterr().err


def test_invalid_campaign_id_exits_64_runtime_config_invalid(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_path = tmp_path / "campaign.json"
    env_path = tmp_path / "service.env"
    env_path.write_text(
        _service_environment(campaign_id="bad%campaign"),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--state-file",
                str(state_path),
                "--service-environment-file",
                str(env_path),
            ]
        )
    assert exc_info.value.code == 64
    assert "runtime_config_invalid" in capsys.readouterr().err


def test_invalid_accepted_through_exits_64_runtime_config_invalid(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_path = tmp_path / "campaign.json"
    env_path = tmp_path / "service.env"
    env_path.write_text(
        _service_environment(accepted_through="2026-13-99"),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--state-file",
                str(state_path),
                "--service-environment-file",
                str(env_path),
            ]
        )
    assert exc_info.value.code == 64
    assert "runtime_config_invalid" in capsys.readouterr().err


def test_missing_environment_file_exits_64_runtime_config_invalid(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_path = tmp_path / "campaign.json"
    missing_env = tmp_path / "missing.env"

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--state-file",
                str(state_path),
                "--service-environment-file",
                str(missing_env),
            ]
        )
    assert exc_info.value.code == 64
    assert "runtime_config_invalid" in capsys.readouterr().err
