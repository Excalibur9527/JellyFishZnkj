"""默认提示词模板初始化。

说明：
- 仅在 `prompt_templates` 为空时写入一组系统预置模板，避免覆盖用户已有数据。
- 主要用于 SQLite 本地开发环境，因为仓库中的历史 SQL 初始化脚本并不会自动应用到当前开发库。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.studio import PromptCategory, PromptTemplate


@dataclass(frozen=True)
class BuiltinPromptTemplate:
    """描述一条内置提示词模板。

    之所以在代码里维护，是为了让本地开发库在首次启动时也能拿到可用模板，
    不依赖 MySQL 方言的初始化 SQL。
    """

    category: PromptCategory
    name: str
    content: str
    variables: tuple[str, ...]
    preview: str


_IMAGE_TEMPLATE = """视觉风格：{{ visual_style }}
画面风格：{{ style }}
主体描述：{{ description }}
补充细节：{{ extra_details }}
视角要求：{{ view_angle or view }}
负面约束：{{ base_negative }}
"""

_FRAME_TEMPLATE = """镜头标题：{{ shot_title }}
剧本摘录：{{ script_excerpt }}
动作节拍：{{ action_summary }}
画面风格：{{ visual_style }} / {{ style }}
镜头语言：{{ camera_shot }} / {{ camera_angle }} / {{ camera_movement }}
连续性要求：{{ continuity_guidance }}
输出目标：{{ frame_goal }}
"""

_VIDEO_TEMPLATE = """镜头标题：{{ title }}
剧本摘录：{{ script_excerpt }}
动作节拍：{{ action_beats }}
画面风格：{{ visual_style }} / {{ style }}
镜头语言：{{ camera_shot }} / {{ angle }} / {{ movement }}
时长：{{ duration }}
场景：{{ scene }}
角色：{{ characters }}
道具：{{ props }}
服装：{{ costumes }}
对白摘要：{{ dialogue_summary }}
上一镜头：{{ previous_shot_summary }}
下一镜头目标：{{ next_shot_goal }}
连续性要求：{{ continuity_guidance }}
构图锚点：{{ composition_anchor }}
朝向与视线：{{ screen_direction_guidance }}
氛围：{{ atmosphere }}
负面约束：{{ negative_prompt }}
"""

_STORYBOARD_TEMPLATE = """请根据以下内容输出结构化分镜：
章节标题：{{ chapter_title }}
剧情摘要：{{ summary }}
原文：{{ raw_text }}
风格：{{ visual_style }} / {{ style }}
"""

_AUDIO_TEMPLATE = """场景：{{ scene }}
情绪：{{ mood }}
节奏：{{ rhythm }}
补充说明：{{ description }}
"""

_COMBINED_TEMPLATE = """主描述：{{ description }}
补充细节：{{ extra_details }}
风格：{{ visual_style }} / {{ style }}
"""

_CHARACTER_SHEET_TEMPLATE = """角色名称：{{ name }}
角色描述：{{ description }}
视觉指纹：{{ visual_fingerprint }}
视觉风格：{{ visual_style }}
画面风格：{{ style }}
输出要求：角色设定图、正交信息完整、造型稳定、便于后续镜头复用
"""


def _build_builtin_templates() -> list[BuiltinPromptTemplate]:
    """构造本地开发默认模板清单。

    每个类别都补一条最小可用模板，避免模板页、下拉框和默认渲染逻辑在空库下失去可见数据。
    """

    return [
        BuiltinPromptTemplate(PromptCategory.frame_head_image, "系统首帧图片模板", _FRAME_TEMPLATE, ("shot_title", "script_excerpt", "action_summary", "visual_style", "style", "camera_shot", "camera_angle", "camera_movement", "continuity_guidance", "frame_goal"), "默认首帧图片模板"),
        BuiltinPromptTemplate(PromptCategory.frame_tail_image, "系统尾帧图片模板", _FRAME_TEMPLATE, ("shot_title", "script_excerpt", "action_summary", "visual_style", "style", "camera_shot", "camera_angle", "camera_movement", "continuity_guidance", "frame_goal"), "默认尾帧图片模板"),
        BuiltinPromptTemplate(PromptCategory.frame_key_image, "系统关键帧图片模板", _FRAME_TEMPLATE, ("shot_title", "script_excerpt", "action_summary", "visual_style", "style", "camera_shot", "camera_angle", "camera_movement", "continuity_guidance", "frame_goal"), "默认关键帧图片模板"),
        BuiltinPromptTemplate(PromptCategory.frame_head_prompt, "系统首帧文案模板", _FRAME_TEMPLATE, ("shot_title", "script_excerpt", "action_summary", "visual_style", "style", "camera_shot", "camera_angle", "camera_movement", "continuity_guidance", "frame_goal"), "默认首帧文案模板"),
        BuiltinPromptTemplate(PromptCategory.frame_tail_prompt, "系统尾帧文案模板", _FRAME_TEMPLATE, ("shot_title", "script_excerpt", "action_summary", "visual_style", "style", "camera_shot", "camera_angle", "camera_movement", "continuity_guidance", "frame_goal"), "默认尾帧文案模板"),
        BuiltinPromptTemplate(PromptCategory.frame_key_prompt, "系统关键帧文案模板", _FRAME_TEMPLATE, ("shot_title", "script_excerpt", "action_summary", "visual_style", "style", "camera_shot", "camera_angle", "camera_movement", "continuity_guidance", "frame_goal"), "默认关键帧文案模板"),
        BuiltinPromptTemplate(PromptCategory.video_prompt, "系统视频提示词模板", _VIDEO_TEMPLATE, ("title", "script_excerpt", "action_beats", "visual_style", "style", "camera_shot", "angle", "movement", "duration", "scene", "characters", "props", "costumes", "dialogue_summary", "previous_shot_summary", "next_shot_goal", "continuity_guidance", "composition_anchor", "screen_direction_guidance", "atmosphere", "negative_prompt"), "默认视频提示词模板"),
        BuiltinPromptTemplate(PromptCategory.storyboard_prompt, "系统分镜模板", _STORYBOARD_TEMPLATE, ("chapter_title", "summary", "raw_text", "visual_style", "style"), "默认分镜拆解模板"),
        BuiltinPromptTemplate(PromptCategory.bgm, "系统配乐模板", _AUDIO_TEMPLATE, ("scene", "mood", "rhythm", "description"), "默认配乐模板"),
        BuiltinPromptTemplate(PromptCategory.sfx, "系统音效模板", _AUDIO_TEMPLATE, ("scene", "mood", "rhythm", "description"), "默认音效模板"),
        BuiltinPromptTemplate(PromptCategory.character_image_front, "系统角色正面图片模板", _IMAGE_TEMPLATE, ("visual_style", "style", "description", "extra_details", "view_angle", "view", "base_negative"), "默认角色正面图片模板"),
        BuiltinPromptTemplate(PromptCategory.character_image_other, "系统角色其他视角模板", _IMAGE_TEMPLATE, ("visual_style", "style", "description", "extra_details", "view_angle", "view", "base_negative"), "默认角色其他视角模板"),
        BuiltinPromptTemplate(PromptCategory.actor_image_front, "系统演员正面图片模板", _IMAGE_TEMPLATE, ("visual_style", "style", "description", "extra_details", "view_angle", "view", "base_negative"), "默认演员正面图片模板"),
        BuiltinPromptTemplate(PromptCategory.actor_image_other, "系统演员其他视角模板", _IMAGE_TEMPLATE, ("visual_style", "style", "description", "extra_details", "view_angle", "view", "base_negative"), "默认演员其他视角模板"),
        BuiltinPromptTemplate(PromptCategory.prop_image_front, "系统道具正面图片模板", _IMAGE_TEMPLATE, ("visual_style", "style", "description", "extra_details", "view_angle", "view", "base_negative"), "默认道具正面图片模板"),
        BuiltinPromptTemplate(PromptCategory.prop_image_other, "系统道具其他视角模板", _IMAGE_TEMPLATE, ("visual_style", "style", "description", "extra_details", "view_angle", "view", "base_negative"), "默认道具其他视角模板"),
        BuiltinPromptTemplate(PromptCategory.scene_image_front, "系统场景正面图片模板", _IMAGE_TEMPLATE, ("visual_style", "style", "description", "extra_details", "view_angle", "view", "base_negative"), "默认场景正面图片模板"),
        BuiltinPromptTemplate(PromptCategory.scene_image_other, "系统场景其他视角模板", _IMAGE_TEMPLATE, ("visual_style", "style", "description", "extra_details", "view_angle", "view", "base_negative"), "默认场景其他视角模板"),
        BuiltinPromptTemplate(PromptCategory.costume_image_front, "系统服装正面图片模板", _IMAGE_TEMPLATE, ("visual_style", "style", "description", "extra_details", "view_angle", "view", "base_negative"), "默认服装正面图片模板"),
        BuiltinPromptTemplate(PromptCategory.costume_image_other, "系统服装其他视角模板", _IMAGE_TEMPLATE, ("visual_style", "style", "description", "extra_details", "view_angle", "view", "base_negative"), "默认服装其他视角模板"),
        BuiltinPromptTemplate(PromptCategory.combined, "系统综合提示词模板", _COMBINED_TEMPLATE, ("description", "extra_details", "visual_style", "style"), "默认综合提示词模板"),
        BuiltinPromptTemplate(PromptCategory.character_sheet, "系统角色设定图模板", _CHARACTER_SHEET_TEMPLATE, ("name", "description", "visual_fingerprint", "visual_style", "style"), "默认角色设定图模板"),
    ]


async def ensure_builtin_prompt_templates(db: AsyncSession) -> int:
    """在空库中写入内置模板并返回新增条数。

    只在表为空时执行，避免覆盖用户已经创建或导入的模板集合。
    """

    total = await db.scalar(select(func.count()).select_from(PromptTemplate))
    if total and total > 0:
        return 0

    created = 0
    for item in _build_builtin_templates():
        db.add(
            PromptTemplate(
                id=f"builtin-{item.category.value}",
                category=item.category,
                name=item.name,
                preview=item.preview,
                content=item.content,
                variables=list(item.variables),
                is_default=True,
                is_system=True,
            )
        )
        created += 1

    await db.commit()
    return created
