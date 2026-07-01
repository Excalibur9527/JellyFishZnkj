"""FileItem 创建工具测试：确认落库 key 与实际存储后端一致。"""

from __future__ import annotations

from app.core.storage import StoredFileInfo
from app.models.studio import FileItem
from app.utils import files as file_utils


class _MemorySession:
    """最小内存会话桩，用于捕获 create_file_from_url_or_b64 创建的 FileItem。"""

    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def refresh(self, _obj: object) -> None:
        return None


async def test_create_file_from_b64_persists_backend_storage_key(monkeypatch) -> None:
    """生成文件落库时使用 storage.upload_file 返回的真实 key，避免本地存储裂图。"""

    async def _fake_upload_file(**_kwargs) -> StoredFileInfo:
        return StoredFileInfo(key="local-file:generated-images/shot/ok.png", url="")

    session = _MemorySession()
    monkeypatch.setattr(file_utils.storage, "upload_file", _fake_upload_file)

    file_obj = await file_utils.create_file_from_url_or_b64(
        session,  # type: ignore[arg-type]
        b64_data="cG5nLWJ5dGVz",
        name="shot-frame",
        prefix="generated-images/shot",
    )

    assert isinstance(file_obj, FileItem)
    assert file_obj.storage_key == "local-file:generated-images/shot/ok.png"
    assert session.added == [file_obj]
