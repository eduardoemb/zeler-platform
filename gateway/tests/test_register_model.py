from __future__ import annotations

import pytest
from pydantic import ValidationError

from zeler_gateway.auth.router import RegisterRequest


def test_register_request_rejects_invalid_email_format() -> None:
    with pytest.raises(ValidationError) as exc_info:
        RegisterRequest(
            email="not-an-email",
            name="Operator One",
            auth_provider="local",
        )

    first_error = exc_info.value.errors()[0]
    assert first_error["loc"] == ("email",)
