from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.models.studio import Chapter, Shot
from app.schemas.skills.script_processing import ScriptDivisionResult, ShotDivision
from app.services.studio.script_division import write_division_result_to_chapter


async def _build_session() -> tuple[AsyncSession, object]:
    """构建内存数据库会话，用于验证章节分镜覆盖写回行为。"""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return session_local(), engine


def _result_for(*titles: str) -> ScriptDivisionResult:
    """快速构造测试用分镜结果。"""

    shots = [
        ShotDivision(
            index=index,
            start_line=index,
            end_line=index,
            script_excerpt=f"excerpt-{index}",
            shot_name=title,
            time_of_day="UNKNOWN",
            character_emotions=[],
        )
        for index, title in enumerate(titles, start=1)
    ]
    return ScriptDivisionResult(shots=shots, total_shots=len(shots), notes=None)


@pytest.mark.asyncio
async def test_write_division_result_to_chapter_replaces_existing_shots() -> None:
    """同章重新提取分镜时，应覆盖旧镜头而不是直接失败。"""

    db, engine = await _build_session()
    async with db:
        db.add(
            Chapter(
                id="chapter-1",
                project_id="project-1",
                index=1,
                title="章节一",
                summary="",
                raw_text="原文",
                storyboard_count=0,
                status="draft",
            )
        )
        await db.commit()

        await write_division_result_to_chapter(db, chapter_id="chapter-1", result=_result_for("旧镜头一", "旧镜头二"))
        await db.commit()

        await write_division_result_to_chapter(db, chapter_id="chapter-1", result=_result_for("新镜头一", "新镜头二", "新镜头三"))
        await db.commit()

        rows = (
            await db.execute(
                select(Shot).where(Shot.chapter_id == "chapter-1").order_by(Shot.index.asc())
            )
        ).scalars().all()

        assert [row.title for row in rows] == ["新镜头一", "新镜头二", "新镜头三"]
        assert [row.index for row in rows] == [1, 2, 3]

    await engine.dispose()
