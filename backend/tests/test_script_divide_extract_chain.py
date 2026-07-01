from __future__ import annotations

from types import SimpleNamespace

from app.schemas.skills.script_processing import ScriptDivisionResult, ShotDivision
from app.services import script_processing_worker
from app.services.script_processing_worker import DivideTaskExecutor


def _division_result() -> ScriptDivisionResult:
    """构造一条最小分镜结果，验证分镜与信息提取的串联参数。"""

    return ScriptDivisionResult(
        total_shots=1,
        notes=None,
        shots=[
            ShotDivision(
                index=1,
                start_line=1,
                end_line=1,
                script_excerpt="艾铃站在厅中。",
                shot_name="镜头一",
                time_of_day="UNKNOWN",
                character_emotions=[],
            )
        ],
    )


def test_divide_apply_chains_shot_extraction(monkeypatch) -> None:
    """主流程开启串联提取后，应使用刚落库的分镜结果继续生成候选项。"""

    calls: dict[str, object] = {}
    draft = object()
    chapter = SimpleNamespace(project_id="project-1")

    class _FakeDB:
        """提供执行器串联逻辑所需的最小同步会话接口。"""

        def get(self, model, entity_id):
            calls["chapter_lookup"] = (model, entity_id)
            return chapter

    def _fake_apply_division(db, *, chapter_id, result):
        calls["division"] = (db, chapter_id, result)

    def _fake_generate_extraction(**kwargs):
        calls["extraction_args"] = kwargs
        return draft, False

    def _fake_apply_extraction(db, *, chapter_id, draft):
        calls["extraction_apply"] = (db, chapter_id, draft)

    monkeypatch.setattr(script_processing_worker, "apply_division_result", _fake_apply_division)
    monkeypatch.setattr(script_processing_worker, "generate_extraction_result", _fake_generate_extraction)
    monkeypatch.setattr(script_processing_worker, "apply_extraction_result", _fake_apply_extraction)

    result = _division_result()
    db = _FakeDB()
    DivideTaskExecutor().apply_result(
        SimpleNamespace(db=db),
        {
            "chapter_id": "chapter-1",
            "write_to_db": True,
            "extract_after_divide": True,
        },
        result,
    )

    assert calls["division"] == (db, "chapter-1", result)
    assert calls["extraction_args"] == {
        "db": db,
        "project_id": "project-1",
        "chapter_id": "chapter-1",
        "script_division": result.model_dump(),
        "consistency": None,
        "refresh_cache": False,
    }
    assert calls["extraction_apply"] == (db, "chapter-1", draft)

