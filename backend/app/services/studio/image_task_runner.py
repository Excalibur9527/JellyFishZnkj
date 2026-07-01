from __future__ import annotations

import base64
import html
import logging
import struct
from io import BytesIO
import zlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_maker
from app.core.task_manager import DeliveryMode, SqlAlchemyTaskStore, TaskManager
from app.core.task_manager.types import TaskStatus
from app.core.contracts.image_generation import ImageGenerationInput, ImageGenerationResult, ImageItem
from app.core.tasks import ImageGenerationTask
from app.models.studio import (
    ActorImage,
    AssetQualityLevel,
    AssetViewAngle,
    CharacterImage,
    CostumeImage,
    PropImage,
    SceneImage,
    ShotDetail,
    ShotFrameImage,
)
from app.models.task_links import GenerationTaskLink
from app.models.types import FileUsageKind
from app.services.studio.file_usages import (
    first_project_id_for_actor,
    first_project_id_for_costume,
    first_project_id_for_prop,
    first_project_id_for_scene,
    sync_usage_from_character,
    sync_usage_from_shot_context,
    upsert_file_usage,
)
from app.services.studio.shot_status import mark_shot_generating, recompute_shot_status
from app.services.studio.image_tasks import load_provider_config, resolve_image_model
from app.services.worker.async_task_support import cancel_if_requested_async
from app.services.worker.task_logging import log_task_event, log_task_failure
from app.utils.files import create_file_from_url_or_b64
from app.models.studio import FileItem, FileType
import uuid

logger = logging.getLogger(__name__)


class _CreateOnlyTask:
    """仅用于 TaskManager.create：提供 __class__.__name__，避免传入 lambda。"""

    async def run(self, *args: object, **kwargs: object):  # noqa: ANN001, ANN003
        return None


def _allow_local_image_fallback() -> bool:
    """仅在本地 SQLite 环境启用占位图兜底。"""

    from app.config import settings

    return (settings.database_url or "").strip().lower().startswith("sqlite")


def _build_inline_svg_data(prompt: str) -> tuple[str, str]:
    """构造轻量 SVG 占位图，便于本地环境继续走图像流程。"""

    preview = html.escape((prompt or "").strip().replace("\n", " ")[:80] or "Local placeholder image")
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='1536' height='1024' viewBox='0 0 1536 1024'>"
        "<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>"
        "<stop offset='0%' stop-color='#dbeafe'/><stop offset='100%' stop-color='#fde68a'/>"
        "</linearGradient></defs>"
        "<rect width='1536' height='1024' fill='url(#g)'/>"
        "<rect x='88' y='88' width='1360' height='848' rx='36' fill='rgba(255,255,255,0.72)'/>"
        "<text x='128' y='220' font-size='56' font-family='Arial, sans-serif' fill='#0f172a'>Local Placeholder Frame</text>"
        f"<text x='128' y='320' font-size='32' font-family='Arial, sans-serif' fill='#334155'>{preview}</text>"
        "</svg>"
    )
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return encoded, f"data:image/svg+xml;base64,{encoded}"


async def _persist_local_placeholder_image(
    session: AsyncSession,
    *,
    task_id: str,
    relation_type: str,
    relation_entity_id: str,
    prompt: str,
) -> None:
    """在无可用图片模型时，写入一张本地占位图。"""

    encoded, data_url = _build_inline_svg_data(prompt)
    file_obj = FileItem(
        id=str(uuid.uuid4()),
        type=FileType.image,
        name=f"{relation_type}-{relation_entity_id}",
        thumbnail=data_url,
        tags=["local_placeholder"],
        storage_key=f"inline-svg:{encoded}",
    )
    session.add(file_obj)
    await session.flush()
    await session.refresh(file_obj)

    link_stmt = (
        select(GenerationTaskLink)
        .where(
            GenerationTaskLink.task_id == task_id,
            GenerationTaskLink.relation_type == relation_type,
            GenerationTaskLink.relation_entity_id == relation_entity_id,
        )
        .limit(1)
    )
    link_row = (await session.execute(link_stmt)).scalars().first()
    if link_row is not None:
        link_row.file_id = file_obj.id

    if relation_type == "shot_frame_image":
        image_row = await session.get(ShotFrameImage, int(relation_entity_id))
        if image_row is not None:
            image_row.file_id = file_obj.id

    async def status(self) -> dict[str, object]:
        return {}

    async def is_done(self) -> bool:
        return False

    async def get_result(self) -> object:
        return None


