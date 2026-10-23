from fastapi import HTTPException, Request

from app.api.runtime import AgentRuntime
from app.core.config import Settings
from collections.abc import AsyncIterator
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import TokenError, decode_access_token
from app.db import models, repository

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

bearer_scheme = HTTPBearer(auto_error=False)  # we raise our own 401, in our own error shape


def _not_authenticated() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Not authenticated.",  # the same text for every kind of failure
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> models.User:
    if credentials is None:
        raise _not_authenticated()
    try:
        user_id = decode_access_token(credentials.credentials, settings)
    except TokenError:
        raise _not_authenticated() from None
    user = await repository.get_user_by_id(db, user_id)
    if user is None:
        raise _not_authenticated()
    return user 