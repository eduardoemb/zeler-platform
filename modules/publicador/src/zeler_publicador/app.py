from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from zeler_platform_core.runtime.checks import mongo_check_factory, rabbitmq_check_factory
from zeler_platform_core.runtime.health import HealthCheck, build_health_router
from zeler_platform_core.runtime.manifest import validate_manifest
from zeler_platform_core.runtime.registration import register_module, registration_matches_manifest
from zeler_publicador.ai import ProviderConfig, PublicadorConfigError
from zeler_publicador.api import Generator, Publisher, build_router
from zeler_publicador.generator import ListingGenerator, LLMNotConfiguredError, Stub503LLM
from zeler_publicador.publisher import PublicadorPublisher

LEGAL_LISTING_LLM_VALUES = frozenset({"stub", "disabled"})
AI_FAIL_CLOSED_PROVIDER = "stub"
AI_FAIL_CLOSED_MODEL = "disabled"


@dataclass(frozen=True)
class PublicadorRuntimeConfig:
    gateway_base_url: str
    gateway_module_token: str


def resolve_publicador_runtime_config(env: dict[str, str | None]) -> PublicadorRuntimeConfig:
    gateway_base_url = (env.get("GATEWAY_BASE_URL") or "").strip().rstrip("/")
    gateway_module_token = (env.get("GATEWAY_MODULE_TOKEN") or "").strip()

    if not gateway_base_url:
        raise PublicadorConfigError("GATEWAY_BASE_URL is required for Publicador API mode")
    if not gateway_module_token:
        raise PublicadorConfigError("GATEWAY_MODULE_TOKEN is required for Publicador API mode")
    if _is_unsafe_gateway_base_url(gateway_base_url):
        raise PublicadorConfigError(
            "GATEWAY_BASE_URL must point to the live gateway proxy, "
            "not local or legacy Publicador runtime"
        )

    return PublicadorRuntimeConfig(
        gateway_base_url=gateway_base_url,
        gateway_module_token=gateway_module_token,
    )


def build_app(
    *,
    mongo_db: object,
    generator: Generator | None = None,
    publisher: Publisher | None = None,
    rabbitmq_url: str | None = None,
    rabbitmq_connect: Callable[..., Awaitable[Any]] | None = None,
) -> FastAPI:
    app = FastAPI(title="zeler-publicador")
    app.state.mongo_db = mongo_db
    manifest = validate_manifest(Path(__file__).resolve().parents[2] / "manifest.yaml")
    # Single construction path: reject unsupported LISTING_LLM values before serving.
    selected_generator = select_listing_generator()
    generator = generator or selected_generator
    publisher = publisher or _StubPublisher()

    # Both AI routes derive from the stub selector: only the fail-closed stub
    # provider is legal, so /publicador/ai/generate can never serve a listing.
    app.state.publicador_ai_providers = {}
    app.state.publicador_ai_default = ProviderConfig(
        provider=AI_FAIL_CLOSED_PROVIDER, model=AI_FAIL_CLOSED_MODEL
    )

    async def llm_not_configured_handler(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=503, content={"code": "llm_not_configured"})

    app.add_exception_handler(LLMNotConfiguredError, llm_not_configured_handler)
    app.add_exception_handler(PublicadorConfigError, llm_not_configured_handler)

    mongo_check = mongo_check_factory(mongo_db)
    rabbitmq_check = rabbitmq_check_factory(
        lambda: rabbitmq_url,
        timeout_seconds=5.0,
        connect=rabbitmq_connect,
    )

    async def registry_check() -> tuple[bool, str]:
        try:
            database = cast(Any, mongo_db)
            document = await database["module_registry"].find_one({"_id": manifest.module_id})
        except Exception:  # noqa: BLE001 - health must fail closed on registry read errors.
            return False, "registry_fingerprint_unavailable"
        if not registration_matches_manifest(document=document, manifest=manifest):
            return False, "registry_fingerprint_mismatch"
        return True, "registry_fingerprint_match"

    app.include_router(
        build_health_router(
            manifest.name,
            checks=[
                HealthCheck(name="mongo", check=mongo_check),
                HealthCheck(name="rabbitmq", check=rabbitmq_check),
                HealthCheck(name="registry", check=registry_check),
            ],
        )
    )
    app.include_router(build_router(generator=generator, publisher=publisher))

    async def register_startup() -> None:
        await register_module(manifest, mongo_db)

    app.router.on_startup.append(register_startup)
    return app


def make_app() -> FastAPI:
    """No-arg factory for uvicorn --factory; resolves deps at call time."""
    import os

    from motor.motor_asyncio import AsyncIOMotorClient

    mongo_uri = os.environ.get("MONGO_URI")
    mongo_db_name = os.environ.get("MONGO_DB")
    if not mongo_uri:
        raise RuntimeError("MONGO_URI is required for API mode")
    if not mongo_db_name:
        raise RuntimeError("MONGO_DB is required for API mode")
    mongo_db: object = AsyncIOMotorClient(mongo_uri)[mongo_db_name]
    return build_app(
        mongo_db=mongo_db,
        generator=select_listing_generator(),
        publisher=PublicadorPublisher(mongo_db=mongo_db, gateway_client=_GatewayProxyClient()),
        rabbitmq_url=os.environ.get("RABBITMQ_URL"),
    )


def select_listing_generator(listing_llm: str | None = None) -> ListingGenerator:
    """Build the listing generator from the single legal LISTING_LLM contract.

    Only ``stub`` and ``disabled`` are legal; both return the fail-closed 503
    stub. Any other value raises :class:`PublicadorConfigError` so unsupported
    providers fail closed at startup instead of serving a contradictory state.
    """
    import os

    raw_value = listing_llm or os.environ.get("LISTING_LLM", AI_FAIL_CLOSED_PROVIDER)
    provider = raw_value.strip().lower()
    if provider in LEGAL_LISTING_LLM_VALUES:
        return ListingGenerator(llm=Stub503LLM())
    raise PublicadorConfigError(
        f"invalid LISTING_LLM provider {provider!r}; only 'stub' or 'disabled' are legal"
    )


class _StubPublisher:
    async def publish(self, draft_id: str) -> Any:
        raise RuntimeError(f"Publicador publisher is not configured for draft {draft_id}")


class _GatewayProxyClient:
    def __init__(self, config: PublicadorRuntimeConfig | None = None) -> None:
        self._config = config

    async def request(
        self, method: str, path: str, *, seller_id: str, json: dict[str, Any]
    ) -> dict[str, Any]:
        import os

        import httpx

        config = self._config or resolve_publicador_runtime_config(
            {
                "GATEWAY_BASE_URL": os.environ.get("GATEWAY_BASE_URL"),
                "GATEWAY_MODULE_TOKEN": os.environ.get("GATEWAY_MODULE_TOKEN"),
            }
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.request(
                method,
                f"{config.gateway_base_url}/{path.lstrip('/')}",
                headers={
                    "Authorization": f"Bearer {config.gateway_module_token}",
                    "X-Seller-Id": seller_id,
                },
                json=json,
            )
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]


def _is_unsafe_gateway_base_url(base_url: str) -> bool:
    lowered = base_url.lower()
    return (
        lowered.startswith("http://localhost")
        or lowered.startswith("http://127.0.0.1")
        or "publicadormeli" in lowered
        or "zeler-core" in lowered
    )
