"""Isolated-image hook; mount as sitecustomize.py, NEVER production.

Only the provider constructor and synthetic event boundary are replaced. Actual
entrypoints, worker lifecycle, SyncJobsProcessor claim/fence/finish, Mongo driver,
Rabbit consumer and broker acknowledgement code remain unchanged. Normal module
imports are inert: installation requires an explicit isolated marker and role.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NoReturn, cast


class NoProvider:
    def __getattr__(self, _name: str) -> NoReturn:
        raise RuntimeError("external provider forbidden in isolated rehearsal")


def install_fixture_hooks(environ: Mapping[str, str] | None = None) -> None:
    source = os.environ if environ is None else environ
    if source.get("ZELER_REHEARSAL_ACTIVE") != "isolated-pause-20261003":
        raise RuntimeError("isolated rehearsal marker required")
    role = source.get("ZELER_REHEARSAL_ROLE")
    if role not in ("sheets-worker", "sheets-api", "bootstrap-dispatcher"):
        raise RuntimeError("rehearsal role required")
    if source.get("GOOGLE_APPLICATION_CREDENTIALS"):
        raise RuntimeError("credential files forbidden in isolated rehearsal")

    from google.cloud import kms

    cast(Any, kms).KeyManagementServiceClient = lambda *args, **kwargs: NoProvider()
    if role == "sheets-worker":
        from zeler_sheets.consumer import SheetsEventHandler

        async def synthetic_handle(self: Any, event: Any) -> str:
            if event.resource == "/items/SYNTHETIC_PAUSE_JOB":
                lane = "job"
            elif event.resource == "/items/SYNTHETIC_PAUSE_AMQP":
                lane = "amqp"
            else:
                raise RuntimeError("nonfixture event forbidden")
            control = Path("/rehearsal-control")
            with (control / ("entered_" + lane)).open("a") as stream:
                stream.write("entered\n")
            while not (control / ("release_" + lane)).exists():
                await asyncio.sleep(0.1)
            with (control / ("completed_" + lane)).open("a") as stream:
                stream.write("completed\n")
            return "appended"

        cast(Any, SheetsEventHandler).handle = synthetic_handle
    elif role == "bootstrap-dispatcher":
        from zeler_bootstrap.cloud_run_jobs_client import CloudRunJobsClient

        async def forbidden_dispatch(self: Any, **kwargs: Any) -> NoReturn:
            raise RuntimeError("Cloud Run forbidden in isolated rehearsal")

        cast(Any, CloudRunJobsClient).run_job = forbidden_dispatch


if __name__ == "sitecustomize":
    install_fixture_hooks()
