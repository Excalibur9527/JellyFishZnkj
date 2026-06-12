"""OpenAI Videos API / DashScope 视频生成适配器。

当模型名以已知 DashScope 前缀开头时（如 happyhorse），自动使用
DashScope 原生端点 `/api/v1/services/aigc/video-generation/video-synthesis`
和轮询端点 `/api/v1/tasks/{task_id}`。
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.integrations.openai.video_payload import build_create_video_body, pick_input_reference
from app.core.contracts.provider import ProviderConfig
from app.core.contracts.video_generation import VideoGenerationInput

logger = logging.getLogger(__name__)

# 需要使用 DashScope 原生格式的模型前缀（小写）
_DASHSCOPE_MODEL_PREFIXES = ("happyhorse",)


def _is_dashscope_model(model: str | None) -> bool:
    m = (model or "").strip().lower()
    return any(m.startswith(p) for p in _DASHSCOPE_MODEL_PREFIXES)


class OpenAIVideoApiAdapter:
    """OpenAI 视频 / DashScope 视频：自动按模型选择端点。"""

    async def create_video(
        self,
        *,
        cfg: ProviderConfig,
        input_: VideoGenerationInput,
        timeout_s: float,
    ) -> str:
        if _is_dashscope_model(input_.model):
            return await self._create_dashscope(cfg=cfg, input_=input_, timeout_s=timeout_s)
        return await self._create_openai(cfg=cfg, input_=input_, timeout_s=timeout_s)

    async def get_video(
        self,
        *,
        cfg: ProviderConfig,
        video_id: str,
        timeout_s: float,
    ) -> dict[str, Any]:
        # task_id 前缀区分（DashScope task_id 以 task_ 或 uuid 开头）
        # 简单策略：如果 cfg 的 base_url 包含 DashScope 端点标识，则用 DashScope 轮询
        # 统一通过存储在 video_id 里的前缀标识
        if video_id.startswith("ds:"):
            real_id = video_id[3:]
            return await self._poll_dashscope(cfg=cfg, task_id=real_id, timeout_s=timeout_s)
        return await self._poll_openai(cfg=cfg, video_id=video_id, timeout_s=timeout_s)

    # ── OpenAI 原生路径 ─────────────────────────────────────────────────────────

    async def _create_openai(
        self, *, cfg: ProviderConfig, input_: VideoGenerationInput, timeout_s: float
    ) -> str:
        try:
            import httpx
        except ImportError as e:
            raise RuntimeError("httpx is required for video generation tasks") from e

        base_url = (cfg.base_url or "https://api.openai.com/v1").rstrip("/")
        headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}
        body = build_create_video_body(input_)

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.post(f"{base_url}/videos", headers=headers, json=body)
            if not r.is_success:
                raise RuntimeError(f"视频生成失败: {r.status_code} {r.text[:500]}")
            data: dict[str, Any] = r.json()
            video_id = str(data.get("id") or "")
            if not video_id:
                raise RuntimeError(f"OpenAI /videos missing id: {data!r}")
            return video_id

    async def _poll_openai(
        self, *, cfg: ProviderConfig, video_id: str, timeout_s: float
    ) -> dict[str, Any]:
        try:
            import httpx
        except ImportError as e:
            raise RuntimeError("httpx is required for video generation tasks") from e

        base_url = (cfg.base_url or "https://api.openai.com/v1").rstrip("/")
        headers = {"Authorization": f"Bearer {cfg.api_key}"}

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            rr = await client.get(f"{base_url}/videos/{video_id}", headers=headers)
            rr.raise_for_status()
            data = rr.json()
            logger.info("OpenAI video poll response: %s", data)
            return data

    # ── DashScope 原生路径 ──────────────────────────────────────────────────────

    async def _create_dashscope(
        self, *, cfg: ProviderConfig, input_: VideoGenerationInput, timeout_s: float
    ) -> str:
        """调用 DashScope 视频合成接口，返回 'ds:{task_id}' 格式 ID。"""
        try:
            import httpx
        except ImportError as e:
            raise RuntimeError("httpx is required for video generation tasks") from e

        base_url = (cfg.base_url or "https://dashscope.aliyuncs.com").rstrip("/")
        endpoint = f"{base_url}/api/v1/services/aigc/video-generation/video-synthesis"
        headers = {
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }

        # 构建 media 列表（优先首帧）
        ref = pick_input_reference(input_)
        media_list: list[dict[str, str]] = []
        if ref:
            image_url = ref.get("image_url") or ""
            if image_url:
                media_list.append({"type": "first_frame", "url": image_url})

        body: dict[str, Any] = {
            "model": input_.model or "happyhorse-1.0-i2v",
            "input": {
                "prompt": (input_.prompt or "").strip(),
                **({"media": media_list} if media_list else {}),
            },
            "parameters": {
                "resolution": "720P",
                **({"duration": int(input_.seconds)} if input_.seconds is not None else {}),
            },
        }

        logger.info("DashScope create video body (media_count=%d): model=%s", len(media_list), input_.model)

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.post(endpoint, headers=headers, json=body)
            if not r.is_success:
                raise RuntimeError(f"DashScope 视频生成失败: {r.status_code} {r.text[:500]}")
            data: dict[str, Any] = r.json()
            logger.info("DashScope create response: %s", data)
            task_id = str((data.get("output") or {}).get("task_id") or "")
            if not task_id:
                raise RuntimeError(f"DashScope 缺少 task_id: {data!r}")
            return f"ds:{task_id}"

    async def _poll_dashscope(
        self, *, cfg: ProviderConfig, task_id: str, timeout_s: float
    ) -> dict[str, Any]:
        try:
            import httpx
        except ImportError as e:
            raise RuntimeError("httpx is required for video generation tasks") from e

        base_url = (cfg.base_url or "https://dashscope.aliyuncs.com").rstrip("/")
        url = f"{base_url}/api/v1/tasks/{task_id}"
        headers = {"Authorization": f"Bearer {cfg.api_key}"}

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            rr = await client.get(url, headers=headers)
            rr.raise_for_status()
            data = rr.json()
            logger.info("DashScope poll response: %s", str(data)[:300])
            # 归一化为 OpenAI 风格，方便上层统一处理
            output = data.get("output") or {}
            task_status = str(output.get("task_status") or "").upper()
            # PENDING/RUNNING → queued/running；SUCCEEDED/FAILED → succeeded/failed
            status_map = {
                "PENDING": "queued",
                "RUNNING": "running",
                "SUCCEEDED": "succeeded",
                "FAILED": "failed",
            }
            normalized_status = status_map.get(task_status, task_status.lower())
            video_url = output.get("video_url") or output.get("url") or ""
            return {
                "id": task_id,
                "status": normalized_status,
                "video_url": video_url,
                "_raw": data,
            }
