from fastapi import HTTPException, Request

from app.api.runtime import AgentRuntime
from app.core.config import Settings
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession


def get_runtime(request: Request) -> AgentRuntime:
    runtime = request.app.state.runtime
    if runtime is None:
        raise HTTPException(status_code=503, detail="The assistant is not available right now.")
    return runtime


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings

async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.db_session_factory
    if factory is None:
        raise HTTPException(status_code=503, detail="The database is not available right now.")
    async with factory() as session:
        yield session