async def _persist_images_to_assets(
    session: AsyncSession,
    *,
    task_id: str,
    relation_type: str,
    relation_entity_id: str,
    result: ImageGenerationResult,
) -> None:
    """将图片生成结果落库到 FileItem 与业务图片表。"""
    images = result.images or []
    if not images:
        return

    item = images[0]
    if not item.url and not item.b64_json:
        return

    file_obj = await create_file_from_url_or_b64(
        session,
        url=item.url or None,
        b64_data=item.b64_json or None,
        name=f"{relation_type}-{relation_entity_id}",
        prefix=f"generated-images/{relation_type}/{relation_entity_id}",
    )
    file_id = file_obj.id

    link_stmt = (
        select(GenerationTaskLink)
        .where(
            GenerationTaskLink.task_id == task_id,
            GenerationTaskLink.relation_type == relation_type,
            GenerationTaskLink.relation_entity_id == relation_entity_id,
        )
        .limit(1)
    )
    link_row = (await session.execute(link_stmt)).scalars().first()
    if link_row is not None:
        link_row.file_id = file_id

    if relation_type == "actor_image":
        image_row = await session.get(ActorImage, int(relation_entity_id))
        if image_row is not None:
            image_row.file_id = file_id
            pid = await first_project_id_for_actor(session, image_row.actor_id)
            if pid:
                await upsert_file_usage(
                    session,
                    file_id=file_id,
                    project_id=pid,
                    chapter_id=None,
                    shot_id=None,
                    usage_kind=FileUsageKind.asset_image,
                    source_ref=f"actor_image:{image_row.id}",
                )
    elif relation_type == "scene_image":
        image_row = await session.get(SceneImage, int(relation_entity_id))
        if image_row is not None:
            image_row.file_id = file_id
            pid = await first_project_id_for_scene(session, image_row.scene_id)
            if pid:
                await upsert_file_usage(
                    session,
                    file_id=file_id,
                    project_id=pid,
                    chapter_id=None,
                    shot_id=None,
                    usage_kind=FileUsageKind.asset_image,
                    source_ref=f"scene_image:{image_row.id}",
                )
    elif relation_type == "prop_image":
        image_row = await session.get(PropImage, int(relation_entity_id))
        if image_row is not None:
            image_row.file_id = file_id
            pid = await first_project_id_for_prop(session, image_row.prop_id)
            if pid:
                await upsert_file_usage(
                    session,
                    file_id=file_id,
                    project_id=pid,
                    chapter_id=None,
                    shot_id=None,
                    usage_kind=FileUsageKind.asset_image,
                    source_ref=f"prop_image:{image_row.id}",
                )
    elif relation_type == "costume_image":
        image_row = await session.get(CostumeImage, int(relation_entity_id))
        if image_row is not None:
            image_row.file_id = file_id
            pid = await first_project_id_for_costume(session, image_row.costume_id)
            if pid:
                await upsert_file_usage(
                    session,
                    file_id=file_id,
                    project_id=pid,
                    chapter_id=None,
                    shot_id=None,
                    usage_kind=FileUsageKind.asset_image,
                    source_ref=f"costume_image:{image_row.id}",
                )
    elif relation_type == "character_image":
        image_row = await session.get(CharacterImage, int(relation_entity_id))
        if image_row is not None:
            image_row.file_id = file_id
            await sync_usage_from_character(
                session,
                file_id=file_id,
                character_id=image_row.character_id,
                usage_kind=FileUsageKind.character_image,
                source_ref=f"character_image:{image_row.id}",
            )
    elif relation_type == "character_sheet":
        # 设定图：存入 view_angle=DETAIL, quality_level=ULTRA 的槽位
        character_id = relation_entity_id
        stmt_sheet = (
            select(CharacterImage)
            .where(
                CharacterImage.character_id == character_id,
                CharacterImage.quality_level == AssetQualityLevel.ultra,
                CharacterImage.view_angle == AssetViewAngle.detail,
            )
            .order_by(CharacterImage.id.asc())
            .limit(1)
        )
        sheet_row = (await session.execute(stmt_sheet)).scalars().first()
        if sheet_row is not None:
            sheet_row.file_id = file_id
            await sync_usage_from_character(
                session,
                file_id=file_id,
                character_id=character_id,
                usage_kind=FileUsageKind.character_image,
                source_ref=f"character_sheet:{sheet_row.id}",
            )
    elif relation_type == "character":
        character_id = relation_entity_id
        stmt_ci = (
            select(CharacterImage)
            .where(
                CharacterImage.character_id == character_id,
                CharacterImage.quality_level == AssetQualityLevel.low,
                CharacterImage.view_angle == AssetViewAngle.front,
            )
            .order_by(CharacterImage.id.asc())
            .limit(1)
        )
        ci = (await session.execute(stmt_ci)).scalars().first()
        if ci is not None:
            ci.file_id = file_id
            ci.format = getattr(ci, "format", "") or "png"
        else:
            ci = CharacterImage(
                character_id=character_id,
                file_id=file_id,
                quality_level=AssetQualityLevel.low,
                view_angle=AssetViewAngle.front,
                width=None,
                height=None,
                format="png",
                is_primary=True,
            )
            session.add(ci)

        if ci is not None and getattr(ci, "is_primary", False) is True and getattr(ci, "id", None) is not None:
            stmt_clear = (
                CharacterImage.__table__.update()  # type: ignore[attr-defined]
                .where(CharacterImage.character_id == character_id, CharacterImage.id != ci.id)
                .values(is_primary=False)
            )
            await session.execute(stmt_clear)
        await session.flush()
        if ci is not None:
            await sync_usage_from_character(
                session,
                file_id=file_id,
                character_id=character_id,
                usage_kind=FileUsageKind.character_image,
                source_ref=f"character_image:{ci.id}",
            )
    elif relation_type == "shot_frame_image":
        image_row = await session.get(ShotFrameImage, int(relation_entity_id))
        if image_row is not None:
            image_row.file_id = file_id
            detail = await session.get(ShotDetail, image_row.shot_detail_id)
            if detail is not None:
                await sync_usage_from_shot_context(
                    session,
                    file_id=file_id,
                    shot_id=detail.id,
                    usage_kind=FileUsageKind.shot_frame,
                    source_ref=f"shot_frame_image:{image_row.id}",
                )


