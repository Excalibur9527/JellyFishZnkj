"""可灵 AI 视频模型能力约束。"""

from __future__ import annotations

from app.core.integrations.video_capabilities import VideoModelCapability

_DEFAULT_KLING_CAPABILITY = VideoModelCapability(
    supports_seed=False,
    supports_watermark=False,
    allowed_ratios={"16:9", "9:16", "1:1", "4:3", "3:4"},
    default_ratio="16:9",
    min_seconds=5,
    max_seconds=10,
)

_OVERRIDES: dict[str, VideoModelCapability] = {}


def register_kling_video_capability(*, model_prefix: str, capability: VideoModelCapability) -> None:
    _OVERRIDES[model_prefix.lower()] = capability


def clear_kling_video_capability_overrides() -> None:
    _OVERRIDES.clear()


def resolve_kling_video_capability(model: str | None) -> VideoModelCapability:
    if model:
        key = model.lower()
        for prefix, cap in _OVERRIDES.items():
            if key.startswith(prefix):
                return cap
    return _DEFAULT_KLING_CAPABILITY
