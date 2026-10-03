"""Approved, operator-controlled Google refresh diagnostic; never retry this run.

This is not an exactly-once guard across processes. The operator records the
operation ID and evidence, executes once in the approved VM runtime, and must
not rerun after failure, timeout or uncertain outcome. No new persistent claim
or schema is introduced. GoogleTokenStore owns all normal token side effects.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, NoReturn

import httpx

from zeler_sheets.google_token_encryption import KmsClient
from zeler_sheets.google_token_store import GoogleTokenStore
from zeler_sheets.sheets_config import SheetsSettings

TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - public endpoint.
PILOT = "82453304"
TOTAL_TIMEOUT_SECONDS = 30.0
# Safe labels, not a diagnosis that any given flow or incident has this cause.
# https://developers.google.com/identity/protocols/oauth2/web-server#errors
# https://developers.google.com/identity/protocols/oauth2/service-account#error-codes
OAUTH_CATEGORIES = frozenset(
    {
        "invalid_client",
        "invalid_grant",
        "invalid_request",
        "unauthorized_client",
        "unsupported_grant_type",
        "invalid_scope",
        "access_denied",
        "server_error",
        "temporarily_unavailable",
        "deleted_client",
        "disabled_client",
        "admin_policy_enforced",
        "disallowed_useragent",
        "org_internal",
        "redirect_uri_mismatch",
    }
)
_PROJECTION = {"_id": 0, "status": 1, "last_error": 1, "expires_at": 1, "updated_at": 1}


@dataclass(frozen=True)
class DiagnosticRequest:
    seller_id: str
    operation_id: str
    expected_expires_at: datetime
    expected_updated_at: datetime
    confirm_approved_runtime: bool
    confirm_diagnostic: bool


def _valid(request: DiagnosticRequest) -> bool:
    return (
        request.seller_id == PILOT
        and request.confirm_approved_runtime
        and request.confirm_diagnostic
        and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request.operation_id) is not None
        and request.expected_expires_at.utcoffset() is not None
        and request.expected_updated_at.utcoffset() is not None
    )


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _status(doc: Any) -> str:
    value = doc.get("status") if isinstance(doc, dict) else None
    return value if value in ("active", "error", "revoked") else "unknown"


class _OneAttempt(httpx.AsyncBaseTransport):
    def __init__(self, wrapped: httpx.AsyncBaseTransport, output: dict[str, Any]) -> None:
        self.wrapped = wrapped
        self.output = output
        self.attempted = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.attempted or request.method != "POST" or str(request.url) != TOKEN_URL:
            raise RuntimeError("diagnostic request refused")
        self.attempted = True
        response = await self.wrapped.handle_async_request(request)
        self.output["http_status"] = response.status_code
        await response.aread()
        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                self.output["oauth_category"] = "response_not_json"
            else:
                if not isinstance(payload, dict) or "error" not in payload:
                    self.output["oauth_category"] = "error_missing"
                elif not isinstance(payload["error"], str):
                    self.output["oauth_category"] = "error_not_string"
                else:
                    category = payload["error"]
                    self.output["oauth_category"] = (
                        category if category in OAUTH_CATEGORIES else "unknown_error_code"
                    )
        return response

    async def aclose(self) -> None:
        await self.wrapped.aclose()


async def diagnose(
    *,
    request: DiagnosticRequest,
    db: Any,
    kms_client: KmsClient,
    settings: SheetsSettings,
    transport: httpx.AsyncBaseTransport | None = None,
    now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    output: dict[str, Any] = {
        "http_status": None,
        "oauth_category": "none",
        "result": "precondition_refused",
        "status": "unknown",
    }
    if not _valid(request) or settings.google_oauth_token_url != TOKEN_URL:
        return output
    tokens = db["google_oauth_tokens"]
    key = {"_id": f"google-token-{PILOT}"}
    try:
        async with asyncio.timeout(TOTAL_TIMEOUT_SECONDS):
            doc = await tokens.find_one(key, _PROJECTION)
            output["status"] = _status(doc)
            if (
                not doc
                or doc.get("status") != "error"
                or doc.get("last_error") != "Google token refresh failed with status 400"
                or _utc(doc.get("expires_at")) != request.expected_expires_at
                or _utc(doc.get("updated_at")) != request.expected_updated_at
                or request.expected_expires_at >= now_fn()
            ):
                return output
            guard = _OneAttempt(transport or httpx.AsyncHTTPTransport(retries=0), output)
            store = GoogleTokenStore(
                db=db,
                kms_client=kms_client,
                settings=settings,
                now_fn=now_fn,
                http_client_factory=lambda: httpx.AsyncClient(
                    transport=guard,
                    timeout=10.0,
                    follow_redirects=False,
                    trust_env=False,
                ),
            )
            output["result"] = "refresh_failed"
            try:
                await store.get_access_token(PILOT)
                output["result"] = "refreshed" if guard.attempted else "precondition_refused"
            except httpx.TimeoutException:
                output["result"] = "timeout_outcome_unknown"
            except Exception:  # noqa: BLE001 - never expose provider/credential exception text.
                output["result"] = "refresh_failed"
            finally:
                await guard.aclose()
            output["status"] = _status(await tokens.find_one(key, {"_id": 0, "status": 1}))
    except TimeoutError:
        output["result"] = "timeout_outcome_unknown"
    except Exception:  # noqa: BLE001 - sanitized operational boundary.
        output["result"] = "runtime_failed"
    return output


class _BoundedKms:
    def __init__(self, client: Any) -> None:
        self.client = client

    def encrypt(self, request: dict[str, bytes | str]) -> Any:
        return self.client.encrypt(request=request, retry=None, timeout=5.0)

    def decrypt(self, request: dict[str, bytes | str]) -> Any:
        return self.client.decrypt(request=request, retry=None, timeout=5.0)


async def run_runtime(request: DiagnosticRequest) -> dict[str, Any]:
    from google.cloud import kms_v1
    from motor.motor_asyncio import AsyncIOMotorClient

    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(
        os.environ["MONGO_URI"],
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=5000,
        tz_aware=True,
        retryReads=False,
        retryWrites=False,
    )
    try:
        return await diagnose(
            request=request,
            db=client[os.environ["MONGO_DB"]],
            kms_client=_BoundedKms(kms_v1.KeyManagementServiceClient()),
            settings=SheetsSettings(),  # type: ignore[call-arg]
        )
    finally:
        client.close()


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError("invalid diagnostic arguments")


def _request(argv: Sequence[str] | None) -> DiagnosticRequest:
    parser = _Parser(description=__doc__)
    parser.add_argument("--seller-id", required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--expected-expires-at", required=True)
    parser.add_argument("--expected-updated-at", required=True)
    parser.add_argument("--confirm-approved-runtime", action="store_true")
    parser.add_argument("--confirm-diagnostic", action="store_true")
    args = parser.parse_args(argv)
    request = DiagnosticRequest(
        seller_id=args.seller_id,
        operation_id=args.operation_id,
        expected_expires_at=datetime.fromisoformat(args.expected_expires_at.replace("Z", "+00:00")),
        expected_updated_at=datetime.fromisoformat(args.expected_updated_at.replace("Z", "+00:00")),
        confirm_approved_runtime=args.confirm_approved_runtime,
        confirm_diagnostic=args.confirm_diagnostic,
    )
    if not _valid(request):
        raise ValueError("diagnostic boundary refused")
    return request


def main(argv: Sequence[str] | None = None) -> int:
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        try:
            request = _request(argv)
        except (ValueError, TypeError):
            result = {
                "http_status": None,
                "oauth_category": "none",
                "result": "precondition_refused",
                "status": "unknown",
            }
        else:
            try:
                result = asyncio.run(run_runtime(request))
            except (Exception, KeyboardInterrupt):  # noqa: BLE001 - never print runtime exceptions.
                result = {
                    "http_status": None,
                    "oauth_category": "none",
                    "result": "runtime_failed",
                    "status": "unknown",
                }
        print(json.dumps(result, sort_keys=True))
        return (
            0
            if result["result"] == "refreshed"
            else 2
            if result["result"] == "precondition_refused"
            else 1
        )
    finally:
        logging.disable(previous_logging)


if __name__ == "__main__":
    raise SystemExit(main())
