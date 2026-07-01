"""图片 integrations：httpx MockTransport 单测（不发起真实网络请求）。"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.core.integrations.openai.images import OpenAIImageApiAdapter
from app.core.integrations.volcengine.images import VolcengineImageApiAdapter
from app.core.contracts.image_generation import ImageGenerationInput, InputImageRef
from app.core.contracts.provider import ProviderConfig
from app.core.integrations.image_capabilities import (
    ImageModelCapability,
    clear_image_model_capability_overrides,
    register_image_model_capability,
)


def _patch_httpx_client(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    """让各 adapter 内 `import httpx` 后使用的 AsyncClient 走 MockTransport。"""

    real_client = httpx.AsyncClient

    def factory(**kwargs: object) -> httpx.AsyncClient:
        timeout = kwargs.get("timeout", 60.0)
        return real_client(transport=transport, timeout=timeout)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_openai_image_adapter_generations(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.content.decode()
        assert request.headers.get("authorization", "").startswith("Bearer ")
        return httpx.Response(
            200,
            json={"data": [{"url": "https://cdn.example.com/1.png"}], "status": "succeeded"},
        )

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))
    cfg = ProviderConfig(provider="openai", api_key="sk-test", base_url="https://api.openai.com/v1")
    inp = ImageGenerationInput(prompt="hello", n=1, watermark=False)
    result = await OpenAIImageApiAdapter().generate(cfg=cfg, inp=inp, timeout_s=30.0)
    assert captured["path"].endswith("/images/generations")
    body = json.loads(captured["body"])
    assert body["prompt"] == "hello"
    assert body["watermark"] is False
    assert result.provider == "openai"
    assert result.images[0].url == "https://cdn.example.com/1.png"


@pytest.mark.asyncio
async def test_openai_image_adapter_edits_when_references(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        """分别模拟参考图下载和图片编辑接口响应。"""
        if request.method == "GET":
            return httpx.Response(200, content=b"reference-image", headers={"content-type": "image/png"})
        captured["body"] = request.content.decode()
        assert request.url.path.endswith("/images/edits")
        return httpx.Response(200, json={"data": [{"b64_json": "abc"}]})

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))
    cfg = ProviderConfig(provider="openai", api_key="sk-test")
    inp = ImageGenerationInput(
        prompt="edit me",
        model="gpt-image-2",
        n=1,
        watermark=True,
        images=[InputImageRef(image_url="https://example.com/ref.png")],
    )
    result = await OpenAIImageApiAdapter().generate(cfg=cfg, inp=inp, timeout_s=30.0)
    assert 'name="prompt"' in captured["body"]
    assert "edit me" in captured["body"]
    assert 'name="image[]"' in captured["body"]
    assert 'name="stream"' in captured["body"]
    assert 'name="partial_images"' in captured["body"]
    assert 'name="input_fidelity"' not in captured["body"]
    assert result.images[0].b64_json == "abc"


@pytest.mark.asyncio
async def test_openai_image_adapter_uploads_four_references_as_repeated_image_array_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """GPT Image 2 应把四类参考图全部作为官方 image[] 文件字段上传。"""

    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode("latin1")
        assert request.url.path.endswith("/images/edits")
        return httpx.Response(200, json={"data": [{"b64_json": "abc"}]})

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))
    cfg = ProviderConfig(provider="openai", api_key="sk-test")
    tiny_png_data_url = "data:image/png;base64," + base64.b64encode(b"fake-png-bytes").decode("ascii")
    inp = ImageGenerationInput(
        prompt="use character, costume, scene and prop references",
        model="gpt-image-2",
        n=1,
        images=[
            InputImageRef(image_url=tiny_png_data_url),
            InputImageRef(image_url=tiny_png_data_url),
            InputImageRef(image_url=tiny_png_data_url),
            InputImageRef(image_url=tiny_png_data_url),
        ],
    )

    result = await OpenAIImageApiAdapter().generate(cfg=cfg, inp=inp, timeout_s=30.0)

    assert captured["body"].count('name="image[]"') == 4
    assert 'name="image"' not in captured["body"]
    assert 'name="input_fidelity"' not in captured["body"]
    assert result.images[0].b64_json == "abc"


@pytest.mark.asyncio
async def test_openai_image_adapter_uploads_mask_with_edit_references(monkeypatch: pytest.MonkeyPatch) -> None:
    """图片局部编辑应额外上传 mask，且 mask 不计入参考图数量。"""

    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode("latin1")
        assert request.url.path.endswith("/images/edits")
        return httpx.Response(200, json={"data": [{"b64_json": "abc"}]})

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))
    cfg = ProviderConfig(provider="openai", api_key="sk-test")
    tiny_png_data_url = "data:image/png;base64," + base64.b64encode(b"fake-png-bytes").decode("ascii")
    mask_png_data_url = "data:image/png;base64," + base64.b64encode(b"fake-mask-png").decode("ascii")
    inp = ImageGenerationInput(
        prompt="correct only the masked face area",
        model="gpt-image-2",
        images=[InputImageRef(image_url=tiny_png_data_url), InputImageRef(image_url=tiny_png_data_url)],
        mask=InputImageRef(image_url=mask_png_data_url),
    )

    await OpenAIImageApiAdapter().generate(cfg=cfg, inp=inp, timeout_s=30.0)

    assert captured["body"].count('name="image[]"') == 2
    assert 'name="mask"' in captured["body"]
    assert b"fake-mask-png".decode("latin1") in captured["body"]


@pytest.mark.asyncio
async def test_openai_image_adapter_keeps_gpt_image_2_reference_bytes_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GPT Image 2 参考图不得被预先缩图或转成有损 JPEG。"""

    captured: dict[str, bytes] = {}
    original_png = b"\x89PNG\r\n\x1a\nidentity-details-must-remain"

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(200, json={"data": [{"b64_json": "abc"}]})

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))
    cfg = ProviderConfig(provider="openai", api_key="sk-test")
    inp = ImageGenerationInput(
        prompt="preserve identity",
        model="gpt-image-2",
        images=[
            InputImageRef(
                image_url="data:image/png;base64," + base64.b64encode(original_png).decode("ascii")
            )
        ],
    )

    await OpenAIImageApiAdapter().generate(cfg=cfg, inp=inp, timeout_s=30.0)

    assert original_png in captured["body"]


