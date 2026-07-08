"""剧本分镜 Agent：ScriptDividerAgent"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.prompts import PromptTemplate

from app.chains.agents.base import AgentBase, _extract_json_from_text
from app.schemas.skills.script_processing import ScriptDivisionResult

_SCRIPT_DIVIDER_SYSTEM_PROMPT = """\
你是\"短剧分镜师\"。将完整短剧剧本分割为多个镜头，严格遵循短剧节奏规律。

## 短剧分镜核心原则
1. **开头强勾子**：第 1~3 个镜头必须制造强烈悬念、冲突或情绪冲击，让观众无法关掉；避免平淡的环境介绍或寒暄开场。
2. **节奏快**：单镜对应的剧情内容控制在 3~8 秒可呈现的范围内；情绪平缓段落可适当合并，高潮段落需细拆。
3. **情绪波峰**：每 3~5 个镜头应有一个情绪峰值镜头（冲突爆发、反转揭露、情感崩溃等）；不要让连续多个镜头情绪平铺。
4. **镜头划分依据**：以"视角切换""情绪转折""动作完成"或"时空跳跃"作为分镜边界，而非段落换行。
5. **shot_name 要抓画面**：用动词+主体+状态描述当前镜头最核心的视觉动作，例如"林小雨摔碎手机""陈总突然推开门"，不要用"场景一""镜头五"这类无信息标题。

## 输出字段
- index（从 1 开始）
- start_line、end_line
- shot_name（一句话画面动作描述）
- script_excerpt（对应剧本原文）
- time_of_day
- character_emotions（列表，**必须输出，不可省略**）：本镜每个出场角色的情绪与微表情，若无角色则输出空列表 []。每项格式：
  - character_name：角色名（与剧本一致）
  - emotion：主情绪标签，**只能**从以下选择：悲伤、愤怒、惊恐、喜悦、平静、紧张、羞耻、绝望、冷漠、轻蔑、震惊、委屈
  - intensity：情绪强度，**只能**从以下选择：轻微、明显、强烈
  - expression_hint：具体微表情，2～4个短语，如"眉头紧皱、眼眶泛红、嘴角下垂"

**character_emotions 示例**（每个镜头都必须有此字段）：
```json
"character_emotions": [
  {
    "character_name": "林小雨",
    "emotion": "愤怒",
    "intensity": "强烈",
    "expression_hint": "眉头紧皱、牙关咬紧、眼神犀利"
  },
  {
    "character_name": "陈总",
    "emotion": "轻蔑",
    "intensity": "明显",
    "expression_hint": "嘴角微扬、眼皮低垂、目光漠然"
  }
]
```

只输出 JSON，符合 ScriptDivisionResult 结构。
"""

SCRIPT_DIVIDER_PROMPT = PromptTemplate(
    input_variables=["script_text"],
    template="## 输入脚本\n{script_text}\n\n## 输出\n",
)


class ScriptDividerAgent(AgentBase[ScriptDivisionResult]):
    """剧本自动分镜：输入完整剧本文本，输出分镜列表。"""

    enable_thinking: bool = False

    @property
    def system_prompt(self) -> str:
        return _SCRIPT_DIVIDER_SYSTEM_PROMPT

    @property
    def prompt_template(self) -> PromptTemplate:
        return SCRIPT_DIVIDER_PROMPT

    @property
    def output_model(self) -> type[ScriptDivisionResult]:
        return ScriptDivisionResult

    def format_output(self, raw: str) -> ScriptDivisionResult:
        """
        更强的兜底解析：
        LLM 可能输出：
        - 正常结构：{shots:[...], total_shots:N}
        - 包裹结构：{"ScriptDivisionResult": {...}}
        - 直接列表：[{...}, {...}]（视为 shots）
        """

        json_str = _extract_json_from_text(raw)
        data: Any = json.loads(json_str)

        if isinstance(data, list):
            data = {"shots": data}
        elif isinstance(data, dict) and "ScriptDivisionResult" in data:
            inner = data.get("ScriptDivisionResult")
            if isinstance(inner, list):
                data = {"shots": inner}
            elif isinstance(inner, dict):
                data = inner
            else:
                data = {"shots": []}

        if isinstance(data, dict):
            data = self._normalize(data)

        return self.output_model.model_validate(data)  # type: ignore[arg-type]

    def divide_script(self, *, script_text: str) -> ScriptDivisionResult:
        return self.extract(script_text=script_text)

    async def adivide_script(self, *, script_text: str) -> ScriptDivisionResult:
        return await self.aextract(script_text=script_text)

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        """规范化脚本分割结果。"""
        data = dict(data)

        # 兼容：LLM 可能输出 {"ScriptDivisionResult": {...}} 或 {"ScriptDivisionResult": [...]}
        if "ScriptDivisionResult" in data:
            inner = data.get("ScriptDivisionResult")
            if isinstance(inner, list):
                data = {"shots": inner}
            elif isinstance(inner, dict):
                data = dict(inner)
            else:
                data = {"shots": []}

        if "shots" in data and isinstance(data["shots"], list):
            shots = []
            for idx, shot in enumerate(data["shots"]):
                shot_dict: dict[str, Any] = (
                    dict(shot) if isinstance(shot, dict) else {"script_excerpt": str(shot), "shot_name": ""}
                )
                if "index" not in shot_dict:
                    shot_dict["index"] = idx + 1
                # 兼容：LLM 可能用 title/shot_title 代替 shot_name
                if "shot_name" not in shot_dict:
                    if "title" in shot_dict:
                        shot_dict["shot_name"] = str(shot_dict.pop("title"))
                    elif "shot_title" in shot_dict:
                        shot_dict["shot_name"] = str(shot_dict.pop("shot_title"))
                shot_dict.setdefault("shot_name", "")
                shot_dict.setdefault("character_emotions", [])
                # 严格对齐 ShotDivision：移除已废弃的弱语义字段，避免 extra="forbid" 校验失败
                shot_dict.pop("scene_name", None)
                shot_dict.pop("character_names_in_text", None)
                shot_dict.pop("character_ids", None)
                shots.append(shot_dict)
            data["shots"] = shots

        if "total_shots" not in data and "shots" in data:
            data["total_shots"] = len(data["shots"])

        return data

