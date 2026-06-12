from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.models.studio import (
    Actor,
    ActorImage,
    AssetQualityLevel,
    AssetViewAngle,
    Character,
    CharacterImage,
    Costume,
    CostumeImage,
    PromptCategory,
    Prop,
    PropImage,
    Scene,
    SceneImage,
)
from app.services.common import entity_not_found
from app.services.studio.generation.shared.types import GenerationBaseDraft
from app.services.studio.image_task_references import (
    pick_front_ref_file_id,
    pick_ordered_ref_file_ids,
)
from app.services.studio.image_task_validation import (
    validate_actor_image,
    validate_asset_image_and_relation_type,
    validate_character_image,
)
from app.services.studio.image_tasks import (
    asset_prompt_category,
    build_prompt_with_template,
    is_front_view,
    map_view_angle_for_prompt,
)


class AssetImageBaseDraft(GenerationBaseDraft):
    """资产图片生成的基础真值。"""

    kind: str = "asset_image"
    entity_type: str
    entity_id: str
    image_id: int
    relation_type: str
    relation_entity_id: str
    prompt: str
    default_images: list[str]


def _enum_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "")


async def _build_asset_prompt(
    db,
    *,
    relation_type: str,
    name: str,
    description: str,
    tags: list[str] | None,
    visual_style: Any,
    style: Any,
    image_row: Any,
) -> str:
    category = asset_prompt_category(
        relation_type=relation_type,
        is_front_view=is_front_view(image_row.view_angle),
    )
    return await build_prompt_with_template(
        db,
        category=category,
        variables={
            "name": name,
            "description": description,
            "tags": ", ".join(tags or []),
            "visual_style": _enum_value(visual_style),
            "style": _enum_value(style),
            "view_angle": map_view_angle_for_prompt(image_row.view_angle),
            "quality_level": image_row.quality_level,
            "format": image_row.format,
        },
        fallback_prompt=description,
        not_found_msg=f"{relation_type}.description is empty",
    )


async def _resolve_front_ref(
    db,
    *,
    image_model,
    parent_field_name: str,
    parent_id: str,
    preferred_quality_level: str | None,
) -> list[str]:
    file_id = await pick_front_ref_file_id(
        db,
        image_model=image_model,
        parent_field_name=parent_field_name,
        parent_id=parent_id,
        preferred_quality_level=preferred_quality_level,
    )
    return [file_id] if file_id else []


async def build_actor_image_base_draft(
    db,
    *,
    actor_id: str,
    image_id: int | None,
) -> AssetImageBaseDraft:
    actor = await db.get(Actor, actor_id)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=entity_not_found("Actor"))
    image_row = await validate_actor_image(db, actor_id=actor_id, image_id=image_id)
    prompt = await _build_asset_prompt(
        db,
        relation_type="actor_image",
        name=actor.name,
        description=actor.description,
        tags=actor.tags,
        visual_style=actor.visual_style,
        style=actor.style,
        image_row=image_row,
    )
    refs = []
    if not is_front_view(image_row.view_angle):
        refs = await _resolve_front_ref(
            db,
            image_model=ActorImage,
            parent_field_name="actor_id",
            parent_id=actor_id,
            preferred_quality_level=image_row.quality_level,
        )
    return AssetImageBaseDraft(
        entity_type="actor",
        entity_id=actor_id,
        image_id=image_row.id,
        relation_type="actor_image",
        relation_entity_id=str(image_row.id),
        prompt=prompt,
        default_images=refs,
    )


async def build_asset_image_base_draft(
    db,
    *,
    asset_type: str,
    asset_id: str,
    image_id: int | None,
) -> AssetImageBaseDraft:
    relation_entity_id, relation_type = await validate_asset_image_and_relation_type(
        db,
        asset_type=asset_type,
        asset_id=asset_id,
        image_id=image_id,
    )
    asset_type_norm = asset_type.strip().lower()
    refs: list[str] = []
    if asset_type_norm == "prop":
        asset = await db.get(Prop, asset_id)
        image_row = await db.get(PropImage, relation_entity_id)
        image_model = PropImage
        parent_field_name = "prop_id"
    elif asset_type_norm == "scene":
        asset = await db.get(Scene, asset_id)
        image_row = await db.get(SceneImage, relation_entity_id)
        image_model = SceneImage
        parent_field_name = "scene_id"
    else:
        asset = await db.get(Costume, asset_id)
        image_row = await db.get(CostumeImage, relation_entity_id)
        image_model = CostumeImage
        parent_field_name = "costume_id"
    if asset is None or image_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=entity_not_found("AssetImage"))
    prompt = await _build_asset_prompt(
        db,
        relation_type=relation_type,
        name=asset.name,
        description=asset.description,
        tags=asset.tags,
        visual_style=asset.visual_style,
        style=asset.style,
        image_row=image_row,
    )
    if not is_front_view(image_row.view_angle):
        refs = await _resolve_front_ref(
            db,
            image_model=image_model,
            parent_field_name=parent_field_name,
            parent_id=asset_id,
            preferred_quality_level=image_row.quality_level,
        )
    return AssetImageBaseDraft(
        entity_type=asset_type.strip().lower(),
        entity_id=asset_id,
        image_id=relation_entity_id,
        relation_type=relation_type,
        relation_entity_id=str(relation_entity_id),
        prompt=prompt,
        default_images=refs,
    )


