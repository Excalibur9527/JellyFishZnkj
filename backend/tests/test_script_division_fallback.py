from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import Base
from app.models.llm import Model, ModelCategoryKey, ModelSettings, Provider
from app.services.script_division_fallback import divide_script_locally
from app.services.script_processing_worker import DivideResultGenerator


def test_divide_script_locally_splits_text_into_editable_shots() -> None:
    """规则兜底分镜至少应产出可编辑镜头列表。"""

    result = divide_script_locally("少女在荒野醒来。她环顾四周。远处传来脚步声。她立刻起身逃跑。")

    assert result.total_shots >= 2
    assert len(result.shots) == result.total_shots
    assert result.shots[0].index == 1
    assert result.shots[0].start_line == 1
    assert result.shots[0].end_line >= result.shots[0].start_line
    assert result.shots[0].script_excerpt
    assert result.notes is not None


def test_divide_result_generator_falls_back_to_local_divider_in_sqlite(monkeypatch, tmp_path) -> None:
    """本地 SQLite 环境在线模型不可用时，应自动降级为规则法分镜。"""

    db_path = tmp_path / "divide-fallback.db"
    sync_engine = create_engine(f"sqlite:///{db_path}", future=True)
    sync_session_local = sessionmaker(sync_engine, class_=Session, expire_on_commit=False)

    import app.models.task  # noqa: F401
    import app.models.task_links  # noqa: F401

    Base.metadata.create_all(sync_engine)
    with sync_session_local() as db:
        provider = Provider(id="p1", name="DeepSeek", base_url="https://api.deepseek.com/v1", api_key="broken-key")
        model = Model(id="m1", name="deepseek-chat", category=ModelCategoryKey.text, provider_id="p1")
        settings = ModelSettings(id=1, default_text_model_id="m1")
        db.add_all([provider, model, settings])
        db.commit()

        monkeypatch.setattr("app.services.script_processing_worker.settings.database_url", "sqlite+aiosqlite:///./jellyfish.db")
        monkeypatch.setattr(
            "app.services.worker.task_executor.build_default_text_llm_sync",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(HTTPException(status_code=401, detail="invalid key")),
        )

        result = DivideResultGenerator().generate(
            db,
            {"script_text": "少女在荒野醒来。她环顾四周。远处传来脚步声。她立刻起身逃跑。"},
        )

        assert result.total_shots >= 2
        assert result.shots[0].script_excerpt
        assert "本地规则兜底分镜" in (result.notes or "")

    sync_engine.dispose()
