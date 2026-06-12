"""Studio 实体图片 CRUD。"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.utils import apply_order, paginate
from app.models.studio import CharacterImage
from app.services.common import entity_not_found
from app.services.studio.entity_specs import entity_spec, normalize_entity_type

IMAGE_ORDER_FIELDS = {"id", "quality_level", "view_angle", "created_at", "updated_at"}


async def list_entity_images_paginated(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    order: str | None,
    is_desc: bool,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    spec = entity_spec(entity_type)
    parent = await db.get(spec.model, entity_id)
    if parent is None:
        raise HTTPException(status_code=404, detail=entity_not_found(spec.model.__name__))

    id_field = getattr(spec.image_model, spec.id_field)
    stmt = select(spec.image_model).where(id_field == entity_id)
    stmt = apply_order(
        stmt,
        model=spec.image_model,
        order=order,
        is_desc=is_desc,
        allow_fields=IMAGE_ORDER_FIELDS,
        default="id",
    )
    items, total = await paginate(db, stmt=stmt, page=page, page_size=page_size)
    payload = [spec.image_read_model.model_validate(x).model_dump() for x in items]
    return payload, total


async def create_entity_image(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    entity_type_norm = normalize_entity_type(entity_type)
    spec = entity_spec(entity_type_norm)
    parent = await db.get(spec.model, entity_id)
    if parent is None:
        raise HTTPException(status_code=404, detail=entity_not_found(spec.model.__name__))

    parsed = spec.image_create_model.model_validate(body).model_dump()

    # 幂等：若相同 (entity_id, quality_level, view_angle) 已存在则直接返回
    id_field_col = getattr(spec.image_model, spec.id_field)
    existing_stmt = select(spec.image_model).where(id_field_col == entity_id)
    for key in ("quality_level", "view_angle"):
        if key in parsed and parsed[key] is not None:
            existing_stmt = existing_stmt.where(getattr(spec.image_model, key) == parsed[key])
    existing = (await db.execute(existing_stmt)).scalars().first()
    if existing is not None:
        return spec.image_read_model.model_validate(existing).model_dump()

    obj = spec.image_model(**{spec.id_field: entity_id, **parsed})
    db.add(obj)
    await db.flush()
    await db.refresh(obj)

    if entity_type_norm == "character" and getattr(obj, "is_primary", False):
        stmt = (
            CharacterImage.__table__.update()
            .where(CharacterImage.character_id == entity_id, CharacterImage.id != obj.id)
            .values(is_primary=False)
        )
        await db.execute(stmt)
        await db.refresh(obj)

    return spec.image_read_model.model_validate(obj).model_dump()


async def update_entity_image(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    image_id: int,
    body: dict[str, Any],
) -> dict[str, Any]:
    entity_type_norm = normalize_entity_type(entity_type)
    spec = entity_spec(entity_type_norm)
    obj = await db.get(spec.image_model, image_id)
    if obj is None or getattr(obj, spec.id_field) != entity_id:
        raise HTTPException(status_code=404, detail=entity_not_found(spec.image_model.__name__))

    update_data = spec.image_update_model.model_validate(body).model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(obj, key, value)
    await db.flush()
    await db.refresh(obj)

    if entity_type_norm == "character" and update_data.get("is_primary") is True:
        stmt = (
            CharacterImage.__table__.update()
            .where(CharacterImage.character_id == entity_id, CharacterImage.id != obj.id)
            .values(is_primary=False)
        )
        await db.execute(stmt)
        await db.refresh(obj)

    return spec.image_read_model.model_validate(obj).model_dump()


async def delete_entity_image(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    image_id: int,
) -> None:
    spec = entity_spec(entity_type)
    obj = await db.get(spec.image_model, image_id)
    if obj is None or getattr(obj, spec.id_field) != entity_id:
        return
    await db.delete(obj)
    await db.flush()
