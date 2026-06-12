"""阿里百炼视频生成：DashScope 原生异步任务格式。

POST  {base_url}/api/v1/services/aigc/video-generation/video-synthesis
GET   {base_url}/api/v1/tasks/{task_id}
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.contracts.provider import ProviderConfig
from app.core.contracts.video_generation import VideoGenerationInput, _strip_optional_b64

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://juhe.34ku.com"


def _resolve_base(cfg: ProviderConfig) -> str:
    return (cfg.base_url or _DEFAULT_BASE_URL).rstrip("/")


def _build_media_list(input_: VideoGenerationInput) -> list[dict[str, str]]:
    """按优先级构建 media 列表：first_frame > key_frame > last_frame。"""
    pairs = [
        ("first_frame", input_.first_frame_base64),
        ("key_frame", input_.key_frame_base64),
        ("last_frame", input_.last_frame_base64),
    ]
    result = []
    for frame_type, raw in pairs:
        stripped = _strip_optional_b64(raw)
        if stripped:
            # 重组成 data URL
            url = raw if (raw or "").startswith("data:") else f"data:image/png;base64,{stripped}"
            result.append({"type": frame_type, "url": url})
    return result


class BailianVideoApiAdapter:
    """阿里百炼视频任务 HTTP 适配器（DashScope 原生格式）。"""

    async def create_video_task(
        self,
        *,
        cfg: ProviderConfig,
        input_: VideoGenerationInput,
        timeout_s: float,
    ) -> str:
        """创建视频任务，返回 task_id。"""
        try:
            import httpx
        except ImportError as e:
            raise RuntimeError("httpx is required for Bailian video generation") from e

        base_url = _resolve_base(cfg)
        endpoint = f"{base_url}/alibailian/api/v1/services/aigc/video-generation/video-synthesis"
        headers = {
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }

        media_list = _build_media_list(input_)
        body: dict[str, Any] = {
            "model": (input_.model or "happyhorse-1.0-i2v").strip(),
            "input": {
                "prompt": (input_.prompt or "").strip(),
                **({"media": media_list} if media_list else {}),
            },
            "parameters": {
                "resolution": "720P",
                "logo_add": False,
                **({"duration": int(input_.seconds)} if input_.seconds is not None else {}),
            },
        }

        logger.info(
            "Bailian create video: model=%s media_count=%d",
            body["model"], len(media_list),
        )

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.post(endpoint, headers=headers, json=body)
            if not r.is_success:
                raise RuntimeError(f"百炼视频创建失败: {r.status_code} {r.text[:500]}")
            data: dict[str, Any] = r.json()
            logger.info("Bailian create response: %s", str(data)[:300])
            task_id = str((data.get("output") or {}).get("task_id") or "")
            if not task_id:
                raise RuntimeError(f"百炼缺少 task_id: {data!r}")
            return task_id

    async def get_video_task(
        self,
        *,
        cfg: ProviderConfig,
        task_id: str,
        timeout_s: float,
    ) -> dict[str, Any]:
        """查询任务状态，返回归一化结果。"""
        try:
            import httpx
        except ImportError as e:
            raise RuntimeError("httpx is required for Bailian video generation") from e

        base_url = _resolve_base(cfg)
        url = f"{base_url}/alibailian/api/v1/tasks/{task_id}"
        headers = {"Authorization": f"Bearer {cfg.api_key}"}

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            data: dict[str, Any] = r.json()
            logger.info("Bailian poll: %s", str(data)[:300])

        output = data.get("output") or {}
        task_status = str(output.get("task_status") or "").upper()
        status_map = {
            "PENDING": "queued",
            "RUNNING": "running",
            "SUCCEEDED": "succeeded",
            "FAILED": "failed",
        }
        normalized = status_map.get(task_status, task_status.lower() or "queued")
        video_url = output.get("video_url") or output.get("url") or ""

        return {
            "status": normalized,
            "video_url": video_url,
            "error_message": output.get("message") or output.get("error_message") or "",
            "_raw": data,
        }
