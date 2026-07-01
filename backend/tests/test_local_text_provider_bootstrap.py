from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.models.llm import Model, ModelCategoryKey, ModelSettings, Provider
from app.services.llm.local_text_provider_bootstrap import (
    LOCAL_DEEPSEEK_MODEL_ID,
    LOCAL_DEEPSEEK_PROVIDER_ID,
    ensure_local_default_text_provider,
)


async def _build_session() -> tuple[AsyncSession, object]:
    """构建内存数据库会话，验证本地文本模型自修复逻辑。"""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return session_local(), engine


@pytest.mark.asyncio
async def test_ensure_local_default_text_provider_bootstraps_deepseek_when_default_provider_missing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """默认文本供应商缺 key 时，应自动切到环境里可用的 DeepSeek 文本模型。"""

    db, engine = await _build_session()
    monkeypatch.setattr("app.services.llm.local_text_provider_bootstrap.settings.database_url", "sqlite+aiosqlite:///./jellyfish.db")
    monkeypatch.setattr("app.services.llm.local_text_provider_bootstrap.settings.deepseek_api_key", "deepseek-test-key")
    monkeypatch.setattr("app.services.llm.local_text_provider_bootstrap.settings.deepseek_base_url", "https://api.deepseek.com/v1")
    monkeypatch.setattr("app.services.llm.local_text_provider_bootstrap.settings.deepseek_text_model", "deepseek-chat")

    async with db:
        provider = Provider(id="p-openai", name="OpenAI", base_url="https://api.openai.com/v1", api_key="")
        model = Model(id="m-openai", name="gpt-5.5", category=ModelCategoryKey.text, provider_id="p-openai")
        settings = ModelSettings(id=1, default_text_model_id="m-openai")
        db.add_all([provider, model, settings])
        await db.commit()

        changed = await ensure_local_default_text_provider(db)
        assert changed is True

        boot_provider = await db.get(Provider, LOCAL_DEEPSEEK_PROVIDER_ID)
        boot_model = await db.get(Model, LOCAL_DEEPSEEK_MODEL_ID)
        boot_settings = await db.get(ModelSettings, 1)

        assert boot_provider is not None
        assert boot_provider.name == "DeepSeek"
        assert boot_provider.api_key == "deepseek-test-key"
        assert boot_provider.base_url == "https://api.deepseek.com/v1"

        assert boot_model is not None
        assert boot_model.name == "deepseek-chat"
        assert boot_model.provider_id == LOCAL_DEEPSEEK_PROVIDER_ID
        assert boot_model.category == ModelCategoryKey.text

        assert boot_settings is not None
        assert boot_settings.default_text_model_id == LOCAL_DEEPSEEK_MODEL_ID

    await engine.dispose()


@pytest.mark.asyncio
async def test_ensure_local_default_text_provider_keeps_existing_ready_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已有可用默认文本供应商时，不应覆盖用户配置。"""

    db, engine = await _build_session()
    monkeypatch.setattr("app.services.llm.local_text_provider_bootstrap.settings.database_url", "sqlite+aiosqlite:///./jellyfish.db")
    monkeypatch.setattr("app.services.llm.local_text_provider_bootstrap.settings.deepseek_api_key", "deepseek-test-key")

    async with db:
        provider = Provider(id="p-openai", name="OpenAI", base_url="https://api.openai.com/v1", api_key="ready-key")
        model = Model(id="m-openai", name="gpt-4o-mini", category=ModelCategoryKey.text, provider_id="p-openai")
        settings = ModelSettings(id=1, default_text_model_id="m-openai")
        db.add_all([provider, model, settings])
        await db.commit()

        changed = await ensure_local_default_text_provider(db)
        assert changed is False

        boot_provider = await db.get(Provider, LOCAL_DEEPSEEK_PROVIDER_ID)
        boot_settings = await db.get(ModelSettings, 1)
        assert boot_provider is None
        assert boot_settings is not None
        assert boot_settings.default_text_model_id == "m-openai"

    await engine.dispose()
