from __future__ import annotations

from app.schemas.studio.shots import FrameGuidanceDecisionRead, RenderedShotFramePromptRead, ShotFramePromptMappingRead
from app.services.studio.generation.frame.build_base import FrameBaseDraft
from app.services.studio.generation.frame.build_context import FrameGenerationContext
from app.services.studio.generation.shared.types import GenerationDerivedPreview


# 现实风格：保留真实影视质感，只约束不得模仿真实人物
FRAME_FACE_INTEGRITY_LIVE_ACTION = (
    "人物面部约束：如画面中有人物，必须保留清晰可辨的完整自然五官；"
    "不要生成无脸、遮脸、背影替代、面部模糊或五官缺失；"
    "画面应呈现高质量影视级写实质感，保持参考图中人物的面部特征、气质与外貌细节；"
    "不要模仿任何真实个人、明星、公众人物或版权角色。"
)

# 动漫/非写实风格：明确保留风格化设计感，避免混入摄影质感
FRAME_FACE_INTEGRITY_ANIME = (
    "人物面部约束：如画面中有人物，必须保留清晰可辨的原创虚构人脸和完整自然五官；"
    "不要生成无脸、遮脸、背影替代、面部模糊或五官缺失；"
    "画面应是高质量影视概念参考图，保留原创角色的风格化设计感，避免真实摄影照片、街拍、证件照或真人抓拍质感；"
    "不要模仿任何真实个人、明星、公众人物或版权角色。"
)

# 兼容旧调用路径（无 visual_style 时的默认值，保持现有行为）
FRAME_ORIGINAL_FACE_INTEGRITY_PROMPT = FRAME_FACE_INTEGRITY_ANIME


def _character_identity_lock_prompt(mappings: list[ShotFramePromptMappingRead]) -> str:
    """生成角色身份锁定规则，避免非角色参考图或剧情重绘改变人脸。

    仅当存在 character 参考图时追加。相比通用“保持参考图人物”，这里明确
    指定角色图是唯一身份来源，并把脸型、五官比例、眼型等身份锚点拆开写，
    降低模型把服装图、场景图或剧情人物重新融合成另一张脸的概率。
    """

    character_refs = [mapping for mapping in mappings if mapping.type == "character"]
    if not character_refs:
        return ""
    labels = "、".join(f"{mapping.token}（{mapping.name}）" for mapping in character_refs)
    return (
        f"人物身份锁定：{labels}是人物身份与脸部特征的唯一来源；"
        "必须保持对应角色的脸型轮廓、五官比例、眼型、鼻型、嘴型、下巴轮廓、发际线、发型、神态气质和年龄感；"
        "只允许因当前镜头表情、视线方向和机位角度产生自然变化，不得重绘成另一张脸；"
        "服装、场景、道具参考图中若出现人脸或人物，均不得作为身份来源。"
    )


def _face_integrity_prompt_for_style(visual_style: str | None, mappings: list[ShotFramePromptMappingRead] | None = None) -> str:
    """根据项目视觉风格返回人物面部约束，并按角色参考图补身份锁定。

    现实（live_action）风格用写实影视约束；其余风格（动漫等）用原有风格化约束。
    """
    style = (visual_style or "").strip().lower()
    identity_lock = _character_identity_lock_prompt(mappings or [])
    identity_suffix = f"{identity_lock}" if identity_lock else ""
    if style in ("现实", "live_action"):
        return f"{FRAME_FACE_INTEGRITY_LIVE_ACTION}{identity_suffix}"
    return f"{FRAME_FACE_INTEGRITY_ANIME}{identity_suffix}"