def _image_item_to_data_url(item: ImageItem) -> str | None:
    """把供应商返回的首张图片转成可再次提交给图片编辑接口的引用。

    A 方案的修脸后处理需要把“刚生成的成片”作为第一张输入图传回模型。
    OpenAI 流式编辑通常返回 b64_json，因此这里优先构造 data URL；若只有
    URL，则直接交给适配器下载。
    """

    if item.b64_json:
        return f"data:image/png;base64,{item.b64_json}"
    if item.url:
        return item.url
    return None


def _build_center_face_mask_data_url(image_data_url: str) -> str | None:
    """为分镜帧后处理生成一个保守的中央头脸区域 mask。

    OpenAI 图片编辑 mask 作用于第一张输入图。这里用透明椭圆标出可编辑区，
    其余区域保持不透明，目的是只允许模型在主角常见的头脸位置做身份修正，
    避免二次编辑重绘服装、场景、构图。
    """

    if not image_data_url.startswith("data:") or "," not in image_data_url:
        return None
    try:
        _header, encoded = image_data_url.split(",", 1)
        raw = base64.b64decode(encoded)
        mask_bytes = _build_center_face_mask_with_pillow(raw)
        if mask_bytes is None:
            mask_bytes = _build_center_face_mask_png(raw)
        if mask_bytes is None:
            return None
        encoded_mask = base64.b64encode(mask_bytes).decode("ascii")
        return f"data:image/png;base64,{encoded_mask}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("face correction mask build failed: %s", exc)
        return None


