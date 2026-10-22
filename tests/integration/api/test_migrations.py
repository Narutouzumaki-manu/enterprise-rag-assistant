import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.models import Base

ROOT = Path(__file__).resolve().parents[3]
APP_TABLES = {
    "users", "sessions", "documents", "chunks", "messages",
    "citations", "agent_traces", "feedback", "audit_events",
}


def _config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "app" / "db" / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


async def _with_connection(url: str, work):
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            return await conn.run_sync(work)
    finally:
        await engine.dispose()


def _empty_schema(url: str) -> None:
    async def reset():
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("DROP SCHEMA public CASCADE"))
                await conn.execute(text("CREATE SCHEMA public"))
        finally:
            await engine.dispose()

    try:
        asyncio.run(reset())
    except (OSError, SQLAlchemyError) as exc:
        pytest.skip(f"Test database not available: {exc}")


def _table_names(url: str) -> set[str]:
    return asyncio.run(_with_connection(url, lambda c: set(inspect(c).get_table_names())))


def test_upgrade_creates_the_tables_and_downgrade_removes_them(database_url):
    _empty_schema(database_url)
    config = _config(database_url)

    command.upgrade(config, "head")
    assert APP_TABLES <= _table_names(database_url)

    command.downgrade(config, "base")
    assert not (APP_TABLES & _table_names(database_url))


def test_migration_and_models_agree(database_url):
    _empty_schema(database_url)
    command.upgrade(_config(database_url), "head")

    def pending(sync_conn):
        return compare_metadata(MigrationContext.configure(sync_conn), Base.metadata)

    assert asyncio.run(_with_connection(database_url, pending)) == []