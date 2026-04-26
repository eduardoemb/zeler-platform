from __future__ import annotations

import asyncio
from typing import Protocol

import httpx
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build  # type: ignore[import-untyped]
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

from zeler_sheets.google_errors import GoogleSheetsApiError
from zeler_sheets.google_token_encryption import KmsClient
from zeler_sheets.google_token_store import GoogleTokenStore
from zeler_sheets.sheets_config import SheetsSettings


class GoogleTokenStoreLike(Protocol):
    async def get_access_token(self, seller_id: str) -> str: ...

    async def mark_error(self, seller_id: str, *, reason: str) -> None: ...


class GoogleSheetsClient:
    def __init__(self, *, token_store: GoogleTokenStoreLike) -> None:
        self._token_store = token_store

    async def append_row(
        self,
        *,
        seller_id: str,
        spreadsheet_id: str,
        worksheet_name: str,
        row: list[str],
        idempotency_key: str,
    ) -> None:
        del (
            idempotency_key
        )  # Google append is not idempotent; caller-level idempotency guards this path.
        token = await self._token_store.get_access_token(str(seller_id))
        credentials = Credentials(token=token)  # type: ignore[no-untyped-call]
        service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        request = (
            service.spreadsheets()
            .values()
            .append(
                spreadsheetId=spreadsheet_id,
                range=f"{worksheet_name}!A1",
                valueInputOption="USER_ENTERED",
                body={"values": [row]},
            )
        )
        try:
            await asyncio.to_thread(request.execute)
        except HttpError as exc:
            if int(getattr(exc.resp, "status", 0)) == 401:
                reason = "Google Sheets API returned 401"
                await self._token_store.mark_error(str(seller_id), reason=reason)
                raise GoogleSheetsApiError(reason) from exc
            raise


def make_sheets_client(
    db: object,
    kms_client: KmsClient,
    settings: SheetsSettings,
) -> GoogleSheetsClient:
    token_store = GoogleTokenStore(
        db=db,
        kms_client=kms_client,
        http_client_factory=lambda: httpx.AsyncClient(timeout=10.0),
        settings=settings,
    )
    return GoogleSheetsClient(token_store=token_store)
