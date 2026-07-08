from __future__ import annotations

import base64
import struct
from io import BytesIO
import mimetypes
import zlib

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.models.studio import AssetViewAngle, FileItem
from app.schemas.studio.shots import ShotLinkedAssetItem


async def resolve_reference_file_ids_and_names_from_linked_items(
    db: AsyncSession,  # noqa: ARG001
    *,
    items: list[ShotLinkedAssetItem],
) -> tuple[list[str], list[str]]:
    """将关联资产条目解析为参考图 file_id 列表（顺序有效）。"""
    file_ids: list[str] = []
    names: list[str] = []
    for item in items or []:
        name = (item.name or "").strip()
        file_id = (item.file_id or "").strip()
        if not file_id:
            continue
        file_ids.append(str(file_id))
        names.append(name or (item.id or ""))
    return file_ids, names


async def resolve_reference_image_refs_by_file_ids(
    db: AsyncSession,
    *,
    file_ids: list[str],
) -> list[dict[str, str]]:
    """将 file_id 列表解析为图片参考（data url）。顺序与入参一致。"""
    out: list[dict[str, str]] = []
    for fid in file_ids or []:
        resolved = await _resolve_reference_image_content(db, file_id=fid)
        if resolved is None:
            continue
        content, content_type = resolved
        out.append(_to_data_url_ref(content=content, content_type=content_type))
    return out


async def resolve_shot_frame_reference_image_refs(
    db: AsyncSession,
    *,
    items: list[ShotLinkedAssetItem],
) -> list[dict[str, str]]:
    """按分镜帧资产类型解析参考图，并对非身份参考做用途隔离。

    分镜首帧/关键帧/尾帧会同时上传角色、服装、场景、道具等参考图。供应商
    接口本身只接收图片数组，无法给每张图绑定机器可读的“角色/服装”语义，
    因此这里必须在传输前做类型化处理：角色图保持原始身份信息；服装图若
    作为镜头参考，会遮掉头脸区域，只让它承担服装款式、颜色、纹样和层次
    职责，避免服装模特的人脸与角色身份竞争。
    """

    out: list[dict[str, str]] = []
    seen_file_ids: set[str] = set()
    for item in items or []:
        file_id = (item.file_id or "").strip()
        if not file_id or file_id in seen_file_ids:
            continue
        seen_file_ids.add(file_id)
        resolved = await _resolve_reference_image_content(db, file_id=file_id)
        if resolved is None:
            continue
        content, content_type = resolved
        if item.type == "costume":
            content, content_type = _isolate_costume_reference_identity(content=content, content_type=content_type)
        out.append(_to_data_url_ref(content=content, content_type=content_type))
    return out


async def _resolve_reference_image_content(
    db: AsyncSession,
    *,
    file_id: str,
) -> tuple[bytes, str] | None:
    """下载并校验单个参考图片文件，返回原始字节与 MIME 类型。

    这个私有入口服务于旧 file_id 列表解析和新的分镜帧类型化解析，保证两条
    路径对“文件必须存在、必须是图片、内容不能为空”的错误语义保持一致。
    """

    normalized_file_id = (file_id or "").strip()
    if not normalized_file_id:
        return None
    file_obj = await db.get(FileItem, normalized_file_id)
    if file_obj is None or not file_obj.storage_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"FileItem not found or storage_key empty for file_id={normalized_file_id}",
        )
    try:
        content = await storage.download_file(key=file_obj.storage_key)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to download file for file_id={normalized_file_id}: {exc}",
        ) from exc
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Empty file content for file_id={normalized_file_id}",
        )

    content_type: str | None = None
    try:
        info = await storage.get_file_info(key=file_obj.storage_key)
        content_type = (info.content_type or "").strip().lower() or None
    except Exception:  # noqa: BLE001
        content_type = None
    if not content_type:
        guessed_type, _ = mimetypes.guess_type(file_obj.storage_key)
        content_type = (guessed_type or "").strip().lower() or None
    if not content_type or not content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File is not an image for file_id={normalized_file_id}",
        )
    return content, content_type


def _to_data_url_ref(*, content: bytes, content_type: str) -> dict[str, str]:
    """把图片字节编码成图片生成契约需要的 data URL。"""

    image_format = content_type.split("/", 1)[1].split(";", 1)[0].strip().lower() or "png"
    encoded = base64.b64encode(content).decode("ascii")
    return {"image_url": f"data:image/{image_format};base64,{encoded}"}


