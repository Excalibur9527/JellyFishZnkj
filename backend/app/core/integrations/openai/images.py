"""OpenAI Images API（generations / edits）。"""

from __future__ import annotations

import io
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

                        for i, ref in enumerate(resolved_input.images):
                            if ref.image_url and ref.image_url.startswith("data:"):
                                header, encoded = ref.image_url.split(",", 1)
                                img_bytes = base64.b64decode(encoded)
                                mime = re.search(r"data:([^;]+)", header)
                                mime_type = mime.group(1) if mime else "image/png"
                                # 压缩参考图：转为 JPEG 且长边不超过 1024px，减少上传体积
                                img_bytes, mime_type = _compress_ref_image(img_bytes, mime_type, max_side=1024)
                                ext = "jpg" if "jpeg" in mime_type or "jpg" in mime_type else mime_type.split("/")[-1]
                                multipart.append(
                                    (f"image[{i}]", (f"ref_{i}.{ext}", img_bytes, mime_type))
                                )
                            elif ref.image_url:
                                img_resp = await client.get(ref.image_url)
                                img_resp.raise_for_status()
                                mime_type = img_resp.headers.get("content-type", "image/png").split(";")[0]
                                img_bytes, mime_type = _compress_ref_image(img_resp.content, mime_type, max_side=1024)
                                ext = "jpg" if "jpeg" in mime_type or "jpg" in mime_type else mime_type.split("/")[-1]
                                multipart.append(
                                    (f"image[{i}]", (f"ref_{i}.{ext}", img_bytes, mime_type))
                                )

                        edit_headers = {"Authorization": f"Bearer {cfg.api_key}"}
                        url = f"{base_url}/images/edits"
                        t0 = time.perf_counter()
                        log_image_http_request(
                            provider="openai",
                            method="POST",
                            url=url,
                            headers=edit_headers,
                            body_log=json_dumps_for_log({"prompt": resolved_input.prompt, "n": resolved_input.n, "image_count": len(resolved_input.images)}),
                        )
                        r = await client.post(url, headers=edit_headers, files=multipart)
                    else:
                        body = {
                            "prompt": resolved_input.prompt,
                            "n": resolved_input.n,
                            "response_format": "b64_json",
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