def replace_reference_names_in_prompt(
    *,
    base_prompt: str,
    mappings: list[ShotFramePromptMappingRead],
) -> str:
    """保留旧入口但不再替换剧情正文中的实体名。

    早期实现会把“艾铃”这类角色名替换成“图1”，方便模型把文字与参考图
    建立联系。但在真实首帧 prompt 中，这会把剧情句子改成“图1原本是……”
    这类不自然表达，导致模型同时把图号当角色、当图片引用，反而削弱身份
    和服装约束。现在图号只出现在参考图说明区，剧情正文保持原始角色名。
    """
    text = (base_prompt or "").strip()
    return text


def should_apply_face_integrity_prompt(
    *,
    prompt: str,
    mappings: list[ShotFramePromptMappingRead],
) -> bool:
    """判断当前分镜帧是否包含人物，从而决定是否追加面部完整性约束。"""
    if any(mapping.type == "character" for mapping in mappings):
        return True
    text = str(prompt or "")
    return any(keyword in text for keyword in ("人物", "角色", "主角", "男人", "女人", "男孩", "女孩", "他", "她"))


def _reference_usage_rule(mapping: ShotFramePromptMappingRead) -> str:
    """生成单张参考图的类型化使用规则，避免多参考图互相污染。

    分镜帧生成通常同时携带角色、服装、场景与道具参考图。模型若只看到
    “图1/图2”名称，容易把服装图里的人脸、场景图里的人物或道具图背景
    混入结果，因此这里按资产类型明确“取什么 / 忽略什么”。
    """

    input_label = mapping.token.removeprefix("图") if mapping.token.startswith("图") else mapping.token
    label = f"第{input_label}张输入参考图（{mapping.token}，{mapping.name}）"
    if mapping.type == "character":
        return (
            f"{label}是角色身份参考：只以该图确定对应人物的脸型、五官、发型、气质、体态与身份一致性；"
            "必须保持脸型轮廓、五官比例、眼型、鼻型、嘴型、下巴轮廓、发际线和神态气质；"
            "不要把该图里的临时背景、临时姿势或非当前镜头服装当成硬约束。"
        )
    if mapping.type == "costume":
        return (
            f"{label}是服装参考：只提取服装款式、颜色、纹样、材质与层次；"
            "必须逐项保持参考服装的主色、辅色、纹样、材质和层次；"
            "即使剧情出现婚礼、嫁娶、大婚或退婚等语义，也不得把服装默认改成红色婚服或其他剧本常识服装；"
            "必须忽略该图中的人脸、发型、身体姿势、手持物、背景与场景。"
        )
    if mapping.type == "scene":
        return (
            f"{label}是场景参考：只提取空间结构、时代氛围、光线、色调、背景陈设与环境质感；"
            "必须忽略该图中的人物、脸、服装、动作和临时道具，除非这些对象另有独立参考图。"
        )
    if mapping.type == "prop":
        return (
            f"{label}是道具参考：只提取道具造型、材质、尺寸感、颜色与使用方式；"
            "必须忽略该图中的人物、手、脸、服装、背景和摆拍环境。"
        )
    return f"{label}是参考图：只提取与其资产类型相关的信息，忽略无关人物、背景和临时姿势。"


def build_frame_reference_usage_contract(mappings: list[ShotFramePromptMappingRead]) -> list[str]:
    """构建分镜帧参考图使用契约。

    返回值会进入最终图片 prompt，用统一优先级约束多参考图融合：
    角色负责身份，服装负责穿着，场景负责环境，道具负责物件。
    """

    if not mappings:
        return []

    rules = [_reference_usage_rule(mapping) for mapping in mappings]
    present_types = {mapping.type for mapping in mappings}
    priority_parts: list[str] = []
    if "character" in present_types:
        priority_parts.append("人物身份、脸型、五官、发型和气质以角色参考图为最高优先级")
    if "costume" in present_types:
        priority_parts.append("服装款式、颜色、纹样和材质以服装参考图为最高优先级")
    if "scene" in present_types:
        priority_parts.append("空间结构、光线和环境陈设以场景参考图为最高优先级")
    if "prop" in present_types:
        priority_parts.append("道具造型、材质和使用方式以道具参考图为最高优先级")
    if priority_parts:
        rules.append(f"参考图冲突处理：{'；'.join(priority_parts)}；不同类型参考图不得互相覆盖职责。")
    if "character" in present_types and any(t in present_types for t in ("costume", "scene", "prop")):
        rules.append("身份一致性硬规则：非角色参考图中若出现人脸或人物，必须视为无关信息，不得改变角色参考图确定的人脸与身份。")
    if "costume" in present_types:
        rules.append("服装一致性硬规则：服装参考图的颜色、款式、纹样和层次优先于剧情词、时代词与类型片常识；不得因为“大婚”“婚房”“嫁娶”等文字把服装自动改红或替换为其他婚服。")
    return rules


