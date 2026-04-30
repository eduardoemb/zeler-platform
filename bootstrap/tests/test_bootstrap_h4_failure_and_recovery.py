from __future__ import annotations

from typing import Any

import pytest
from bootstrap.tests._h4_fixtures import NOW, FakeBootstrapJobs, LogCaptureContext

from zeler_bootstrap.runner import BootstrapDagRunner
from zeler_bootstrap.runtime import BootstrapPublishError, _publish_with_retry
from zeler_bootstrap.state_machine import (
    BootstrapStateMachine,
    IllegalTransition,
    InvalidTransitionError,
    _redact_error,
)


class RecordingStage:
    def __init__(self, name: str = "items", *, fail_once: bool = False) -> None:
        self.name = name
        self.fail_once = fail_once
        self.calls = 0

    async def run(self, job: dict[str, Any], state_machine: BootstrapStateMachine) -> None:
        self.calls += 1
        if self.fail_once and self.calls == 1:
            raise RuntimeError("boom bearer SECRET_TOKEN_123")
        await state_machine.update_cursor(self.name, {"page": self.calls})


class FailingStage:
    name = "items"

    async def run(self, job: dict[str, Any], state_machine: BootstrapStateMachine) -> None:
        raise RuntimeError("boom BOOTSTRAP_GATEWAY_TOKEN=super-secret")


class RecordingPublisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.events: list[dict[str, Any]] = []

    async def publish_bootstrap_completed(self, job: dict[str, Any]) -> None:
        self.events.append({"state_at_publish": job["state"], "job_id": job["_id"]})
        if self.fail:
            raise BootstrapPublishError(
                message_id="bootstrap-completed-job-1",
                last_attempt=3,
                cause=ConnectionError("amqp down"),
            )


class TerminalFailingPublisher:
    async def publish_bootstrap_completed(self, job: dict[str, Any]) -> None:
        async def publish(_message_id: str) -> None:
            raise ValueError(f"terminal publish failure for {job['_id']}")

        await _publish_with_retry(
            publish_fn=publish,
            message_id=f"bootstrap-completed-{job['_id']}",
            max_attempts=3,
        )


def test_redact_bearer_token() -> None:
    assert _redact_error("failed with bearer ABC123.def-456") == "failed with Bearer ***"


def test_redact_uri_userinfo() -> None:
    assert _redact_error("see http://user:pass@host/path") == "see http://***@host/path"


def test_redact_jwt_like() -> None:
    token = "eyJheader.eyJpayload.signature"  # noqa: S105 - redaction fixture, not a secret
    assert _redact_error(f"jwt={token}") == "jwt=***"


def test_redact_long_base64_hex() -> None:
    secret = "a" * 40
    assert _redact_error(f"secret {secret} leaked") == "secret *** leaked"


def test_redact_bootstrap_gateway_token_env() -> None:
    assert (
        _redact_error("BOOTSTRAP_GATEWAY_TOKEN=abc123 failed")
        == "BOOTSTRAP_GATEWAY_TOKEN=*** failed"
    )


def test_redact_truncates_after_redaction() -> None:
    assert len(_redact_error(" ".join(["boom"] * 300))) == 1024


@pytest.mark.asyncio
async def test_requeue_for_retry_idempotent_on_pending() -> None:
    jobs = FakeBootstrapJobs({**FakeBootstrapJobs().document, "attempt_count": 2})
    machine = BootstrapStateMachine(jobs, "job-1", now_fn=lambda: NOW)

    updated = await machine.requeue_for_retry(max_attempts=3)

    assert updated["state"] == "pending"
    assert updated["attempt_count"] == 2


@pytest.mark.asyncio
async def test_requeue_for_retry_rejects_succeeded() -> None:
    jobs = FakeBootstrapJobs(
        {**FakeBootstrapJobs().document, "state": "succeeded", "attempt_count": 1}
    )
    machine = BootstrapStateMachine(jobs, "job-1", now_fn=lambda: NOW)

    with pytest.raises(IllegalTransition):
        await machine.requeue_for_retry(max_attempts=3)

    assert jobs.document["state"] == "succeeded"


@pytest.mark.asyncio
async def test_concurrent_requeue_for_retry_safe() -> None:
    jobs = FakeBootstrapJobs(
        {**FakeBootstrapJobs().document, "state": "failed", "attempt_count": 1}
    )
    first = BootstrapStateMachine(jobs, "job-1", now_fn=lambda: NOW)
    second = BootstrapStateMachine(jobs, "job-1", now_fn=lambda: NOW)

    first_result = await first.requeue_for_retry(max_attempts=3)
    second_result = await second.requeue_for_retry(max_attempts=3)

    assert first_result["state"] == "pending"
    assert second_result["state"] == "pending"
    assert jobs.document["attempt_count"] == 1


@pytest.mark.asyncio
async def test_stage_exception_transitions_failed_with_required_fields() -> None:
    jobs = FakeBootstrapJobs(
        {**FakeBootstrapJobs().document, "state": "running", "attempt_count": 1}
    )
    machine = BootstrapStateMachine(jobs, "job-1", now_fn=lambda: NOW)

    failed = await machine.transition(
        "failed", error=RuntimeError("boom BOOTSTRAP_GATEWAY_TOKEN=abc123")
    )

    assert failed["state"] == "failed"
    assert failed["failed_at"] == NOW
    assert failed["finished_at"] == NOW
    assert failed["last_error"] == "RuntimeError: boom BOOTSTRAP_GATEWAY_TOKEN=***"
    assert failed["attempt_count"] == 1


