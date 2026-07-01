"""Files 接口响应壳测试。"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from app.api.v1.routes.studio import files as files_route
from app.core.storage import StoredFileInfo
from app.dependencies import get_db
from app.main import app
from app.models.studio import FileItem
from app.models.types import FileType
from app.services.studio.files import build_download_response


class _DummyDB:
    async def get(self, *_args, **_kwargs):
        return None

    async def delete(self, *_args, **_kwargs) -> None:
        return None

    async def flush(self) -> None:
        return None

    async def refresh(self, *_args, **_kwargs) -> None:
        return None

    def add(self, *_args, **_kwargs) -> None:
        return None


def _override_db(db: _DummyDB):
    async def _get_db() -> AsyncGenerator[_DummyDB, None]:
        yield db

    return _get_db


def test_list_files_requires_project_id_when_scope_filters_set(client: TestClient) -> None:
    db = _DummyDB()
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.get("/api/v1/studio/files", params={"chapter_title": "第一章"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json() == {
        "code": 400,
        "message": "project_id is required when chapter_title or shot_title is set",
        "data": None,
        "meta": None,
    }


def test_get_file_detail_not_found_returns_api_response(client: TestClient, monkeypatch) -> None:
    db = _DummyDB()

    async def _fake_get_file_detail(*_args, **_kwargs):
        raise HTTPException(status_code=404, detail="File not found")

    monkeypatch.setattr(files_route, "get_file_detail_service", _fake_get_file_detail)
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.get("/api/v1/studio/files/missing")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json() == {"code": 404, "message": "File not found", "data": None, "meta": None}


def test_delete_file_returns_empty_envelope(client: TestClient, monkeypatch) -> None:
    db = _DummyDB()

    async def _fake_delete_file(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(files_route, "delete_file", _fake_delete_file)
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.delete("/api/v1/studio/files/file-1")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"code": 200, "message": "success", "data": None, "meta": None}


def test_update_file_meta_returns_success_envelope(client: TestClient, monkeypatch) -> None:
    db = _DummyDB()
    now = datetime.now(UTC)
    file_item = FileItem(
        id="file-1",
        type=FileType.image,
        name="封面图",
        thumbnail="https://example.com/image.png",
        tags=["cover"],
        storage_key="files/image.png",
    )
    file_item.created_at = now
    file_item.updated_at = now

    async def _fake_update_file_meta(*_args, **_kwargs):
        return file_item

    monkeypatch.setattr(files_route, "update_file_meta_service", _fake_update_file_meta)
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        response = client.patch(
            "/api/v1/studio/files/file-1",
            json={"name": "新封面图"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert body["message"] == "success"
    assert body["data"]["id"] == "file-1"
    assert body["data"]["name"] == "封面图"


@pytest.mark.asyncio
async def test_build_download_response_uses_storage_content_type_for_inline_svg(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    file_item = FileItem(
        id="file-svg",
        type=FileType.image,
        name="占位图",
        thumbnail="data:image/svg+xml;base64,PHN2Zy8+",
        tags=[],
        storage_key="inline-svg:PHN2Zy8+",
    )
    file_item.created_at = now
    file_item.updated_at = now

    async def _fake_get_or_404(*_args, **_kwargs):
        return file_item

    async def _fake_download_file(*_args, **_kwargs) -> bytes:
        return b"<svg/>"

    async def _fake_get_file_info(*_args, **_kwargs) -> StoredFileInfo:
        return StoredFileInfo(
            key="inline-svg:PHN2Zy8+",
            url="data:image/svg+xml;base64,PHN2Zy8+",
            size=6,
            content_type="image/svg+xml",
            etag=None,
            extra=None,
        )

    monkeypatch.setattr("app.services.studio.files.get_or_404", _fake_get_or_404)
    monkeypatch.setattr("app.services.studio.files.storage.download_file", _fake_download_file)
    monkeypatch.setattr("app.services.studio.files.storage.get_file_info", _fake_get_file_info)

    response = await build_download_response(_DummyDB(), file_id="file-svg")

    assert response.media_type == "image/svg+xml"
    assert response.headers["content-disposition"].startswith("inline;")
    assert "filename*=UTF-8''%E5%8D%A0%E4%BD%8D%E5%9B%BE.svg" == response.headers["content-disposition"].split("; ", 1)[1]
