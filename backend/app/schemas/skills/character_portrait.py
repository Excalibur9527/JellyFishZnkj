"""人物画像缺失信息分析：结构化输出 schema。"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, ConfigDict


class CharacterPortraitAnalysisResult(BaseModel):
    """根据原文人物描述，分析缺少的信息，并给出优化后的可生成画像描述。"""

    model_config = ConfigDict(extra="forbid")

    issues: List[str]
    optimized_description: str
    visual_fingerprint: str = ""
    """视觉指纹：从 optimized_description 中提炼的 30~60 字精华外貌标签。
    格式固定：「脸型，五官特征，发型发色，肤色，体型，服装颜色材质关键词」。
    供跨镜头提示词直接复用，不含任何修饰词或模糊表达。
    """


__all__ = ["CharacterPortraitAnalysisResult"]

