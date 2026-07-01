"""OpenAI Images API（generations / edits）。"""

from __future__ import annotations

import io
import json
import logging
import ssl
import time
from typing import Any

logger = logging.getLogger(__name__)

from app.core.integrations.http_logging import (
    json_dumps_for_log,
    log_image_http_request,
    log_image_http_response,
    safe_body_for_log_openai,
)
from app.core.contracts.image_generation import (
    ImageGenerationInput,
    ImageGenerationResult,
    ImageItem,
)
from app.core.contracts.provider import ProviderConfig
from app.core.integrations.image_capabilities import resolve_image_size
from app.core.integrations.openai.image_capabilities import validate_openai_image_options


class OpenAIImageApiAdapter:
    """OpenAI 图片生成 HTTP；无状态，可单测替换。"""

    async def generate(
        self,
        *,
        cfg: ProviderConfig,
        inp: ImageGenerationInput,
        timeout_s: float,
    ) -> ImageGenerationResult:
        try:
            import httpx
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("httpx is required for image generation tasks") from e

        base_url = (cfg.base_url or "https://api.openai.com/v1").rstrip("/")
        resolved_size = resolve_image_size(
            provider="openai",
            model=inp.model,
            purpose=inp.purpose,
            target_ratio=inp.target_ratio,
            resolution_profile=inp.resolution_profile,
            requested_size=inp.size,
        )
        resolved_input = inp.model_copy(update={"size": resolved_size})
        validate_openai_image_options(resolved_input)
        headers = {
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
        }

        max_attempts = 3
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                async with httpx.AsyncClient(timeout=timeout_s) as client:
                    if resolved_input.images:
                        import base64, re
                        multipart: list[tuple[str, Any]] = [
                            ("prompt", (None, resolved_input.prompt)),
                            ("n", (None, str(resolved_input.n))),
                        ]
                        if resolved_input.model:
                            multipart.append(("model", (None, resolved_input.model)))
                        if resolved_input.size:
                            multipart.append(("size", (None, resolved_input.size)))
                        input_fidelity = _resolve_edit_input_fidelity(
                            model=resolved_input.model,
                            requested=resolved_input.input_fidelity,
                        )
                        if input_fidelity:
                            multipart.append(("input_fidelity", (None, input_fidelity)))
                        multipart.extend(
                            [
                                ("stream", (None, "true")),
                                ("partial_images", (None, "1")),
                            ]
                        )

                        uploaded_ref_count = 0
                        uploaded_ref_bytes = 0
                        for i, ref in enumerate(resolved_input.images):
                            if ref.image_url and ref.image_url.startswith("data:"):
                                header, encoded = ref.image_url.split(",", 1)
                                img_bytes = base64.b64decode(encoded)
                                mime = re.search(r"data:([^;]+)", header)
                                mime_type = mime.group(1) if mime else "image/png"
                                # 压缩参考图：转为 JPEG 且长边不超过 1024px，减少上传体积
                                img_bytes, mime_type = _compress_ref_image(img_bytes, mime_type, max_side=1024)
                                ext = "jpg" if "jpeg" in mime_type or "jpg" in mime_type else mime_type.split("/")[-1]
                                uploaded_ref_count += 1
                                uploaded_ref_bytes += len(img_bytes)
                                multipart.append(
                                    ("image", (f"ref_{i}.{ext}", img_bytes, mime_type))
                                )
                            elif ref.image_url:
                                img_resp = await client.get(ref.image_url)
                                img_resp.raise_for_status()
                                mime_type = img_resp.headers.get("content-type", "image/png").split(";")[0]
                                img_bytes, mime_type = _compress_ref_image(img_resp.content, mime_type, max_side=1024)
                                ext = "jpg" if "jpeg" in mime_type or "jpg" in mime_type else mime_type.split("/")[-1]
                                uploaded_ref_count += 1
                                uploaded_ref_bytes += len(img_bytes)
                                multipart.append(
                                    ("image", (f"ref_{i}.{ext}", img_bytes, mime_type))
                                )

                        if uploaded_ref_count != len(resolved_input.images):
                            raise RuntimeError(
                                f"image edit reference upload mismatch: expected {len(resolved_input.images)}, "
                                f"uploaded {uploaded_ref_count}"
                            )

                        edit_headers = {"Authorization": f"Bearer {cfg.api_key}"}
                        url = f"{base_url}/images/edits"
                        t0 = time.perf_counter()
                        log_image_http_request(
                            provider="openai",
                            method="POST",
                            url=url,
                            headers=edit_headers,
                            body_log=json_dumps_for_log(
                                {
                                    "prompt": resolved_input.prompt,
                                    "n": resolved_input.n,
                                    "image_count": len(resolved_input.images),
                                    "uploaded_image_count": uploaded_ref_count,
                                    "uploaded_image_bytes": uploaded_ref_bytes,
                                    "multipart_image_field": "image",
                                    "input_fidelity": input_fidelity,
                                    "size": resolved_input.size,
                                }
                            ),
                        )
                        r = await client.post(url, headers=edit_headers, files=multipart)
                    else:
                        body = {
                            "prompt": resolved_input.prompt,
                            "n": resolved_input.n,
                            "response_format": "b64_json",
                            "stream": True,
                            "partial_images": 1,
                        }
                        if resolved_input.model:
                            body["model"] = resolved_input.model
                        if resolved_input.size:
                            body["size"] = resolved_input.size
                        if resolved_input.watermark is not None:
                            body["watermark"] = bool(resolved_input.watermark)

                        url = f"{base_url}/images/generations"
                        t0 = time.perf_counter()
                        log_image_http_request(
                            provider="openai",
                            method="POST",
                            url=url,
                            headers=headers,
                            body_log=json_dumps_for_log(safe_body_for_log_openai(body)),
                        )
                        r = await client.post(url, headers=headers, json=body)

                    dt_ms = int((time.perf_counter() - t0) * 1000)
                    resp_text = ""
                    try:
                        resp_text = r.text or ""
                    except Exception:  # noqa: BLE001
                        resp_text = ""
                    log_image_http_response(
                        provider="openai",
                        status_code=r.status_code,
                        elapsed_ms=dt_ms,
                        resp_headers=dict(r.headers),
                        resp_text=resp_text,
                    )

                    r.raise_for_status()
                    content_type = str(r.headers.get("content-type") or "").lower()
                    if "text/event-stream" in content_type or resp_text.lstrip().startswith("data:"):
                        return _parse_openai_images_stream(resp_text)
                    data = r.json()

                return _parse_openai_images_payload(data)

            except ssl.SSLError as exc:
                last_exc = exc
                logger.warning("image_generation SSL error on attempt %d/%d: %s", attempt + 1, max_attempts, exc)
                if attempt < max_attempts - 1:
                    await _async_sleep(2.0)
                    continue
                raise
            except Exception:
                raise

        raise last_exc  # type: ignore[misc]