@pytest.mark.asyncio
async def test_attempt_count_incremented_atomically_on_running_entry() -> None:
    jobs = FakeBootstrapJobs()
    first = BootstrapStateMachine(jobs, "job-1", now_fn=lambda: NOW)
    second = BootstrapStateMachine(jobs, "job-1", now_fn=lambda: NOW)

    running = await first.transition("running")

    assert running["attempt_count"] == 1
    with pytest.raises(InvalidTransitionError):
        await second.transition("running")
    assert jobs.document["attempt_count"] == 1


@pytest.mark.asyncio
async def test_last_error_truncated_to_1024() -> None:
    jobs = FakeBootstrapJobs(
        {**FakeBootstrapJobs().document, "state": "running", "attempt_count": 1}
    )
    machine = BootstrapStateMachine(jobs, "job-1", now_fn=lambda: NOW)

    failed = await machine.transition("failed", error=RuntimeError(" ".join(["boom"] * 300)))

    assert len(failed["last_error"]) == 1024


@pytest.mark.asyncio
async def test_read_compat_legacy_documents() -> None:
    jobs = FakeBootstrapJobs()
    machine = BootstrapStateMachine(jobs, "job-1", now_fn=lambda: NOW)

    loaded = await machine.load()
    running = await machine.transition("running")

    assert loaded.get("attempt_count", 0) == 0
    assert loaded.get("failed_at") is None
    assert loaded.get("last_error") is None
    assert running["attempt_count"] == 1


@pytest.mark.asyncio
async def test_cloud_run_retry_within_budget_auto_recovers() -> None:
    jobs = FakeBootstrapJobs(
        {**FakeBootstrapJobs().document, "state": "failed", "attempt_count": 1}
    )
    machine = BootstrapStateMachine(jobs, "job-1", now_fn=lambda: NOW)
    stage = RecordingStage()
    publisher = RecordingPublisher()

    completed = await BootstrapDagRunner(
        machine, [stage], publisher=publisher, max_attempts=3
    ).run()

    assert completed["state"] == "succeeded"
    assert jobs.document["attempt_count"] == 2
    assert stage.calls == 1


@pytest.mark.asyncio
async def test_retry_beyond_budget_stays_failed() -> None:
    jobs = FakeBootstrapJobs(
        {**FakeBootstrapJobs().document, "state": "failed", "attempt_count": 3}
    )
    machine = BootstrapStateMachine(jobs, "job-1", now_fn=lambda: NOW)

    with LogCaptureContext() as capture, pytest.raises(RuntimeError, match="retry budget"):
        await BootstrapDagRunner(machine, [RecordingStage()], max_attempts=3).run()

    assert jobs.document["state"] == "failed"
    assert any(
        event["event"] == "bootstrap.job.failed" and event["terminal"] is True
        for event in capture.entries
    )


@pytest.mark.asyncio
async def test_terminal_retry_budget_exhaustion_emits_job_status() -> None:
    jobs = FakeBootstrapJobs(
        {**FakeBootstrapJobs().document, "state": "failed", "attempt_count": 3}
    )
    machine = BootstrapStateMachine(jobs, "job-1", now_fn=lambda: NOW)

    with LogCaptureContext() as capture, pytest.raises(RuntimeError, match="retry budget"):
        await BootstrapDagRunner(machine, [RecordingStage()], max_attempts=3).run()

    assert any(
        event["event"] == "bootstrap.job_status"
        and event["terminal"] is True
        and event["status"] == "failed"
        and event["attempt_count"] == 3
        for event in capture.entries
    )


@pytest.mark.asyncio
async def test_publish_failure_routes_through_failed_state() -> None:
    jobs = FakeBootstrapJobs(
        {**FakeBootstrapJobs().document, "state": "running", "attempt_count": 1}
    )
    machine = BootstrapStateMachine(jobs, "job-1", now_fn=lambda: NOW)
    publisher = RecordingPublisher(fail=True)

    with pytest.raises(BootstrapPublishError):
        await BootstrapDagRunner(machine, [RecordingStage()], publisher=publisher).run()

    assert publisher.events == [{"state_at_publish": "running", "job_id": "job-1"}]
    assert jobs.document["state"] == "failed"
    assert "BootstrapPublishError" in jobs.document["last_error"]


@pytest.mark.asyncio
async def test_publish_terminal_exception_routes_through_failed_state() -> None:
    jobs = FakeBootstrapJobs(
        {**FakeBootstrapJobs().document, "state": "running", "attempt_count": 1}
    )
    machine = BootstrapStateMachine(jobs, "job-1", now_fn=lambda: NOW)

    with pytest.raises(BootstrapPublishError, match="bootstrap publish failed"):
        await BootstrapDagRunner(
            machine,
            [RecordingStage()],
            publisher=TerminalFailingPublisher(),
        ).run()

    assert jobs.document["state"] == "failed"
    assert "BootstrapPublishError" in jobs.document["last_error"]