def append_frame_face_integrity_prompt(
    *,
    rendered_prompt: str,
    mappings: list[ShotFramePromptMappingRead],
    visual_style: str | None = None,
) -> str:
    """为人物分镜帧追加人脸约束。

    根据项目视觉风格选择约束文案：
    - 现实（live_action）风格：保留写实影视质感，只限制不得模仿真实人物
    - 动漫等其他风格：保留原有风格化约束，避免摄影质感

    该约束只进入最终图片 prompt，不改变资产绑定。
    """
    text = str(rendered_prompt or "").strip()
    normalized = text.replace(" ", "")
    if "人物面部约束" in normalized:
        return text
    if not should_apply_face_integrity_prompt(prompt=text, mappings=mappings):
        return text
    integrity_prompt = _face_integrity_prompt_for_style(visual_style, mappings)
    if not text:
        return integrity_prompt
    return f"{text}\n{integrity_prompt}".strip()


def _score_frame_guidance_line(
    *,
    frame_type: str,
    category: str,
    text: str,
) -> int:
    """按帧类型和文本特征给图片 guidance 打分，控制最终 prompt 的收敛顺序。"""
    score_by_category = {
        "summary": 100,
        "continuity": 80,
        "frame": 70,
        "screen": 65,
        "composition": 60,
    }
    score = score_by_category.get(category, 0)

    if frame_type == "first" and category == "frame":
        score += 18
    if frame_type == "first" and category == "composition":
        score += 15
    if frame_type == "key" and category == "frame":
        score += 6
    if frame_type == "last" and category == "frame":
        score += 8
    if frame_type in {"key", "last"} and category == "screen":
        score += 10
    if frame_type == "last" and category == "continuity":
        score += 5

    if category == "frame" and any(keyword in text for keyword in ("触发瞬间", "初始反应", "尚未完成", "动作峰值", "情绪余韵", "收束")):
        score += 8
    if category == "screen" and any(keyword in text for keyword in ("视线", "对视", "左右", "朝向", "跳轴")):
        score += 10
    if category == "composition" and any(keyword in text for keyword in ("空间", "重心", "环境", "锚点", "站位")):
        score += 10
    if category == "continuity" and any(keyword in text for keyword in ("上一镜头", "下一镜头", "承接", "收束")):
        score += 5

    return score