def _compress_ref_image(img_bytes: bytes, mime_type: str, *, max_side: int = 1024) -> tuple[bytes, str]:
    """把参考图压缩为 JPEG、长边不超过 max_side，减少上传体积。
    若 Pillow 未安装或图片已经够小则直接返回原始数据。
    """
    try:
        from PIL import Image as PILImage
    except ImportError:
        return img_bytes, mime_type

    try:
        img = PILImage.open(io.BytesIO(img_bytes))
        w, h = img.size
        if w <= max_side and h <= max_side and not mime_type.endswith("png"):
            # 已经够小且不是 PNG，直接原样返回
            return img_bytes, mime_type
        # 按比例缩小
        if max(w, h) > max_side:
            ratio = max_side / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), PILImage.LANCZOS)
        # 转 RGB（PNG 可能有透明通道，JPEG 不支持）
        if img.mode in ("RGBA", "P", "LA"):
            bg = PILImage.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        compressed = buf.getvalue()
        logger.debug(
            "ref_image compressed: %d KB → %d KB (%.0f%%)",
            len(img_bytes) // 1024,
            len(compressed) // 1024,
            len(compressed) / len(img_bytes) * 100,
        )
        return compressed, "image/jpeg"
    except Exception as exc:  # noqa: BLE001
        logger.warning("ref_image compress failed, using original: %s", exc)
        return img_bytes, mime_type


async def _async_sleep(seconds: float) -> None:
    import asyncio
    await asyncio.sleep(seconds)


def _resolve_edit_input_fidelity(*, model: str | None, requested: str | None) -> str | None:
    """为 GPT Image 编辑请求选择参考图保真强度。

    OpenAI 的图片编辑接口提供 `input_fidelity` 来提高输入图特征匹配，
    尤其是人脸特征。分镜帧带参考图时通常需要身份一致性，因此默认使用
    high；`gpt-image-1-mini` 不支持该参数，需跳过。
    """

    normalized_model = (model or "").strip().lower()
    if normalized_model.startswith("gpt-image-1-mini"):
        return None
    value = (requested or "high").strip().lower()
    if value not in {"high", "low"}:
        return "high"
    return value


def _parse_openai_images_payload(data: dict[str, Any]) -> ImageGenerationResult:
    raw_items = data.get("data") or []
    images: list[ImageItem] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        b64 = item.get("b64_json")
        if not url and not b64:
            continue
        images.append(ImageItem(url=url, b64_json=b64))

    if not images:
        raise RuntimeError(f"OpenAI images response has no usable data: {data!r}")

    return ImageGenerationResult(
        images=images,
        provider="openai",
        provider_task_id=None,
        status=str(data.get("status") or "succeeded"),
    )


def _parse_openai_images_stream(payload: str) -> ImageGenerationResult:
    """解析 OpenAI Images SSE，优先采用 completed，缺失时采用最后一张 partial。

    流式模式让长耗时图片请求在生成过程中持续产生响应字节，避免兼容网关因
    长时间无响应而断开连接。只解析图片事件，不对断连请求进行自动重放。
    """

    completed_item: ImageItem | None = None
    latest_partial_item: ImageItem | None = None
    provider_task_id: str | None = None
    terminal_status = "succeeded"

    for raw_line in (payload or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        raw_data = line[5:].strip()
        if not raw_data or raw_data == "[DONE]":
            continue
        try:
            event = json.loads(raw_data)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue

        event_type = str(event.get("type") or "")
        provider_task_id = str(event.get("id") or provider_task_id or "") or None
        b64_json = event.get("b64_json") or event.get("partial_image_b64")
        image_url = event.get("url")
        if not b64_json and not image_url:
            continue
        item = ImageItem(
            url=str(image_url) if image_url else None,
            b64_json=str(b64_json) if b64_json else None,
        )
        if event_type.endswith(".completed"):
            completed_item = item
            terminal_status = "succeeded"
        elif event_type.endswith(".partial_image"):
            latest_partial_item = item

    image = completed_item or latest_partial_item
    if image is None:
        raise RuntimeError("OpenAI images stream ended without a usable image event")
    return ImageGenerationResult(
        images=[image],
        provider="openai",
        provider_task_id=provider_task_id,
        status=terminal_status,
    )
