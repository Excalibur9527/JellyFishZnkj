"""可灵 AI 通过 34ku 中转的视频生成适配器。

POST  {base_url}/kling/v1/videos/omni-video
GET   {base_url}/kling/v1/videos/omni-video/{task_id}

鉴权：Bearer API Key（34ku 密钥，无需 JWT）
响应格式：与可灵原生 API 相同（code / data.task_id / data.task_status）
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from app.core.contracts.provider import ProviderConfig
from app.core.contracts.video_generation import VideoGenerationInput

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://juhe.34ku.com"

_DURATION_MAP: dict[int, str] = {5: "5", 10: "10"}
_DEFAULT_DURATION = "5"


def _resolve_base(cfg: ProviderConfig) -> str:
    return (cfg.base_url or _DEFAULT_BASE_URL).rstrip("/")


def _strip_data_prefix(value: str) -> str:
    if "base64," in value:
        return value.split("base64,", 1)[1]
    return value


def _compress_to_b64(b64_data: str, max_kb: int = 400) -> str:
    """压缩图片到目标大小，返回纯 base64（不带 data: 前缀）。"""
    import io
    from PIL import Image

    raw = _strip_data_prefix(b64_data)
    image_bytes = base64.b64decode(raw)

    if len(image_bytes) <= max_kb * 1024:
        return raw

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    quality = 82
    scale = 1.0
    for _ in range(10):
        w, h = int(img.width * scale), int(img.height * scale)
        resized = img.resize((max(w, 64), max(h, 64)), Image.LANCZOS)
        buf = io.BytesIO()
        resized.save(buf, format="JPEG", quality=quality)
        data = buf.getvalue()
        if len(data) <= max_kb * 1024:
            break
        if quality > 60:
            quality -= 10
        else:
            scale *= 0.75

    compressed = base64.b64encode(data).decode()
    logger.info("KlingProxy image: %dKB -> %dKB", len(image_bytes) // 1024, len(data) // 1024)
    return compressed


# 运镜 code → Kling camera_control 参数映射
# Kling simple 模式：horizontal/vertical/zoom/tilt/pan/roll，取值范围 [-10, 10]
_CAMERA_CONTROL_MAP: dict[str, dict[str, Any]] = {
    "STATIC":    {"type": "simple", "config": {"horizontal": 0, "vertical": 0, "zoom": 0, "tilt": 0, "pan": 0, "roll": 0}},
    "PAN":       {"type": "simple", "config": {"horizontal": 8, "vertical": 0, "zoom": 0, "tilt": 0, "pan": 0, "roll": 0}},
    "TILT":      {"type": "simple", "config": {"horizontal": 0, "vertical": 8, "zoom": 0, "tilt": 0, "pan": 0, "roll": 0}},
    "DOLLY_IN":  {"type": "simple", "config": {"horizontal": 0, "vertical": 0, "zoom": 0, "tilt": 0, "pan": 0, "roll": 0}},  # dolly 靠首尾帧控制，camera_control 留空
    "DOLLY_OUT": {"type": "simple", "config": {"horizontal": 0, "vertical": 0, "zoom": 0, "tilt": 0, "pan": 0, "roll": 0}},
    "ZOOM_IN":   {"type": "simple", "config": {"horizontal": 0, "vertical": 0, "zoom": 8, "tilt": 0, "pan": 0, "roll": 0}},
    "ZOOM_OUT":  {"type": "simple", "config": {"horizontal": 0, "vertical": 0, "zoom": -8, "tilt": 0, "pan": 0, "roll": 0}},
    "TRACK":     {"type": "simple", "config": {"horizontal": 6, "vertical": 0, "zoom": 0, "tilt": 0, "pan": 0, "roll": 0}},
    "CRANE":     {"type": "simple", "config": {"horizontal": 0, "vertical": 8, "zoom": 2, "tilt": 0, "pan": 0, "roll": 0}},
    "HANDHELD":  {"type": "simple", "config": {"horizontal": 2, "vertical": 2, "zoom": 0, "tilt": 0, "pan": 0, "roll": 0}},
    "STEADICAM": {"type": "simple", "config": {"horizontal": 4, "vertical": 0, "zoom": 0, "tilt": 0, "pan": 0, "roll": 0}},
}


async def _build_body(input_: VideoGenerationInput) -> dict[str, Any]:
    duration = _DURATION_MAP.get(input_.seconds or 5, _DEFAULT_DURATION)
    body: dict[str, Any] = {
        "model_name": (input_.model or "kling-video-o1").strip(),
        "prompt": (input_.prompt or "").strip()[:2500],
        "duration": duration,
        "mode": "std",
    }

    # 运镜参数直接传给 Kling camera_control（STATIC/DOLLY_IN/DOLLY_OUT 靠帧控制，不额外传）
    movement_code = (input_.camera_movement or "").upper().strip()
    camera_ctrl = _CAMERA_CONTROL_MAP.get(movement_code)
    if camera_ctrl and movement_code not in ("STATIC", "DOLLY_IN", "DOLLY_OUT"):
        body["camera_control"] = camera_ctrl

    # 压缩图片后以 data URL 格式传递（Kling 支持 base64 编码）
    image_list = []
    if input_.first_frame_base64:
        b64 = _compress_to_b64(input_.first_frame_base64)
        image_list.append({"image_url": b64, "type": "first_frame"})
    if input_.last_frame_base64:
        b64 = _compress_to_b64(input_.last_frame_base64)
        image_list.append({"image_url": b64, "type": "end_frame"})

    for ref_b64 in (input_.character_references or []):
        b64 = _compress_to_b64(ref_b64)
        image_list.append({"image_url": b64, "type": "reference"})

    if image_list:
        body["image_list"] = image_list
    else:
        ratio_map = {"16:9": "16:9", "9:16": "9:16", "1:1": "1:1", "4:3": "4:3", "3:4": "3:4"}
        body["aspect_ratio"] = ratio_map.get(input_.ratio or "16:9", "16:9")

    return body


class KlingProxyVideoApiAdapter:
    """可灵中转视频任务 HTTP 适配器（34ku Bearer 鉴权）。"""

    async def create_video_task(
        self,
        *,
        cfg: ProviderConfig,
        input_: VideoGenerationInput,
        timeout_s: float,
    ) -> str:
        try:
            import httpx
        except ImportError as e:
            raise RuntimeError("httpx is required") from e

        base_url = _resolve_base(cfg)
        endpoint = f"{base_url}/kling/v1/videos/omni-video"
        headers = {
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
        }
        body = await _build_body(input_)
        logger.info("KlingProxy create: endpoint=%s model=%s", endpoint, body.get("model_name"))

        # connect_timeout 短，read_timeout 长（大 body 上传慢）
        timeout = httpx.Timeout(connect=30.0, read=120.0, write=120.0, pool=30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(endpoint, headers=headers, json=body)
            if not r.is_success:
                raise RuntimeError(f"可灵中转创建失败: {r.status_code} {r.text[:500]}")
            data: dict[str, Any] = r.json()
            logger.info("KlingProxy create response: %s", str(data)[:300])
            if data.get("code", 0) != 0:
                raise RuntimeError(f"可灵中转 API 错误: code={data.get('code')} msg={data.get('message')}")
            task_id = str((data.get("data") or {}).get("task_id") or "")
            if not task_id:
                raise RuntimeError(f"可灵中转缺少 task_id: {data!r}")
            return task_id

    async def get_video_task(
        self,
        *,
        cfg: ProviderConfig,
        task_id: str,
        timeout_s: float,
    ) -> dict[str, Any]:
        try:
            import httpx
        except ImportError as e:
            raise RuntimeError("httpx is required") from e

        base_url = _resolve_base(cfg)
        url = f"{base_url}/kling/v1/videos/omni-video/{task_id}"
        headers = {"Authorization": f"Bearer {cfg.api_key}"}

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            data: dict[str, Any] = r.json()
            logger.info("KlingProxy poll: %s", str(data)[:300])

        if data.get("code", 0) != 0:
            raise RuntimeError(f"可灵中转轮询错误: code={data.get('code')} msg={data.get('message')}")

        task_data = data.get("data") or {}
        status = str(task_data.get("task_status") or "")
        video_url = ""
        if status == "succeed":
            result = task_data.get("task_result") or {}
            videos = result.get("videos") or []
            if videos and isinstance(videos[0], dict):
                video_url = videos[0].get("url") or ""

        return {
            "status": status,
            "video_url": video_url,
            "error_message": task_data.get("task_status_msg") or "",
            "_raw": data,
        }
