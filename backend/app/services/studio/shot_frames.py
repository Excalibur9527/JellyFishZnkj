"""镜头分镜帧服务：ShotFrameImage 的分页查询与 CRUD。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.utils import apply_order, paginate
from app.models.studio import ShotDetail, ShotFrameImage
from app.schemas.common import ApiResponse, PaginatedData, paginated_response
from app.schemas.studio.shots import ShotFrameImageCreate, ShotFrameImageRead, ShotFrameImageUpdate
from app.services.common import (
    create_and_refresh,
    delete_if_exists,
    entity_not_found,
    flush_and_refresh,
    get_or_404,
    patch_model,
    require_entity,
)


async def list_paginated(
    db: AsyncSession,
    *,
    shot_detail_id: str | None,
    order: str | None,
    is_desc: bool,
    page: int,
    page_size: int,
    allow_fields: set[str],
) -> ApiResponse[PaginatedData[ShotFrameImageRead]]:
    """分页查询镜头分镜帧图片。"""
    stmt = select(ShotFrameImage)
    if shot_detail_id is not None:
        stmt = stmt.where(ShotFrameImage.shot_detail_id == shot_detail_id)
    stmt = apply_order(
        stmt,
        model=ShotFrameImage,
        order=order,
        is_desc=is_desc,
        allow_fields=allow_fields,
        default="id",
    )
    items, total = await paginate(db, stmt=stmt, page=page, page_size=page_size)
    return paginated_response(
        [ShotFrameImageRead.model_validate(x) for x in items],
        page=page,
        page_size=page_size,
        total=total,
    )


async def create(
    db: AsyncSession,
    *,
    body: ShotFrameImageCreate,
) -> ShotFrameImage:
    """创建镜头分镜帧图片。"""
    await require_entity(db, ShotDetail, body.shot_detail_id, detail=entity_not_found("ShotDetail"), status_code=400)
    return await create_and_refresh(db, ShotFrameImage(**body.model_dump()))


async def update(
    db: AsyncSession,
    *,
    image_id: int,
    body: ShotFrameImageUpdate,
) -> ShotFrameImage:
    """更新镜头分镜帧图片。"""
    obj = await get_or_404(db, ShotFrameImage, image_id, detail=entity_not_found("ShotFrameImage"))
    patch_model(obj, body.model_dump(exclude_unset=True))
    return await flush_and_refresh(db, obj)


def set_reference_assets(
    frame: 'ShotFrameImage',
    *,
    reference_assets: list[dict],
) -> None:
    """更新单个帧位的独立参考资产快照，避免三种帧共享选择状态。"""
    frame.reference_assets = reference_assets


def frame_reference_assets_match(
    frame: 'ShotFrameImage',
    *,
    requested_assets: list[dict],
) -> bool:
    """校验生成请求使用的素材集合是否属于当前帧，阻止跨帧或镜头级素材混入。

    图片顺序允许在提示词预览中调整；同一个角色、服装、场景或道具换了最新
    图片时，file_id 可以随实体当前图片刷新，因此这里只校验资产类型与业务
    ID 集合一致。None 表示旧帧尚未配置，可由首次生成初始化。
    """
    if frame.reference_assets is None:
        return True

    def signature(items: list[dict]) -> list[tuple[str, str]]:
        """把资产快照转换为可稳定比较的类型、实体二元组。"""
        return sorted(
            (
                str(item.get("type") or "").strip(),
                str(item.get("id") or "").strip(),
            )
            for item in items
        )

    return signature(list(frame.reference_assets or [])) == signature(requested_assets)



async def delete(
    db: AsyncSession,
    *,
    image_id: int,
) -> None:
    """删除镜头分镜帧图片。"""
    await delete_if_exists(db, ShotFrameImage, image_id)
