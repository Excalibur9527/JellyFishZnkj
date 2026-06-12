"""可灵视频生成请求体构建。"""

from __future__ import annotations

from typing import Any

from app.core.contracts.video_generation import VideoGenerationInput

# 可灵比例映射
_RATIO_MAP: dict[str, str] = {
    "16:9": "16:9",
    "9:16": "9:16",
    "1:1": "1:1",
    "4:3": "4:3",
    "3:4": "3:4",
    "21:9": "16:9",  # 可灵不支持 21:9，降级到 16:9
}

# 可灵时长映射（秒 → 字符串）
_DURATION_MAP: dict[int, str] = {5: "5", 10: "10"}
_DEFAULT_DURATION = "5"


def _strip_data_url_prefix(value: str) -> str:
    """移除 data:image/...;base64, 前缀，只保留纯 base64。"""
    if "base64," in value:
        return value.split("base64,", 1)[1]
    return value


def build_image2video_body(input_: VideoGenerationInput, model: str | None = None) -> dict[str, Any]:
    """构建 image2video 请求体。"""
    model_name = (model or "kling-v1").strip()
    duration = _DURATION_MAP.get(input_.seconds or 5, _DEFAULT_DURATION)
    aspect_ratio = _RATIO_MAP.get(input_.ratio or "16:9", "16:9")

    body: dict[str, Any] = {
        "model_name": model_name,
        "duration": duration,
        "cfg_scale": 0.5,
        "mode": "std",
    }
    if input_.prompt:
        body["prompt"] = input_.prompt.strip()

    if input_.first_frame_base64:
        body["image"] = _strip_data_url_prefix(input_.first_frame_base64)
    if input_.last_frame_base64:
        body["image_tail"] = _strip_data_url_prefix(input_.last_frame_base64)

    # 如果没有参考图，作为 text2video 模式需要比例
    if not input_.first_frame_base64 and not input_.last_frame_base64:
        body["aspect_ratio"] = aspect_ratio

    return body


def build_text2video_body(input_: VideoGenerationInput, model: str | None = None) -> dict[str, Any]:
    """构建 text2video 请求体（无参考图时使用）。"""
    model_name = (model or "kling-v1").strip()
    duration = _DURATION_MAP.get(input_.seconds or 5, _DEFAULT_DURATION)
    aspect_ratio = _RATIO_MAP.get(input_.ratio or "16:9", "16:9")

    body: dict[str, Any] = {
        "model_name": model_name,
        "prompt": (input_.prompt or "").strip(),
        "duration": duration,
        "aspect_ratio": aspect_ratio,
        "cfg_scale": 0.5,
        "mode": "std",
    }
    return body
