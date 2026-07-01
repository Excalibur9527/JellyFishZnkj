from __future__ import annotations

import pytest

from app.core.contracts.image_generation import ImageGenerationInput
from app.core.contracts.provider import ProviderConfig
from app.core.tasks.image_generation_tasks import OpenAIImageGenerationTask


class _DisconnectingAdapter:
    """模拟供应商已接收请求、但返回响应前连接被中转服务断开。"""

    async def generate(self, **_kwargs):
        raise RuntimeError("Server disconnected without sending a response.")


@pytest.mark.asyncio
async def test_image_task_get_result_preserves_provider_exception() -> None:
    """图片任务不得把真实供应商异常覆盖成空结果。"""

    task = OpenAIImageGenerationTask(
        adapter=_DisconnectingAdapter(),
        provider_config=ProviderConfig(provider="openai", api_key="secret"),
        input_=ImageGenerationInput(prompt="frame"),
    )

    await task.run()

    with pytest.raises(RuntimeError, match="Server disconnected without sending a response"):
        await task.get_result()