def _isolate_costume_reference_identity(*, content: bytes, content_type: str) -> tuple[bytes, str]:
    """遮蔽服装参考图的头脸区域，只保留服装信息给生图模型使用。

    服装参考图常常是“真人模特穿着服装”的整身图。即使 prompt 写明忽略
    人脸，多图生图模型仍可能把模特脸当成身份线索，与角色参考图混合。
    这里采用保守的上中部遮蔽：不减少参考图数量，不改变服装主体，只把最
    容易携带身份的头脸/头饰区域用背景色覆盖，降低换脸概率。
    """

    pil_result = _isolate_costume_reference_identity_with_pillow(content=content)
    if pil_result is not None:
        return pil_result, "image/png"
    png_result = _isolate_costume_reference_identity_in_png(content=content)
    if png_result is not None:
        return png_result, "image/png"
    return content, content_type


def _isolate_costume_reference_identity_with_pillow(*, content: bytes) -> bytes | None:
    """在安装 Pillow 的环境下遮蔽服装图身份区域；未安装时静默让内置 PNG 逻辑接手。"""

    try:
        from PIL import Image, ImageDraw  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001
        return None

    try:
        image = Image.open(BytesIO(content)).convert("RGB")
    except Exception:  # noqa: BLE001
        return None
    width, height = image.size
    if width <= 0 or height <= 0:
        return None

    background_color = _estimate_corner_background_color(
        width=width,
        height=height,
        get_rgb=lambda x, y: image.getpixel((x, y))[:3],
    )
    draw = ImageDraw.Draw(image)
    draw.rectangle(_identity_mask_box(width=width, height=height), fill=background_color)

    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _isolate_costume_reference_identity_in_png(*, content: bytes) -> bytes | None:
    """使用标准库处理常见 PNG 图，保证本地后端无 Pillow 时也能做身份隔离。

    当前系统上传的参考图主要是 8 位 RGB/RGBA PNG。这里只支持该安全子集：
    无隔行、标准 filter、颜色类型 2 或 6。遇到 JPEG、调色板 PNG 等格式时
    返回 None，由调用方保留原图，避免为了处理图片导致生成链路失败。
    """

    try:
        width, height, color_type, rows = _decode_png_rows(content)
    except Exception:  # noqa: BLE001
        return None
    channels = 4 if color_type == 6 else 3
    background_color = _estimate_corner_background_color(
        width=width,
        height=height,
        get_rgb=lambda x, y: tuple(rows[y][x * channels + channel] for channel in range(3)),
    )
    left, top, right, bottom = _identity_mask_box(width=width, height=height)
    for y in range(top, min(bottom + 1, height)):
        row = rows[y]
        for x in range(left, min(right + 1, width)):
            offset = x * channels
            row[offset : offset + 3] = bytes(background_color)
            if channels == 4:
                row[offset + 3] = 255
    return _encode_png_rows(width=width, height=height, color_type=color_type, rows=rows)


def _identity_mask_box(*, width: int, height: int) -> tuple[int, int, int, int]:
    """返回服装参考图中最容易携带身份的上中部遮蔽区域。"""

    return int(width * 0.34), 0, int(width * 0.66), int(height * 0.27)


def _estimate_corner_background_color(
    *,
    width: int,
    height: int,
    get_rgb,
) -> tuple[int, int, int]:
    """估算图片边角背景色，用于自然覆盖服装模特的身份区域。"""

    sample_points = (
        (max(0, int(width * 0.04)), max(0, int(height * 0.04))),
        (min(width - 1, int(width * 0.96)), max(0, int(height * 0.04))),
        (max(0, int(width * 0.04)), min(height - 1, int(height * 0.16))),
        (min(width - 1, int(width * 0.96)), min(height - 1, int(height * 0.16))),
    )
    samples = [get_rgb(x, y) for x, y in sample_points]
    return tuple(int(sum(pixel[channel] for pixel in samples) / len(samples)) for channel in range(3))


