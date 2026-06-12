"""生成能力共享的供应商类型契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ProviderKey = Literal["openai", "volcengine", "kling", "bailian", "kling_proxy"]


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """执行生成任务时需要的供应商配置。"""

    provider: ProviderKey
    api_key: str
    base_url: str | None = None
    api_secret: str | None = None  # Kling 等需要双密钥的供应商使用
