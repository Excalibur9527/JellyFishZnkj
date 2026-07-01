"""image_task_* services 单测。"""

from __future__ import annotations

import base64
import struct
from types import SimpleNamespace
import zlib

import pytest
from fastapi import HTTPException

from app.models.studio import (
    Actor,
    ActorImage,
    AssetViewAngle,
    Character,
    CharacterImage,
    Costume,
    FileItem,
    ShotFrameType,
)
from app.schemas.studio.shots import ShotLinkedAssetItem
from app.services.studio.generation.asset_image import build_base as asset_base
from app.services.studio.generation.frame.build_base import build_frame_base_draft
from app.services.studio.generation.frame.build_context import build_frame_context
from app.services.studio.generation.frame.derive_preview import derive_frame_preview
from app.services.studio.image_task_references import (
    pick_ordered_ref_file_ids,
    resolve_reference_file_ids_and_names_from_linked_items,
    resolve_reference_image_refs_by_file_ids,
    resolve_shot_frame_reference_image_refs,
)
from app.services.studio.image_task_validation import (
    validate_actor_image,
    validate_asset_image_and_relation_type,
    validate_character_image,
)


class _FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeExecuteResult:
    def __init__(self, rows=None, single=None):
        self._rows = rows or []
        self._single = single

    def scalars(self):
        return _FakeScalarResult(self._rows)

    def scalar_one_or_none(self):
        return self._single


class _FakeColumn:
    def is_not(self, _value):
        return self

    def desc(self):
        return self

    def __eq__(self, _other):
        return self


class _FakeImageModel:
    actor_id = _FakeColumn()
    file_id = _FakeColumn()
    created_at = _FakeColumn()
    id = _FakeColumn()


class _FakeStmt:
    def where(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self


class _FakeDB:
    def __init__(self, mapping=None, execute_results=None):
        self.mapping = mapping or {}
        self.execute_results = list(execute_results or [])

    async def get(self, model, entity_id):
        return self.mapping.get((model, entity_id))

    async def execute(self, *_args, **_kwargs):
        if not self.execute_results:
            return _FakeExecuteResult()
        return self.execute_results.pop(0)


def _make_solid_png(color: tuple[int, int, int]) -> bytes:
    """生成单色 PNG 测试图，便于断言未被类型化处理改动。"""

    return _encode_rgb_png(width=12, height=12, pixel_at=lambda _x, _y: color)


def _make_costume_like_png() -> bytes:
    """生成带上方“脸”和下方“服装”的 PNG，用于验证服装去身份处理。"""

    def _pixel_at(x: int, y: int) -> tuple[int, int, int]:
        if 28 <= x <= 72 and y <= 31:
            return 210, 160, 120
        if y >= 55:
            return 20, 140, 90
        return 240, 232, 220

    return _encode_rgb_png(width=100, height=100, pixel_at=_pixel_at)


def _decode_png_data_url(data_url: str) -> list[list[tuple[int, int, int]]]:
    """解码测试中的 PNG data URL，方便检查像素变化。"""

    _, encoded = data_url.split(",", 1)
    return _decode_rgb_png(base64.b64decode(encoded))


def _encode_rgb_png(*, width: int, height: int, pixel_at) -> bytes:
    """用标准库生成测试 PNG，避免测试依赖外部图片库。"""

    raw_rows: list[bytes] = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            row.extend(pixel_at(x, y))
        raw_rows.append(bytes([0]) + bytes(row))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(b"".join(raw_rows)))
        + _png_chunk(b"IEND", b"")
    )


