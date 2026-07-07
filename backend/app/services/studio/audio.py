"""镜头音频服务。

当前阶段先补齐“对白 -> TTS 音频文件 -> 镜头音频片段”的闭环；
视频混音依赖 ffmpeg，因此这里也提供明确的依赖检查，避免无声视频问题继续
以“生成失败/没有提示”的方式暴露给用户。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from anyio import to_thread
from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import storage
from app.models.studio import Character, Chapter, FileItem, FileType, FileUsageKind, Shot, ShotAudioClip, ShotDialogLine
from app.schemas.studio.audio import AttachShotAudioFileRequest, GenerateShotTtsRequest, MuxShotVideoAudioRequest
from app.services.common import entity_not_found, get_or_404
from app.services.studio.file_usages import upsert_file_usage

_LOCAL_TTS_PROVIDER = "local_say"


@dataclass(frozen=True)
class ResolvedTtsVoice:
    """单条对白最终采用的 TTS 声线。

    `voice` 与 `rate` 是当前本机 `say` 供应商可直接消费的参数；
    `source` 记录声线来源，方便后续排查是角色覆盖、演员继承还是默认声音。
    """

    voice: str
    rate: int | None
    source: str


def _require_executable(name: str, install_hint: str) -> str:
    """查找本机命令行工具，缺失时返回清晰的业务错误。"""
    path = shutil.which(name)
    if not path:
        raise HTTPException(status_code=501, detail=f"当前环境缺少 {name}，{install_hint}")
    return path


def _run_checked_command(args: list[str]) -> None:
    """在线程中执行外部命令，失败时保留 stderr 便于定位。"""
    try:
        subprocess.run(args, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or exc.stdout or "").strip()
        raise HTTPException(status_code=500, detail=message or f"命令执行失败：{args[0]}") from exc


def _read_audio_duration_ms(path: Path) -> int:
    """读取音频时长；若 afinfo 不可用或解析失败，则返回 0 交给调用方兜底。"""
    afinfo = shutil.which("afinfo")
    if not afinfo:
        return 0
    try:
        result = subprocess.run([afinfo, str(path)], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError:
        return 0
    match = re.search(r"estimated duration:\s*([0-9.]+)\s*sec", result.stdout)
    if not match:
        return 0
    return max(1, int(float(match.group(1)) * 1000))


def _read_media_duration_ms(path: Path) -> int:
    """读取音视频媒体时长。

    混音阶段必须以原视频时长为准：音频较短时不能裁掉画面，音频较长时也
    不能把镜头视频拖成长尾空画面。`ffprobe` 随 ffmpeg 安装，缺失或解析
    失败时返回 0，让调用方退化为不额外限制时长。
    """

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        return 0
    try:
        seconds = float((result.stdout or "").strip())
    except ValueError:
        return 0
    return max(1, int(seconds * 1000))


def _clip_type_for_line(line: ShotDialogLine) -> str:
    """根据对白模式映射音频片段类型，旁白和画外音不混成普通对白。"""
    mode = str(line.line_mode or "").upper()
    if "VOICE_OVER" in mode or "OFF_SCREEN" in mode:
        return "voice_over"
    return "dialogue"


def _normalize_dialogue_name(value: str | None) -> str:
    """归一化对白说话人名称，用于从提取结果回查角色。"""

    return re.sub(r"\s+", "", str(value or "").strip())


def _read_local_say_profile(profile: object) -> tuple[str, int | None]:
    """从角色/演员 voice_profile 中读取本机 say 供应商参数。

    兼容两种写法：
    - `{"local_say": {"voice": "Tingting", "rate": 180}}`
    - `{"voice": "Tingting", "rate": 180}`

    这样现在能用本机 TTS，后续云 TTS 也可以在同一字段里增加供应商配置。
    """

    if not isinstance(profile, dict):
        return "", None
    provider_block = profile.get(_LOCAL_TTS_PROVIDER)
    source = provider_block if isinstance(provider_block, dict) else profile
    voice = str(source.get("voice") or source.get("voice_id") or "").strip()
    rate_raw = source.get("rate")
    try:
        rate = int(rate_raw) if rate_raw not in (None, "") else None
    except (TypeError, ValueError):
        rate = None
    if rate is not None:
        rate = min(320, max(80, rate))
    return voice, rate


def _voice_from_character(character: Character | None) -> ResolvedTtsVoice:
    """按“角色声线优先，演员声线兜底”的规则解析 TTS 声线。"""

    if character is None:
        return ResolvedTtsVoice(voice="", rate=None, source="default")
    character_voice, character_rate = _read_local_say_profile(getattr(character, "voice_profile", None))
    if character_voice or character_rate is not None:
        return ResolvedTtsVoice(voice=character_voice, rate=character_rate, source=f"character:{character.id}")
    actor = getattr(character, "actor", None)
    actor_voice, actor_rate = _read_local_say_profile(getattr(actor, "voice_profile", None))
    if actor_voice or actor_rate is not None:
        return ResolvedTtsVoice(voice=actor_voice, rate=actor_rate, source=f"actor:{getattr(actor, 'id', '')}")
    return ResolvedTtsVoice(voice="", rate=None, source="default")


async def _resolve_voice_by_dialogue_line(
    db: AsyncSession,
    *,
    project_id: str,
    lines: list[ShotDialogLine],
) -> dict[int, ResolvedTtsVoice]:
    """为每条对白解析角色/演员声线。

    优先使用 `speaker_character_id` 精确匹配；没有角色 ID 时，用
    `speaker_name` 在当前项目角色库中匹配。返回值以对白行 ID 为 key。
    """

    speaker_ids = {line.speaker_character_id for line in lines if line.speaker_character_id}
    speaker_names = {str(line.speaker_name or "").strip() for line in lines if str(line.speaker_name or "").strip()}
    if not speaker_ids and not speaker_names:
        return {line.id: ResolvedTtsVoice(voice="", rate=None, source="default") for line in lines}

    filters = []
    if speaker_ids:
        filters.append(Character.id.in_(speaker_ids))
    if speaker_names:
        filters.append(Character.name.in_(speaker_names))
    stmt = (
        select(Character)
        .options(selectinload(Character.actor))
        .where(Character.project_id == project_id)
        .where(or_(*filters))
    )
    characters = list((await db.execute(stmt)).scalars().all())
    by_id = {character.id: character for character in characters}
    by_name = {_normalize_dialogue_name(character.name): character for character in characters}

    resolved: dict[int, ResolvedTtsVoice] = {}
    for line in lines:
        character = None
        if line.speaker_character_id:
            character = by_id.get(line.speaker_character_id)
        if character is None:
            character = by_name.get(_normalize_dialogue_name(line.speaker_name))
        resolved[line.id] = _voice_from_character(character)
    return resolved


async def list_audio_clips(db: AsyncSession, *, shot_id: str) -> list[ShotAudioClip]:
    """读取镜头已生成/绑定的全部音频片段。"""
    stmt = (
        select(ShotAudioClip)
        .options(selectinload(ShotAudioClip.file))
        .where(ShotAudioClip.shot_id == shot_id)
        .order_by(ShotAudioClip.track.asc(), ShotAudioClip.start_ms.asc(), ShotAudioClip.id.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def generate_tts_for_shot(
    db: AsyncSession,
    *,
    shot_id: str,
    body: GenerateShotTtsRequest,
) -> list[ShotAudioClip]:
    """按镜头已确认对白生成本机 TTS 音频。

    生成策略：
    - 一条对白生成一个 m4a 文件，便于后续单独试听/替换；
    - 若请求未显式指定 voice，则按“对白说话人 -> 角色 -> 演员”解析声线；
    - 片段时间优先使用真实音频时长，镜头总时长不足时仍保留自然顺序；
    - 本阶段使用 macOS `say` + `afconvert`，后续可替换为云 TTS 供应商。
    """
    say = _require_executable("say", "无法使用本机 TTS；请在 macOS 环境运行，或后续配置云 TTS 供应商。")
    afconvert = _require_executable("afconvert", "无法把 TTS 输出转换为 m4a 音频。")

    shot = await get_or_404(db, Shot, shot_id, detail=entity_not_found("Shot"))
    chapter = await get_or_404(db, Chapter, shot.chapter_id, detail=entity_not_found("Chapter"))

    stmt = (
        select(ShotDialogLine)
        .where(ShotDialogLine.shot_detail_id == shot_id)
        .order_by(ShotDialogLine.index.asc(), ShotDialogLine.id.asc())
    )
    if body.dialogue_line_ids:
        stmt = stmt.where(ShotDialogLine.id.in_(body.dialogue_line_ids))
    lines = [line for line in (await db.execute(stmt)).scalars().all() if (line.text or "").strip()]
    if not lines:
        raise HTTPException(status_code=400, detail="当前镜头没有已确认对白，无法生成配音。请先在分镜编辑页确认或新增对白。")
    voices_by_line = await _resolve_voice_by_dialogue_line(db, project_id=chapter.project_id, lines=lines)

    if body.overwrite:
        old_stmt = select(ShotAudioClip).where(
            ShotAudioClip.shot_id == shot_id,
            ShotAudioClip.provider == _LOCAL_TTS_PROVIDER,
            ShotAudioClip.clip_type.in_(["dialogue", "voice_over"]),
        )
        for old_clip in (await db.execute(old_stmt)).scalars().all():
            await db.delete(old_clip)
        await db.flush()

    created: list[ShotAudioClip] = []
    cursor_ms = 0
    with tempfile.TemporaryDirectory(prefix="jellyfish-tts-") as tmp:
        tmp_dir = Path(tmp)
        for line in lines:
            text = line.text.strip()
            resolved_voice = voices_by_line.get(line.id, ResolvedTtsVoice(voice="", rate=None, source="default"))
            effective_voice = (body.voice or resolved_voice.voice or "").strip()
            effective_rate = body.rate if body.rate is not None else resolved_voice.rate
            stem = f"{shot_id}-{line.id}-{uuid.uuid4().hex}"
            aiff_path = tmp_dir / f"{stem}.aiff"
            m4a_path = tmp_dir / f"{stem}.m4a"

            say_args = [say, "-o", str(aiff_path), "--data-format=LEF32@22050"]
            if effective_voice:
                say_args.extend(["-v", effective_voice])
            if effective_rate:
                say_args.extend(["-r", str(effective_rate)])
            say_args.append(text)

            await to_thread.run_sync(_run_checked_command, say_args)
            await to_thread.run_sync(
                _run_checked_command,
                [afconvert, "-f", "m4af", "-d", "aac", str(aiff_path), str(m4a_path)],
            )

            audio_bytes = await to_thread.run_sync(m4a_path.read_bytes)
            file_id = str(uuid.uuid4())
            display_name = f"{shot.title or shot.index} - {line.speaker_name or '对白'} {line.index + 1}"
            info = await storage.upload_file(
                key=f"generated-audio/shots/{shot_id}/{file_id}.m4a",
                data=audio_bytes,
                content_type="audio/mp4",
                extra_args={"ACL": "public-read"},
            )
            file_item = FileItem(
                id=file_id,
                type=FileType.audio,
                name=display_name,
                thumbnail="",
                tags=["tts", "dialogue"],
                storage_key=info.key,
            )
            db.add(file_item)
            await db.flush()
            await upsert_file_usage(
                db,
                file_id=file_id,
                project_id=chapter.project_id,
                chapter_id=chapter.id,
                shot_id=shot_id,
                usage_kind=FileUsageKind.generated_audio,
                source_ref=f"tts:{shot_id}:{line.id}",
            )

            duration_ms = await to_thread.run_sync(_read_audio_duration_ms, m4a_path)
            if duration_ms <= 0:
                duration_ms = max(800, int(len(text) * 180))
            start_ms = cursor_ms
            end_ms = start_ms + duration_ms
            cursor_ms = end_ms + 180

            clip = ShotAudioClip(
                shot_id=shot_id,
                file_id=file_id,
                dialogue_line_id=line.id,
                clip_type=_clip_type_for_line(line),
                label=display_name,
                start_ms=start_ms,
                end_ms=end_ms,
                volume=100,
                track=1,
                provider=_LOCAL_TTS_PROVIDER,
                voice=effective_voice,
                usage_kind=FileUsageKind.generated_audio.value,
            )
            db.add(clip)
            created.append(clip)

    await db.commit()
    created_ids = [clip.id for clip in created]
    if not created_ids:
        return []
    stmt = (
        select(ShotAudioClip)
        .options(selectinload(ShotAudioClip.file))
        .where(ShotAudioClip.id.in_(created_ids))
        .order_by(ShotAudioClip.start_ms.asc(), ShotAudioClip.id.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def attach_audio_file_to_shot(
    db: AsyncSession,
    *,
    shot_id: str,
    body: AttachShotAudioFileRequest,
) -> ShotAudioClip:
    """把已上传的音频文件绑定到镜头音轨。

    这个入口服务于“上传音频”按钮：上传文件只负责创建 FileItem，
    绑定入口负责说明这个音频在当前镜头里从哪里开始播放、是什么类型。
    """
    await get_or_404(db, Shot, shot_id, detail=entity_not_found("Shot"))
    file_item = await get_or_404(db, FileItem, body.file_id, detail=entity_not_found("File"))
    if file_item.type != FileType.audio:
        raise HTTPException(status_code=400, detail="只能把音频文件绑定到镜头音轨。")
    end_ms = body.end_ms if body.end_ms is not None else 0
    clip = ShotAudioClip(
        shot_id=shot_id,
        file_id=file_item.id,
        dialogue_line_id=None,
        clip_type=body.clip_type.value,
        label=body.label or file_item.name,
        start_ms=body.start_ms,
        end_ms=end_ms,
        volume=body.volume,
        track=body.track,
        provider="upload",
        voice="",
        usage_kind=FileUsageKind.upload.value,
    )
    db.add(clip)
    await db.commit()
    stmt = select(ShotAudioClip).options(selectinload(ShotAudioClip.file)).where(ShotAudioClip.id == clip.id)
    return (await db.execute(stmt)).scalars().one()


async def mux_shot_video_with_audio(
    db: AsyncSession,
    *,
    shot_id: str,
    body: MuxShotVideoAudioRequest,
) -> FileItem:
    """将镜头视频和音频片段合成为有声视频。

    当前运行环境没有 ffmpeg 时会明确报错；等 ffmpeg 可用后，这个函数会成为
    真正的视频混音入口，而不是让用户在视频供应商侧碰运气。
    """
    ffmpeg = _require_executable("ffmpeg", "无法把音频合成进视频。请先安装 ffmpeg，例如：brew install ffmpeg。")
    shot = await get_or_404(db, Shot, shot_id, detail=entity_not_found("Shot"))
    if not shot.generated_video_file_id:
        raise HTTPException(status_code=400, detail="当前镜头还没有已生成视频，无法合成音频。")
    chapter = await get_or_404(db, Chapter, shot.chapter_id, detail=entity_not_found("Chapter"))
    video_file = await get_or_404(db, FileItem, shot.generated_video_file_id, detail=entity_not_found("File"))
    audio_clips = await list_audio_clips(db, shot_id=shot_id)
    if not audio_clips:
        raise HTTPException(status_code=400, detail="当前镜头还没有音频片段，请先生成配音或添加音频。")

    with tempfile.TemporaryDirectory(prefix="jellyfish-mux-") as tmp:
        tmp_dir = Path(tmp)
        video_path = tmp_dir / "input.mp4"
        output_path = tmp_dir / "output.mp4"
        video_bytes = await storage.download_file(key=video_file.storage_key)
        await to_thread.run_sync(video_path.write_bytes, video_bytes)
        video_duration_ms = await to_thread.run_sync(_read_media_duration_ms, video_path)

        input_args: list[str] = ["-y", "-i", str(video_path)]
        filter_parts: list[str] = []
        mix_labels: list[str] = []
        for idx, clip in enumerate(audio_clips, start=1):
            if clip.file is None:
                continue
            audio_path = tmp_dir / f"audio-{idx}.m4a"
            audio_bytes = await storage.download_file(key=clip.file.storage_key)
            await to_thread.run_sync(audio_path.write_bytes, audio_bytes)
            input_args.extend(["-i", str(audio_path)])
            delay = max(0, int(clip.start_ms or 0))
            volume = max(0, min(200, int(clip.volume or 100))) / 100
            label = f"a{idx}"
            filter_parts.append(f"[{idx}:a]adelay={delay}|{delay},volume={volume:.2f}[{label}]")
            mix_labels.append(f"[{label}]")

        if not mix_labels:
            raise HTTPException(status_code=400, detail="当前镜头音频片段缺少可下载音频文件，无法合成。")

        filter_parts.append(f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:duration=longest:dropout_transition=0[mix]")
        command = [
            ffmpeg,
            *input_args,
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "0:v:0",
            "-map",
            "[mix]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
        ]
        if video_duration_ms > 0:
            command.extend(["-t", f"{video_duration_ms / 1000:.3f}"])
        command.append(str(output_path))
        await to_thread.run_sync(_run_checked_command, command)
        output_bytes = await to_thread.run_sync(output_path.read_bytes)

    file_id = str(uuid.uuid4())
    info = await storage.upload_file(
        key=f"generated-videos/shots/{shot_id}/{file_id}-with-audio.mp4",
        data=output_bytes,
        content_type="video/mp4",
        extra_args={"ACL": "public-read"},
    )
    output_file = FileItem(
        id=file_id,
        type=FileType.video,
        name=body.output_name or f"{shot.title or shot.index} - 有声视频",
        thumbnail="",
        tags=["video", "audio_mux"],
        storage_key=info.key,
    )
    db.add(output_file)
    await db.flush()
    await upsert_file_usage(
        db,
        file_id=file_id,
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        shot_id=shot_id,
        usage_kind=FileUsageKind.generated_video,
        source_ref=f"audio-mux:{shot_id}:{shot.generated_video_file_id}",
    )
    shot.generated_video_file_id = file_id
    await db.commit()
    await db.refresh(output_file)
    return output_file
