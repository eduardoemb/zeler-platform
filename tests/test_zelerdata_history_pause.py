import copy
from pathlib import Path
from typing import Any

import pytest
from infra.operations import zelerdata_history_pause as mod


class Fake:
    def __init__(self, role: str = "sheets-api", delay: float = 0, restart: bool = False) -> None:
        self.clock = 0.0
        self.delay = delay
        self.restart = restart
        self.commands: list[str] = []
        self.state: dict[str, Any] = {
            "Id": "id",
            "Image": mod.IMAGES[role],
            "RestartCount": 0,
            "Config": {"Cmd": ["sh", "-c", "uvicorn"], "Entrypoint": None, "StopSignal": ""},
            "HostConfig": {"RestartPolicy": {"Name": "unless-stopped"}},
            "State": {
                "Running": True,
                "Restarting": False,
                "Paused": False,
                "OOMKilled": False,
                "StartedAt": "original",
                "ExitCode": 0,
            },
        }
        self.role = role
        self.signaled = False
        self.shutdown_logs = ""

    def api_shutdown_complete(self, record: dict[str, Any]) -> bool:
        return mod.api_shutdown_complete(
            self.shutdown_logs, record["target"]["pid"], record["started_at"]
        )

    def inspect(self, _: str) -> dict[str, Any]:
        if self.signaled and self.clock >= self.delay:
            if self.restart:
                self.state["State"]["StartedAt"] = "new"
                self.state["RestartCount"] = 1
            else:
                self.state["State"]["Running"] = False
        return copy.deepcopy(self.state)

    def target(self, _: str, role: str) -> dict[str, Any]:
        return {"pid": 7 if role == "sheets-api" else 1, "start_ticks": "42", "role": role}

    def term(self, _: str) -> None:
        self.commands.append("docker_TERM")
        if self.role != "sheets-api":
            self.signaled = True

    def child_term(self, _: str, target: dict[str, Any]) -> None:
        assert target["start_ticks"] == "42"
        self.commands.append("verified_child_TERM")
        self.signaled = True

    def start(self, _: str) -> None:
        self.commands.append("start")
        self.state["State"]["Running"] = True
        self.state["State"]["StartedAt"] = "resumed"
        self.signaled = False

    def sleep(self, seconds: float) -> None:
        self.clock += seconds

    def now(self) -> float:
        return self.clock


def record(fake: Fake) -> dict[str, Any]:
    return mod.capture(fake, "id", fake.role)


def test_api_marks_docker_before_child_and_manual_pause_stays_stopped() -> None:
    f = Fake()
    r = record(f)
    mod.pause(f, r, timeout=2, settle=2)
    assert f.commands == ["docker_TERM", "verified_child_TERM"]
    assert r["marked"] and not f.inspect("id")["State"]["Running"]
    mod.resume(f, r, timeout=2)
    assert f.commands[-1] == "start"
    assert r["resumed"] is True


def test_python_pid1_does_not_receive_second_child_signal() -> None:
    f = Fake("sheets-worker")
    r = record(f)
    mod.pause(f, r, timeout=2, settle=1)
    assert f.commands == ["docker_TERM"]


def test_deadline_does_not_force_kill_or_claim_recovery_then_late_exit_resumes() -> None:
    f = Fake(delay=5)
    r = record(f)
    with pytest.raises(mod.SafetyError, match="grace_exhausted"):
        mod.pause(f, r, timeout=1, settle=0)
    assert mod.resume(f, r, timeout=1) is False
    assert not r.get("resumed")
    assert mod.resume(f, r, timeout=10) is True
    assert f.commands == ["docker_TERM", "verified_child_TERM", "start"]


def test_autorestart_is_immediate_failure() -> None:
    f = Fake(restart=True)
    with pytest.raises(mod.SafetyError, match="generation_changed"):
        mod.pause(f, record(f), timeout=2)


def test_resume_never_starts_replacement_container_or_image() -> None:
    f = Fake()
    r = record(f)
    r["marked"] = True
    f.state["Image"] = "replacement"
    with pytest.raises(mod.SafetyError, match="identity_changed"):
        mod.resume(f, r, timeout=2)
    assert f.commands == []


def test_relevant_config_changed_aborts_before_signal() -> None:
    f = Fake()
    r = record(f)
    f.state["HostConfig"]["RestartPolicy"]["Name"] = "always"
    with pytest.raises(mod.SafetyError, match="config_changed"):
        mod.pause(f, r, timeout=2)
    assert f.commands == []


