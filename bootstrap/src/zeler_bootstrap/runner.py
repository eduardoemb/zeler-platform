from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any, Protocol

import structlog

from zeler_bootstrap.runtime import BootstrapPublishError
from zeler_bootstrap.stages import (
    AccountsStage,
    BootstrapDatabase,
    BootstrapGatewayClient,
    BootstrapPublisher,
    ClaimsStage,
    InMemoryPublisher,
    ItemsStage,
    MessagesStage,
    OrdersStage,
    QuestionsStage,
    ShipmentsStage,
)
from zeler_bootstrap.state_machine import BootstrapStateMachine, _redact_error


class BootstrapTerminalFailure(RuntimeError):  # noqa: N818 - public name from SDD design
    pass


class BootstrapStage(Protocol):
    name: str

    async def run(self, job: dict[str, Any], state_machine: BootstrapStateMachine) -> None: ...


DEFAULT_STAGE_ORDER = [
    "accounts",
    "items",
    "orders",
    "questions",
    "messages",
    "shipments",
    "claims",
]


class BootstrapDagRunner:
    def __init__(
        self,
        state_machine: BootstrapStateMachine,
        stages: list[BootstrapStage],
        *,
        publisher: BootstrapPublisher | None = None,
        max_attempts: int = 3,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.state_machine = state_machine
        self.stages = stages
        self.publisher = publisher or InMemoryPublisher()
        self.max_attempts = max_attempts
        self.clock = clock

    async def run(self) -> dict[str, Any]:
        started_at = self.clock()
        while True:
            job = await self._enter_running_state_if_needed()
            log = self._logger(job)
            log.info(
                "bootstrap.startup_config_loaded",
                env=os.environ.get("ZELER_ENV", "development"),
                stages_count=len(self.stages),
                attempt_count=int(job.get("attempt_count", 0)),
            )

            try:
                await self._run_stages(log)
                final_job = await self.state_machine.load()
                log.info("bootstrap.publish_attempted", attempt=1, max_attempts=1)
                try:
                    await self.publisher.publish_bootstrap_completed(final_job)
                except BootstrapPublishError as exc:
                    await self._record_failure(log, "__publish__", exc, 0)
                    log.warning(
                        "bootstrap.publish_result",
                        success=False,
                        attempts_used=1,
                        error_class=type(exc).__name__,
                    )
                    raise
                log.info("bootstrap.publish_result", success=True, attempts_used=1)
                completed = await self.state_machine.transition("succeeded")
                log.info(
                    "bootstrap.job.completed",
                    total_elapsed_ms=int((self.clock() - started_at) * 1000),
                    stages_succeeded=len(self.stages),
                    event_published=True,
                )
                log.info(
                    "bootstrap.job_status",
                    status="succeeded",
                    terminal=True,
                    attempt_count=int(completed.get("attempt_count", 0)),
                )
                return completed
            except Exception as exc:
                current = await self.state_machine.load()
                if (
                    not isinstance(exc, BootstrapPublishError)
                    and current.get("state") == "failed"
                    and int(current.get("attempt_count", 0)) < self.max_attempts
                ):
                    await self.state_machine.requeue_for_retry(self.max_attempts)
                    continue
                raise exc

    async def _enter_running_state_if_needed(self) -> dict[str, Any]:
        job = await self.state_machine.load()
        if job["state"] == "failed":
            if int(job.get("attempt_count", 0)) >= self.max_attempts:
                attempt_count = int(job.get("attempt_count", 0))
                self._logger(job).error(
                    "bootstrap.job.failed",
                    terminal=True,
                    attempt_count=attempt_count,
                )
                self._logger(job).error(
                    "bootstrap.job_status",
                    status="failed",
                    terminal=True,
                    attempt_count=attempt_count,
                )
                raise BootstrapTerminalFailure(
                    f"bootstrap retry budget exhausted for job {job['_id']}"
                )
            job = await self.state_machine.requeue_for_retry(self.max_attempts)
        if job["state"] in {"pending", "paused"}:
            job = await self.state_machine.transition("running")
        return job

    async def _run_stages(self, log: Any) -> None:
        for stage in self.stages:
            job = await self.state_machine.load()
            if job.get("dag", {}).get(stage.name) == "done":
                continue
            stage_started_at = self.clock()
            log.info("bootstrap.stage_started", stage=stage.name)
            try:
                await stage.run(job, self.state_machine)
            except Exception as exc:
                elapsed_ms = int((self.clock() - stage_started_at) * 1000)
                await self._record_failure(log, stage.name, exc, elapsed_ms)
                raise
            updated = await self.state_machine.mark_stage_done(stage.name)
            progress = updated.get("stage_progress", {}).get(stage.name, {})
            log.info(
                "bootstrap.stage_completed",
                stage=stage.name,
                duration_ms=int((self.clock() - stage_started_at) * 1000),
                records_written=int(progress.get("records_written", 0)),
            )

    async def _record_failure(
        self, log: Any, stage: str, exc: BaseException, elapsed_ms: int
    ) -> dict[str, Any]:
        last_error = _redact_error(f"{type(exc).__name__}: {exc}")
        log.error(
            "bootstrap.stage.failed",
            stage=stage,
            exc_type=type(exc).__name__,
            last_error=last_error,
            elapsed_ms=elapsed_ms,
        )
        failed_doc = await self.state_machine.transition("failed", error=exc)
        log.error(
            "bootstrap.job.failed",
            terminal=False,
            attempt_count=int(failed_doc.get("attempt_count", 0)),
            last_error=last_error,
        )
        log.error(
            "bootstrap.job_status",
            status="failed",
            terminal=False,
            attempt_count=int(failed_doc.get("attempt_count", 0)),
            last_error=last_error,
        )
        return failed_doc

    def _logger(self, job: dict[str, Any]) -> Any:
        return structlog.get_logger("zeler_bootstrap").bind(
            seller_id=str(job["seller_id"]), job_id=str(job["_id"])
        )


def build_default_stages(
    gateway: BootstrapGatewayClient, database: BootstrapDatabase
) -> list[BootstrapStage]:
    return [
        AccountsStage(gateway, database),
        ItemsStage(gateway, database),
        OrdersStage(gateway, database),
        QuestionsStage(gateway, database),
        MessagesStage(gateway, database),
        ShipmentsStage(gateway, database),
        ClaimsStage(gateway, database),
    ]
