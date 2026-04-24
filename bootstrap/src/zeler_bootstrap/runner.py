from __future__ import annotations

from typing import Any, Protocol

from zeler_bootstrap.state_machine import BootstrapStateMachine


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
    def __init__(self, state_machine: BootstrapStateMachine, stages: list[BootstrapStage]) -> None:
        self.state_machine = state_machine
        self.stages = stages

    async def run(self) -> dict[str, Any]:
        job = await self.state_machine.load()
        if job["state"] == "pending" or job["state"] == "paused":
            job = await self.state_machine.transition("running")

        for stage in self.stages:
            job = await self.state_machine.load()
            if job.get("dag", {}).get(stage.name) == "done":
                continue
            await stage.run(job, self.state_machine)
            job = await self.state_machine.mark_stage_done(stage.name)

        return await self.state_machine.transition("succeeded")
