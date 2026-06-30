from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.models.studio import PromptCategory, PromptTemplate
from app.services.studio.prompt_template_bootstrap import ensure_builtin_prompt_templates


async def _build_session() -> tuple[AsyncSession, object]:
    """构建内存数据库会话，用于验证默认模板初始化逻辑。"""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return session_local(), engine


@pytest.mark.asyncio
async def test_ensure_builtin_prompt_templates_seeds_empty_database_once() -> None:
    """空库启动时应补齐全部内置模板，重复执行不应重复插入。"""

    db, engine = await _build_session()
    async with db:
        created = await ensure_builtin_prompt_templates(db)
        assert created == len(PromptCategory)

        rows = (await db.execute(select(PromptTemplate))).scalars().all()
        assert len(rows) == len(PromptCategory)
        assert {row.category for row in rows} == set(PromptCategory)
        assert all(row.is_system for row in rows)
        assert all(row.is_default for row in rows)
        assert all(row.content.strip() for row in rows)

        created_again = await ensure_builtin_prompt_templates(db)
        assert created_again == 0

    await engine.dispose()
