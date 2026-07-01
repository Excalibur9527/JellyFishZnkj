"""本地规则分镜兜底。

说明：
- 当本地开发环境没有可用文本模型，或在线模型鉴权失败时，主流程不应彻底不可用；
- 这里提供最小可编辑的章节切镜结果，让用户至少能进入“分镜确认 / 修正”流程；
- 该兜底追求“可继续工作”，不追求替代 LLM 的镜头理解质量。
"""

from __future__ import annotations

import re

from app.schemas.skills.script_processing import ScriptDivisionResult, ShotDivision


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])")
_META_LINE_PREFIXES = (
    "#",
    "##",
    "###",
    "---",
    "主题：",
    "集数建议：",
    "核心作用：",
    "这一集的钩子",
    "这一单元总情绪",
    "第一单元总情绪",
)


def _is_meta_line(line: str) -> bool:
    """过滤章节说明、标题和分隔符，尽量保留真正可拍内容。"""

    normalized = line.strip()
    if not normalized:
        return True
    if any(normalized.startswith(prefix) for prefix in _META_LINE_PREFIXES):
        return True
    if normalized.endswith("：") and len(normalized) <= 12:
        return True
    return False


def _normalize_units(script_text: str) -> list[str]:
    """将原文归一成更接近真实镜头节奏的文本单元。"""

    raw_lines = [line.strip() for line in script_text.splitlines()]
    content_lines = [line for line in raw_lines if line and not _is_meta_line(line)]

    if not content_lines:
        sentence_source = script_text.strip()
        if not sentence_source:
            return []
        return [part.strip() for part in _SENTENCE_SPLIT_RE.split(sentence_source) if part.strip()] or [sentence_source]

    sentences: list[str] = []
    for line in content_lines:
        parts = [part.strip() for part in _SENTENCE_SPLIT_RE.split(line) if part.strip()]
        if parts:
            sentences.extend(parts)
        else:
            sentences.append(line)

    units: list[str] = []
    current: list[str] = []
    current_len = 0
    for sentence in sentences:
        normalized = sentence.strip()
        if not normalized:
            continue
        sentence_len = len(normalized)
        should_flush = bool(current) and (
            current_len >= 90
            or len(current) >= 3
            or (current_len >= 50 and sentence_len >= 28)
        )
        if should_flush:
            units.append("".join(current))
            current = []
            current_len = 0
        current.append(normalized)
        current_len += sentence_len

    if current:
        units.append("".join(current))
    return units


def _infer_time_of_day(text: str) -> str:
    """按关键词推断时间字段，保持结构完整。"""

    if any(token in text for token in ("深夜", "夜里", "夜晚", "晚上")):
        return "NIGHT"
    if any(token in text for token in ("黎明", "清晨", "凌晨")):
        return "DAWN"
    if any(token in text for token in ("黄昏", "傍晚")):
        return "DUSK"
    if any(token in text for token in ("白天", "中午", "午后", "清早", "早晨")):
        return "DAY"
    return "UNKNOWN"


def _build_shot_name(text: str, *, index: int) -> str:
    """为兜底分镜生成一个可读的镜头标题。"""

    normalized = re.sub(r"\s+", "", text)
    if not normalized:
        return f"镜头{index}"
    preview = normalized[:12]
    return preview if len(normalized) <= 12 else f"{preview}..."


def divide_script_locally(script_text: str) -> ScriptDivisionResult:
    """使用规则法将章节切成最小可编辑的分镜列表。"""

    units = _normalize_units(script_text)
    if not units:
        return ScriptDivisionResult(shots=[], total_shots=0, notes="本地兜底分镜：原文为空，未生成镜头。")

    shots: list[ShotDivision] = []
    for shot_index, excerpt in enumerate(units, start=1):
        shots.append(
            ShotDivision(
                index=shot_index,
                start_line=shot_index,
                end_line=shot_index,
                script_excerpt=excerpt,
                shot_name=_build_shot_name(excerpt, index=shot_index),
                time_of_day=_infer_time_of_day(excerpt),
                character_emotions=[],
            )
        )

    return ScriptDivisionResult(
        shots=shots,
        total_shots=len(shots),
        notes="本次结果来自本地规则兜底分镜：在线文本模型当前不可用，建议后续手动确认镜头边界与标题。",
    )