def _build_frame_guidance_reason(
    *,
    frame_type: str,
    category: str,
    selected: bool,
) -> str:
    """生成 guidance 被保留或压缩的可解释原因。"""
    if selected:
        if category == "frame":
            if frame_type == "first":
                return "当前是首帧，系统优先保留触发瞬间与未完成态约束，避免画面直接跳到后续完成动作。"
            if frame_type == "key":
                return "当前是关键帧，系统保留帧职责 guidance 来强化动作峰值或情绪爆点。"
            if frame_type == "last":
                return "当前是尾帧，系统保留帧职责 guidance 来强化动作收束与情绪落点。"
        if frame_type == "first" and category == "composition":
            return "当前是首帧，系统优先稳住空间建立与主体站位，所以保留构图锚点。"
        if frame_type in {"key", "last"} and category == "screen":
            return "当前镜头更看重视线与左右轴线稳定，因此优先保留朝向与视线 guidance。"
        if category == "summary":
            return "导演主指令始终属于最高优先级约束，因此会优先保留。"
        if category == "continuity":
            return "连续性 guidance 直接影响镜头承接稳定性，因此被保留。"
        if category == "composition":
            return "这条 guidance 对画面空间重心更关键，因此被保留。"
        if category == "screen":
            return "这条 guidance 对视线、朝向或轴线更关键，因此被保留。"

    if category == "frame":
        if frame_type == "first":
            return "当前已有更高优先级的首帧约束进入最终 prompt，因此这条帧职责 guidance 被压缩。"
        if frame_type == "key":
            return "当前已有更高优先级的关键帧约束进入最终 prompt，因此这条帧职责 guidance 被压缩。"
        if frame_type == "last":
            return "当前已有更高优先级的尾帧约束进入最终 prompt，因此这条帧职责 guidance 被压缩。"
    if frame_type == "first" and category == "screen":
        return "当前是首帧，系统更优先保空间建立与站位关系，因此将朝向与视线 guidance 降为次级。"
    if frame_type in {"key", "last"} and category == "composition":
        return "当前镜头更优先保视线与左右轴线稳定，因此构图锚点 guidance 被压缩。"
    if category == "summary":
        return "当前已有更高分的导演主指令进入最终 prompt，这条摘要未继续保留。"
    if category == "continuity":
        return "当前已有更高优先级的镜头约束进入最终 prompt，因此这条连续性 guidance 被压缩。"
    if category == "composition":
        return "当前已有更高优先级的空间或朝向约束进入最终 prompt，因此这条构图 guidance 被压缩。"
    if category == "screen":
        return "当前已有更高优先级的空间或连续性约束进入最终 prompt，因此这条朝向/视线 guidance 被压缩。"
    return "当前已有更高优先级 guidance 进入最终 prompt，因此该条目未被保留。"


def _build_frame_guidance_reason_tag(
    *,
    frame_type: str,
    category: str,
    selected: bool,
) -> str:
    """生成更适合前端快速阅读的短标签。"""
    if category == "summary":
        return "导演主指令"
    if category == "frame":
        if frame_type == "first":
            return "首帧保时序" if selected else "首帧降时序"
        if frame_type == "key":
            return "关键帧保峰值" if selected else "关键帧降峰值"
        if frame_type == "last":
            return "尾帧保收束" if selected else "尾帧降收束"
    if category == "continuity":
        return "连续性优先" if selected else "连续性降级"
    if frame_type == "first" and category == "composition":
        return "首帧保空间" if selected else "首帧降构图"
    if frame_type == "first" and category == "screen":
        return "首帧降轴线"
    if frame_type in {"key", "last"} and category == "screen":
        return "关键帧保轴线" if frame_type == "key" and selected else ("尾帧保轴线" if selected else "轴线降级")
    if frame_type in {"key", "last"} and category == "composition":
        return "关键帧降构图" if frame_type == "key" else "尾帧降构图"
    if category == "composition":
        return "构图优先" if selected else "构图降级"
    if category == "screen":
        return "轴线优先" if selected else "轴线降级"
    return "优先级调整"