def _decode_rgb_png(content: bytes) -> list[list[tuple[int, int, int]]]:
    """解码测试生成的无过滤 RGB PNG。"""

    offset = 8
    width = height = 0
    idat_parts: list[bytes] = []
    while offset + 8 <= len(content):
        length = struct.unpack(">I", content[offset : offset + 4])[0]
        chunk_type = content[offset + 4 : offset + 8]
        chunk_data = content[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, *_rest = struct.unpack(">IIBBBBB", chunk_data)
            assert bit_depth == 8
            assert color_type == 2
        elif chunk_type == b"IDAT":
            idat_parts.append(chunk_data)
    raw = zlib.decompress(b"".join(idat_parts))
    rows: list[list[tuple[int, int, int]]] = []
    stride = width * 3
    position = 0
    for _ in range(height):
        assert raw[position] == 0
        position += 1
        row = raw[position : position + stride]
        position += stride
        rows.append([tuple(row[x * 3 : x * 3 + 3]) for x in range(width)])  # type: ignore[list-item]
    return rows


def _png_chunk(chunk_type: bytes, chunk_data: bytes) -> bytes:
    """生成测试 PNG chunk。"""

    crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
    return struct.pack(">I", len(chunk_data)) + chunk_type + chunk_data + struct.pack(">I", crc)


@pytest.mark.asyncio
async def test_validate_actor_image_returns_row_when_belongs_to_actor():
    actor = SimpleNamespace(id="actor-1")
    image = SimpleNamespace(id=1, actor_id="actor-1")
    db = _FakeDB(
        mapping={
            (Actor, "actor-1"): actor,
            (ActorImage, 1): image,
        }
    )

    row = await validate_actor_image(db, actor_id="actor-1", image_id=1)

    assert row is image


@pytest.mark.asyncio
async def test_validate_asset_image_and_relation_type_rejects_invalid_asset_type():
    db = _FakeDB()

    with pytest.raises(HTTPException) as exc:
        await validate_asset_image_and_relation_type(
            db,
            asset_type="invalid",
            asset_id="asset-1",
            image_id=1,
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "asset_type must be one of: prop/scene/costume"


@pytest.mark.asyncio
async def test_validate_character_image_requires_image_id():
    character = SimpleNamespace(id="char-1")
    db = _FakeDB(mapping={(Character, "char-1"): character})

    with pytest.raises(HTTPException) as exc:
        await validate_character_image(db, character_id="char-1", image_id=None)

    assert exc.value.status_code == 400
    assert exc.value.detail == "image_id is required for character image generation"


@pytest.mark.asyncio
async def test_resolve_reference_file_ids_and_names_filters_empty_file_ids():
    items = [
        ShotLinkedAssetItem(id="a1", type="prop", name="道具一", file_id="file-1"),
        ShotLinkedAssetItem(id="a2", type="scene", name="", file_id="file-2"),
        ShotLinkedAssetItem(id="a3", type="costume", name="忽略项", file_id=""),
    ]

    file_ids, names = await resolve_reference_file_ids_and_names_from_linked_items(None, items=items)

    assert file_ids == ["file-1", "file-2"]
    assert names == ["道具一", "a2"]


@pytest.mark.asyncio
async def test_resolve_reference_image_refs_by_file_ids_returns_data_urls(monkeypatch):
    file_obj = FileItem(id="file-1", name="sample.png", storage_key="images/sample.png")
    db = _FakeDB(mapping={(FileItem, "file-1"): file_obj})

    async def _fake_download_file(*, key: str):
        assert key == "images/sample.png"
        return b"png-bytes"

    async def _fake_get_file_info(*, key: str):
        assert key == "images/sample.png"
        return SimpleNamespace(content_type="image/png")

    monkeypatch.setattr("app.services.studio.image_task_references.storage.download_file", _fake_download_file)
    monkeypatch.setattr("app.services.studio.image_task_references.storage.get_file_info", _fake_get_file_info)

    refs = await resolve_reference_image_refs_by_file_ids(db, file_ids=["file-1"])

    assert len(refs) == 1
    assert refs[0]["image_url"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_resolve_shot_frame_reference_image_refs_isolates_costume_identity(monkeypatch):
    character_file = FileItem(id="char-file", name="character.png", storage_key="images/character.png")
    costume_file = FileItem(id="costume-file", name="costume.png", storage_key="images/costume.png")
    db = _FakeDB(mapping={(FileItem, "char-file"): character_file, (FileItem, "costume-file"): costume_file})
    character_bytes = _make_solid_png((12, 34, 56))
    costume_bytes = _make_costume_like_png()

    async def _fake_download_file(*, key: str):
        if key == "images/character.png":
            return character_bytes
        if key == "images/costume.png":
            return costume_bytes
        raise AssertionError(f"unexpected key: {key}")

    async def _fake_get_file_info(*, key: str):
        assert key in {"images/character.png", "images/costume.png"}
        return SimpleNamespace(content_type="image/png")

    monkeypatch.setattr("app.services.studio.image_task_references.storage.download_file", _fake_download_file)
    monkeypatch.setattr("app.services.studio.image_task_references.storage.get_file_info", _fake_get_file_info)

    refs = await resolve_shot_frame_reference_image_refs(
        db,
        items=[
            ShotLinkedAssetItem(id="char-1", type="character", name="艾铃", file_id="char-file"),
            ShotLinkedAssetItem(id="costume-1", type="costume", name="大婚衣服", file_id="costume-file"),
        ],
    )

    assert len(refs) == 2
    assert refs[0]["image_url"] == "data:image/png;base64," + base64.b64encode(character_bytes).decode("ascii")
    isolated_costume = _decode_png_data_url(refs[1]["image_url"])
    assert isolated_costume[8][50] == isolated_costume[4][4]
    assert isolated_costume[78][50] == (20, 140, 90)


@pytest.mark.asyncio
async def test_pick_ordered_ref_file_ids_returns_requested_angle_order(monkeypatch):
    rows = [
        SimpleNamespace(file_id="file-back", view_angle=AssetViewAngle.back),
        SimpleNamespace(file_id="file-right", view_angle=AssetViewAngle.right),
        SimpleNamespace(file_id="file-front", view_angle=AssetViewAngle.front),
    ]
    db = _FakeDB(execute_results=[_FakeExecuteResult(rows=rows)])
    monkeypatch.setattr("app.services.studio.image_task_references.select", lambda *_args, **_kwargs: _FakeStmt())

    out = await pick_ordered_ref_file_ids(
        db,
        image_model=_FakeImageModel,
        parent_field_name="actor_id",
        parent_id="actor-1",
        view_angles=(AssetViewAngle.front, AssetViewAngle.right, AssetViewAngle.left),
    )

    assert out == ["file-front", "file-right"]


@pytest.mark.asyncio
async def test_build_actor_image_base_draft_front_view_returns_no_refs(monkeypatch):
    actor = SimpleNamespace(
        id="actor-1",
        name="演员A",
        description="沉稳男性",
        tags=["成熟", "都市"],
        visual_style="写实",
        style="影视",
    )
    image = SimpleNamespace(
        id=1,
        actor_id="actor-1",
        view_angle=AssetViewAngle.front,
        quality_level="high",
        format="png",
    )
    db = _FakeDB(
        mapping={
            (Actor, "actor-1"): actor,
            (ActorImage, 1): image,
        }
    )

    async def _fake_build_prompt(*_args, **_kwargs):
        return "演员渲染提示词"

    monkeypatch.setattr(asset_base, "build_prompt_with_template", _fake_build_prompt)
    monkeypatch.setattr(asset_base, "asset_prompt_category", lambda **_kwargs: "actor_front")

    draft = await asset_base.build_actor_image_base_draft(
        db,
        actor_id="actor-1",
        image_id=1,
    )

    assert draft.prompt == "演员渲染提示词"
    assert draft.default_images == []
    assert draft.image_id == 1


@pytest.mark.asyncio
async def test_build_character_image_base_draft_combines_actor_and_costume_refs(monkeypatch):
    character = SimpleNamespace(
        id="char-1",
        name="角色A",
        description="主角",
        actor_id="actor-1",
        costume_id="costume-1",
        visual_style="写实",
        style="影视",
    )
    image = SimpleNamespace(
        id=1,
        character_id="char-1",
        view_angle=AssetViewAngle.front,
        quality_level="high",
        format="png",
    )
    db = _FakeDB(
        mapping={
            (Character, "char-1"): character,
            (CharacterImage, 1): image,
            (Actor, "actor-1"): SimpleNamespace(id="actor-1"),
            (Costume, "costume-1"): SimpleNamespace(id="costume-1"),
        }
    )

    async def _fake_build_prompt(*_args, **_kwargs):
        return "角色合成提示词"

    async def _fake_pick_ordered(*_args, parent_id: str, **_kwargs):
        if parent_id == "actor-1":
            return ["actor-front", "actor-left"]
        return ["costume-front"]

    monkeypatch.setattr(asset_base, "build_prompt_with_template", _fake_build_prompt)
    monkeypatch.setattr(asset_base, "pick_ordered_ref_file_ids", _fake_pick_ordered)

    draft = await asset_base.build_character_image_base_draft(
        db,
        character_id="char-1",
        image_id=1,
    )

    assert draft.prompt == "角色合成提示词"
    assert draft.default_images == ["actor-front", "actor-left", "costume-front"]
    assert draft.image_id == 1


def test_derive_frame_preview_keeps_story_names_and_uses_stable_reference_order() -> None:
    base = build_frame_base_draft(
        shot_id="shot-1",
        frame_type=ShotFrameType.first,
        prompt="张三在雨夜中逼近李四",
        director_command_summary="必须：锁定主角视线方向；优先：保持同场景轴线稳定",
        continuity_guidance="当前镜头应承接上一镜头的动作与情绪，不要像全新场面重新开局",
        frame_specific_guidance="首帧只表现受惊瞬间，人物身体骤然僵住，动作尚未完成",
        composition_anchor="以门口灯光和主角站位作为画面重心，保持环境与人物同时可读",
        screen_direction_guidance="保持张三与李四的左右站位和对视方向稳定，避免无故翻转朝向",
    )
    context = build_frame_context(
        shot_id="shot-1",
        frame_type=ShotFrameType.first,
        items=[
            ShotLinkedAssetItem(id="char-1", type="character", name="张三", file_id="char-1-front"),
            ShotLinkedAssetItem(id="char-2", type="character", name="李四", file_id="char-2-front"),
        ],
    )

    preview = derive_frame_preview(base=base, context=context)

    assert preview.images == ["char-1-front", "char-2-front"]
    assert preview.mappings[0].token == "图1"
    assert preview.mappings[1].token == "图2"
    assert preview.selected_guidance == [
        "高优先级导演指令：必须：锁定主角视线方向；优先：保持同场景轴线稳定",
        "当前帧职责：首帧只表现受惊瞬间，人物身体骤然僵住，动作尚未完成",
        "连续性要求：当前镜头应承接上一镜头的动作与情绪，不要像全新场面重新开局",
    ]
    assert preview.dropped_guidance == [
        "构图锚点：以门口灯光和主角站位作为画面重心，保持环境与人物同时可读",
        "朝向与视线：保持张三与李四的左右站位和对视方向稳定，避免无故翻转朝向",
    ]
    assert preview.selected_guidance_details[1].reason_tag == "首帧保时序"
    assert preview.selected_guidance_details[1].reason == "当前是首帧，系统优先保留触发瞬间与未完成态约束，避免画面直接跳到后续完成动作。"
    assert preview.dropped_guidance_details[0].reason_tag == "首帧降构图"
    assert preview.dropped_guidance_details[1].reason_tag == "首帧降轴线"
    assert "高优先级导演指令：必须：锁定主角视线方向；优先：保持同场景轴线稳定" in preview.rendered_prompt
    assert "当前帧职责：首帧只表现受惊瞬间，人物身体骤然僵住，动作尚未完成" in preview.rendered_prompt
    assert "连续性要求：当前镜头应承接上一镜头的动作与情绪，不要像全新场面重新开局" in preview.rendered_prompt
    assert "构图锚点：以门口灯光和主角站位作为画面重心，保持环境与人物同时可读" not in preview.rendered_prompt
    assert "朝向与视线：保持张三与李四的左右站位和对视方向稳定，避免无故翻转朝向" not in preview.rendered_prompt
    assert "人物面部约束：如画面中有人物，必须保留清晰可辨的原创虚构人脸和完整自然五官" in preview.rendered_prompt
    assert "人物身份锁定：图1（张三）、图2（李四）共同定义各自对应角色的人物身份与脸部特征" in preview.rendered_prompt
    assert "不是生成相似演员或重新设计角色" in preview.rendered_prompt
    assert "身份判断必须以输入参考图的可见图像为准" in preview.rendered_prompt
    assert "不作为重新想象人物外貌的描述词" in preview.rendered_prompt
    assert "脸部结构、五官比例和年龄感必须与角色参考图连续一致" in preview.rendered_prompt
    assert "不要生成无脸、遮脸、背影替代、面部模糊或五官缺失" in preview.rendered_prompt
    assert "高质量影视概念参考图" in preview.rendered_prompt
    assert "避免真实摄影照片、街拍、证件照或真人抓拍质感" in preview.rendered_prompt
    assert "不要模仿任何真实个人、明星、公众人物或版权角色" in preview.rendered_prompt
    assert "张三在雨夜中逼近李四" in preview.rendered_prompt
    assert "图1在雨夜中逼近图2" not in preview.rendered_prompt
    assert "图1: 张三" in preview.rendered_prompt
    assert "图2: 李四" in preview.rendered_prompt


def test_derive_frame_preview_does_not_add_face_prompt_for_scene_only_frame() -> None:
    base = build_frame_base_draft(
        shot_id="shot-scene",
        frame_type=ShotFrameType.first,
        prompt="空旷大厅的清晨光线穿过玻璃天窗",
        director_command_summary="必须：先建立空间",
        continuity_guidance="",
        frame_specific_guidance="首帧优先表现空间关系",
        composition_anchor="以大厅纵深作为空间锚点",
        screen_direction_guidance="",
    )
    context = build_frame_context(
        shot_id="shot-scene",
        frame_type=ShotFrameType.first,
        items=[],
    )

    preview = derive_frame_preview(base=base, context=context)

    assert "空旷大厅的清晨光线" in preview.rendered_prompt
    assert "人物面部约束" not in preview.rendered_prompt


def test_derive_frame_preview_adds_typed_reference_usage_contract() -> None:
    base = build_frame_base_draft(
        shot_id="shot-contract",
        frame_type=ShotFrameType.first,
        prompt="艾铃站在婚房里，手持团扇",
        director_command_summary="必须：保持人物身份稳定",
        continuity_guidance="",
        frame_specific_guidance="首帧建立婚房空间与人物站位",
        composition_anchor="",
        screen_direction_guidance="",
    )
    context = build_frame_context(
        shot_id="shot-contract",
        frame_type=ShotFrameType.first,
        items=[
            ShotLinkedAssetItem(id="char-1", type="character", name="艾铃", file_id="char-file"),
            ShotLinkedAssetItem(id="costume-1", type="costume", name="大婚衣服", file_id="costume-file"),
            ShotLinkedAssetItem(id="scene-1", type="scene", name="婚房", file_id="scene-file"),
            ShotLinkedAssetItem(id="prop-1", type="prop", name="团扇", file_id="prop-file"),
        ],
    )

    preview = derive_frame_preview(base=base, context=context)

    assert "## 参考图使用规则" in preview.rendered_prompt
    assert "第1张输入参考图（图1，艾铃）是角色身份参考" in preview.rendered_prompt
    assert "必须保持脸型轮廓、五官比例、眼型、鼻型、嘴型、下巴轮廓、发际线和神态气质" in preview.rendered_prompt
    assert "第2张输入参考图（图2，大婚衣服）是服装参考" in preview.rendered_prompt
    assert "必须逐项保持参考服装的主色、辅色、纹样、材质和层次" in preview.rendered_prompt
    assert "即使剧情出现婚礼、嫁娶、大婚或退婚等语义，也不得把服装默认改成红色婚服" in preview.rendered_prompt
    assert "若该服装图的头脸区域被遮挡或涂抹，这是系统为避免换脸做的身份隔离处理" in preview.rendered_prompt
    assert "必须忽略该图中的人脸、发型、身体姿势、手持物、背景与场景" in preview.rendered_prompt
    assert "第3张输入参考图（图3，婚房）是场景参考" in preview.rendered_prompt
    assert "必须忽略该图中的人物、脸、服装、动作和临时道具" in preview.rendered_prompt
    assert "第4张输入参考图（图4，团扇）是道具参考" in preview.rendered_prompt
    assert "必须忽略该图中的人物、手、脸、服装、背景和摆拍环境" in preview.rendered_prompt
    assert "不同类型参考图不得互相覆盖职责" in preview.rendered_prompt
    assert "非角色参考图中若出现人脸或人物，必须视为无关信息" in preview.rendered_prompt
    assert "不得改变角色参考图确定的人脸与身份" in preview.rendered_prompt
    assert "服装参考图的颜色、款式、纹样和层次优先于剧情词、时代词与类型片常识" in preview.rendered_prompt
    assert "不得因为“大婚”“婚房”“嫁娶”等文字把服装自动改红或替换为其他婚服" in preview.rendered_prompt
    assert "人物身份锁定：图1（艾铃）共同定义各自对应角色的人物身份与脸部特征" in preview.rendered_prompt
    assert preview.rendered_prompt.index("人物身份锁定：图1（艾铃）") < preview.rendered_prompt.index("第1张输入参考图（图1，艾铃）")
    assert preview.rendered_prompt.index("人物身份锁定：图1（艾铃）") < preview.rendered_prompt.index("## 生成内容")


def test_derive_frame_preview_prioritizes_composition_for_first_frame() -> None:
    base = build_frame_base_draft(
        shot_id="shot-2",
        frame_type=ShotFrameType.first,
        prompt="主角推门进入空旷大厅",
        director_command_summary="必须：先建立空间",
        continuity_guidance="当前镜头应承接上一镜头的动作与情绪",
        frame_specific_guidance="首帧优先表现推门瞬间和人物尚未完全进入大厅的状态",
        composition_anchor="以门框、人物站位和大厅纵深作为空间锚点，优先建立环境与人物关系",
        screen_direction_guidance="保持人物朝向稳定",
    )
    context = build_frame_context(
        shot_id="shot-2",
        frame_type=ShotFrameType.first,
        items=[],
    )

    preview = derive_frame_preview(base=base, context=context)

    assert preview.selected_guidance[1] == "当前帧职责：首帧优先表现推门瞬间和人物尚未完全进入大厅的状态"
    assert preview.dropped_guidance == [
        "构图锚点：以门框、人物站位和大厅纵深作为空间锚点，优先建立环境与人物关系",
        "朝向与视线：保持人物朝向稳定",
    ]
    assert preview.selected_guidance_details[1].reason_tag == "首帧保时序"
    assert preview.selected_guidance_details[1].reason == "当前是首帧，系统优先保留触发瞬间与未完成态约束，避免画面直接跳到后续完成动作。"
    assert "当前帧职责：首帧优先表现推门瞬间和人物尚未完全进入大厅的状态" in preview.rendered_prompt
    assert "构图锚点：以门框、人物站位和大厅纵深作为空间锚点，优先建立环境与人物关系" not in preview.rendered_prompt
    assert "朝向与视线：保持人物朝向稳定" not in preview.rendered_prompt


def test_derive_frame_preview_prioritizes_screen_guidance_for_key_frame() -> None:
    base = build_frame_base_draft(
        shot_id="shot-3",
        frame_type=ShotFrameType.key,
        prompt="两人对峙，情绪到达顶点",
        director_command_summary="必须：锁定对峙张力",
        continuity_guidance="当前镜头应承接上一镜头的动作与情绪",
        frame_specific_guidance="关键帧应锁定对峙动作的峰值瞬间",
        composition_anchor="以走廊尽头和人物站位作为空间锚点，保持环境与人物同时可读",
        screen_direction_guidance="保持两人的左右站位和对视方向稳定，避免跳轴",
    )
    context = build_frame_context(
        shot_id="shot-3",
        frame_type=ShotFrameType.key,
        items=[],
    )

    preview = derive_frame_preview(base=base, context=context)

    assert preview.selected_guidance[2] == "朝向与视线：保持两人的左右站位和对视方向稳定，避免跳轴"
    assert preview.dropped_guidance == [
        "当前帧职责：关键帧应锁定对峙动作的峰值瞬间",
        "构图锚点：以走廊尽头和人物站位作为空间锚点，保持环境与人物同时可读",
    ]
    assert preview.selected_guidance_details[2].reason_tag == "关键帧保轴线"
    assert preview.selected_guidance_details[2].reason == "当前镜头更看重视线与左右轴线稳定，因此优先保留朝向与视线 guidance。"
    assert preview.dropped_guidance_details[0].reason_tag == "关键帧降峰值"
    assert "朝向与视线：保持两人的左右站位和对视方向稳定，避免跳轴" in preview.rendered_prompt
    assert "构图锚点：以走廊尽头和人物站位作为空间锚点，保持环境与人物同时可读" not in preview.rendered_prompt
    assert "当前帧职责：关键帧应锁定对峙动作的峰值瞬间" not in preview.rendered_prompt