@pytest.mark.asyncio
async def test_openai_image_adapter_skips_input_fidelity_for_unsupported_mini_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """gpt-image-1-mini 不支持 input_fidelity，适配器不应传该字段。"""

    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode("latin1")
        assert request.url.path.endswith("/images/edits")
        return httpx.Response(200, json={"data": [{"b64_json": "abc"}]})

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))
    cfg = ProviderConfig(provider="openai", api_key="sk-test")
    tiny_png_data_url = "data:image/png;base64," + base64.b64encode(b"fake-png-bytes").decode("ascii")
    inp = ImageGenerationInput(
        prompt="edit with mini",
        model="gpt-image-1-mini",
        images=[InputImageRef(image_url=tiny_png_data_url)],
    )

    await OpenAIImageApiAdapter().generate(cfg=cfg, inp=inp, timeout_s=30.0)

    assert 'name="image"' in captured["body"]
    assert 'name="input_fidelity"' not in captured["body"]


@pytest.mark.asyncio
async def test_openai_image_adapter_rejects_when_any_reference_cannot_be_uploaded(monkeypatch: pytest.MonkeyPatch) -> None:
    """只要存在无法展开成图片文件的参考项，就拒绝继续提交给供应商。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"request should not be sent, got path={request.url.path}")

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))
    cfg = ProviderConfig(provider="openai", api_key="sk-test")
    inp = ImageGenerationInput(
        prompt="must use all references",
        n=1,
        images=[InputImageRef(file_id="file-only-ref")],
    )

    with pytest.raises(RuntimeError) as exc_info:
        await OpenAIImageApiAdapter().generate(cfg=cfg, inp=inp, timeout_s=30.0)

    assert "reference upload mismatch" in str(exc_info.value)


@pytest.mark.asyncio
async def test_openai_image_adapter_parses_streamed_edit_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """流式图片编辑应采用 completed 事件并返回最终图片。"""

    def handler(request: httpx.Request) -> httpx.Response:
        """模拟参考图下载及 SSE 图片编辑结果。"""
        if request.method == "GET":
            return httpx.Response(200, content=b"reference-image", headers={"content-type": "image/png"})
        stream_body = "\n".join(
            [
                'data: {"type":"image_edit.partial_image","b64_json":"partial","partial_image_index":0}',
                "",
                'data: {"type":"image_edit.completed","b64_json":"final","id":"image-task-1"}',
                "",
                "data: [DONE]",
            ]
        )
        return httpx.Response(
            200,
            text=stream_body,
            headers={"content-type": "text/event-stream"},
        )

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))
    cfg = ProviderConfig(provider="openai", api_key="sk-test")
    inp = ImageGenerationInput(
        prompt="stream edit",
        n=1,
        images=[InputImageRef(image_url="https://example.com/ref.png")],
    )

    result = await OpenAIImageApiAdapter().generate(cfg=cfg, inp=inp, timeout_s=30.0)

    assert result.images[0].b64_json == "final"
    assert result.provider_task_id == "image-task-1"


@pytest.mark.asyncio
async def test_openai_image_adapter_returns_completed_event_before_gateway_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """收到完整图片事件后应立即返回，不受随后发生的网关断连影响。"""

    class DisconnectAfterCompleted(httpx.AsyncByteStream):
        """模拟网关先发 completed，再在关闭连接时抛出协议错误。"""

        async def __aiter__(self):
            yield b'data: {"type":"image_edit.completed","b64_json":"final","id":"image-task-2"}\n\n'
            raise httpx.RemoteProtocolError("server disconnected")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=DisconnectAfterCompleted(),
            headers={"content-type": "text/event-stream"},
        )

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))
    cfg = ProviderConfig(provider="openai", api_key="sk-test")
    ref = "data:image/png;base64," + base64.b64encode(b"reference").decode("ascii")
    inp = ImageGenerationInput(
        prompt="return before disconnect",
        model="gpt-image-2",
        images=[InputImageRef(image_url=ref)],
    )

    result = await OpenAIImageApiAdapter().generate(cfg=cfg, inp=inp, timeout_s=30.0)

    assert result.images[0].b64_json == "final"
    assert result.provider_task_id == "image-task-2"


@pytest.mark.asyncio
async def test_openai_image_adapter_retries_transport_disconnect_before_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """请求尚未返回响应就被网关断开时，应自动重试而不是立刻失败。"""

    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        return httpx.Response(
            200,
            text='data: {"type":"image_edit.completed","b64_json":"final","id":"image-task-retry"}\n\n',
            headers={"content-type": "text/event-stream"},
        )

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))
    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("app.core.integrations.openai.images._async_sleep", _no_sleep)
    cfg = ProviderConfig(provider="openai", api_key="sk-test")
    ref = "data:image/png;base64," + base64.b64encode(b"reference").decode("ascii")
    inp = ImageGenerationInput(
        prompt="retry disconnect",
        model="gpt-image-2",
        images=[InputImageRef(image_url=ref)],
    )

    result = await OpenAIImageApiAdapter().generate(cfg=cfg, inp=inp, timeout_s=30.0)

    assert attempts == 2
    assert result.images[0].b64_json == "final"
    assert result.provider_task_id == "image-task-retry"


@pytest.mark.asyncio
async def test_openai_image_adapter_resolves_video_reference_size(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"data": [{"url": "https://cdn.example.com/ref.png"}]})

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))
    clear_image_model_capability_overrides(provider="openai")
    register_image_model_capability(
        provider="openai",
        model_prefix="gpt-image-video-ref",
        capability=ImageModelCapability(
            supported_ratios={"16:9"},
            ratio_size_profiles={"16:9": {"standard": "1792x1024"}},
        ),
    )
    cfg = ProviderConfig(provider="openai", api_key="sk-test", base_url="https://api.openai.com/v1")
    inp = ImageGenerationInput(
        prompt="video ref",
        model="gpt-image-video-ref-1",
        target_ratio="16:9",
        resolution_profile="standard",
        purpose="video_reference",
    )
    try:
        await OpenAIImageApiAdapter().generate(cfg=cfg, inp=inp, timeout_s=30.0)
        body = json.loads(captured["body"])
        assert body["size"] == "1792x1024"
    finally:
        clear_image_model_capability_overrides(provider="openai")


@pytest.mark.asyncio
async def test_volcengine_image_adapter_generations(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/images/generations")
        payload = json.loads(request.content.decode())
        assert payload["prompt"] == "火山"
        assert payload["n"] == 1
        assert payload["watermark"] is True
        assert payload["size"] == "1600x2848"
        return httpx.Response(
            200,
            json={
                "data": [{"image_url": "https://volc.example/v.mp4"}],
                "id": "task-xyz",
                "status": "succeeded",
            },
        )

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))
    cfg = ProviderConfig(provider="volcengine", api_key="ak-test")
    inp = ImageGenerationInput(
        prompt="火山",
        n=1,
        seed=42,
        watermark=True,
        target_ratio="9:16",
        resolution_profile="standard",
        purpose="video_reference",
    )
    result = await VolcengineImageApiAdapter().generate(cfg=cfg, inp=inp, timeout_s=30.0)
    assert result.provider == "volcengine"
    assert result.provider_task_id == "task-xyz"
    assert result.images[0].url == "https://volc.example/v.mp4"


@pytest.mark.asyncio
async def test_openai_image_adapter_rejects_unsupported_watermark(monkeypatch: pytest.MonkeyPatch) -> None:
    """当能力配置不支持 watermark 时，adapter 在发请求前直接拒绝。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"request should not be sent, got path={request.url.path}")

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))
    clear_image_model_capability_overrides(provider="openai")
    register_image_model_capability(
        provider="openai",
        model_prefix="gpt-image-no-wm",
        capability=ImageModelCapability(supports_watermark=False),
    )
    cfg = ProviderConfig(provider="openai", api_key="sk-test", base_url="https://api.openai.com/v1")
    inp = ImageGenerationInput(prompt="hello", model="gpt-image-no-wm-1", n=1, watermark=True)
    try:
        with pytest.raises(ValueError) as exc_info:
            await OpenAIImageApiAdapter().generate(cfg=cfg, inp=inp, timeout_s=30.0)
        assert "watermark is not supported" in str(exc_info.value)
    finally:
        clear_image_model_capability_overrides(provider="openai")