def _collect_frame_guidance_lines(
    *,
    frame_type: str,
    replaced_prompt: str,
    director_command_summary: str,
    continuity_guidance: str,
    frame_specific_guidance: str,
    composition_anchor: str,
    screen_direction_guidance: str,
) -> tuple[list[str], list[str], list[FrameGuidanceDecisionRead], list[FrameGuidanceDecisionRead]]:
    """收集最终保留与被压缩掉的 guidance，供渲染与前端展示共用。"""
    text = (replaced_prompt or "").strip()
    candidates: list[tuple[int, int, str, str]] = []
    normalized_summary = (director_command_summary or "").strip()
    normalized_continuity = (continuity_guidance or "").strip()
    normalized_frame = (frame_specific_guidance or "").strip()
    normalized_composition = (composition_anchor or "").strip()
    normalized_screen = (screen_direction_guidance or "").strip()

    if normalized_summary and normalized_summary not in text:
        candidates.append(
            (
                _score_frame_guidance_line(frame_type=frame_type, category="summary", text=normalized_summary),
                0,
                "summary",
                f"高优先级导演指令：{normalized_summary}",
            )
        )
    if (
        normalized_continuity
        and normalized_continuity not in text
        and normalized_continuity not in normalized_summary
        and "连续性要求：" not in text
    ):
        candidates.append(
            (
                _score_frame_guidance_line(frame_type=frame_type, category="continuity", text=normalized_continuity),
                1,
                "continuity",
                f"连续性要求：{normalized_continuity}",
            )
        )
    if (
        normalized_frame
        and normalized_frame not in text
        and normalized_frame not in normalized_summary
        and "当前帧职责：" not in text
    ):
        candidates.append(
            (
                _score_frame_guidance_line(frame_type=frame_type, category="frame", text=normalized_frame),
                2,
                "frame",
                f"当前帧职责：{normalized_frame}",
            )
        )
    if (
        normalized_composition
        and normalized_composition not in text
        and "构图锚点：" not in text
    ):
        candidates.append(
            (
                _score_frame_guidance_line(frame_type=frame_type, category="composition", text=normalized_composition),
                4,
                "composition",
                f"构图锚点：{normalized_composition}",
            )
        )
    if (
        normalized_screen
        and normalized_screen not in text
        and "朝向与视线：" not in text
    ):
        candidates.append(
            (
                _score_frame_guidance_line(frame_type=frame_type, category="screen", text=normalized_screen),
                3,
                "screen",
                f"朝向与视线：{normalized_screen}",
            )
        )

    ranked = sorted(candidates, key=lambda item: (-item[0], item[1]))
    selected_rows = ranked[:3]
    dropped_rows = ranked[3:]
    selected = [line for _, _, _, line in selected_rows]
    dropped = [line for _, _, _, line in dropped_rows]
    selected_details = [
        FrameGuidanceDecisionRead(
            text=line,
            category=category,
            reason_tag=_build_frame_guidance_reason_tag(frame_type=frame_type, category=category, selected=True),
            reason=_build_frame_guidance_reason(frame_type=frame_type, category=category, selected=True),
        )
        for _, _, category, line in selected_rows
    ]
    dropped_details = [
        FrameGuidanceDecisionRead(
            text=line,
            category=category,
            reason_tag=_build_frame_guidance_reason_tag(frame_type=frame_type, category=category, selected=False),
            reason=_build_frame_guidance_reason(frame_type=frame_type, category=category, selected=False),
        )
        for _, _, category, line in dropped_rows
    ]
    return selected, dropped, selected_details, dropped_details


def enrich_frame_prompt_with_guidance(
    *,
    frame_type: str,
    replaced_prompt: str,
    director_command_summary: str,
    continuity_guidance: str,
    frame_specific_guidance: str,
    composition_anchor: str,
    screen_direction_guidance: str,
) -> str:
    """将高优先级导演约束补入最终图片提示词，避免只停留在调试展示。"""
    text = (replaced_prompt or "").strip()
    guidance_lines, _, _, _ = _collect_frame_guidance_lines(
        frame_type=frame_type,
        replaced_prompt=text,
        director_command_summary=director_command_summary,
        continuity_guidance=continuity_guidance,
        frame_specific_guidance=frame_specific_guidance,
        composition_anchor=composition_anchor,
        screen_direction_guidance=screen_direction_guidance,
    )
    if not guidance_lines:
        return text
    return "\n".join([*guidance_lines, text]).strip()


