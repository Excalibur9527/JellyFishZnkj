"""可灵 AI：视频生成任务创建与查询。"""

from __future__ import annotations

from typing import Any

from app.core.contracts.provider import ProviderConfig
from app.core.contracts.video_generation import VideoGenerationInput
from app.core.integrations.kling.auth import build_kling_jwt
from app.core.integrations.kling.video_payload import build_image2video_body, build_text2video_body

_BASE_URL = "https://api.klingai.com"


def _resolve_base(cfg: ProviderConfig) -> str:
    return (cfg.base_url or _BASE_URL).rstrip("/")


def _auth_header(cfg: ProviderConfig) -> str:
    """生成 JWT Bearer token。access_key=api_key, secret_key=api_secret。"""
    access_key = (cfg.api_key or "").strip()
    secret_key = (cfg.api_secret or "").strip()
    if not access_key or not secret_key:
        raise RuntimeError("Kling 需要 api_key（Access Key）和 api_secret（Secret Key）")
    return f"Bearer {build_kling_jwt(access_key=access_key, secret_key=secret_key)}"


def _has_image_ref(input_: VideoGenerationInput) -> bool:
    return bool(input_.first_frame_base64 or input_.last_frame_base64 or input_.key_frame_base64)


class KlingVideoApiAdapter:
    """可灵视频任务 HTTP 适配器。"""

    async def create_video_task(
        self,
        *,
        cfg: ProviderConfig,
        input_: VideoGenerationInput,
        timeout_s: float,
    ) -> tuple[str, str]:
        """创建视频任务，返回 (task_id, endpoint_type: 'image2video'|'text2video')。"""
        try:
            import httpx
        except ImportError as e:
            raise RuntimeError("httpx is required for Kling video generation") from e

        base_url = _resolve_base(cfg)
        auth = _auth_header(cfg)
        headers = {"Authorization": auth, "Content-Type": "application/json"}

        use_image = _has_image_ref(input_)
        if use_image:
            endpoint = f"{base_url}/v1/videos/image2video"
            body = build_image2video_body(input_, model=input_.model)
            endpoint_type = "image2video"
        else:
            endpoint = f"{base_url}/v1/videos/text2video"
            body = build_text2video_body(input_, model=input_.model)
            endpoint_type = "text2video"

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.post(endpoint, headers=headers, json=body)
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(f"Kling create failed: {r.status_code} {r.text}") from exc

            data: dict[str, Any] = r.json()
            if data.get("code", 0) != 0:
                raise RuntimeError(f"Kling API error: code={data.get('code')} msg={data.get('message')} body={data!r}")

            task_id = str((data.get("data") or {}).get("task_id") or "")
            if not task_id:
                raise RuntimeError(f"Kling create missing task_id: {data!r}")
            return task_id, endpoint_type

    async def get_video_task(
        self,
        *,
        cfg: ProviderConfig,
        task_id: str,
        endpoint_type: str,
        timeout_s: float,
    ) -> dict[str, Any]:
        """查询任务状态。"""
        try:
            import httpx
        except ImportError as e:
            raise RuntimeError("httpx is required for Kling video generation") from e

        base_url = _resolve_base(cfg)
        auth = _auth_header(cfg)
        headers = {"Authorization": auth}
        url = f"{base_url}/v1/videos/{endpoint_type}/{task_id}"

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            return r.json()
