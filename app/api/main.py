from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app.api.bootstrap import build_real_components, real_ingest
from app.api.errors import register_error_handlers
from app.api.ingestion_service import IngestionRunner
from app.api.routes import auth, chat, documents, feedback, health, prometheus, sessions
from app.api.runtime import AgentRuntime
from app.api.shutdown import drain_background_tasks
from app.api.startup import sweep_interrupted_documents
from app.api.exchange import ChatStore
from app.api.middleware import UploadSizeLimitMiddleware
from app.api.uploads import MIB
from app.core.config import Settings, get_settings
from app.api.limits import limiter
from app.db.session import create_engine, create_session_factory
from app.api.request_id import RequestIdMiddleware
from app.api.metrics import MetricsMiddleware
from app.core.logging_setup import configure_logging


def make_runtime(agent, settings: Settings) -> AgentRuntime:
    return AgentRuntime(
        agent,
        settings.agent_max_concurrent,
        settings.agent_wait_seconds,
    )


def make_ingestion_runner(session_factory, retriever, ingest, settings: Settings):
    if session_factory is None or retriever is None:
        return None  # uploads need both a database and a retriever
    return IngestionRunner(
        session_factory,
        retriever,
        ingest,
        settings.ingest_max_concurrent,
    )


def create_app(
    agent=None,
    retriever=None,
    settings: Settings | None = None,
    session_factory=None,
    chat_store=None,
    ingest=None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)
    ingest = ingest or real_ingest

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = None
        try:
            if app.state.db_session_factory is None:
                engine = create_engine(settings.database_url)
                app.state.db_session_factory = create_session_factory(engine)
                if app.state.chat_store is None:
                    app.state.chat_store = ChatStore(
                        app.state.db_session_factory
                    )

            if app.state.runtime is None and settings.agent_enabled:
                real_retriever, real_agent = await run_in_threadpool(
                    build_real_components, settings
                )
                app.state.retriever = real_retriever
                app.state.runtime = make_runtime(real_agent, settings)

            if app.state.ingestion_runner is None:
                app.state.ingestion_runner = make_ingestion_runner(
                    app.state.db_session_factory,
                    app.state.retriever,
                    ingest,
                    settings,
                )

            if app.state.db_session_factory is not None:
                await sweep_interrupted_documents(
                    app.state.db_session_factory, app.state.retriever
                )

            yield
        finally:
            await drain_background_tasks(
                app.state.background_tasks, settings.shutdown_grace_seconds
            )
            if engine is not None:
                await engine.dispose()

    app = FastAPI(title="Enterprise RAG Assistant API", lifespan=lifespan)

    app.add_middleware(
        UploadSizeLimitMiddleware,
        path="/documents/upload",
        max_bytes=settings.max_upload_mb * MIB,
    )
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(MetricsMiddleware)

    app.state.settings = settings
    app.state.limiter = limiter
    app.state.retriever = retriever
    app.state.runtime = make_runtime(agent, settings) if agent is not None else None
    app.state.db_session_factory = session_factory
    app.state.background_tasks = set()
    app.state.ingestion_runner = make_ingestion_runner(
        session_factory, retriever, ingest, settings
    )

    if chat_store is None and session_factory is not None:
        chat_store = ChatStore(session_factory)
    app.state.chat_store = chat_store

    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(sessions.router)
    app.include_router(chat.router)
    app.include_router(documents.router)
    app.include_router(feedback.router)  # change 2: registered after documents
    app.include_router(prometheus.router)

    return app


app = create_app()