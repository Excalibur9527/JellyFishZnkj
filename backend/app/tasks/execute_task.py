"""统一任务执行入口。

职责：
- 统一只接收业务 task_id；
- 通过 GenerationTask.task_kind + registry 找到具体 WorkerTaskExecutor；
- 按配置选择 Celery 或本地线程执行；
- 回写 executor_type / executor_task_id，便于排障。
"""

from __future__ import annotations

import logging
from datetime import datetime
from threading import Thread
from types import SimpleNamespace

from celery.result import AsyncResult

from app.config import settings
from app.core.celery_app import celery_app
from app.core.db_sync import sync_session_maker
from app.models.task import GenerationTask, GenerationTaskStatus
from app.services.worker.task_registry import task_executor_registry

logger = logging.getLogger(__name__)


def _record_executor_dispatch(task_id: str, *, executor_type: str, executor_task_id: str | None) -> None:
    """回写任务执行器信息，便于 UI 展示与排障定位。"""

    try:
        with sync_session_maker() as db:
            row = db.get(GenerationTask, task_id)
            if row is None:
                return
            row.executor_type = executor_type
            row.executor_task_id = executor_task_id
            db.commit()
    except Exception:  # noqa: BLE001
        logger.warning(
            "failed to record task executor dispatch, task will still run: task_id=%s executor_type=%s",
            task_id,
            executor_type,
            exc_info=True,
        )


def _mark_local_dispatch_failure(task_id: str, *, error: str) -> None:
    """本地线程启动后若执行入口异常，尽量把任务从 pending 转为 failed。

    本地开发环境没有独立 Celery worker。若后台线程在读取任务或执行器分派时
    发生数据库锁等异常，不能只让线程静默退出，否则页面会长期看到 pending。
    """

    try:
        with sync_session_maker() as db:
            row = db.get(GenerationTask, task_id)
            if row is None:
                return
            if str(row.status) in {"succeeded", "failed", "cancelled"}:
                return
            row.status = GenerationTaskStatus.failed.value
            row.progress = max(int(row.progress or 0), 10)
            row.error = error[:1000]
            row.finished_at = datetime.utcnow()
            db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("failed to mark local task dispatch failure: task_id=%s", task_id)


def _run_task_local_entry(task_id: str) -> None:
    """本地线程执行入口，负责捕获同步执行器抛出的异常。"""

    try:
        run_task_celery(task_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("local task execution failed before worker handled task: task_id=%s", task_id)
        _mark_local_dispatch_failure(task_id, error=str(exc) or exc.__class__.__name__)


def _should_execute_locally() -> bool:
    """解析当前任务执行模式。

    规则：
    - `local`：始终走本地线程，适合本地开发仅启动 Web 进程的场景；
    - `celery`：始终走 Celery，适合独立 worker 常驻的环境；
    - `auto`：SQLite 默认走本地线程，其余环境维持 Celery。
    """

    mode = (settings.task_execution_mode or "auto").strip().lower()
    if mode == "local":
        return True
    if mode == "celery":
        return False
    database_url = (settings.database_url or "").strip().lower()
    return database_url.startswith("sqlite")


def _run_task_local(task_id: str) -> SimpleNamespace:
    """在后台线程中直接执行统一 task executor。

    本地开发经常只启动 FastAPI + Vite，不额外拉起 Celery worker。
    这里提供最小兜底，保证任务不会长期卡在 pending 0%。
    """

    thread_name = f"local-task-{task_id[:8]}"
    worker = Thread(
        target=_run_task_local_entry,
        args=(task_id,),
        name=thread_name,
        daemon=True,
    )
    worker.start()
    _record_executor_dispatch(
        task_id,
        executor_type="local_thread",
        executor_task_id=thread_name,
    )
    return SimpleNamespace(id=thread_name)


def enqueue_task_execution(task_id: str) -> AsyncResult:
    """按配置投递任务到 Celery 或本地线程。"""

    if _should_execute_locally():
        return _run_task_local(task_id)
    async_result = run_task_celery.delay(task_id)
    _record_executor_dispatch(
        task_id,
        executor_type="celery",
        executor_task_id=async_result.id,
    )
    return async_result


def revoke_task_execution(task_id: str, *, terminate: bool = True, signal: str = "SIGTERM") -> bool:
    """撤销已分发任务。

    仅 Celery executor 支持 best-effort revoke；
    本地线程执行保留协作式取消，不做强杀。
    """

    with sync_session_maker() as db:
        row = db.get(GenerationTask, task_id)
        if row is None:
            return False
        if (row.executor_type or "").strip() != "celery":
            return False
        executor_task_id = (row.executor_task_id or "").strip()
        if not executor_task_id:
            return False

    try:
        AsyncResult(executor_task_id, app=celery_app).revoke(terminate=terminate, signal=signal)
    except Exception:  # noqa: BLE001
        logger.exception("failed to revoke celery task: task_id=%s executor_task_id=%s", task_id, executor_task_id)
        return False
    return True


@celery_app.task(name="task.execute")
def run_task_celery(task_id: str) -> None:
    with sync_session_maker() as db:
        row = db.get(GenerationTask, task_id)
        if row is None:
            return
        task_kind = (row.task_kind or "").strip() or str((row.payload or {}).get("task_kind") or "").strip()
    executor = task_executor_registry.resolve(task_kind)
    executor.run(task_id)