def _decode_png_rows(content: bytes) -> tuple[int, int, int, list[bytearray]]:
    """解码 8 位 RGB/RGBA PNG 为逐行像素，供服装身份隔离修改。"""

    if not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not png")
    offset = 8
    width = height = color_type = 0
    idat_parts: list[bytes] = []
    while offset + 8 <= len(content):
        length = struct.unpack(">I", content[offset : offset + 4])[0]
        chunk_type = content[offset + 4 : offset + 8]
        chunk_data = content[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
                ">IIBBBBB", chunk_data
            )
            if bit_depth != 8 or color_type not in (2, 6) or compression != 0 or filter_method != 0 or interlace != 0:
                raise ValueError("unsupported png")
        elif chunk_type == b"IDAT":
            idat_parts.append(chunk_data)
        elif chunk_type == b"IEND":
            break
    if not width or not height or color_type not in (2, 6) or not idat_parts:
        raise ValueError("invalid png")

    channels = 4 if color_type == 6 else 3
    stride = width * channels
    raw = zlib.decompress(b"".join(idat_parts))
    expected = height * (stride + 1)
    if len(raw) != expected:
        raise ValueError("unexpected png payload")
    rows: list[bytearray] = []
    previous = bytearray(stride)
    position = 0
    for _ in range(height):
        filter_type = raw[position]
        position += 1
        row = bytearray(raw[position : position + stride])
        position += stride
        _unfilter_png_row(row=row, previous=previous, filter_type=filter_type, bytes_per_pixel=channels)
        rows.append(row)
        previous = row
    return width, height, color_type, rows


def _unfilter_png_row(*, row: bytearray, previous: bytearray, filter_type: int, bytes_per_pixel: int) -> None:
    """还原 PNG scanline filter，支持标准 0-4 五种过滤器。"""

    for index, value in enumerate(row):
        left = row[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
        up = previous[index] if previous else 0
        up_left = previous[index - bytes_per_pixel] if previous and index >= bytes_per_pixel else 0
        if filter_type == 0:
            predictor = 0
        elif filter_type == 1:
            predictor = left
        elif filter_type == 2:
            predictor = up
        elif filter_type == 3:
            predictor = (left + up) // 2
        elif filter_type == 4:
            predictor = _paeth_predictor(left, up, up_left)
        else:
            raise ValueError("unsupported png filter")
        row[index] = (value + predictor) & 0xFF


def _paeth_predictor(left: int, up: int, up_left: int) -> int:
    """PNG Paeth 预测器实现，用于还原 filter type 4。"""

    estimate = left + up - up_left
    distance_left = abs(estimate - left)
    distance_up = abs(estimate - up)
    distance_up_left = abs(estimate - up_left)
    if distance_left <= distance_up and distance_left <= distance_up_left:
        return left
    if distance_up <= distance_up_left:
        return up
    return up_left


def _encode_png_rows(*, width: int, height: int, color_type: int, rows: list[bytearray]) -> bytes:
    """把已修改的 RGB/RGBA 像素行重新编码为无过滤 PNG。"""

    raw = b"".join(bytes([0]) + bytes(row) for row in rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw))
        + _png_chunk(b"IEND", b"")
    )


def _png_chunk(chunk_type: bytes, chunk_data: bytes) -> bytes:
    """生成 PNG chunk，并计算 CRC。"""

    crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
    return struct.pack(">I", len(chunk_data)) + chunk_type + chunk_data + struct.pack(">I", crc)


async def pick_front_ref_file_id(
    db: AsyncSession,
    *,
    image_model: type,
    parent_field_name: str,
    parent_id: str,
    preferred_quality_level: object | None,
) -> str | None:
    """按旧语义挑选 front 参考图的 file_id（不下载文件）。"""
    parent_field = getattr(image_model, parent_field_name)
    stmt = (
        select(image_model)
        .where(
            parent_field == parent_id,
            image_model.view_angle == AssetViewAngle.front,
            image_model.file_id.is_not(None),
        )
        .order_by(image_model.created_at.desc(), image_model.id.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return None

    target = rows[0]
    if preferred_quality_level is not None:
        for row in rows:
            if getattr(row, "quality_level", None) == preferred_quality_level:
                target = row
                break

    fid = getattr(target, "file_id", None)
    return str(fid) if fid else None


async def pick_ordered_ref_file_ids(
    db: AsyncSession,
    *,
    image_model: type,
    parent_field_name: str,
    parent_id: str,
    view_angles: tuple[AssetViewAngle, ...],
) -> list[str]:
    """按旧语义按角度顺序挑选参考图 file_id（不下载文件）。"""
    parent_field = getattr(image_model, parent_field_name)
    stmt = (
        select(image_model)
        .where(parent_field == parent_id, image_model.file_id.is_not(None))
        .order_by(image_model.created_at.desc(), image_model.id.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return []

    best_by_angle: dict[str, object] = {}
    for row in rows:
        angle = getattr(row, "view_angle", None)
        key = angle.value if isinstance(angle, AssetViewAngle) else str(angle)
        if key and key not in best_by_angle:
            best_by_angle[key] = row

    out: list[str] = []
    for angle in view_angles:
        row = best_by_angle.get(angle.value)
        if row is None:
            continue
        fid = getattr(row, "file_id", None)
        if fid:
            out.append(str(fid))
    return out
