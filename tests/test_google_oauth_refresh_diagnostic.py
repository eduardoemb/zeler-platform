from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from google_test_fakes import FakeKmsClient, fake_kms_client
from infra.operations import google_oauth_refresh_diagnostic as diagnostic

from zeler_sheets.google_token_encryption import encrypt_token
from zeler_sheets.sheets_config import SheetsSettings

__all__ = ["fake_kms_client"]
NOW = datetime(2026, 10, 2, 16, tzinfo=UTC)
EXPIRED = NOW - timedelta(days=2)
UPDATED = NOW - timedelta(minutes=1)


class FakeTokens:
    def __init__(self, doc: dict[str, Any]) -> None:
        self.doc = doc
        self.writes = 0

    async def find_one(self, query: dict[str, Any], projection: Any = None) -> dict[str, Any]:
        assert query == {"_id": "google-token-82453304"}
        return dict(self.doc)

    async def update_one(self, query: Any, update: Any) -> None:
        self.writes += 1
        self.doc.update(update["$set"])


class FakeDb:
    def __init__(self, doc: dict[str, Any]) -> None:
        self.tokens = FakeTokens(doc)

    def __getitem__(self, name: str) -> FakeTokens:
        assert name == "google_oauth_tokens"
        return self.tokens


def request(**changes: Any) -> Any:
    values: dict[str, Any] = dict(
        seller_id="82453304",
        operation_id="approved-diagnostic-1",
        expected_expires_at=EXPIRED,
        expected_updated_at=UPDATED,
        confirm_approved_runtime=True,
        confirm_diagnostic=True,
    )
    values.update(changes)
    return diagnostic.DiagnosticRequest(**values)


def database() -> FakeDb:
    access = encrypt_token("DO_NOT_PRINT_ACCESS", account_id="82453304")
    refresh = encrypt_token("DO_NOT_PRINT_REFRESH", account_id="82453304")
    return FakeDb(
        {
            "status": "error",
            "last_error": "Google token refresh failed with status 400",
            "expires_at": EXPIRED,
            "updated_at": UPDATED,
            "access_token_ciphertext": access.ciphertext,
            "access_token_dek_wrapped": access.dek_wrapped,
            "token_nonce": access.nonce,
            "refresh_token_ciphertext": refresh.ciphertext,
            "refresh_token_dek_wrapped": refresh.dek_wrapped,
            "refresh_token_nonce": refresh.nonce,
            "kms_key_version": access.kms_key_version,
        }
    )


async def run(db: FakeDb, kms: FakeKmsClient, handler: Any, **kwargs: Any) -> dict[str, Any]:
    return await diagnostic.diagnose(
        request=kwargs.pop("request", request()),
        db=db,
        kms_client=kms,
        settings=SheetsSettings(),  # type: ignore[call-arg]
        transport=httpx.MockTransport(handler),
        now_fn=lambda: NOW,
        **kwargs,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "category, expected_category",
    [
        ("invalid_client", "invalid_client"),
        ("invalid_grant", "invalid_grant"),
        ("invalid_request", "invalid_request"),
        ("deleted_client", "deleted_client"),
        ("disabled_client", "disabled_client"),
        ("admin_policy_enforced", "admin_policy_enforced"),
        ("disallowed_useragent", "disallowed_useragent"),
        ("org_internal", "org_internal"),
        ("redirect_uri_mismatch", "redirect_uri_mismatch"),
        ("DO_NOT_PRINT_PROVIDER_DETAIL", "unknown_error_code"),
        (None, "error_not_string"),
    ],
)
async def test_one_normal_refresh_reports_only_allowlisted_fields(
    fake_kms_client: FakeKmsClient,
    category: str | None,
    expected_category: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db = database()
    calls = []

    async def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(400, json={"error": category, "error_description": "SECRET_BODY"})

    result = await run(db, fake_kms_client, handler)
    assert len(calls) == 1
    assert calls[0].method == "POST"
    assert str(calls[0].url) == "https://oauth2.googleapis.com/token"
    assert b"grant_type=refresh_token" in calls[0].content
    assert result == {
        "http_status": 400,
        "oauth_category": expected_category,
        "result": "refresh_failed",
        "status": "revoked" if category == "invalid_grant" else "error",
    }
    assert db.tokens.writes == 1
    assert capsys.readouterr().out == ""
    assert not any(x in json.dumps(result) for x in ["SECRET", "DO_NOT_PRINT", "82453304"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body, expected_category",
    [
        (b"SECRET_NON_JSON", "response_not_json"),
        (b'{"error_description":"SECRET_BODY"}', "error_missing"),
        (b'["SECRET_BODY"]', "error_missing"),
        (b'"SECRET_BODY"', "error_missing"),
        (b'{"error":{"nested":"SECRET_BODY"}}', "error_not_string"),
        (b'{"error":["SECRET_BODY"]}', "error_not_string"),
        (b'{"error":123}', "error_not_string"),
        (b'{"error":"https://secret.invalid?token=SECRET_BODY"}', "unknown_error_code"),
    ],
)
async def test_error_response_shape_is_reported_without_provider_content(
    fake_kms_client: FakeKmsClient,
    body: bytes,
    expected_category: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(400, content=body)

    result = await run(database(), fake_kms_client, handler)
    assert result == {
        "http_status": 400,
        "oauth_category": expected_category,
        "result": "refresh_failed",
        "status": "error",
    }
    assert len(calls) == 1
    assert capsys.readouterr().out == ""
    assert not any(
        value in json.dumps(result) for value in ["SECRET", "https", "token", "82453304"]
    )


@pytest.mark.asyncio
async def test_success_uses_normal_store_and_metadata_rejects_operator_rerun(
    fake_kms_client: FakeKmsClient,
) -> None:
    db = database()
    calls = []

    async def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(200, json={"access_token": "NEW_SECRET", "expires_in": 3600})

    result = await run(db, fake_kms_client, handler)
    assert result == {
        "http_status": 200,
        "oauth_category": "none",
        "result": "refreshed",
        "status": "active",
    }
    assert db.tokens.doc["expires_at"] == NOW + timedelta(hours=1)
    again = await run(db, fake_kms_client, handler)
    assert again["result"] == "precondition_refused"
    assert len(calls) == 1
    assert db.tokens.writes == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"status": "active"},
        {"status": "revoked"},
        {"expires_at": NOW + timedelta(hours=1)},
        {"updated_at": NOW},
        {"last_error": "invalid_grant"},
    ],
)
async def test_metadata_mismatch_never_decrypts_or_calls_provider(
    fake_kms_client: FakeKmsClient, change: dict[str, Any]
) -> None:
    db = database()
    db.tokens.doc.update(change)
    before = fake_kms_client.decrypt_calls

    def forbidden(req: httpx.Request) -> httpx.Response:
        pytest.fail("provider must not be called")

    result = await run(db, fake_kms_client, forbidden)
    assert result["result"] == "precondition_refused"
    assert fake_kms_client.decrypt_calls == before
    assert db.tokens.writes == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"seller_id": "different"},
        {"confirm_approved_runtime": False},
        {"confirm_diagnostic": False},
        {"operation_id": ""},
    ],
)
async def test_boundary_rejection_has_no_provider_or_store_effects(
    fake_kms_client: FakeKmsClient, change: dict[str, Any]
) -> None:
    db = database()

    def forbidden(req: httpx.Request) -> httpx.Response:
        pytest.fail("provider must not be called")

    result = await run(db, fake_kms_client, forbidden, request=request(**change))
    assert result["result"] == "precondition_refused"
    assert db.tokens.writes == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["timeout", "malformed", "redirect", "rate_limit"])