def _build_center_face_mask_with_pillow(raw: bytes) -> bytes | None:
    """优先用 Pillow 生成 alpha mask；生产环境没装 Pillow 时返回 None。"""

    try:
        from PIL import Image, ImageDraw  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001
        return None

    try:
        image = Image.open(BytesIO(raw))
        width, height = image.size
        if width <= 0 or height <= 0:
            return None
        mask = Image.new("RGBA", (width, height), (0, 0, 0, 255))
        draw = ImageDraw.Draw(mask)
        left, top, right, bottom = _conservative_face_correction_box(width=width, height=height)
        draw.ellipse((left, top, right, bottom), fill=(0, 0, 0, 0))
        output = BytesIO()
        mask.save(output, format="PNG")
        return output.getvalue()
    except Exception as exc:  # noqa: BLE001
        logger.warning("face correction mask build failed: %s", exc)
        return None


def _build_center_face_mask_png(raw: bytes) -> bytes | None:
    """无第三方依赖生成 PNG alpha mask，保证服务端最小环境也能跑 A 方案。

    OpenAI mask 只要求尺寸与第一张输入图一致，并用 alpha 表示可编辑区域。
    这里仅从 PNG IHDR 读取宽高，然后编码一张 RGBA PNG：不透明区域保持原图，
    中央椭圆透明区域允许模型修正主角头脸。
    """

    try:
        width, height = _read_png_size(raw)
    except Exception:  # noqa: BLE001
        return None
    if width <= 0 or height <= 0:
        return None

    left, top, right, bottom = _conservative_face_correction_box(width=width, height=height)
    cx = (left + right) / 2
    cy = (top + bottom) / 2
    rx = max(1.0, (right - left) / 2)
    ry = max(1.0, (bottom - top) / 2)

    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            inside = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0
            alpha = 0 if inside else 255
            rows.extend((0, 0, 0, alpha))
    return _encode_png_rgba(width=width, height=height, raw_rows=bytes(rows))


def _conservative_face_correction_box(*, width: int, height: int) -> tuple[int, int, int, int]:
    """返回更保守的脸部微调区域，避免 A 方案二次重绘整张脸。

    首轮生成图通常已经融合了角色参考图和服装/场景约束。A 方案后处理只应
    校准五官与轻微脸部比例，而不是重画发型、头饰、下颌和整张脸。区域越大，
    模型越容易把任务理解成“重新生成一个角色脸”，导致用户感知上反而变不像。
    """

    return int(width * 0.38), int(height * 0.18), int(width * 0.58), int(height * 0.43)


def _read_png_size(raw: bytes) -> tuple[int, int]:
    """读取 PNG IHDR 宽高；非 PNG 或格式异常时抛错。"""

    if not raw.startswith(b"\x89PNG\r\n\x1a\n") or raw[12:16] != b"IHDR":
        raise ValueError("not png")
    width, height = struct.unpack(">II", raw[16:24])
    return int(width), int(height)


def _encode_png_rgba(*, width: int, height: int, raw_rows: bytes) -> bytes:
    """编码 8-bit RGBA PNG，供无 Pillow 环境生成编辑 mask。"""

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + chunk_type
            + data
            + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw_rows)) + chunk(b"IEND", b"")


