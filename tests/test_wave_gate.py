from __future__ import annotations

import json

import pytest
from infra.rollout import wave_gate


def test_wave_1_passes_with_all_services_green() -> None:
    result = wave_gate.evaluate_wave(
        1,
        health_source=lambda services, window: {service: True for service in services},
    )

    assert result.passed is True
    assert result.details["health_all_green"]["passed"] is True


def test_wave_2_fails_when_dlq_grew() -> None:
    result = wave_gate.evaluate_wave(
        2,
        health_source=lambda services, window: {service: True for service in services},
        metrics_source=lambda metric, window: 3 if metric == "dlq_events_total" else 0,
        logs_source=lambda severity, window: [],
        bootstrap_source=lambda: 0,
        paused_accounts_source=lambda window: 0,
    )

    assert result.passed is False
    assert result.details["dlq_depth_flat"]["delta"] == 3


def test_wave_2_passes_when_dlq_flat_24h() -> None:
    result = wave_gate.evaluate_wave(
        2,
        health_source=lambda services, window: {service: True for service in services},
        metrics_source=lambda metric, window: 0,
        logs_source=lambda severity, window: [],
        bootstrap_source=lambda: 0,
        paused_accounts_source=lambda window: 0,
    )

    assert result.passed is True
    assert result.details["dlq_depth_flat"]["window"] == "24h"


def test_cli_exits_nonzero_on_any_fail(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        wave_gate,
        "evaluate_wave",
        lambda wave: wave_gate.WaveEvaluation(
            passed=False,
            details={"health_all_green": {"passed": False, "services": {"gateway": False}}},
        ),
    )

    with pytest.raises(SystemExit) as exc_info:
        wave_gate.main(["--wave=1"])

    assert exc_info.value.code == 1
    assert json.loads(capsys.readouterr().out) == {
        "wave": 1,
        "status": "fail",
        "gates": [
            {
                "gate": "health_all_green",
                "status": "fail",
                "evidence": {"services": {"gateway": False}},
            }
        ],
    }


def test_cli_emits_json_on_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        wave_gate,
        "evaluate_wave",
        lambda wave: wave_gate.WaveEvaluation(
            passed=True,
            details={"health_all_green": {"passed": True, "services": {"gateway": True}}},
        ),
    )

    with pytest.raises(SystemExit) as exc_info:
        wave_gate.main(["--wave=2"])

    assert exc_info.value.code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pass"


def test_paused_count_predicate_passes_under_threshold() -> None:
    passed, details = wave_gate.no_paused_accounts_below(
        threshold=10,
        paused_accounts_source=lambda window: 4,
    )

    assert passed is True
    assert details["paused_count"] == 4


def test_paused_count_predicate_fails_over_threshold() -> None:
    passed, details = wave_gate.no_paused_accounts_below(
        threshold=10,
        paused_accounts_source=lambda window: 11,
    )

    assert passed is False
    assert details["paused_count"] == 11
