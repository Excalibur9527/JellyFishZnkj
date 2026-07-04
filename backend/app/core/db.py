"""SQLAlchemy 异步引擎与会话。"""

from typing import Any

from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


def _build_engine() -> AsyncEngine:
    """创建异步数据库引擎，并为本地 SQLite 开发库开启等待锁释放。

    本地工作室会同时进行任务轮询、运行时摘要刷新和生成任务状态落库。
    SQLite 只能同时处理有限写入；如果不配置 busy timeout，短暂撞锁会被
    立即抛成 ``database is locked``，导致提示词/图片/视频任务误失败。
    """

    engine_options: dict[str, Any] = {}
    database_url = str(settings.database_url or "").strip().lower()
    if database_url.startswith("sqlite"):
        engine_options["connect_args"] = {"timeout": 30}

    built_engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        future=True,
        **engine_options,
    )
    if database_url.startswith("sqlite"):
        sync_engine = built_engine.sync_engine

        @event.listens_for(sync_engine, "connect")
        def _set_sqlite_busy_timeout(dbapi_connection: Any, _connection_record: Any) -> None:
            """优化本地 SQLite 并发读写，避免工作室轮询与任务落库互相卡死。"""

            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA busy_timeout = 30000")
                cursor.execute("PRAGMA journal_mode = WAL")
                cursor.execute("PRAGMA synchronous = NORMAL")
            finally:
                cursor.close()

    return built_engine


def _build_session_maker(bind_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


class _AsyncSessionMakerProxy:
    """可重绑定的 sessionmaker 代理。

    Celery prefork 模式下，worker 子进程不能继续复用父进程里初始化的
    async engine / sessionmaker。这里保持导入对象稳定，同时允许在子进程
    启动后重新绑定底层 sessionmaker。
    """

    def __init__(self, maker: async_sessionmaker[AsyncSession]) -> None:
        self._maker = maker

    def configure(self, maker: async_sessionmaker[AsyncSession]) -> None:
        self._maker = maker

    def __call__(self, *args: Any, **kwargs: Any) -> AsyncSession:
        return self._maker(*args, **kwargs)


engine = _build_engine()
async_session_maker = _AsyncSessionMakerProxy(_build_session_maker(engine))


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""

    pass


async def init_db() -> None:
    """创建所有表，并补齐无迁移框架时期新增的兼容字段。"""
    # 确保 ORM 模型已导入，从而注册到 Base.metadata
    import app.models.llm  # noqa: F401  # pylint: disable=unused-import
    import app.models.studio  # noqa: F401
    import app.models.task  # noqa: F401
    import app.models.task_links  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        columns = await conn.run_sync(
            lambda sync_conn: {item["name"] for item in inspect(sync_conn).get_columns("shot_frame_images")}
        )
        if "reference_assets" not in columns:
            # 现有开发库由 create_all 管理；create_all 不会给旧表补列，因此在启动时幂等补齐。
            await conn.execute(text("ALTER TABLE shot_frame_images ADD COLUMN reference_assets JSON"))


async def close_db() -> None:
    """关闭数据库连接。"""
    await engine.dispose()


def reset_db_runtime() -> None:
    """在 Celery worker 子进程中重建 engine 与 sessionmaker。

    这样可以避免 prefork 继承父进程中的 async engine，导致连接对象和事件循环
    绑定错乱，触发 Future attached to a different loop。
    """

    global engine

    engine = _build_engine()
    async_session_maker.configure(_build_session_maker(engine))
