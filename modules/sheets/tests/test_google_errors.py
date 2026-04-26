from __future__ import annotations

from zeler_sheets.google_errors import (
    GoogleSheetsApiError,
    GoogleSheetsError,
    SellerNotConnectedError,
    SellerTokenRevokedError,
)


def test_error_hierarchy() -> None:
    assert issubclass(GoogleSheetsError, RuntimeError)
    assert issubclass(SellerNotConnectedError, GoogleSheetsError)
    assert issubclass(SellerTokenRevokedError, GoogleSheetsError)
    assert issubclass(GoogleSheetsApiError, GoogleSheetsError)
    assert str(SellerNotConnectedError("seller missing")) == "seller missing"