def _character_reference_images_for_correction(input_dict: dict, render_context: object) -> list[dict[str, str]]:
    """按提示词映射提取角色参考图，避免服装/场景/道具参与身份修正。

    生成请求中的 images 数组与 render_context.mappings 一一对应。后处理只取
    type=character 的条目作为身份来源，防止服装模特或场景人物再次竞争主角脸。
    """

    images = input_dict.get("images")
    mappings = render_context.get("mappings") if isinstance(render_context, dict) else None
    if not isinstance(images, list) or not isinstance(mappings, list):
        return []

    refs: list[dict[str, str]] = []
    for index, mapping in enumerate(mappings):
        if not isinstance(mapping, dict) or mapping.get("type") != "character":
            continue
        if index >= len(images) or not isinstance(images[index], dict):
            continue
        image_url = str(images[index].get("image_url") or "").strip()
        if image_url:
            refs.append({"image_url": image_url})
    return refs


def _build_face_correction_prompt(render_context: object) -> str:
    """构造 A 方案后处理提示词：第一图是成片，只局部拉回角色身份。"""

    mappings = render_context.get("mappings") if isinstance(render_context, dict) else []
    character_names = [
        str(mapping.get("name") or "").strip()
        for mapping in mappings
        if isinstance(mapping, dict) and mapping.get("type") == "character"
    ]
    names = "、".join(name for name in character_names if name) or "主角"
    return (
        "对第1张输入图进行保守的局部身份微调。第1张输入图是已经生成好的成片，"
        "它的构图、人物位置、发型、头饰、脸部大轮廓、服装、背景和光线都必须作为主基准保留；"
        f"后续输入图是角色参考图（{names}），只用于核对眼型、瞳仁神态、鼻型、嘴型、"
        "五官比例、年龄感和整体气质。只在 mask 标出的内脸区域做小幅校准，"
        "不要重新设计或重绘整张脸，不要改变下巴外轮廓、发际线、发型、头饰、脖颈、身体、"
        "服装颜色、服装纹样、场景和画面比例。若第1张成片与角色参考图已经接近，"
        "只做轻微修正并保持第1张成片的演员感；不得把人物换成另一张新脸。"
    )


