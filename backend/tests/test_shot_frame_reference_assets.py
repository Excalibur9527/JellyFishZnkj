"""分镜帧独立参考资产配置测试。"""

from app.models.studio import ShotFrameImage
from app.services.studio.shot_frames import frame_reference_assets_match, set_reference_assets


def test_frame_reference_assets_are_isolated_by_frame_slot() -> None:
    """更新首帧参考资产时不得改变关键帧或尾帧配置。"""

    first = ShotFrameImage(shot_detail_id="shot-1", frame_type="first", format="png")
    key = ShotFrameImage(shot_detail_id="shot-1", frame_type="key", format="png")
    last = ShotFrameImage(shot_detail_id="shot-1", frame_type="last", format="png")
    key.reference_assets = [{"type": "scene", "id": "scene-1", "file_id": "file-scene"}]
    last.reference_assets = [{"type": "prop", "id": "prop-1", "file_id": "file-prop"}]

    set_reference_assets(
        first,
        reference_assets=[{"type": "character", "id": "character-1", "file_id": "file-character"}],
    )

    assert first.reference_assets == [
        {"type": "character", "id": "character-1", "file_id": "file-character"}
    ]
    assert key.reference_assets == [{"type": "scene", "id": "scene-1", "file_id": "file-scene"}]
    assert last.reference_assets == [{"type": "prop", "id": "prop-1", "file_id": "file-prop"}]


def test_frame_reference_assets_reject_cross_frame_payload() -> None:
    """当前帧配置角色图时，不得接受另一帧的服装图生成请求。"""

    frame = ShotFrameImage(shot_detail_id="shot-1", frame_type="key", format="png")
    frame.reference_assets = [
        {"type": "character", "id": "character-1", "file_id": "file-character"}
    ]

    assert frame_reference_assets_match(
        frame,
        requested_assets=[
            {"type": "character", "id": "character-1", "file_id": "file-character"}
        ],
    )
    assert not frame_reference_assets_match(
        frame,
        requested_assets=[{"type": "costume", "id": "costume-1", "file_id": "file-costume"}],
    )


def test_frame_reference_assets_allow_same_asset_with_refreshed_file_id() -> None:
    """同一资产换了最新图片时，当前帧可接受新 file_id 并在生成时刷新快照。"""

    frame = ShotFrameImage(shot_detail_id="shot-1", frame_type="first", format="png")
    frame.reference_assets = [
        {"type": "character", "id": "character-1", "file_id": "old-character-file"}
    ]

    assert frame_reference_assets_match(
        frame,
        requested_assets=[
            {"type": "character", "id": "character-1", "file_id": "new-character-file"}
        ],
    )
