"""镜头音频相关 schemas。

这些 DTO 用于把“对白配音/BGM/音效”从视频生成黑盒中拆出来，便于先试听、
再合成，避免视频已经生成成功但没有声音时无法定位原因。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.studio.files import FileRead


class ShotAudioClipTypeEnum(str, Enum):
    """镜头音频片段类型。"""

    dialogue = "dialogue"
    voice_over = "voice_over"
    bgm = "bgm"
    sfx = "sfx"


class GenerateShotTtsRequest(BaseModel):
    """为镜头对白生成 TTS 音频的请求。"""

    voice: str | None = Field(None, description="macOS say 声音名；为空使用系统默认声音")
    rate: int | None = Field(None, ge=80, le=320, description="语速，传给 say -r；为空使用系统默认")
    overwrite: bool = Field(False, description="是否清理本镜头旧的 local_say 对白音频片段后重新生成")
    dialogue_line_ids: list[int] | None = Field(None, description="可选：仅为指定对白行生成；为空表示全部对白行")


class ShotAudioClipRead(BaseModel):
    """镜头音频片段读取模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    shot_id: str
    file_id: str
    dialogue_line_id: int | None
    clip_type: ShotAudioClipTypeEnum
    label: str
    start_ms: int
    end_ms: int
    volume: int
    track: int
    provider: str
    voice: str
    usage_kind: str
    file: FileRead | None = Field(None, description="关联音频文件")


class GenerateShotTtsResponse(BaseModel):
    """镜头 TTS 生成结果。"""

    clips: list[ShotAudioClipRead] = Field(default_factory=list, description="本次生成的音频片段")
    message: str = Field("success", description="结果说明")


class MuxShotVideoAudioRequest(BaseModel):
    """将镜头当前视频与音频片段合成为有声视频的请求。"""

    output_name: str | None = Field(None, description="可选输出文件名")


class AttachShotAudioFileRequest(BaseModel):
    """把一个已上传音频文件绑定为镜头音频片段。"""

    file_id: str = Field(..., description="已上传的音频文件 ID")
    clip_type: ShotAudioClipTypeEnum = Field(ShotAudioClipTypeEnum.bgm, description="音频片段类型")
    label: str | None = Field(None, description="展示名称；为空时使用文件名")
    start_ms: int = Field(0, ge=0, description="镜头内起始时间（毫秒）")
    end_ms: int | None = Field(None, ge=0, description="镜头内结束时间；为空时暂用 0 表示待检测")
    volume: int = Field(100, ge=0, le=200, description="音量百分比")
    track: int = Field(2, ge=1, description="音轨序号")


class MuxShotVideoAudioResponse(BaseModel):
    """有声视频合成结果。"""

    file: FileRead = Field(..., description="合成后的有声视频文件")