async def build_character_image_base_draft(
    db,
    *,
    character_id: str,
    image_id: int | None,
) -> AssetImageBaseDraft:
    character = await db.get(Character, character_id)
    if character is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=entity_not_found("Character"))
    image_row = await validate_character_image(db, character_id=character_id, image_id=image_id)
    prompt = await build_prompt_with_template(
        db,
        category=PromptCategory.combined,
        variables={
            "name": character.name,
            "description": character.description,
            "visual_style": _enum_value(character.visual_style),
            "style": _enum_value(character.style),
            "view_angle": map_view_angle_for_prompt(image_row.view_angle),
            "quality_level": image_row.quality_level,
            "format": image_row.format,
        },
        fallback_prompt=character.description,
        not_found_msg="Character.description is empty",
    )
    refs: list[str] = []
    default_view_angles: tuple[AssetViewAngle, ...] = (
        AssetViewAngle.front,
        AssetViewAngle.left,
        AssetViewAngle.right,
        AssetViewAngle.back,
    )
    if character.actor_id:
        refs.extend(
            await pick_ordered_ref_file_ids(
                db,
                image_model=ActorImage,
                parent_field_name="actor_id",
                parent_id=character.actor_id,
                view_angles=default_view_angles,
            )
        )
    if character.costume_id:
        refs.extend(
            await pick_ordered_ref_file_ids(
                db,
                image_model=CostumeImage,
                parent_field_name="costume_id",
                parent_id=character.costume_id,
                view_angles=default_view_angles,
            )
        )
    return AssetImageBaseDraft(
        entity_type="character",
        entity_id=character_id,
        image_id=image_row.id,
        relation_type="character_image",
        relation_entity_id=str(image_row.id),
        prompt=prompt,
        default_images=refs,
    )


# --------------------------------------------------------------------------- #
# 角色设定图（Character Sheet）                                                 #
# --------------------------------------------------------------------------- #

def _sheet_fallback_prompt(name: str, desc: str, visual_fingerprint: str) -> str:
    appearance = visual_fingerprint.strip() if visual_fingerprint else desc.strip()
    char_part = f"{name}，{appearance}。" if appearance else f"{name}。"
    return (
        f"{char_part}"
        "角色设定参考图，白色或浅灰色中性背景，展示同一角色的多个视角："
        "正面半身（左上）、四分之三侧面（右上）、面部特写（左下）、全身正面（右下）；"
        "四格布局，统一光照，清晰展现发型、五官、肤色、服装颜色和材质细节；"
        "不含任何场景背景、文字水印或多余装饰；"
        "原创虚构角色，不模仿真实人物或版权角色。"
    )


async def ensure_character_sheet_image_row(
    db,
    *,
    character_id: str,
) -> CharacterImage:
    """确保角色存在 DETAIL+ULTRA 的设定图槽位，不存在则创建并返回。"""
    from sqlalchemy import select as _select

    stmt = _select(CharacterImage).where(
        CharacterImage.character_id == character_id,
        CharacterImage.view_angle == AssetViewAngle.detail,
        CharacterImage.quality_level == AssetQualityLevel.ultra,
    )
    row = (await db.execute(stmt)).scalars().first()
    if row is not None:
        return row

    row = CharacterImage(
        character_id=character_id,
        view_angle=AssetViewAngle.detail,
        quality_level=AssetQualityLevel.ultra,
        format="png",
        is_primary=False,
    )
    db.add(row)
    await db.flush()
    return row


async def build_character_sheet_base_draft(
    db,
    *,
    character_id: str,
) -> AssetImageBaseDraft:
    """为角色生成"设定图"的基础草稿。

    设定图固定存入 view_angle=DETAIL、quality_level=ULTRA 的槽位，
    生成时会将演员/服装的现有正面图作为参考注入，提高角色外貌一致性。
    """
    character = await db.get(Character, character_id)
    if character is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=entity_not_found("Character"))

    image_row = await ensure_character_sheet_image_row(db, character_id=character_id)

    # 优先使用视觉指纹，无则降级用描述
    desc = (character.description or "").strip()
    visual_fingerprint = (getattr(character, "visual_fingerprint", None) or "").strip()
    fallback = _sheet_fallback_prompt(character.name, desc, visual_fingerprint)

    prompt = await build_prompt_with_template(
        db,
        category=PromptCategory.character_sheet,
        variables={
            "name": character.name,
            "description": desc,
            "visual_fingerprint": visual_fingerprint,
            "visual_style": _enum_value(character.visual_style),
            "style": _enum_value(character.style),
        },
        fallback_prompt=fallback,
        not_found_msg="character_sheet template not found, using fallback",
    )

    # 把演员正面图 + 服装正面图作为参考，最多各取一张
    refs: list[str] = []
    if character.actor_id:
        actor_refs = await pick_ordered_ref_file_ids(
            db,
            image_model=ActorImage,
            parent_field_name="actor_id",
            parent_id=character.actor_id,
            view_angles=(AssetViewAngle.front,),
        )
        refs.extend(actor_refs[:1])
    if character.costume_id:
        costume_refs = await pick_ordered_ref_file_ids(
            db,
            image_model=CostumeImage,
            parent_field_name="costume_id",
            parent_id=character.costume_id,
            view_angles=(AssetViewAngle.front,),
        )
        refs.extend(costume_refs[:1])

    return AssetImageBaseDraft(
        entity_type="character",
        entity_id=character_id,
        image_id=image_row.id,
        relation_type="character_image",
        relation_entity_id=str(image_row.id),
        prompt=prompt,
        default_images=refs,
    )