def test_journal_marks_before_first_signal_even_if_signal_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = Fake()
    r = record(f)
    observed: list[bool] = []

    def fail(_: str) -> None:
        assert observed == [True]
        raise mod.SafetyError("signal_unconfirmed")

    monkeypatch.setattr(f, "term", fail)
    with pytest.raises(mod.SafetyError, match="signal_unconfirmed"):
        mod.pause(f, r, timeout=2, save=lambda: observed.append(r["marked"]))
    assert r["marked"]


def test_source_has_no_docker_stop_timeout_policy_update_or_force_signal() -> None:
    source = Path(mod.__file__).read_text()
    assert '["docker", "stop"' not in source
    assert "SIGKILL" not in source
    assert "docker update" not in source
    assert "os.environ" not in source


def test_guard_waits_armed_and_rereads_journal_before_late_resume() -> None:
    assert mod.guard_arm_seconds([]) == 600
    assert mod.guard_arm_seconds(["5"]) == 5
    with pytest.raises(mod.SafetyError, match="guard_arm_budget"):
        mod.guard_arm_seconds(["721"])
    f = Fake(delay=3)
    r = record(f)
    reads: list[float] = []

    def load() -> list[dict[str, Any]]:
        reads.append(f.clock)
        if f.clock >= 1:
            r["marked"] = True
            f.signaled = True
        return [r]

    assert mod.guard(f, load, lambda: None, arm_seconds=2, recover_seconds=5)
    assert len(reads) > 1
    assert f.commands == ["start"]


def test_rehearsal_hook_import_is_inert_and_install_requires_offline_marker() -> None:
    from infra.operations.zelerdata_history_pause_rehearsal_sitecustomize import (
        install_fixture_hooks,
    )

    with pytest.raises(RuntimeError, match="isolated rehearsal marker required"):
        install_fixture_hooks({})


def test_rehearsal_hook_refuses_unknown_role_before_replacing_provider() -> None:
    from infra.operations.zelerdata_history_pause_rehearsal_sitecustomize import (
        install_fixture_hooks,
    )

    with pytest.raises(RuntimeError, match="rehearsal role required"):
        install_fixture_hooks(
            {
                "ZELER_REHEARSAL_ACTIVE": "isolated-pause-20261003",
                "ZELER_REHEARSAL_ROLE": "unknown",
            }
        )


def test_authenticated_manifest_and_config_pair_work_across_docker_image_stores() -> None:
    f = Fake()
    f.state["Image"] = "sha256:f3dce59352c049ea3f95ad8be13d571b4cddd4e74c81e67b2bbc1c795952f164"
    assert record(f)["image"] == f.state["Image"]
    f.state["Image"] = "sha256:a9d33c3fcb428bb8502feba4b7a05084a08eeb4fa097069c6de40daafae1f72b"
    assert record(f)["image"] == f.state["Image"]
    f.state["Image"] = "sha256:" + "a" * 64
    with pytest.raises(mod.SafetyError, match="preflight_image_or_running"):
        record(f)


def test_selective_inspect_uses_optional_map_lookup_without_reading_environment() -> None:
    assert '{{json (index .Config "StopSignal")}}' in mod.INSPECT
    assert '{{json (index .Config "Healthcheck")}}' in mod.INSPECT
    assert ".Config.StopSignal" not in mod.INSPECT
    assert ".Config.Healthcheck" not in mod.INSPECT
    assert "Env" not in mod.INSPECT


def test_capture_accepts_absent_stop_signal_but_rejects_explicit_override() -> None:
    f = Fake()
    f.state["Config"]["StopSignal"] = None
    r = record(f)
    mod.pause(f, r, timeout=2, settle=0)
    assert f.commands == ["docker_TERM", "verified_child_TERM"]
    rejected = Fake()
    rejected.state["Config"]["StopSignal"] = "SIGINT"
    with pytest.raises(mod.SafetyError, match="preflight_stop_signal"):
        record(rejected)
    assert rejected.commands == []


