"""OpenAI Videos API：请求体与参考图映射。"""

from __future__ import annotations

from typing import Any

from app.core.integrations.openai.video_capabilities import validate_openai_video_options
from app.core.integrations.video_capabilities import derive_provider_size, resolve_effective_ratio
from app.core.contracts.video_generation import VideoGenerationInput, _strip_optional_b64


def to_image_data_url(value: str) -> str:
    v = value.strip()
    if v.startswith("data:image/"):
        return v
    return f"data:image/png;base64,{v}"


def pick_input_reference(input_: VideoGenerationInput) -> dict[str, str] | None:
    """OpenAI 仅支持单一 input_reference；优先级：key > first > last。"""
    for raw in (
        _strip_optional_b64(input_.key_frame_base64),
        _strip_optional_b64(input_.first_frame_base64),
        _strip_optional_b64(input_.last_frame_base64),
    ):
        if raw:
            return {"image_url": to_image_data_url(raw)}
    return None


def build_create_video_body(input_: VideoGenerationInput) -> dict[str, Any]:
    import logging as _log
    _log.getLogger(__name__).info(
        "build_create_video_body: model=%r first_frame=%s last_frame=%s key_frame=%s",
        input_.model,
        "SET" if input_.first_frame_base64 else "NONE",
        "SET" if input_.last_frame_base64 else "NONE",
        "SET" if input_.key_frame_base64 else "NONE",
    )
    validate_openai_video_options(input_)
    body: dict[str, Any] = {"prompt": input_.prompt or ""}
    if input_.model:
        body["model"] = input_.model
    size = derive_provider_size(provider="openai", model=input_.model, ratio=input_.ratio)
    if size:
        body["size"] = size
    if input_.seconds is not None:
        body["seconds"] = str(int(input_.seconds))
    effective_ratio = resolve_effective_ratio(input_)
    if effective_ratio:
        body["ratio"] = effective_ratio
    if input_.seed is not None:
        body["seed"] = int(input_.seed)
    if input_.watermark is not None:
        body["watermark"] = bool(input_.watermark)

    ref = pick_input_reference(input_)
    if ref:
        # 标准 OpenAI 格式
        body["input_reference"] = ref.get("image_url") or ref

    # ── Bailian/DashScope 兼容格式（阿里百炼系列模型通过代理时需要）──
    # 同时发 input/parameters 字段，代理会用它能识别的那套
    input_media = (ref or {}).get("image_url") if ref else None
    body["input"] = {
        "text": input_.prompt or "",
        **({"media": input_media} if input_media else {}),
    }
    # resolution: 优先 size，否则按比例推断
    ratio = (input_.ratio or "16:9").strip()
    resolution = "720P"  # 默认 720P；如需 1080P 可在模型参数里配置
    body["parameters"] = {
        "resolution": resolution,
        **({"duration": int(input_.seconds)} if input_.seconds is not None else {}),
    }

    return body