def compose_shot_frame_rendered_prompt(
    *,
    replaced_prompt: str,
    mappings: list[ShotFramePromptMappingRead],
) -> str:
    """拼装最终提交给模型的关键帧提示词。"""
    lines: list[str] = []
    if mappings:
        lines.append("## 图片内容说明")
        for mapping in mappings:
            lines.append(f"{mapping.token}: {mapping.name}")
        usage_contract = build_frame_reference_usage_contract(mappings)
        if usage_contract:
            lines.append("")
            lines.append("## 参考图使用规则")
            lines.extend(usage_contract)
        lines.append("")
    lines.append("## 生成内容")
    lines.append((replaced_prompt or "").strip())
    return "\n".join(lines).strip()


class FrameDerivedPreview(GenerationDerivedPreview):
    """分镜帧图片生成的最终预览结果。"""

    kind: str = "frame"
    shot_id: str
    frame_type: str
    base_prompt: str
    rendered_prompt: str
    selected_guidance: list[str]
    dropped_guidance: list[str]
    selected_guidance_details: list[FrameGuidanceDecisionRead]
    dropped_guidance_details: list[FrameGuidanceDecisionRead]
    images: list[str]
    mappings: list[ShotFramePromptMappingRead]


def derive_frame_preview(
    *,
    base: FrameBaseDraft,
    context: FrameGenerationContext,
) -> FrameDerivedPreview:
    normalized_base_prompt = (base.prompt or "").strip()
    replaced_prompt = replace_reference_names_in_prompt(
        base_prompt=normalized_base_prompt,
        mappings=context.ordered_refs,
    )
    selected_guidance, dropped_guidance, selected_guidance_details, dropped_guidance_details = _collect_frame_guidance_lines(
        frame_type=base.frame_type.value if hasattr(base.frame_type, "value") else str(base.frame_type),
        replaced_prompt=replaced_prompt,
        director_command_summary=base.director_command_summary,
        continuity_guidance=base.continuity_guidance,
        frame_specific_guidance=base.frame_specific_guidance,
        composition_anchor=base.composition_anchor,
        screen_direction_guidance=base.screen_direction_guidance,
    )
    enriched_prompt = enrich_frame_prompt_with_guidance(
        frame_type=base.frame_type.value if hasattr(base.frame_type, "value") else str(base.frame_type),
        replaced_prompt=replaced_prompt,
        director_command_summary=base.director_command_summary,
        continuity_guidance=base.continuity_guidance,
        frame_specific_guidance=base.frame_specific_guidance,
        composition_anchor=base.composition_anchor,
        screen_direction_guidance=base.screen_direction_guidance,
    )
    enriched_prompt = append_frame_face_integrity_prompt(
        rendered_prompt=enriched_prompt,
        mappings=context.ordered_refs,
        visual_style=getattr(base, "visual_style", None),
    )
    rendered_prompt = compose_shot_frame_rendered_prompt(
        replaced_prompt=enriched_prompt,
        mappings=context.ordered_refs,
    )
    return FrameDerivedPreview(
        shot_id=base.shot_id,
        frame_type=base.frame_type.value if hasattr(base.frame_type, "value") else str(base.frame_type),
        base_prompt=normalized_base_prompt,
        rendered_prompt=rendered_prompt,
        selected_guidance=selected_guidance,
        dropped_guidance=dropped_guidance,
        selected_guidance_details=selected_guidance_details,
        dropped_guidance_details=dropped_guidance_details,
        images=[mapping.file_id for mapping in context.ordered_refs],
        mappings=context.ordered_refs,
    )


def to_rendered_shot_frame_prompt_read(
    *,
    derived: FrameDerivedPreview,
) -> RenderedShotFramePromptRead:
    return RenderedShotFramePromptRead(
        base_prompt=derived.base_prompt,
        rendered_prompt=derived.rendered_prompt,
        selected_guidance=derived.selected_guidance,
        dropped_guidance=derived.dropped_guidance,
        selected_guidance_details=derived.selected_guidance_details,
        dropped_guidance_details=derived.dropped_guidance_details,
        images=derived.images,
        mappings=derived.mappings,
    )
