"""Migration tests for 0027_users_vectoree_project.

Cloud previews scope DeerFlow users to a Vectoree project: the same email may
exist once per project, while local accounts keep ``vectoree_project_id = ''``.
This file owns the chain-head pin. Set ``TEST_POSTGRES_URI`` to also run the
upgrade/downgrade against Postgres.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence import bootstrap

pytestmark = pytest.mark.asyncio

REVISION = "0027_users_vectoree_project"
PREVIOUS = "0026_mcp_task_lease_tokens"


async def test_0027_is_the_chain_head():
    assert bootstrap._get_head_revision() == REVISION


def _insert(conn, email: str, project: str | None = None) -> None:
    columns = {"id": str(uuid.uuid4()), "email": email, "system_role": "user", "created_at": datetime(2026, 10, 13, tzinfo=UTC), "needs_setup": False, "token_version": 0}
    if project is not None:
        columns["vectoree_project_id"] = project
    names = ", ".join(columns)
    params = ", ".join(f":{name}" for name in columns)
    conn.execute(sa.text(f"INSERT INTO users ({names}) VALUES ({params})"), columns)


async def _exercise(engine) -> None:
    cfg = bootstrap._get_alembic_config(engine)

    async def run(fn):
        async with engine.begin() as conn:
            return await conn.run_sync(fn)

    def indexes(sync):
        return {index["name"]: bool(index["unique"]) for index in sa.inspect(sync).get_indexes("users")}

    await asyncio.to_thread(bootstrap._upgrade, cfg, PREVIOUS)
    await run(lambda sync: _insert(sync, "legacy@example.com"))

    await asyncio.to_thread(bootstrap._upgrade, cfg, "head")
    upgraded = await run(indexes)
    assert (upgraded.get("ix_users_email"), upgraded.get("uq_users_project_email")) == (False, True)
    legacy = await run(lambda sync: sync.execute(sa.text("SELECT vectoree_project_id FROM users WHERE email = 'legacy@example.com'")).scalar_one())
    assert legacy == ""

    await run(lambda sync: _insert(sync, "ada@example.com", "proj-a"))
    await run(lambda sync: _insert(sync, "ada@example.com", "proj-b"))
    with pytest.raises(sa.exc.IntegrityError):
        await run(lambda sync: _insert(sync, "ada@example.com", "proj-a"))

    await run(lambda sync: sync.execute(sa.text("DELETE FROM users WHERE vectoree_project_id = 'proj-b'")))
    await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
    after = await run(indexes)
    assert after.get("ix_users_email") is True
    assert "uq_users_project_email" not in after
    columns = await run(lambda sync: {column["name"] for column in sa.inspect(sync).get_columns("users")})
    assert "vectoree_project_id" not in columns


async def test_0027_scopes_email_per_project_and_downgrades_on_sqlite(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'users-project.db'}")
    try:
        await _exercise(engine)
    finally:
        await engine.dispose()


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URI"), reason="TEST_POSTGRES_URI not set")
async def test_0027_scopes_email_per_project_and_downgrades_on_postgres():
    url = os.environ["TEST_POSTGRES_URI"].replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(sa.text("DROP SCHEMA public CASCADE"))
            await conn.execute(sa.text("CREATE SCHEMA public"))
        await _exercise(engine)
    finally:
        await engine.dispose()
