"""视频生成任务（Task）：对接 OpenAI Videos API 与火山方舟内容生成。

HTTP 细节在 `app.core.integrations`；本模块保留轮询节奏与 BaseTask 契约。
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from app.core.integrations.openai.video import OpenAIVideoApiAdapter
from app.core.integrations.volcengine.video import VolcengineVideoApiAdapter
from app.core.integrations.kling.video import KlingVideoApiAdapter
from app.core.integrations.bailian.video import BailianVideoApiAdapter
from app.core.integrations.kling_proxy.video import KlingProxyVideoApiAdapter
from app.core.contracts.provider import ProviderConfig
from app.core.tasks.registry import resolve_task_adapter
from app.core.contracts.video_generation import VideoGenerationInput, VideoGenerationResult
from app.core.task_manager.types import BaseTask

__all__ = [
    "VideoGenerationInput",
    "VideoGenerationResult",
    "AbstractVideoGenerationTask",
    "OpenAIVideoGenerationTask",
    "VolcengineVideoGenerationTask",
    "KlingVideoGenerationTask",
    "BailianVideoGenerationTask",
    "KlingProxyVideoGenerationTask",
    "VideoGenerationTask",
]


class AbstractVideoGenerationTask(BaseTask, ABC):
    """视频生成任务基类：公共状态与 run/status/is_done/get_result。"""

    def __init__(
        self,
        *,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 2.0,
        timeout_s: float = 120.0,
    ) -> None:
        self._cfg = provider_config
        self._input = input_
        self._poll_interval_s = poll_interval_s
        self._timeout_s = timeout_s
        self._provider_task_id: str | None = None
        self._result: VideoGenerationResult | None = None
        self._error: str = ""

    async def _sleep_poll(self) -> None:
        await asyncio.sleep(self._poll_interval_s)

    @abstractmethod
    async def _create_task(self) -> None:
        """发起供应商创建任务请求，并设置 self._provider_task_id。"""

    @abstractmethod
    async def _poll_and_get_result(self) -> VideoGenerationResult:
        """轮询至终态并解析为 VideoGenerationResult。"""

    async def run(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any] | None:  # type: ignore[override]
        import logging as _logging
        _log = _logging.getLogger(__name__)
        try:
            await self._create_task()
            _log.info("video_run: _create_task done, provider_task_id=%r", self._provider_task_id)
            self._result = await self._poll_and_get_result()
            if self._result is not None:
                self._provider_task_id = self._result.provider_task_id
        except BaseException as exc:  # noqa: BLE001
            self._error = repr(exc) if not str(exc) else str(exc)
            _log.error("video_run exception: %r", exc, exc_info=True)
            self._result = None
        return None

    async def status(self) -> dict[str, Any]:  # type: ignore[override]
        return {
            "task": "video_generation",
            "provider": self._cfg.provider,
            "provider_task_id": self._provider_task_id,
            "done": await self.is_done(),
            "has_result": self._result is not None,
            "error": self._error,
            "status": self._result.status if self._result else None,
        }

    async def is_done(self) -> bool:  # type: ignore[override]
        return self._result is not None or bool(self._error)

    async def get_result(self) -> VideoGenerationResult | None:  # type: ignore[override]
        return self._result


class OpenAIVideoGenerationTask(AbstractVideoGenerationTask):
    """OpenAI Videos：adapter 负责 HTTP，Task 负责轮询间隔。"""

    def __init__(
        self,
        *,
        adapter: OpenAIVideoApiAdapter | None = None,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 2.0,
        timeout_s: float = 120.0,
    ) -> None:
        super().__init__(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )
        self._adapter = adapter or OpenAIVideoApiAdapter()

    async def _create_task(self) -> None:
        self._provider_task_id = await self._adapter.create_video(
            cfg=self._cfg,
            input_=self._input,
            timeout_s=self._timeout_s,
        )

    async def _poll_and_get_result(self) -> VideoGenerationResult:
        video_id = self._provider_task_id or ""
        if not video_id:
            raise RuntimeError("OpenAI poll missing provider task id")

        base_url = (self._cfg.base_url or "https://api.openai.com/v1").rstrip("/")
        is_dashscope = video_id.startswith("ds:")
        status_val = ""
        meta: dict = {}
        _consecutive_errors = 0
        _max_errors = 5
        while True:
            try:
                meta = await self._adapter.get_video(
                    cfg=self._cfg,
                    video_id=video_id,
                    timeout_s=self._timeout_s,
                )
                _consecutive_errors = 0
            except Exception as poll_exc:  # noqa: BLE001
                _consecutive_errors += 1
                if _consecutive_errors >= _max_errors:
                    raise RuntimeError(f"轮询失败（连续 {_consecutive_errors} 次网络错误）: {poll_exc}") from poll_exc
                await asyncio.sleep(5)
                continue
            status_val = str(meta.get("status") or "")
            if status_val in ("completed", "succeeded", "failed"):
                if status_val == "failed":
                    err = meta.get("error") or meta.get("_raw", {}).get("output", {}).get("message", "")
                    raise RuntimeError(f"视频生成失败: {err!r}")
                break
            await self._sleep_poll()

        # 提取视频 URL
        video_url: str | None = None
        if is_dashscope:
            video_url = meta.get("video_url") or None
        if not video_url:
            generations = meta.get("generations") or []
            if generations and isinstance(generations[0], dict):
                video_obj = generations[0].get("video") or {}
                if isinstance(video_obj, dict):
                    video_url = video_obj.get("url") or None
        if not video_url:
            video_url = meta.get("video_url") or None
        if not video_url:
            real_id = video_id[3:] if is_dashscope else video_id
            video_url = f"{base_url}/videos/{real_id}/content"

        return VideoGenerationResult(
            url=video_url,
            file_id=None,
            provider_task_id=video_id,
            provider="openai",
            status=status_val or "succeeded",
        )


class VolcengineVideoGenerationTask(AbstractVideoGenerationTask):
    """火山内容生成任务：adapter 负责 HTTP，Task 负责轮询。"""

    def __init__(
        self,
        *,
        adapter: VolcengineVideoApiAdapter | None = None,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 2.0,
        timeout_s: float = 120.0,
    ) -> None:
        super().__init__(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )
        self._adapter = adapter or VolcengineVideoApiAdapter()

    async def _create_task(self) -> None:
        self._provider_task_id = await self._adapter.create_contents_task(
            cfg=self._cfg,
            input_=self._input,
            timeout_s=self._timeout_s,
        )

    async def _poll_and_get_result(self) -> VideoGenerationResult:
        task_id = self._provider_task_id or ""
        if not task_id:
            raise RuntimeError("Volcengine poll missing provider task id")

        base_url = (self._cfg.base_url or "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
        status_val = ""
        video_url: str | None = None
        while True:
            meta = await self._adapter.get_contents_task(
                cfg=self._cfg,
                task_id=task_id,
                timeout_s=self._timeout_s,
            )
            status_val = str(meta.get("status") or "")
            content = meta.get("content") or {}
            if isinstance(content, dict):
                vu = content.get("video_url")
                if isinstance(vu, str) and vu:
                    video_url = vu
            if status_val in ("succeeded", "failed", "cancelled"):
                if status_val != "succeeded":
                    raise RuntimeError(f"Volcengine task not succeeded: status={status_val!r} meta={meta!r}")
                break
            await self._sleep_poll()

        if not video_url:
            video_url = f"{base_url}/contents/generations/tasks/{task_id}"

        return VideoGenerationResult(
            url=video_url,
            file_id=None,
            provider_task_id=task_id,
            provider="volcengine",
            status=status_val or "succeeded",
        )


class KlingVideoGenerationTask(AbstractVideoGenerationTask):
    """可灵 AI 视频生成任务。"""

    def __init__(
        self,
        *,
        adapter: KlingVideoApiAdapter | None = None,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 3.0,
        timeout_s: float = 120.0,
    ) -> None:
        super().__init__(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )
        self._adapter = adapter or KlingVideoApiAdapter()
        self._endpoint_type: str = "text2video"

    async def _create_task(self) -> None:
        task_id, endpoint_type = await self._adapter.create_video_task(
            cfg=self._cfg,
            input_=self._input,
            timeout_s=self._timeout_s,
        )
        self._provider_task_id = task_id
        self._endpoint_type = endpoint_type

    async def _poll_and_get_result(self) -> VideoGenerationResult:
        task_id = self._provider_task_id or ""
        if not task_id:
            raise RuntimeError("Kling poll missing provider task id")

        status_val = ""
        video_url: str | None = None
        while True:
            meta = await self._adapter.get_video_task(
                cfg=self._cfg,
                task_id=task_id,
                endpoint_type=self._endpoint_type,
                timeout_s=self._timeout_s,
            )
            if meta.get("code", 0) != 0:
                raise RuntimeError(f"Kling poll error: code={meta.get('code')} msg={meta.get('message')}")

            task_data = meta.get("data") or {}
            status_val = str(task_data.get("task_status") or "")
            if status_val in ("succeed", "failed"):
                if status_val == "failed":
                    raise RuntimeError(f"Kling task failed: {task_data.get('task_status_msg')!r}")
                # 提取视频 URL
                result = task_data.get("task_result") or {}
                videos = result.get("videos") or []
                if videos and isinstance(videos[0], dict):
                    video_url = videos[0].get("url") or None
                break
            await self._sleep_poll()

        if not video_url:
            raise RuntimeError(f"Kling task succeeded but no video URL: {meta!r}")

        return VideoGenerationResult(
            url=video_url,
            file_id=None,
            provider_task_id=task_id,
            provider="kling",
            status=status_val,
        )


class BailianVideoGenerationTask(AbstractVideoGenerationTask):
    """阿里百炼视频生成任务（DashScope 原生格式）。"""

    def __init__(
        self,
        *,
        adapter: BailianVideoApiAdapter | None = None,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 5.0,
        timeout_s: float = 300.0,
    ) -> None:
        super().__init__(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )
        self._adapter = adapter or BailianVideoApiAdapter()

    async def _create_task(self) -> None:
        self._provider_task_id = await self._adapter.create_video_task(
            cfg=self._cfg,
            input_=self._input,
            timeout_s=self._timeout_s,
        )

    async def _poll_and_get_result(self) -> VideoGenerationResult:
        task_id = self._provider_task_id or ""
        if not task_id:
            raise RuntimeError("Bailian poll missing provider task id")

        _consecutive_errors = 0
        _max_errors = 5
        meta: dict = {}
        status_val = ""

        while True:
            try:
                meta = await self._adapter.get_video_task(
                    cfg=self._cfg,
                    task_id=task_id,
                    timeout_s=self._timeout_s,
                )
                _consecutive_errors = 0
            except Exception as poll_exc:  # noqa: BLE001
                _consecutive_errors += 1
                if _consecutive_errors >= _max_errors:
                    raise RuntimeError(f"百炼轮询失败（连续 {_consecutive_errors} 次）: {poll_exc}") from poll_exc
                await asyncio.sleep(5)
                continue

            status_val = str(meta.get("status") or "")
            if status_val in ("succeeded", "failed"):
                if status_val == "failed":
                    raise RuntimeError(f"百炼视频生成失败: {meta.get('error_message') or meta!r}")
                break
            await self._sleep_poll()

        video_url = meta.get("video_url") or ""
        if not video_url:
            raise RuntimeError(f"百炼任务成功但无视频 URL: {meta!r}")

        return VideoGenerationResult(
            url=video_url,
            file_id=None,
            provider_task_id=task_id,
            provider="bailian",
            status=status_val,
        )


class KlingProxyVideoGenerationTask(AbstractVideoGenerationTask):
    """可灵 AI 通过 34ku 中转的视频生成任务。"""

    def __init__(
        self,
        *,
        adapter: KlingProxyVideoApiAdapter | None = None,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 3.0,
        timeout_s: float = 300.0,
    ) -> None:
        super().__init__(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )
        self._adapter = adapter or KlingProxyVideoApiAdapter()

    async def _create_task(self) -> None:
        _max_retries = 5
        for attempt in range(_max_retries):
            try:
                self._provider_task_id = await self._adapter.create_video_task(
                    cfg=self._cfg,
                    input_=self._input,
                    timeout_s=self._timeout_s,
                )
                return
            except Exception as exc:  # noqa: BLE001
                if attempt >= _max_retries - 1:
                    raise
                await asyncio.sleep(5)
                continue

    async def _poll_and_get_result(self) -> VideoGenerationResult:
        task_id = self._provider_task_id or ""
        if not task_id:
            raise RuntimeError("KlingProxy poll missing provider task id")

        meta: dict = {}
        _consecutive_errors = 0
        _max_errors = 5
        while True:
            try:
                meta = await self._adapter.get_video_task(
                    cfg=self._cfg,
                    task_id=task_id,
                    timeout_s=self._timeout_s,
                )
                _consecutive_errors = 0
            except Exception as exc:  # noqa: BLE001
                _consecutive_errors += 1
                if _consecutive_errors >= _max_errors:
                    raise RuntimeError(f"可灵中转轮询失败（连续 {_consecutive_errors} 次）: {exc}") from exc
                await asyncio.sleep(5)
                continue

            status = str(meta.get("status") or "")
            if status in ("succeed", "failed"):
                if status == "failed":
                    raise RuntimeError(f"可灵中转视频生成失败: {meta.get('error_message') or meta!r}")
                break
            await self._sleep_poll()

        video_url = meta.get("video_url") or ""
        if not video_url:
            raise RuntimeError(f"可灵中转任务成功但无视频 URL: {meta!r}")

        return VideoGenerationResult(
            url=video_url,
            file_id=None,
            provider_task_id=task_id,
            provider="kling_proxy",
            status="succeed",
        )


class VideoGenerationTask(BaseTask):
    """按 provider 分派到 OpenAI / 火山 / 可灵实现；对外构造函数签名保持不变。"""

    def __init__(
        self,
        *,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 2.0,
        timeout_s: float = 120.0,
    ) -> None:
        from app.bootstrap import bootstrap_all_registries

        bootstrap_all_registries()
        factory = resolve_task_adapter("video_generation", provider_config.provider)
        self._impl: AbstractVideoGenerationTask = factory(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )  # type: ignore[assignment]

    @staticmethod
    def _build_openai_impl(
        *,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 2.0,
        timeout_s: float = 120.0,
    ) -> AbstractVideoGenerationTask:
        return OpenAIVideoGenerationTask(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )

    @staticmethod
    def _build_volcengine_impl(
        *,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 2.0,
        timeout_s: float = 120.0,
    ) -> AbstractVideoGenerationTask:
        return VolcengineVideoGenerationTask(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )

    @staticmethod
    def _build_kling_impl(
        *,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 3.0,
        timeout_s: float = 120.0,
    ) -> AbstractVideoGenerationTask:
        return KlingVideoGenerationTask(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )

    @staticmethod
    def _build_bailian_impl(
        *,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 5.0,
        timeout_s: float = 300.0,
    ) -> AbstractVideoGenerationTask:
        return BailianVideoGenerationTask(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )

    @staticmethod
    def _build_kling_proxy_impl(
        *,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 3.0,
        timeout_s: float = 300.0,
    ) -> AbstractVideoGenerationTask:
        return KlingProxyVideoGenerationTask(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )

    async def run(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any] | None:  # type: ignore[override]
        return await self._impl.run(*args, **kwargs)

    async def status(self) -> dict[str, Any]:  # type: ignore[override]
        return await self._impl.status()

    async def is_done(self) -> bool:  # type: ignore[override]
        return await self._impl.is_done()

    async def get_result(self) -> VideoGenerationResult | None:  # type: ignore[override]
        return await self._impl.get_result()
