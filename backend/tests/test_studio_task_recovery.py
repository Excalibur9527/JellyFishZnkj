"""Studio 僵尸生成任务恢复测试。"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import Base
from app.models.task import GenerationDeliveryMode, GenerationTask, GenerationTaskStatus
from app.services.studio.task_recovery import expire_stale_image_tasks


@pytest.mark.asyncio
async def test_expire_stale_image_tasks_marks_only_expired_images_failed() -> None:
    """只清理超时图片任务，近期图片任务和长耗时视频任务保持活动状态。"""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    old_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=30)
    async with maker() as db:
        stale_image = GenerationTask(
            id="stale-image",
            mode=GenerationDeliveryMode.async_polling,
            task_kind="image_generation",
            status=GenerationTaskStatus.running,
            progress=10,
            payload={},
            error="",
            updated_at=old_time,
        )
        recent_image = GenerationTask(
            id="recent-image",
            mode=GenerationDeliveryMode.async_polling,
            task_kind="image_generation",
            status=GenerationTaskStatus.running,
            progress=10,
            payload={},
            error="",
        )
        stale_video = GenerationTask(
            id="stale-video",
            mode=GenerationDeliveryMode.async_polling,
            task_kind="video_generation",
            status=GenerationTaskStatus.running,
            progress=10,
            payload={},
            error="",
            updated_at=old_time,
        )
        db.add_all((stale_image, recent_image, stale_video))
        await db.commit()

        expired = await expire_stale_image_tasks(db)

        assert expired == 1
        assert stale_image.status == GenerationTaskStatus.failed
        assert recent_image.status == GenerationTaskStatus.running
        assert stale_video.status == GenerationTaskStatus.running
    await engine.dispose()


@pytest.mark.asyncio
async def test_expire_stale_image_tasks_marks_undispatched_pending_failed() -> None:
    """图片任务若一直 pending 且没有执行器信息，应快速判定为派发丢失。"""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    old_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=3)
    async with maker() as db:
        undispatched = GenerationTask(
            id="undispatched-image",
            mode=GenerationDeliveryMode.async_polling,
            task_kind="image_generation",
            status=GenerationTaskStatus.pending,
            progress=0,
            payload={},
            error="",
            created_at=old_time,
            updated_at=old_time,
        )
        recent_pending = GenerationTask(
            id="recent-pending-image",
            mode=GenerationDeliveryMode.async_polling,
            task_kind="image_generation",
            status=GenerationTaskStatus.pending,
            progress=0,
            payload={},
            error="",
        )
        db.add_all((undispatched, recent_pending))
        await db.commit()

        expired = await expire_stale_image_tasks(db)

        assert expired == 1
        assert undispatched.status == GenerationTaskStatus.failed
        assert undispatched.error == "Image generation task was never dispatched to a worker"
        assert recent_pending.status == GenerationTaskStatus.pending
    await engine.dispose()