@pytest.mark.parametrize(
    "logs,accepted",
    [
        (
            "2026-10-03T20:53:48Z INFO:     Application shutdown complete.\n"
            "2026-10-03T20:53:49Z INFO:     Finished server process [7]",
            True,
        ),
        (
            "2026-10-03T19:00:00Z INFO:     Application shutdown complete.\n"
            "2026-10-03T19:00:01Z INFO:     Finished server process [7]",
            False,
        ),
        (
            "2026-10-03T20:53:48Z INFO:     Application shutdown complete.\n"
            "2026-10-03T20:53:49Z INFO:     Finished server process [99]",
            False,
        ),
        (
            "2026-10-03T20:53:48Z INFO:     Finished server process [7]\n"
            "2026-10-03T20:53:49Z INFO:     Application shutdown complete.",
            False,
        ),
        ("2026-10-03T20:53:49Z INFO:     Finished server process [7]", False),
    ],
)
def test_api_143_requires_ordered_shutdown_markers_this_generation_pid(
    logs: str, accepted: bool
) -> None:
    f = Fake()
    f.state["State"]["StartedAt"] = "2026-10-03T20:00:00Z"
    f.state["State"]["ExitCode"] = 143
    f.shutdown_logs = logs
    r = record(f)
    if accepted:
        mod.pause(f, r, timeout=2, settle=0)
        assert r["stopped"] is True
    else:
        with pytest.raises(mod.SafetyError, match="nonzero_graceful_exit"):
            mod.pause(f, r, timeout=2, settle=0)
        assert not r["stopped"]


def test_worker_143_is_never_api_shutdown_exception() -> None:
    f = Fake("sheets-worker")
    f.state["State"]["ExitCode"] = 143
    with pytest.raises(mod.SafetyError, match="nonzero_graceful_exit"):
        mod.pause(f, record(f), timeout=2, settle=0)


def test_api_shutdown_log_probe_cannot_accept_generation_changed_during_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = Fake()
    f.state["State"]["ExitCode"] = 143
    r = record(f)

    def changed(_: dict[str, Any]) -> bool:
        f.state["State"]["StartedAt"] = "replacement"
        return True

    monkeypatch.setattr(f, "api_shutdown_complete", changed)
    with pytest.raises(mod.SafetyError, match="generation_changed"):
        mod.pause(f, r, timeout=2, settle=0)
    assert not r["stopped"]


def test_real_driver_shutdown_probe_filters_generation_and_merges_private_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    f = Fake()
    f.state["State"]["StartedAt"] = "2026-10-03T20:00:00Z"
    r = record(f)

    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        assert args == [
            "docker",
            "logs",
            "--timestamps",
            "--since",
            r["started_at"],
            "--tail=1000",
            r["id"],
        ]
        assert kwargs["stderr"] == subprocess.STDOUT
        assert kwargs["timeout"] == 15
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=(
                b"2026-10-03T20:53:48Z INFO:     Application shutdown complete.\n"
                b"2026-10-03T20:53:49Z INFO:     Finished server process [7]\n"
            ),
        )

    monkeypatch.setattr(subprocess, "run", run)
    assert mod.Docker().api_shutdown_complete(r) is True


def test_shutdown_parser_handles_actual_docker_nano_timestamps_on_python310(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime

    class Python310Datetime:
        @staticmethod
        def fromisoformat(value: str) -> datetime:
            if "." in value:
                raise ValueError("Python310 rejects Docker nano fractions")
            return datetime.fromisoformat(value)

    monkeypatch.setattr(mod, "datetime", Python310Datetime)
    assert (
        mod.api_shutdown_complete(
            "2026-10-03T21:10:02.451003870Z INFO:     Application shutdown complete.\n"
            "2026-10-03T21:10:02.451807973Z INFO:     Finished server process [7]",
            7,
            "2026-10-03T19:56:38.58167384Z",
        )
        is True
    )


def test_shutdown_parser_does_not_truncate_nanosecond_generation_boundary() -> None:
    assert (
        mod.api_shutdown_complete(
            "2026-10-03T19:56:38.581673839Z INFO:     Application shutdown complete.\n"
            "2026-10-03T19:56:38.581673841Z INFO:     Finished server process [7]",
            7,
            "2026-10-03T19:56:38.58167384Z",
        )
        is False
    )


@pytest.mark.parametrize("digits", range(1, 10))
def test_rfc3339_nano_preserves_every_fraction_digit_and_aware_offset(digits: int) -> None:
    fraction = "123456789"[:digits]
    expected = int(fraction.ljust(9, "0"))
    assert mod.rfc3339_nanoseconds(f"1970-01-01T00:00:00.{fraction}Z") == expected
    assert mod.rfc3339_nanoseconds(f"1969-12-31T18:00:00.{fraction}-06:00") == expected


@pytest.mark.parametrize(
    "invalid",
    [
        "1970-01-01T00:00:00",
        "1970-01-01T00:00:00.1234567890Z",
        "1970-02-31T00:00:00Z",
        "1970-01-01T00:00:00+99:00",
    ],
)
def test_rfc3339_nano_invalid_or_naive_is_fail_closed(invalid: str) -> None:
    assert mod.rfc3339_nanoseconds(invalid) is None
