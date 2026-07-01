"""剧本分镜写库服务：将分镜结果落到 Chapter/Shot/ShotDetail。"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.studio import CameraAngle, CameraMovement, CameraShotType, Chapter, Shot, ShotDetail, VFXType
from app.schemas.skills.script_processing import ScriptDivisionResult
from app.services.common import entity_not_found, require_entity


def _append_division_rows(
    db_add,
    *,
    chapter_id: str,
    result: ScriptDivisionResult,
) -> None:
    for shot_division in result.shots:
        title = (shot_division.shot_name or "").strip() or f"镜头 {shot_division.index}"
        shot_id = str(uuid.uuid4())
        emotions_json = [e.model_dump() for e in shot_division.character_emotions] if shot_division.character_emotions is not None else None
        db_add(
            Shot(
                id=shot_id,
                chapter_id=chapter_id,
                index=shot_division.index,
                title=title,
                script_excerpt=shot_division.script_excerpt,
                character_emotions=emotions_json,
            )
        )
        db_add(
            ShotDetail(
                id=shot_id,
                camera_shot=CameraShotType.ms,
                angle=CameraAngle.eye_level,
                movement=CameraMovement.static,
                follow_atmosphere=True,
                vfx_type=VFXType.none,
                duration=4,
            )
        )


async def write_division_result_to_chapter(
    db: AsyncSession,
    *,
    chapter_id: str,
    result: ScriptDivisionResult,
) -> None:
    """将分镜结果写入指定章节；若章节已有镜头则覆盖旧结果。"""
    await require_entity(
        db,
        Chapter,
        chapter_id,
        detail=entity_not_found("Chapter"),
        status_code=400,
    )

    await db.execute(delete(Shot).where(Shot.chapter_id == chapter_id))
    await db.flush()

    _append_division_rows(db.add, chapter_id=chapter_id, result=result)

    # 触发唯一约束与外键检查，确保在返回前失败。
    await db.flush()


def write_division_result_to_chapter_sync(
    db: Session,
    *,
    chapter_id: str,
    result: ScriptDivisionResult,
) -> None:
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=400, detail=entity_not_found("Chapter"))

    db.execute(delete(Shot).where(Shot.chapter_id == chapter_id))
    db.flush()

    _append_division_rows(db.add, chapter_id=chapter_id, result=result)
    db.flush()
