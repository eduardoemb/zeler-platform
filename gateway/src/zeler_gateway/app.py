from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient

from zeler_gateway.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    get_settings.cache_clear()
    settings = get_settings()
    app.state.mongo_client = AsyncIOMotorClient(
        settings.mongo_uri,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=30000,
    )
    app.state.mongo_db = app.state.mongo_client[settings.mongo_db]
    app.state.scheduler = AsyncIOScheduler()
    app.state.scheduler.start()

    try:
        yield
    finally:
        app.state.scheduler.shutdown(wait=False)
        app.state.mongo_client.close()


app = FastAPI(title="zeler-meli-gateway", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
