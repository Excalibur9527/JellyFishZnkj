from __future__ import annotations

from pathlib import Path

import pytest

from app.core import storage


@pytest.mark.asyncio
async def test_storage_upload_download_delete_uses_local_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(storage.settings, "s3_bucket_name", None)
    monkeypatch.setattr(storage, "_LOCAL_STORAGE_DIR", tmp_path)

    info = await storage.upload_file(
        key="files/test-image.png",
        data=b"png-bytes",
        content_type="image/png",
    )

    assert info.key == "local-file:files/test-image.png"
    assert info.url == ""

    downloaded = await storage.download_file(key=info.key)
    assert downloaded == b"png-bytes"

    meta = await storage.get_file_info(key=info.key)
    assert meta.size == len(b"png-bytes")
    assert meta.content_type == "image/png"

    await storage.delete_file(key=info.key)
    assert not (tmp_path / "files" / "test-image.png").exists()
