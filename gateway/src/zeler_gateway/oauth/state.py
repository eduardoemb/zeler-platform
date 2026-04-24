from __future__ import annotations

import time
from dataclasses import dataclass

import jwt

from zeler_gateway.config import Settings

# TODO(post-P1): replace HS256/HMAC state signing with KMS asymmetric ES256
# using the `platform-jwt` key (see design §5.1). The current HMAC variant
# uses Settings.state_signing_secret which must NEVER leak; for now that's
# acceptable because state carries only platform_user_id + TTL and is
# single-use. KMS asymmetric is scoped as a P1.x hardening task.


@dataclass(frozen=True)
class StateClaims:
    platform_user_id: str
    iat: int
    exp: int


def mint_state_jwt(platform_user_id: str, *, settings: Settings) -> str:
    now = int(time.time())
    payload = {
        "platform_user_id": platform_user_id,
        "iat": now,
        "exp": now + settings.state_ttl_seconds,
    }
    return jwt.encode(payload, settings.state_signing_secret.get_secret_value(), algorithm="HS256")


def verify_state_jwt(token: str, *, settings: Settings) -> StateClaims:
    payload = jwt.decode(
        token,
        settings.state_signing_secret.get_secret_value(),
        algorithms=["HS256"],
    )
    return StateClaims(
        platform_user_id=payload["platform_user_id"],
        iat=payload["iat"],
        exp=payload["exp"],
    )
