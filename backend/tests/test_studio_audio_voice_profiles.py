from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.models.studio import (
    Actor,
    CameraAngle,
    CameraMovement,
    CameraShotType,
    Character,
    Chapter,
    Project,
    ProjectStyle,
    ProjectVisualStyle,
    FileItem,
    FileType,
    FileUsageKind,
    Shot,
    ShotAudioClip,
    ShotDetail,
    ShotDialogLine,
)
from app.schemas.studio.audio import GenerateShotTtsRequest, MuxShotVideoAudioRequest
from app.services.studio import audio as audio_service


async def _build_session() -> tuple[AsyncSession, object]:
    """创建独立内存库，避免音频声线测试污染开发数据。"""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return session_local(), engine


async def _seed_dialogue_graph(db: AsyncSession) -> None:
    """准备一个含演员、角色和两条对白的镜头，用于验证分角色声线。"""

    db.add_all(
        [
            Project(
                id="p1",
                name="项目一",
                description="",
                style=ProjectStyle.real_people_city,
                visual_style=ProjectVisualStyle.live_action,
            ),
            Chapter(id="c1", project_id="p1", index=1, title="第一章"),
            Actor(
                id="actor_a",
                name="演员甲",
                description="",
                tags=[],
                style=ProjectStyle.real_people_city,
                visual_style=ProjectVisualStyle.live_action,
                voice_profile={"local_say": {"voice": "Tingting", "rate": 170}},
            ),
            Actor(
                id="actor_b",
                name="演员乙",
                description="",
                tags=[],
                style=ProjectStyle.real_people_city,
                visual_style=ProjectVisualStyle.live_action,
                voice_profile={"voice": "Sinji", "rate": 145},
            ),
            Character(
                id="char_a",
                project_id="p1",
                name="艾铃",
                description="",
                style=ProjectStyle.real_people_city,
                visual_style=ProjectVisualStyle.live_action,
                actor_id="actor_a",
                voice_profile={},
            ),
            Character(
                id="char_b",
                project_id="p1",
                name="谢砚之",
                description="",
                style=ProjectStyle.real_people_city,
                visual_style=ProjectVisualStyle.live_action,
                actor_id="actor_b",
                voice_profile={"local_say": {"voice": "Meijia", "rate": 190}},
            ),
            Shot(id="s1", chapter_id="c1", index=1, title="镜头一", script_excerpt="艾铃与谢砚之对话。"),
            ShotDetail(
                id="s1",
                camera_shot=CameraShotType.ms,
                angle=CameraAngle.eye_level,
                movement=CameraMovement.static,
                duration=4,
                mood_tags=[],
                atmosphere="",
                vfx_type="NONE",
                vfx_note="",
                description="",
                action_beats=[],
            ),
            ShotDialogLine(
                shot_detail_id="s1",
                index=0,
                text="你终于来了。",
                speaker_character_id="char_a",
                speaker_name="艾铃",
            ),
            ShotDialogLine(
                shot_detail_id="s1",
                index=1,
                text="我一直都在。",
                speaker_character_id="char_b",
                speaker_name="谢砚之",
            ),
        ]
    )
    await db.commit()


