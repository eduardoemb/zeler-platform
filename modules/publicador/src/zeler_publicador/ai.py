from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Literal, Protocol
from uuid import uuid4

from zeler_publicador.schemas import SCHEMA_VERSION

SENSITIVE_KEY_PARTS = (
    "token",
    "secret",
    "authorization",
    "cookie",
    "credential",
    "password",
)


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: str
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationRequest:
    seller_id: str
    account_id: str
    draft_id: str
    operation: str
    source_product: dict[str, Any]
    prompt_inputs: dict[str, Any]
    config: ProviderConfig


class GenerationProvider(Protocol):
    async def generate(self, request: GenerationRequest) -> dict[str, Any]: ...


class StaticGenerationProvider:
    def __init__(self, *, provider: str, generated: dict[str, Any]) -> None:
        self.provider = provider
        self.generated = generated
        self.requests: list[GenerationRequest] = []

    async def generate(self, request: GenerationRequest) -> dict[str, Any]:
        self.requests.append(request)
        return dict(self.generated)


class AIGenerationService:
    def __init__(
        self,
        mongo_db: Any,
        *,
        providers: Mapping[str, GenerationProvider],
        platform_default: ProviderConfig,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[str], str] | None = None,
        retention_days: int = 30,
    ) -> None:
        self._mongo_db = mongo_db
        self._providers = providers
        self._platform_default = platform_default
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda prefix: f"{prefix}-{uuid4().hex}")
        self._retention_days = retention_days

    async def generate_for_draft(
        self,
        *,
        seller_id: str,
        account_id: str,
        draft_id: str,
        operation: Literal["title", "description", "category", "attributes", "family"] | str,
        prompt_inputs: dict[str, Any] | None = None,
        actor_id: str,
    ) -> dict[str, Any]:
        prompt_inputs = prompt_inputs or {}
        draft = await self._mongo_db["publicador_drafts"].find_one(
            {"_id": draft_id, "seller_id": seller_id, "account_id": account_id}
        )
        if draft is None:
            raise ValueError("publicador_draft_not_found")

        config = await self._resolve_config(seller_id=seller_id, account_id=account_id)
        provider = self._providers.get(config.provider)
        if provider is None:
            raise ValueError("publicador_ai_provider_not_configured")

        request = GenerationRequest(
            seller_id=seller_id,
            account_id=account_id,
            draft_id=draft_id,
            operation=operation,
            source_product=dict(draft.get("source_product", {})),
            prompt_inputs=prompt_inputs,
            config=config,
        )
        started_at = self._clock()
        sensitive_values = _sensitive_values(
            {
                "source_product": request.source_product,
                "prompt_inputs": prompt_inputs,
                "config": config.options,
            }
        )
        try:
            generated = await provider.generate(request)
        except Exception as exc:
            await self._persist_audit(
                seller_id=seller_id,
                account_id=account_id,
                draft_id=draft_id,
                operation=operation,
                actor_id=actor_id,
                config=config,
                status="failed",
                redacted_input=redact_payload(
                    {"source_product": request.source_product, "prompt_inputs": prompt_inputs},
                    sensitive_values=sensitive_values,
                ),
                redacted_output={},
                error=str(exc),
                created_at=started_at,
            )
            await self._mark_draft_failed(draft, actor_id=actor_id)
            raise

        redacted_output = redact_payload(generated, sensitive_values=sensitive_values)
        updated_draft = {
            **draft,
            "generated_listing": {**draft.get("generated_listing", {}), **generated},
            "status": "generated",
            "enrichment_status": "generated",
            "updated_at": self._clock(),
            "updated_by": actor_id,
        }
        await self._mongo_db["publicador_drafts"].replace_one(
            {"_id": draft_id, "seller_id": seller_id, "account_id": account_id},
            updated_draft,
            upsert=False,
        )
        audit = await self._persist_audit(
            seller_id=seller_id,
            account_id=account_id,
            draft_id=draft_id,
            operation=operation,
            actor_id=actor_id,
            config=config,
            status="generated",
            redacted_input=redact_payload(
                {"source_product": request.source_product, "prompt_inputs": prompt_inputs},
                sensitive_values=sensitive_values,
            ),
            redacted_output=redacted_output,
            error=None,
            created_at=started_at,
        )
        await self._append_event(
            seller_id=seller_id,
            account_id=account_id,
            draft_id=draft_id,
            operation="ai.generated",
            status="generated",
            actor_id=actor_id,
            details={
                "generation_id": audit["_id"],
                "provider": config.provider,
                "model": config.model,
            },
        )
        return {
            "provider": config.provider,
            "model": config.model,
            "generated_listing": generated,
            "audit_id": audit["_id"],
        }

    async def _resolve_config(self, *, seller_id: str, account_id: str) -> ProviderConfig:
        settings = await self._mongo_db["publicador_settings"].find_one(
            {"seller_id": seller_id, "account_id": account_id}
        )
        ai_config = dict(settings.get("ai_config", {})) if settings else {}
        provider = str(ai_config.get("provider") or self._platform_default.provider)
        model = str(ai_config.get("model") or self._platform_default.model)
        options = {
            key: value for key, value in ai_config.items() if key not in {"provider", "model"}
        }
        return ProviderConfig(provider=provider, model=model, options=options)

    async def _persist_audit(
        self,
        *,
        seller_id: str,
        account_id: str,
        draft_id: str,
        operation: str,
        actor_id: str,
        config: ProviderConfig,
        status: str,
        redacted_input: dict[str, Any],
        redacted_output: dict[str, Any],
        error: str | None,
        created_at: datetime,
    ) -> dict[str, Any]:
        audit = {
            "_id": self._id_factory("ai-generation"),
            "seller_id": seller_id,
            "account_id": account_id,
            "draft_id": draft_id,
            "operation": operation,
            "provider": config.provider,
            "model": config.model,
            "config_fingerprint": _config_fingerprint(config),
            "redacted_input": redacted_input,
            "redacted_output": redacted_output,
            "status": status,
            "error": redact_payload(error, sensitive_values=[]),
            "actor_id": actor_id,
            "created_at": created_at,
            "retention_until": created_at + timedelta(days=self._retention_days),
            "schema_version": SCHEMA_VERSION,
        }
        await self._mongo_db["publicador_ai_generations"].insert_one(audit)
        return audit

    async def _mark_draft_failed(self, draft: dict[str, Any], *, actor_id: str) -> None:
        updated = {
            **draft,
            "enrichment_status": "failed",
            "updated_at": self._clock(),
            "updated_by": actor_id,
        }
        await self._mongo_db["publicador_drafts"].replace_one(
            {
                "_id": draft["_id"],
                "seller_id": draft["seller_id"],
                "account_id": draft["account_id"],
            },
            updated,
            upsert=False,
        )

    async def _append_event(
        self,
        *,
        seller_id: str,
        account_id: str,
        draft_id: str,
        operation: str,
        status: str,
        actor_id: str,
        details: dict[str, Any],
    ) -> None:
        await self._mongo_db["publicador_events"].insert_one(
            {
                "_id": self._id_factory("event"),
                "seller_id": seller_id,
                "account_id": account_id,
                "aggregate_type": "draft",
                "aggregate_id": draft_id,
                "draft_id": draft_id,
                "operation": operation,
                "status": status,
                "actor_id": actor_id,
                "details": details,
                "created_at": self._clock(),
                "schema_version": SCHEMA_VERSION,
            }
        )


def redact_payload(payload: Any, *, sensitive_values: list[str] | None = None) -> Any:
    sensitive_values = sensitive_values or []
    if isinstance(payload, dict):
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            if _is_sensitive_key(key):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_payload(value, sensitive_values=sensitive_values)
        return redacted
    if isinstance(payload, list):
        return [redact_payload(item, sensitive_values=sensitive_values) for item in payload]
    if isinstance(payload, str):
        value = payload
        for secret in sensitive_values:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return re.sub(r"Bearer\s+[^\s]+", "Bearer [REDACTED]", value)
    return payload


def _sensitive_values(payload: Any) -> list[str]:
    values: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if _is_sensitive_key(key) and isinstance(value, str):
                values.append(value)
            else:
                values.extend(_sensitive_values(value))
    elif isinstance(payload, list):
        for item in payload:
            values.extend(_sensitive_values(item))
    return values


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _config_fingerprint(config: ProviderConfig) -> str:
    redacted_options = redact_payload(
        config.options, sensitive_values=_sensitive_values(config.options)
    )
    encoded = json.dumps(
        {"provider": config.provider, "model": config.model, "options": redacted_options},
        sort_keys=True,
        default=str,
    ).encode()
    return sha256(encoded).hexdigest()
