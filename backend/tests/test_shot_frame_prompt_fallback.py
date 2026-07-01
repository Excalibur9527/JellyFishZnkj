from __future__ import annotations

from app.services.film.shot_frame_prompt_fallback import build_local_shot_frame_prompt


def test_build_local_shot_frame_prompt_uses_frame_context() -> None:
    """本地兜底提示词应保留镜头核心上下文，便于继续手工编辑。"""

    result = build_local_shot_frame_prompt(
        frame_type="first",
        input_dict={
            "visual_style": "现实电影感",
            "style": "古风",
            "camera_shot": "中景",
            "angle": "平视",
            "movement": "静止",
            "title": "红宴初现",
            "script_excerpt": "艾铃站在红宴中央，看向谢砚之。",
            "character_context": "艾铃、谢砚之",
            "scene_context": "喜堂红宴",
            "atmosphere": "压抑、危险将至",
            "frame_specific_guidance": "首帧先建立人物站位与对峙关系",
        },
    )

    assert "首帧画面" in result.prompt
    assert "现实电影感" in result.prompt
    assert "喜堂红宴" in result.prompt
    assert "首帧先建立人物站位与对峙关系" in result.prompt
