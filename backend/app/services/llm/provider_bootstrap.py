from __future__ import annotations

from app.models.llm import ModelCategoryKey
from app.services.llm.provider_registry import ProviderSpec, register_many


def bootstrap_builtin_providers() -> None:
    register_many(
        [
            ProviderSpec(
                key="openai",
                display_name="OpenAI",
                aliases=("openai",),
                supported_categories=(
                    ModelCategoryKey.text,
                    ModelCategoryKey.image,
                    ModelCategoryKey.video,
                ),
                default_base_url="https://api.openai.com/v1",
            ),
            ProviderSpec(
                key="volcengine",
                display_name="火山引擎",
                aliases=("火山引擎", "volcengine", "volc", "doubao", "bytedance", "ark"),
                supported_categories=(ModelCategoryKey.image, ModelCategoryKey.video),
                default_base_url="https://ark.cn-beijing.volces.com/api/v3",
            ),
            ProviderSpec(
                key="kling",
                display_name="可灵 AI",
                aliases=("kling", "可灵", "可灵 ai", "可灵ai", "klingai", "kuaishou"),
                supported_categories=(ModelCategoryKey.video,),
                default_base_url="https://api.klingai.com",
                requires_api_key=True,
                requires_api_secret=True,
            ),
            ProviderSpec(
                key="kling_proxy",
                display_name="可灵 AI（中转）",
                aliases=("kling_proxy", "可灵中转", "可灵（中转）", "可灵(中转)", "kling_34ku", "kling34ku", "可灵 ai（中转）", "可灵ai（中转）", "可灵 ai(中转)", "可灵 AI（中转）"),
                supported_categories=(ModelCategoryKey.video,),
                default_base_url="https://juhe.34ku.com",
                requires_api_key=True,
            ),
            ProviderSpec(
                key="bailian",
                display_name="阿里百炼（视频）",
                aliases=("bailian", "阿里百炼", "阿里百炼视频", "阿里百炼（视频）", "阿里百炼(视频)", "dashscope", "aliyun_video", "happyhorse", "bailian_video", "alibaba"),
                supported_categories=(ModelCategoryKey.video,),
                default_base_url="https://juhe.34ku.com",
                requires_api_key=True,
            ),
            ProviderSpec(
                key="aliyun_bailian",
                display_name="阿里百炼（文本）",
                aliases=("aliyun_bailian", "aliyun", "dashscope_text"),
                supported_categories=(ModelCategoryKey.text,),
                default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
        ]
    )
