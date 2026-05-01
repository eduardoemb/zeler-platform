from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class FakeCloudRunJobsClient:
    execution_prefix: str = "executions"
    calls: list[dict[str, str]] = field(default_factory=list)

    async def run_job(self, *, seller_id: str, job_id: str) -> str:
        self.calls.append({"seller_id": seller_id, "job_id": job_id})
        return f"{self.execution_prefix}/{job_id}"


class CloudRunJobsClient:
    def __init__(
        self,
        *,
        project: str,
        location: str,
        job_name: str,
        credentials: Any | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._project = project
        self._location = location
        self._job_name = job_name
        self._credentials = credentials
        self._http_client = http_client or httpx.AsyncClient(timeout=30)

    async def run_job(self, *, seller_id: str, job_id: str) -> str:
        token = await self._access_token()
        url = (
            "https://run.googleapis.com/v2/"
            f"projects/{self._project}/locations/{self._location}/jobs/{self._job_name}:run"
        )
        response = await self._http_client.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "overrides": {
                    "containerOverrides": [
                        {
                            "env": [
                                {"name": "SELLER_ID", "value": seller_id},
                                {"name": "BOOTSTRAP_JOB_ID", "value": job_id},
                            ]
                        }
                    ]
                }
            },
        )
        response.raise_for_status()
        payload = response.json()
        execution_name = payload.get("name")
        if not isinstance(execution_name, str):
            msg = "Cloud Run Jobs response did not include execution name"
            raise ValueError(msg)
        return execution_name

    async def _access_token(self) -> str:
        credentials = self._credentials
        if credentials is None:
            import google.auth

            credentials, _project = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
        if not getattr(credentials, "valid", False):
            from google.auth.transport.requests import Request

            credentials.refresh(Request())
        token = getattr(credentials, "token", None)
        if not isinstance(token, str):
            msg = "Google credentials did not produce an access token"
            raise ValueError(msg)
        return token
