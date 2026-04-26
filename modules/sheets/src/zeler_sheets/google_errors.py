from __future__ import annotations


class GoogleSheetsError(RuntimeError):
    """Base error for Google Sheets integration failures."""


class SellerNotConnectedError(GoogleSheetsError):
    """Raised when a seller has not completed Google OAuth."""


class SellerTokenRevokedError(GoogleSheetsError):
    """Raised when Google rejects the seller refresh token."""


class GoogleSheetsApiError(GoogleSheetsError):
    """Raised when the Sheets API rejects a request."""