async def _maybe_apply_shot_frame_face_correction(
    *,
    provider_cfg,
    input_dict: dict,
    render_context: object,
    relation_type: str,
    result: ImageGenerationResult,
) -> tuple[ImageGenerationResult, dict[str, object] | None]:
    """保留 A 方案实验入口，但默认不再对分镜帧执行二次修脸。

    实测表明：即使 `mask + 角色参考图` 的技术链路能跑通，图片编辑模型仍
    容易把“局部身份校准”理解为二次重绘，导致原本较像的第一阶段成片反而
    被换成新脸。因此正式生成链路不再启用 A 方案，避免破坏首轮生成结果。
    """

    if not _enable_experimental_face_correction():
        return result, None

    if not isinstance(result, ImageGenerationResult):
        return result, None
    if relation_type != "shot_frame_image" or not result.images:
        return result, None
    if str(getattr(provider_cfg, "provider", "") or "") != "openai":
        return result, None

    generated_image_url = _image_item_to_data_url(result.images[0])
    if not generated_image_url:
        return result, None

    character_refs = _character_reference_images_for_correction(input_dict, render_context)
    if not character_refs:
        return result, None

    mask_url = _build_center_face_mask_data_url(generated_image_url)
    if not mask_url:
        return result, {
            "enabled": True,
            "status": "skipped",
            "reason": "mask_unavailable",
            "character_reference_count": len(character_refs),
        }

    correction_input = ImageGenerationInput(
        prompt=_build_face_correction_prompt(render_context),
        model=input_dict.get("model"),
        target_ratio=input_dict.get("target_ratio"),
        resolution_profile=input_dict.get("resolution_profile"),
        purpose=input_dict.get("purpose") or "video_reference",
        size=input_dict.get("size"),
        n=1,
        images=[{"image_url": generated_image_url}, *character_refs],
        mask={"image_url": mask_url},
        response_format="b64_json",
        input_fidelity="high",
    )
    try:
        correction_task = ImageGenerationTask(
            provider_config=provider_cfg,
            input_=correction_input,
            timeout_s=300.0,
        )
        await correction_task.run()
        corrected_result = await correction_task.get_result()
        if corrected_result is None or not corrected_result.images:
            return result, {
                "enabled": True,
                "status": "failed",
                "reason": "empty_correction_result",
                "character_reference_count": len(character_refs),
            }
        return corrected_result, {
            "enabled": True,
            "status": "succeeded",
            "character_reference_count": len(character_refs),
            "mask": "center_face",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("shot frame face correction failed: %s", exc)
        return result, {
            "enabled": True,
            "status": "failed",
            "reason": str(exc),
            "character_reference_count": len(character_refs),
        }


def _enable_experimental_face_correction() -> bool:
    """A 方案实验开关：当前默认关闭，防止局部修脸引发二次换脸。

    这个函数保留实验代码的边界，但不通过环境变量对外开放，避免线上或本地
    正式生成在未重新评估前误启用不可控的人脸重绘链路。
    """

    return False


async def _resolve_related_shot_id(
    session: AsyncSession,
    *,
    relation_type: str,
    relation_entity_id: str,
) -> str | None:
    """仅解析和镜头直接相关的生成任务。"""
    if relation_type != "shot_frame_image":
        return None
    image_row = await session.get(ShotFrameImage, int(relation_entity_id))
    if image_row is None:
        return None
    return image_row.shot_detail_id


async def create_image_task_and_link(
    *,
    db: AsyncSession,
    model_id: str | None,
    relation_type: str,
    relation_entity_id: str,
    prompt: str,
    images: list[dict[str, str]] | None = None,
    target_ratio: str | None = None,
    resolution_profile: str | None = None,
    purpose: str = "generic",
    render_context: dict | None = None,
) -> str:
    """创建图片生成任务并建立关联，持久化数据中不包含供应商密钥。"""
    store = SqlAlchemyTaskStore(db)
    tm = TaskManager(store=store, strategies={})

    model = await resolve_image_model(db, model_id)
    try:
        provider_cfg = await load_provider_config(db, model.provider_id)
        provider_args = {
            "provider": provider_cfg.provider,
            "provider_id": model.provider_id,
        }
    except Exception:
        if not _allow_local_image_fallback():
            raise
        provider_args = {
            "provider": "local_placeholder",
            "provider_id": None,
        }

    run_args: dict = {
        **provider_args,
        "relation_type": relation_type,
        "relation_entity_id": relation_entity_id,
        "input": {
            "prompt": prompt,
            "model": model.name,
            "target_ratio": target_ratio,
            "resolution_profile": resolution_profile,
            "purpose": purpose,
        },
    }
    if images:
        run_args["input"]["images"] = images
    if render_context:
        run_args["render_context"] = render_context

    task_record = await tm.create(
        task=_CreateOnlyTask(),
        mode=DeliveryMode.async_polling,
        task_kind="image_generation",
        run_args=run_args,
    )

    db.add(
        GenerationTaskLink(
            task_id=task_record.id,
            resource_type="image",
            relation_type=relation_type,
            relation_entity_id=relation_entity_id,
        )
    )
    related_shot_id = await _resolve_related_shot_id(
        db,
        relation_type=relation_type,
        relation_entity_id=relation_entity_id,
    )
    if related_shot_id:
        await mark_shot_generating(db, shot_id=related_shot_id)
    await db.commit()

    from app.tasks.execute_task import enqueue_task_execution

    enqueue_task_execution(task_record.id)
    return task_record.id


async def run_image_generation_task(
    task_id: str,
    run_args: dict,
) -> None:
    """执行图片生成任务，并在运行时解析供应商密钥。

    密钥只在当前进程内短暂存在，不进入 generation_tasks.payload。供应商调用
    异常会原样写入任务错误；适配层只对“尚未收到响应”的网络断连做安全重试。
    """
    relation_type = str(run_args.get("relation_type") or "")
    relation_entity_id = str(run_args.get("relation_entity_id") or "")

    async with async_session_maker() as session:
        try:
            store = SqlAlchemyTaskStore(session)
            await store.set_status(task_id, TaskStatus.running)
            await store.set_progress(task_id, 10)
            await session.commit()
            log_task_event("image_generation", task_id, "running")
            if await cancel_if_requested_async(store=store, task_id=task_id, session=session):
                log_task_event("image_generation", task_id, "cancelled", stage="before_execute")
                return

            provider = str(run_args.get("provider") or "")
            input_dict = dict(run_args.get("input") or {})
            face_correction: dict[str, object] | None = None

            if provider == "local_placeholder":
                encoded, _data_url = _build_inline_svg_data(str(input_dict.get("prompt") or ""))
                result = ImageGenerationResult(
                    images=[ImageItem(b64_json=encoded)],
                    provider="local_placeholder",
                    provider_task_id=task_id,
                    status="succeeded",
                )
                await _persist_local_placeholder_image(
                    session,
                    task_id=task_id,
                    relation_type=relation_type,
                    relation_entity_id=relation_entity_id,
                    prompt=str(input_dict.get("prompt") or ""),
                )
            else:
                provider_id = str(run_args.get("provider_id") or "").strip()
                if not provider_id:
                    raise RuntimeError("Image generation task is missing provider_id")
                provider_cfg = await load_provider_config(session, provider_id)
                task = ImageGenerationTask(
                    provider_config=provider_cfg,
                    input_=ImageGenerationInput.model_validate(input_dict),
                    timeout_s=300.0,
                )
                await task.run()
                result = await task.get_result()
                if result is None:
                    raise RuntimeError("Image generation task returned no result")
                await store.set_progress(task_id, 78)
                await session.commit()
                result, face_correction = await _maybe_apply_shot_frame_face_correction(
                    provider_cfg=provider_cfg,
                    input_dict=input_dict,
                    render_context=run_args.get("render_context"),
                    relation_type=relation_type,
                    result=result,
                )
                if face_correction is not None:
                    await store.set_progress(task_id, 92)
                    await session.commit()
            if await cancel_if_requested_async(store=store, task_id=task_id, session=session):
                log_task_event("image_generation", task_id, "cancelled", stage="after_execute")
                return

            result_payload = result.model_dump()
            render_context = run_args.get("render_context")
            if isinstance(render_context, dict):
                result_payload["render_context"] = render_context
            if face_correction is not None:
                result_payload["face_correction"] = face_correction
            await store.set_result(task_id, result_payload)
            if provider != "local_placeholder":
                await _persist_images_to_assets(
                    session,
                    task_id=task_id,
                    relation_type=relation_type,
                    relation_entity_id=relation_entity_id,
                    result=result,
                )
            if await cancel_if_requested_async(store=store, task_id=task_id, session=session):
                log_task_event("image_generation", task_id, "cancelled", stage="after_persist")
                return
            await store.set_progress(task_id, 100)
            await store.set_status(task_id, TaskStatus.succeeded)
            related_shot_id = await _resolve_related_shot_id(
                session,
                relation_type=relation_type,
                relation_entity_id=relation_entity_id,
            )
            if related_shot_id:
                await recompute_shot_status(session, shot_id=related_shot_id)
            await session.commit()
            log_task_event("image_generation", task_id, "succeeded")
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            async with async_session_maker() as s2:
                store = SqlAlchemyTaskStore(s2)
                await store.set_error(task_id, str(exc))
                await store.set_status(task_id, TaskStatus.failed)
                related_shot_id = await _resolve_related_shot_id(
                    s2,
                    relation_type=relation_type,
                    relation_entity_id=relation_entity_id,
                )
                if related_shot_id:
                    await recompute_shot_status(s2, shot_id=related_shot_id)
                await s2.commit()
            log_task_failure("image_generation", task_id, str(exc))
