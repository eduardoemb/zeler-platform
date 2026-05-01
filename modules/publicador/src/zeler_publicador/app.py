from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from zeler_platform_core.runtime.checks import mongo_check_factory
from zeler_platform_core.runtime.health import HealthCheck, build_health_router
from zeler_platform_core.runtime.manifest import validate_manifest
from zeler_platform_core.runtime.registration import register_module
from zeler_publicador.api import Generator, Publisher, build_router
from zeler_publicador.generator import ListingGenerator, LLMNotConfiguredError, Stub503LLM
from zeler_publicador.publisher import PublicadorPublisher


def build_app(
    *, mongo_db: object, generator: Generator | None = None, publisher: Publisher | None = None
) -> FastAPI:
    app = FastAPI(title="zeler-publicador")
    app.state.mongo_db = mongo_db
    manifest = validate_manifest(Path(__file__).resolve().parents[2] / "manifest.yaml")
    generator = generator or _make_generator()
    publisher = publisher or _StubPublisher()

    async def llm_not_configured_handler(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=503, content={"code": "llm_not_configured"})

    app.add_exception_handler(LLMNotConfiguredError, llm_not_configured_handler)

    mongo_check = mongo_check_factory(mongo_db)

    app.include_router(
        build_health_router(
            manifest.name,
            checks=[HealthCheck(name="mongo", check=mongo_check)],
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
        generator=_make_generator(),
        publisher=PublicadorPublisher(mongo_db=mongo_db, gateway_client=_GatewayProxyClient()),
    )


def _make_generator(listing_llm: str | None = None) -> ListingGenerator:
    import os

    provider = listing_llm or os.environ.get("LISTING_LLM", "stub")
    if provider == "stub":
        return ListingGenerator(llm=Stub503LLM())
    return ListingGenerator(llm=Stub503LLM())


class _StubPublisher:
    async def publish(self, draft_id: str) -> Any:
        raise RuntimeError(f"Publicador publisher is not configured for draft {draft_id}")


class _GatewayProxyClient:
    async def request(
        self, method: str, path: str, *, seller_id: str, json: dict[str, Any]
    ) -> dict[str, Any]:
        import os

        import httpx

        base_url = os.environ.get("GATEWAY_BASE_URL", "http://gateway:8080/proxy/meli")
        token = os.environ.get("GATEWAY_MODULE_TOKEN", "")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.request(
                method,
                f"{base_url.rstrip('/')}/{path.lstrip('/')}",
                headers={"Authorization": f"Bearer {token}", "X-Seller-Id": seller_id},
                json=json,
            )
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]
