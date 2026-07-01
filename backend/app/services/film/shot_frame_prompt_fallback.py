"""镜头帧提示词本地兜底。

说明：
- 本地开发环境若文本模型不可用，不应阻塞首帧/尾帧/关键帧工作流；
- 这里生成的是“可编辑基础提示词”，优先保证结构完整、主体清晰、能继续手工微调；
- 不尝试替代 LLM 的创造性，只做稳定、可读的保底输出。
"""

from __future__ import annotations

from typing import Any

from app.schemas.skills.shot_frame_prompt import ShotFramePromptResult


def _clean(value: Any) -> str:
    return str(value or "").strip()


def build_local_shot_frame_prompt(
    *,
    frame_type: str,
    input_dict: dict[str, Any],
) -> ShotFramePromptResult:
    """根据镜头上下文拼装一版本地基础提示词。"""

    frame_label = {
        "first": "首帧",
        "last": "尾帧",
        "key": "关键帧",
    }.get(frame_type, "关键帧")

    parts = [
        _clean(input_dict.get("visual_style")),
        _clean(input_dict.get("style")),
        _clean(input_dict.get("camera_shot")),
        _clean(input_dict.get("angle")),
        _clean(input_dict.get("movement")),
    ]
    prefix = "，".join(part for part in parts if part)

    body_parts = [
        _clean(input_dict.get("title")),
        _clean(input_dict.get("script_excerpt")),
        _clean(input_dict.get("selected_action_beat_text")) or _clean(input_dict.get("action_beats")),
        _clean(input_dict.get("character_context")),
        _clean(input_dict.get("scene_context")),
        _clean(input_dict.get("prop_context")),
        _clean(input_dict.get("costume_context")),
        _clean(input_dict.get("character_emotions")),
        _clean(input_dict.get("atmosphere")),
        _clean(input_dict.get("frame_specific_guidance")),
        _clean(input_dict.get("continuity_guidance")),
    ]
    body = "；".join(part for part in body_parts if part)

    prompt = f"{frame_label}画面，{prefix}。{body}".strip("。")
    prompt = prompt.replace("\n", "，")
    return ShotFramePromptResult(prompt=prompt)
