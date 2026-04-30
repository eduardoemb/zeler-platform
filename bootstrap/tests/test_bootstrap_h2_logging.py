from __future__ import annotations

from typing import Any, cast

import pytest
from bootstrap.tests._h4_fixtures import NOW, FakeBootstrapJobs, FrozenClock, LogCaptureContext

from zeler_bootstrap.runner import BootstrapDagRunner
from zeler_bootstrap.state_machine import BootstrapStateMachine


class ProgressStage:
    name = "items"

    async def run(self, job: dict[str, Any], state_machine: BootstrapStateMachine) -> None:
        await state_machine.update_cursor("items", {"scroll_id": "abc"})
        fake_collection = cast(Any, state_machine.collection)
        fake_collection.document.setdefault("stage_progress", {})["items"] = {"records_written": 3}


class SecretFailingStage:
    name = "items"

    async def run(self, job: dict[str, Any], state_machine: BootstrapStateMachine) -> None:
        raise RuntimeError("http://user:pass@host/ bearer ABC123")


class LoggingPublisher:
    async def publish_bootstrap_completed(self, job: dict[str, Any]) -> None:
        return None


@pytest.mark.asyncio
async def test_successful_job_emits_all_required_events(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZELER_ENV", "test")
    clock = FrozenClock()
    jobs = FakeBootstrapJobs()
    machine = BootstrapStateMachine(jobs, "job-1", now_fn=lambda: NOW)

    with LogCaptureContext() as capture:
        completed = await BootstrapDagRunner(
            machine,
            [ProgressStage()],
            publisher=LoggingPublisher(),
            clock=clock.monotonic,
        ).run()

    events = [entry["event"] for entry in capture.entries]
    assert completed["state"] == "succeeded"
    assert "bootstrap.startup_config_loaded" in events
    assert "bootstrap.stage_started" in events
    assert "bootstrap.stage_completed" in events
    assert "bootstrap.publish_attempted" in events
    assert "bootstrap.publish_result" in events
    assert "bootstrap.job.completed" in events
    stage_completed = next(
        entry for entry in capture.entries if entry["event"] == "bootstrap.stage_completed"
    )
    assert stage_completed["records_written"] == 3
    assert stage_completed["duration_ms"] == 0


@pytest.mark.asyncio
async def test_runner_does_not_emit_synthetic_publish_attempt() -> None:
    jobs = FakeBootstrapJobs()
    machine = BootstrapStateMachine(jobs, "job-1", now_fn=lambda: NOW)

    with LogCaptureContext() as capture:
        await BootstrapDagRunner(machine, [ProgressStage()], publisher=LoggingPublisher()).run()

    assert [
        entry for entry in capture.entries if entry["event"] == "bootstrap.amqp.publish_attempt"
    ] == []


@pytest.mark.asyncio
async def test_runner_emits_only_spec_event_names() -> None:
    jobs = FakeBootstrapJobs()
    machine = BootstrapStateMachine(jobs, "job-1", now_fn=lambda: NOW)

    with LogCaptureContext() as capture:
        await BootstrapDagRunner(machine, [ProgressStage()], publisher=LoggingPublisher()).run()

    events = {entry["event"] for entry in capture.entries}
    assert {
        "bootstrap.job.started",
        "bootstrap.stage.started",
        "bootstrap.stage.completed",
    }.isdisjoint(events)
    assert {
        "bootstrap.startup_config_loaded",
        "bootstrap.stage_started",
        "bootstrap.stage_completed",
        "bootstrap.publish_attempted",
        "bootstrap.publish_result",
        "bootstrap.job_status",
    }.issubset(events)


@pytest.mark.asyncio
async def test_failure_path_emits_required_failure_events() -> None:
    jobs = FakeBootstrapJobs()
    machine = BootstrapStateMachine(jobs, "job-1", now_fn=lambda: NOW)

    with LogCaptureContext() as capture, pytest.raises(RuntimeError, match="host"):
        await BootstrapDagRunner(machine, [SecretFailingStage()], max_attempts=1).run()

    failed = next(entry for entry in capture.entries if entry["event"] == "bootstrap.stage.failed")
    terminal = next(entry for entry in capture.entries if entry["event"] == "bootstrap.job.failed")
    assert failed["exc_type"] == "RuntimeError"
    assert failed["last_error"] == "RuntimeError: http://***@host/ Bearer ***"
    assert terminal["attempt_count"] == 1
    assert terminal["terminal"] is False


@pytest.mark.asyncio
async def test_last_error_redaction_in_log_events() -> None:
    jobs = FakeBootstrapJobs()
    machine = BootstrapStateMachine(jobs, "job-1", now_fn=lambda: NOW)

    with LogCaptureContext() as capture, pytest.raises(RuntimeError):
        await BootstrapDagRunner(machine, [SecretFailingStage()], max_attempts=1).run()

    serialized = repr(capture.entries)
    assert "user:pass" not in serialized
    assert "ABC123" not in serialized
    assert "http://***@host/" in serialized


def test_configure_logging_idempotent() -> None:
    from zeler_platform_core.observability.logging import configure_logging

    configure_logging("test")
    configure_logging("test")

    import logging

    zeler_handlers = [
        handler
        for handler in logging.getLogger().handlers
        if getattr(handler, "_zeler_platform_observability", False)
    ]
    assert len(zeler_handlers) == 1
