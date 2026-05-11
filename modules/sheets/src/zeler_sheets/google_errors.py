DEFAULT_GOOGLE_SHEETS_RETRY_AFTER_SECONDS = 60
MAX_GOOGLE_SHEETS_RETRY_AFTER_SECONDS = 300


class GoogleSheetsError(RuntimeError):
    """Base error for Google Sheets integration failures."""


class SellerNotConnectedError(GoogleSheetsError):
    """Raised when a seller has not completed Google OAuth."""


class SellerTokenRevokedError(GoogleSheetsError):
    """Raised when Google rejects the seller refresh token."""


class GoogleSheetsApiError(GoogleSheetsError):
    """Raised when the Sheets API rejects a request."""


class RetryableGoogleSheetsApiError(GoogleSheetsApiError):
    """Raised when Google asks the worker to retry a Sheets API request later."""

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: int = DEFAULT_GOOGLE_SHEETS_RETRY_AFTER_SECONDS,
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = _bounded_retry_after_seconds(retry_after_seconds)


def is_retryable_google_sheets_error(*, status_code: int, content: bytes | str = b"") -> bool:
    """Return True for quota/rate-limit Sheets errors that should use broker retry."""
    if status_code == 429:
        return True
    if status_code != 403:
        return False
    text = content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else content
    rate_limit_markers = (
        "rateLimitExceeded",
        "quotaExceeded",
        "RESOURCE_EXHAUSTED",
        "WriteRequestsPerMinutePerUser",
    )
    return any(marker in text for marker in rate_limit_markers)


def retry_after_seconds_from_headers(headers: object) -> int:
    """Parse Retry-After seconds from Google response headers with a safe upper bound."""
    header_get = getattr(headers, "get", None)
    if not callable(header_get):
        return DEFAULT_GOOGLE_SHEETS_RETRY_AFTER_SECONDS
    raw_value = header_get("retry-after") or header_get("Retry-After")
    if raw_value is None:
        return DEFAULT_GOOGLE_SHEETS_RETRY_AFTER_SECONDS
    try:
        return _bounded_retry_after_seconds(int(str(raw_value)))
    except ValueError:
        return DEFAULT_GOOGLE_SHEETS_RETRY_AFTER_SECONDS


def _bounded_retry_after_seconds(seconds: int) -> int:
    return max(1, min(seconds, MAX_GOOGLE_SHEETS_RETRY_AFTER_SECONDS))