async def test_failures_never_retry_or_expose_exception_content(
    fake_kms_client: FakeKmsClient,
    mode: str,
) -> None:
    db = database()
    calls = []

    async def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if mode == "timeout":
            raise httpx.ReadTimeout("SECRET_EXCEPTION_WITH_URL", request=req)
        if mode == "malformed":
            return httpx.Response(400, content=b"SECRET_NON_JSON")
        if mode == "redirect":
            return httpx.Response(302, headers={"location": "https://secret.invalid"})
        return httpx.Response(429, json={"error": "temporarily_unavailable"})

    result = await run(db, fake_kms_client, handler)
    assert len(calls) == 1
    assert result["result"] != "refreshed"
    assert "SECRET" not in json.dumps(result)


def test_cli_without_confirmations_is_sanitized_and_does_not_create_runtime(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("runtime must not be constructed")

    monkeypatch.setattr(diagnostic, "run_runtime", forbidden)
    assert diagnostic.main(["--unknown-secret-argument"]) == 2
    captured = capsys.readouterr()
    assert "unknown-secret" not in captured.out + captured.err
    assert json.loads(captured.out)["result"] == "precondition_refused"


@pytest.mark.asyncio
async def test_failed_refresh_changes_normal_metadata_and_refuses_operator_rerun(
    fake_kms_client: FakeKmsClient,
) -> None:
    db = database()
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(400, json={"error": "invalid_client"})

    await run(db, fake_kms_client, handler)
    again = await run(db, fake_kms_client, handler)
    assert again["result"] == "precondition_refused"
    assert len(calls) == 1
    assert db.tokens.writes == 1


@pytest.mark.asyncio
async def test_transport_refuses_a_second_attempt_even_if_called_again() -> None:
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(400, json={"error": "invalid_client"})

    guard = diagnostic._OneAttempt(httpx.MockTransport(handler), {})
    async with httpx.AsyncClient(transport=guard) as client:
        await client.post(diagnostic.TOKEN_URL)
        with pytest.raises(RuntimeError, match="diagnostic request refused"):
            await client.post(diagnostic.TOKEN_URL)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_total_timeout_is_unknown_without_retry(
    fake_kms_client: FakeKmsClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(diagnostic, "TOTAL_TIMEOUT_SECONDS", 0.01)
    db = database()
    calls = []

    async def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        await asyncio.sleep(1)
        return httpx.Response(400)

    result = await run(db, fake_kms_client, handler)
    assert result["result"] == "timeout_outcome_unknown"
    assert len(calls) == 1
    assert db.tokens.writes == 0


def test_kms_operations_have_finite_deadlines_and_no_automatic_retry() -> None:
    class Fake:
        def encrypt(self, **kwargs: Any) -> dict[str, Any]:
            return kwargs

        decrypt = encrypt

    kms = diagnostic._BoundedKms(Fake())
    for operation in (kms.encrypt, kms.decrypt):
        result = operation({"name": "test"})
        assert result["timeout"] == 5
        assert result["retry"] is None


def test_cli_runtime_exception_never_emits_raw_content(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def fail(request: Any) -> Any:
        raise RuntimeError("SECRET_WITH_URL_AND_BODY")

    monkeypatch.setattr(diagnostic, "run_runtime", fail)
    argv = [
        "--seller-id",
        "82453304",
        "--operation-id",
        "one-approved-attempt",
        "--expected-expires-at",
        EXPIRED.isoformat(),
        "--expected-updated-at",
        UPDATED.isoformat(),
        "--confirm-approved-runtime",
        "--confirm-diagnostic",
    ]
    assert diagnostic.main(argv) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "http_status": None,
        "oauth_category": "none",
        "result": "runtime_failed",
        "status": "unknown",
    }
