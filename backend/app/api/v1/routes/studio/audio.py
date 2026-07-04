"""Studio 镜头音频接口。

音频不再隐藏在视频生成按钮背后：先生成/管理镜头音频片段，再按需合成进视频，
方便定位“视频成功但没声音”的问题。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.common import ApiResponse, success_response
from app.schemas.studio.audio import (
    AttachShotAudioFileRequest,
    GenerateShotTtsRequest,
    GenerateShotTtsResponse,
    MuxShotVideoAudioRequest,
    MuxShotVideoAudioResponse,
    ShotAudioClipRead,
)
from app.schemas.studio.files import FileRead
from app.services.studio.audio import attach_audio_file_to_shot, generate_tts_for_shot, list_audio_clips, mux_shot_video_with_audio

router = APIRouter()


@router.get(
    "/shots/{shot_id}/clips",
    response_model=ApiResponse[list[ShotAudioClipRead]],
    summary="读取镜头音频片段",
)
async def list_shot_audio_clips_api(
    shot_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[ShotAudioClipRead]]:
    """读取一个镜头当前已绑定的对白/BGM/音效片段。"""
    clips = await list_audio_clips(db, shot_id=shot_id)
    return success_response([ShotAudioClipRead.model_validate(clip) for clip in clips])


@router.post(
    "/shots/{shot_id}/tts",
    response_model=ApiResponse[GenerateShotTtsResponse],
    summary="为镜头对白生成 TTS 配音",
)
async def generate_shot_tts_api(
    shot_id: str,
    body: GenerateShotTtsRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[GenerateShotTtsResponse]:
    """把镜头中已确认的对白行转换为可试听、可合成的音频片段。"""
    clips = await generate_tts_for_shot(db, shot_id=shot_id, body=body)
    payload = GenerateShotTtsResponse(
        clips=[ShotAudioClipRead.model_validate(clip) for clip in clips],
        message=f"已生成 {len(clips)} 条配音音频",
    )
    return success_response(payload)


@router.post(
    "/shots/{shot_id}/clips",
    response_model=ApiResponse[ShotAudioClipRead],
    summary="绑定已上传音频到镜头",
)
async def attach_shot_audio_file_api(
    shot_id: str,
    body: AttachShotAudioFileRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ShotAudioClipRead]:
    """把素材库中的音频文件作为 BGM/音效/对白片段绑定到当前镜头。"""
    clip = await attach_audio_file_to_shot(db, shot_id=shot_id, body=body)
    return success_response(ShotAudioClipRead.model_validate(clip))


@router.post(
    "/shots/{shot_id}/mux-video",
    response_model=ApiResponse[MuxShotVideoAudioResponse],
    summary="将镜头音频合成进当前视频",
)
async def mux_shot_video_audio_api(
    shot_id: str,
    body: MuxShotVideoAudioRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[MuxShotVideoAudioResponse]:
    """合成有声视频；当前环境缺 ffmpeg 时会明确提示安装依赖。"""
    file_item = await mux_shot_video_with_audio(db, shot_id=shot_id, body=body)
    return success_response(MuxShotVideoAudioResponse(file=FileRead.model_validate(file_item)))
