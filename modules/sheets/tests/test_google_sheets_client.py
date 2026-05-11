# ruff: noqa: S107

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]
from httplib2 import Response  # type: ignore[import-untyped]

from zeler_sheets.google_errors import (
    RetryableGoogleSheetsApiError,
    SellerNotConnectedError,
    SellerTokenRevokedError,
)
from zeler_sheets.google_sheets_client import GoogleSheetsClient


class FakeTokenStore:
    def __init__(self, token: str = "access-token") -> None:
        self.token = token
        self.seller_ids: list[str] = []
        self.marked_errors: list[tuple[str, str]] = []
        self.error: Exception | None = None

    async def get_access_token(self, seller_id: str) -> str:
        self.seller_ids.append(seller_id)
        if self.error is not None:
            raise self.error
        return self.token

    async def mark_error(self, seller_id: str, *, reason: str) -> None:
        self.marked_errors.append((seller_id, reason))


class FakeExecuteRequest:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.executed = False

    def execute(self) -> dict[str, Any]:
        self.executed = True
        if self.error is not None:
            raise self.error
        return {"updates": {"updatedRows": 1}}


def _build_service(request: FakeExecuteRequest) -> tuple[Mock, Mock]:
    values = Mock()
    values.append.return_value = request
    spreadsheets = Mock()
    spreadsheets.values.return_value = values
    service = Mock()
    service.spreadsheets.return_value = spreadsheets
    return service, values


@pytest.mark.asyncio
async def test_append_row_calls_sheets_api_correct_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    request = FakeExecuteRequest()
    service, values = _build_service(request)
    build_calls: list[dict[str, Any]] = []

    def fake_build(*args: Any, **kwargs: Any) -> Mock:
        build_calls.append({"args": args, "kwargs": kwargs})
        return service

    monkeypatch.setattr("zeler_sheets.google_sheets_client.build", fake_build)

    await GoogleSheetsClient(token_store=FakeTokenStore("token-1")).append_row(
        seller_id="seller-1",
        spreadsheet_id="sheet-123",
        worksheet_name="Items",
        row=["items.updated", "MLA1"],
        idempotency_key="idem-1",
    )

    assert build_calls[0]["args"][:2] == ("sheets", "v4")
    assert build_calls[0]["kwargs"]["cache_discovery"] is False
    values.append.assert_called_once_with(
        spreadsheetId="sheet-123",
        range="Items!A1",
        valueInputOption="USER_ENTERED",
        body={"values": [["items.updated", "MLA1"]]},
    )
    assert request.executed is True


@pytest.mark.asyncio
async def test_append_row_raises_seller_not_connected_when_no_token() -> None:
    store = FakeTokenStore()
    store.error = SellerNotConnectedError("seller missing")

    with pytest.raises(SellerNotConnectedError, match="seller missing"):
        await GoogleSheetsClient(token_store=store).append_row(
            seller_id="seller-1",
            spreadsheet_id="sheet-123",
            worksheet_name="Items",
            row=["items.updated"],
            idempotency_key="idem-1",
        )


@pytest.mark.asyncio
async def test_append_row_uses_asyncio_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    request = FakeExecuteRequest()
    service, _values = _build_service(request)
    to_thread_calls: list[Any] = []

    async def fake_to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
        to_thread_calls.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr("zeler_sheets.google_sheets_client.build", lambda *args, **kwargs: service)
    monkeypatch.setattr("zeler_sheets.google_sheets_client.asyncio.to_thread", fake_to_thread)

    await GoogleSheetsClient(token_store=FakeTokenStore()).append_row(
        seller_id="seller-1",
        spreadsheet_id="sheet-123",
        worksheet_name="Items",
        row=["items.updated"],
        idempotency_key="idem-1",
    )

    assert to_thread_calls == [request.execute]


@pytest.mark.asyncio
async def test_append_row_propagates_token_revoked_error() -> None:
    store = FakeTokenStore()
    store.error = SellerTokenRevokedError("token revoked")

    with pytest.raises(SellerTokenRevokedError, match="token revoked"):
        await GoogleSheetsClient(token_store=store).append_row(
            seller_id="seller-1",
            spreadsheet_id="sheet-123",
            worksheet_name="Items",
            row=["items.updated"],
            idempotency_key="idem-1",
        )


@pytest.mark.asyncio
async def test_append_row_marks_error_on_sheets_401_after_fresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = Response({"status": "401", "reason": "Unauthorized"})
    error = HttpError(response, b'{"error":"unauthorized"}')
    request = FakeExecuteRequest(error=error)
    service, _values = _build_service(request)
    store = FakeTokenStore()
    monkeypatch.setattr("zeler_sheets.google_sheets_client.build", lambda *args, **kwargs: service)

    with pytest.raises(RuntimeError, match="Google Sheets API returned 401"):
        await GoogleSheetsClient(token_store=store).append_row(
            seller_id="seller-1",
            spreadsheet_id="sheet-123",
            worksheet_name="Items",
            row=["items.updated"],
            idempotency_key="idem-1",
        )

    assert store.marked_errors == [("seller-1", "Google Sheets API returned 401")]


@pytest.mark.asyncio
async def test_append_row_raises_retryable_error_for_sheets_429_with_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = Response({"status": "429", "reason": "Too Many Requests", "retry-after": "7"})
    error = HttpError(response, b'{"error":{"status":"RESOURCE_EXHAUSTED"}}')
    request = FakeExecuteRequest(error=error)
    service, _values = _build_service(request)
    store = FakeTokenStore()
    monkeypatch.setattr("zeler_sheets.google_sheets_client.build", lambda *args, **kwargs: service)

    with pytest.raises(RetryableGoogleSheetsApiError) as exc_info:
        await GoogleSheetsClient(token_store=store).append_row(
            seller_id="seller-1",
            spreadsheet_id="sheet-123",
            worksheet_name="Items",
            row=["items.updated"],
            idempotency_key="idem-1",
        )

    assert exc_info.value.retry_after_seconds == 7
    assert store.marked_errors == []