@pytest.mark.asyncio
async def test_generate_tts_uses_character_voice_then_actor_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    """TTS 应按对白说话人解析声线：角色配置优先，演员配置兜底。"""

    db, engine = await _build_session()

    def fake_require_executable(name: str, _install_hint: str) -> str:
        return f"/usr/bin/{name}"

    def fake_run_checked_command(args: list[str]) -> None:
        if "-o" in args:
            Path(args[args.index("-o") + 1]).write_bytes(b"aiff")
            return
        Path(args[-1]).write_bytes(b"m4a")

    async def fake_upload_file(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(key=kwargs["key"])

    monkeypatch.setattr(audio_service, "_require_executable", fake_require_executable)
    monkeypatch.setattr(audio_service, "_run_checked_command", fake_run_checked_command)
    monkeypatch.setattr(audio_service, "_read_audio_duration_ms", lambda _path: 1000)
    monkeypatch.setattr(audio_service.storage, "upload_file", fake_upload_file)

    async with db:
        await _seed_dialogue_graph(db)

        clips = await audio_service.generate_tts_for_shot(
            db,
            shot_id="s1",
            body=GenerateShotTtsRequest(overwrite=True),
        )

        stored = (await db.execute(select(ShotAudioClip).order_by(ShotAudioClip.start_ms.asc()))).scalars().all()
        assert [clip.voice for clip in clips] == ["Tingting", "Meijia"]
        assert [clip.voice for clip in stored] == ["Tingting", "Meijia"]

    await engine.dispose()


@pytest.mark.asyncio
async def test_generate_tts_request_voice_overrides_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    """请求显式传 voice 时作为临时覆盖，用于试听或批量试音。"""

    db, engine = await _build_session()

    def fake_run_checked_command(args: list[str]) -> None:
        if "-o" in args:
            Path(args[args.index("-o") + 1]).write_bytes(b"aiff")
            return
        Path(args[-1]).write_bytes(b"m4a")

    async def fake_upload_file(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(key=kwargs["key"])

    monkeypatch.setattr(audio_service, "_require_executable", lambda name, _hint: f"/usr/bin/{name}")
    monkeypatch.setattr(audio_service, "_run_checked_command", fake_run_checked_command)
    monkeypatch.setattr(audio_service, "_read_audio_duration_ms", lambda _path: 1000)
    monkeypatch.setattr(audio_service.storage, "upload_file", fake_upload_file)

    async with db:
        await _seed_dialogue_graph(db)
        clips = await audio_service.generate_tts_for_shot(
            db,
            shot_id="s1",
            body=GenerateShotTtsRequest(voice="Kyoko", overwrite=True),
        )

        assert [clip.voice for clip in clips] == ["Kyoko", "Kyoko"]

    await engine.dispose()


@pytest.mark.asyncio
async def test_mux_video_audio_preserves_video_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    """有声视频合成应以原视频时长为准，避免音频较短时裁掉视频画面。"""

    db, engine = await _build_session()
    captured_command: list[str] = []

    def fake_run_checked_command(args: list[str]) -> None:
        captured_command[:] = args
        Path(args[-1]).write_bytes(b"muxed-video")

    async def fake_download_file(*, key: str) -> bytes:
        return f"bytes:{key}".encode()

    async def fake_upload_file(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(key=kwargs["key"])

    monkeypatch.setattr(audio_service, "_require_executable", lambda name, _hint: f"/usr/bin/{name}")
    monkeypatch.setattr(audio_service, "_run_checked_command", fake_run_checked_command)
    monkeypatch.setattr(audio_service, "_read_media_duration_ms", lambda _path: 4000)
    monkeypatch.setattr(audio_service.storage, "download_file", fake_download_file)
    monkeypatch.setattr(audio_service.storage, "upload_file", fake_upload_file)

    async with db:
        db.add_all(
            [
                Project(
                    id="p1",
                    name="项目一",
                    description="",
                    style=ProjectStyle.real_people_city,
                    visual_style=ProjectVisualStyle.live_action,
                ),
                Chapter(id="c1", project_id="p1", index=1, title="第一章"),
                FileItem(id="video-1", type=FileType.video, name="原视频", thumbnail="", storage_key="video.mp4"),
                FileItem(id="audio-1", type=FileType.audio, name="对白音频", thumbnail="", storage_key="audio.m4a"),
                Shot(
                    id="s1",
                    chapter_id="c1",
                    index=1,
                    title="镜头一",
                    script_excerpt="艾铃说话。",
                    generated_video_file_id="video-1",
                ),
                ShotAudioClip(
                    shot_id="s1",
                    file_id="audio-1",
                    clip_type="dialogue",
                    label="对白音频",
                    start_ms=0,
                    end_ms=1000,
                    volume=100,
                    track=1,
                    provider="local_say",
                    voice="Tingting",
                    usage_kind=FileUsageKind.generated_audio.value,
                ),
            ]
        )
        await db.commit()

        file_item = await audio_service.mux_shot_video_with_audio(
            db,
            shot_id="s1",
            body=MuxShotVideoAudioRequest(),
        )

        assert file_item.id
        assert "-shortest" not in captured_command
        assert "-t" in captured_command
        assert captured_command[captured_command.index("-t") + 1] == "4.000"

    await engine.dispose()
