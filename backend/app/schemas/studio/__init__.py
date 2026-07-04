"""Studio 模块 schemas。"""

from app.schemas.studio.files import (
    FileCreate,
    FileDetailRead,
    FileRead,
    FileTypeEnum,
    FileUpdate,
    FileUsageRead,
    FileUsageWrite,
)
from app.schemas.studio.audio import (
    AttachShotAudioFileRequest,
    GenerateShotTtsRequest,
    GenerateShotTtsResponse,
    MuxShotVideoAudioRequest,
    MuxShotVideoAudioResponse,
    ShotAudioClipRead,
    ShotAudioClipTypeEnum,
)
from app.schemas.studio.prompts import (
    PromptCategoryOptionRead,
    PromptTemplateCreate,
    PromptTemplateRead,
    PromptTemplateUpdate,
)

from app.schemas.studio.entity_existence import (
    EntityNameExistenceCheckRequest,
    EntityNameExistenceCheckResponse,
    EntityNameExistenceItem,
)
