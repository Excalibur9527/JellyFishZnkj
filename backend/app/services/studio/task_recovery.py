"""Studio 生成任务异常退出后的状态恢复。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import GenerationTask, GenerationTaskStatus


async def expire_stale_image_tasks(
    db: AsyncSession,
    *,
    stale_after: timedelta = timedelta(minutes=10),
    undispatched_after: timedelta = timedelta(minutes=1),
) -> int:
    """把长期无更新的图片任务转为失败，避免页面永久显示生成中。

    图片供应商调用正常最多约五分钟；进程重载或异常退出时，任务可能来不及
    写入终态。启动阶段将超过十分钟仍处于活动态的图片任务标记为失败。
    另外，本地开发模式会在任务创建后投递到本地线程；如果任务一直停在
    pending、没有 executor 信息、也没有 started_at，说明派发步骤已经丢失，
    这类任务超过一分钟就应失败，避免 UI 长期显示“排队中”。
    """

    # 数据库存储无时区 UTC 时间；必须使用 UTC 比较，避免本地时区把新任务误判为过期。
    now = datetime.now(UTC).replace(tzinfo=None)
    stale_cutoff = now - stale_after
    undispatched_cutoff = now - undispatched_after
    stmt = select(GenerationTask).where(
        GenerationTask.task_kind == "image_generation",
        GenerationTask.status.in_(
            (
                GenerationTaskStatus.pending,
                GenerationTaskStatus.running,
                GenerationTaskStatus.streaming,
            )
        ),
        or_(
            GenerationTask.updated_at < stale_cutoff,
            and_(
                GenerationTask.status == GenerationTaskStatus.pending,
                GenerationTask.started_at.is_(None),
                or_(GenerationTask.executor_type.is_(None), GenerationTask.executor_type == ""),
                GenerationTask.created_at < undispatched_cutoff,
            ),
        ),
    )
    tasks = (await db.execute(stmt)).scalars().all()
    for task in tasks:
        never_dispatched = (
            task.status == GenerationTaskStatus.pending
            and not (task.executor_type or "").strip()
            and task.started_at is None
        )
        task.status = GenerationTaskStatus.failed
        task.finished_at = now
        if never_dispatched:
            task.error = task.error or "Image generation task was never dispatched to a worker"
        else:
            task.error = task.error or "Image generation task expired after worker interruption"
    if tasks:
        await db.commit()
    return len(tasks)
