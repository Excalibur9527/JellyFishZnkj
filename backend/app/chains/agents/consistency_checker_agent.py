"""一致性检查 Agent：ConsistencyCheckerAgent"""

from __future__ import annotations

from typing import Any

from langchain_core.prompts import PromptTemplate

from app.chains.agents.base import AgentBase
from app.schemas.skills.script_processing import ScriptConsistencyCheckResult

_CONSISTENCY_CHECKER_SYSTEM_PROMPT = """\
你是"短剧一致性检查员"。检测剧本中影响视觉连续性和逻辑可信度的四类问题，为后续 AI 生图/生视频提供预警。

## 检查范围

### 1. 角色混淆（character_confusion）
同一个角色在不同段落被赋予了不同身份或行为主体（同名不同人、代词指代混乱、行为归属错位）。

### 2. 场景矛盾（scene_contradiction）
同一场景在前后描述中出现明显矛盾（室内/室外冲突、关键陈设前后不一致、同场景下昼夜突变但无时间跳跃说明）。

### 3. 时间线跳跃（timeline_jump）
时间或天气发生无说明的突然跳跃，导致观众无法理解时序（白天到黑夜但无过渡、人物状态在无时间跳跃的情况下突然改变）。

### 4. 道具/外观状态矛盾（prop_state_contradiction）
道具或人物外观状态出现不合理变化（已被摔碎的物品重新出现且完好、角色衣物在同一场景无故变换）。

## 输出格式
输出 ScriptConsistencyCheckResult：
- issues: 每条必须包含 issue_type（从上述四类中选一）、character_candidates（角色相关时填写，否则空列表）、description（问题描述）、suggestion（修改建议）；尽量给出 affected_lines（start_line/end_line）。
- has_issues: issues 非空则为 true

只输出 JSON。
"""

CONSISTENCY_CHECKER_PROMPT = PromptTemplate(
    input_variables=["script_text"],
    template="## 原文剧本\n{script_text}\n\n## 输出\n",
)


class ConsistencyCheckerAgent(AgentBase[ScriptConsistencyCheckResult]):
    """一致性检查（角色混淆）：输入原文，检测同一角色身份/行为混淆并给出修改建议。"""

    @property
    def system_prompt(self) -> str:
        return _CONSISTENCY_CHECKER_SYSTEM_PROMPT

    @property
    def prompt_template(self) -> PromptTemplate:
        return CONSISTENCY_CHECKER_PROMPT

    @property
    def output_model(self) -> type[ScriptConsistencyCheckResult]:
        return ScriptConsistencyCheckResult

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        """规范化一致性检查结果（角色混淆）。"""
        data = dict(data)
        if "issues" not in data or not isinstance(data["issues"], list):
            data["issues"] = []
        for it in data["issues"]:
            if isinstance(it, dict):
                it.setdefault("issue_type", "character_confusion")
                it.setdefault("character_candidates", [])
                it.setdefault("affected_lines", None)
                it.setdefault("evidence", [])
        if "has_issues" not in data:
            data["has_issues"] = len(data["issues"]) > 0
        if "summary" not in data:
            data["summary"] = None
        return data

