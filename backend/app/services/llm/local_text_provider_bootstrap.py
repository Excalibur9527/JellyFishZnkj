"""本地默认文本模型自修复。

说明：
- 本地 SQLite 开发环境经常只保留一份库快照，默认文本模型配置可能存在但密钥为空；
- 当前项目启动后若直接进入“分镜提取”，这类缺失会让任务在 5% 处快速失败；
- 这里在检测到 `DEEPSEEK_API_KEY` 可用时，自动补齐一套本地可运行的文本 provider/model，
  仅在当前默认文本模型不可用时接管，避免覆盖用户已经配置好的在线环境。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.llm import Model, ModelCategoryKey, ModelSettings, Provider, ProviderStatus


LOCAL_DEEPSEEK_PROVIDER_ID = "builtin-deepseek-text-provider"
LOCAL_DEEPSEEK_MODEL_ID = "builtin-deepseek-chat-model"


def _use_local_llm_bootstrap() -> bool:
    """仅在本地 SQLite 开发环境启用文本模型自修复。"""

    database_url = (settings.database_url or "").strip().lower()
    return database_url.startswith("sqlite")


async def _get_default_text_provider(db: AsyncSession) -> tuple[ModelSettings | None, Model | None, Provider | None]:
    """解析当前默认文本模型及其供应商，用于判断是否需要兜底接管。"""

    settings_row = await db.get(ModelSettings, 1)
    if settings_row is None or not settings_row.default_text_model_id:
        return settings_row, None, None

    model = await db.get(Model, settings_row.default_text_model_id)
    if model is None:
        return settings_row, None, None

    provider = await db.get(Provider, model.provider_id)
    return settings_row, model, provider


def _provider_ready(provider: Provider | None) -> bool:
    """判断当前默认文本供应商是否已具备最基本可调用条件。"""

    if provider is None:
        return False
    if (provider.api_key or "").strip() == "":
        return False
    return str(provider.status or "").strip().lower() != ProviderStatus.disabled.value


async def ensure_local_default_text_provider(db: AsyncSession) -> bool:
    """在本地环境中补齐可运行的默认文本模型。

    返回：
    - `True`：本次启动对 provider/model/settings 做了修复性写入
    - `False`：当前环境无需处理，或已有可用默认文本模型
    """

    if not _use_local_llm_bootstrap():
        return False

    api_key = (settings.deepseek_api_key or "").strip()
    if not api_key:
        return False

    settings_row, _current_model, current_provider = await _get_default_text_provider(db)
    if _provider_ready(current_provider):
        return False

    provider = await db.get(Provider, LOCAL_DEEPSEEK_PROVIDER_ID)
    if provider is None:
        provider = Provider(
            id=LOCAL_DEEPSEEK_PROVIDER_ID,
            name="DeepSeek",
            base_url=settings.deepseek_base_url,
            api_key=api_key,
            api_secret="",
            description="本地开发自动补齐的 DeepSeek 文本供应商",
            status=ProviderStatus.active,
            created_by="system",
        )
        db.add(provider)
    else:
        provider.name = "DeepSeek"
        provider.base_url = settings.deepseek_base_url
        provider.api_key = api_key
        provider.api_secret = ""
        provider.description = "本地开发自动补齐的 DeepSeek 文本供应商"
        provider.status = ProviderStatus.active

    model = await db.get(Model, LOCAL_DEEPSEEK_MODEL_ID)
    if model is None:
        model = Model(
            id=LOCAL_DEEPSEEK_MODEL_ID,
            name=settings.deepseek_text_model,
            category=ModelCategoryKey.text,
            provider_id=LOCAL_DEEPSEEK_PROVIDER_ID,
            params={"temperature": 0},
            description="本地开发自动补齐的 DeepSeek 默认文本模型",
            created_by="system",
        )
        db.add(model)
    else:
        model.name = settings.deepseek_text_model
        model.category = ModelCategoryKey.text
        model.provider_id = LOCAL_DEEPSEEK_PROVIDER_ID
        model.params = dict(model.params or {}) or {"temperature": 0}
        model.description = "本地开发自动补齐的 DeepSeek 默认文本模型"

    if settings_row is None:
        settings_row = ModelSettings(id=1, default_text_model_id=LOCAL_DEEPSEEK_MODEL_ID)
        db.add(settings_row)
    else:
        settings_row.default_text_model_id = LOCAL_DEEPSEEK_MODEL_ID

    await db.commit()
    return True
