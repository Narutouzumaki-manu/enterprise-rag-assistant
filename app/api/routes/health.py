import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from redis import asyncio as aioredis
from sqlalchemy import text

from app.schemas.api import HealthResponse

logger = logging.getLogger(__name__)
router = APIRouter()

CHECK_TIMEOUT_SECONDS = 2.0  # starting value


async def _ping_postgres(factory) -> None:
    async with factory() as db:
        await db.execute(text("SELECT 1"))


async def check_postgres(request: Request) -> str:
    factory = request.app.state.db_session_factory
    if factory is None:
        return "unavailable"
    try:
        await asyncio.wait_for(_ping_postgres(factory), CHECK_TIMEOUT_SECONDS)
        return "ok"
    except Exception as exc:
        logger.warning("Health check: postgres unavailable (%s)", type(exc).__name__)
        return "unavailable"


async def _ping_redis(url: str) -> None:
    async with aioredis.from_url(url, socket_connect_timeout=CHECK_TIMEOUT_SECONDS) as client:
        await client.ping()


async def check_redis(request: Request) -> str:
    try:
        await asyncio.wait_for(
            _ping_redis(request.app.state.settings.redis_url), CHECK_TIMEOUT_SECONDS
        )
        return "ok"
    except Exception as exc:
        logger.warning("Health check: redis unavailable (%s)", type(exc).__name__)
        return "unavailable"


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> JSONResponse:
    postgres, redis = await asyncio.gather(check_postgres(request), check_redis(request))
    checks = {
        "postgres": postgres,
        "redis": redis,
        "retriever": "ok" if request.app.state.retriever is not None else "disabled",
        "agent": "ok" if request.app.state.runtime is not None else "disabled",
    }
    degraded = "unavailable" in checks.values()
    body = HealthResponse(status="degraded" if degraded else "ok", checks=checks)
    status_code = 503 if postgres == "unavailable" else 200
    return JSONResponse(status_code=status_code, content=body.model_dump())