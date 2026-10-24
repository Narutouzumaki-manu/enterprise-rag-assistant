from fastapi import HTTPException, Request

from app.api.runtime import AgentRuntime
from app.core.config import Settings
from collections.abc import AsyncIterator
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.api.exchange import ChatStore

from app.core.security import TokenError, decode_access_token
from app.db import models, repository

from sqlalchemy.ext.asyncio import AsyncSession
from app.api.ingestion_service import IngestionRunner


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
        user = await repository.get_user_by_id(db, user_id)
    if user is None:
        raise _not_authenticated()
    await db.commit()  # end the read transaction: hand the connection back instead of holding it all request
    return user 

def get_chat_store(request: Request) -> ChatStore:
    store = request.app.state.chat_store
    if store is None:
        raise HTTPException(status_code=503, detail="The database is not available right now.")
    return store

def get_ingestion_runner(request: Request) -> IngestionRunner:
    runner = request.app.state.ingestion_runner
    if runner is None:
        raise HTTPException(status_code=503, detail="Document processing is not available right now.")
    return runner


def get_retriever(request: Request):
    retriever = request.app.state.retriever
    if retriever is None:
        raise HTTPException(status_code=503, detail="The search index is not available right now.")
    return retriever