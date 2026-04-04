from collections.abc import AsyncGenerator
import logging

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.core.config import settings

logger = logging.getLogger(__name__)

if not settings.DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. "
        "Set it in .env (e.g. postgresql+asyncpg://user:pass@host:5432/db) "
        "or for tests use sqlite+aiosqlite:///..."
    )

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

_engine_kwargs: dict = {"echo": False}
if not _is_sqlite:
    _engine_kwargs.update(
        pool_size=16,
        max_overflow=8,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={
            "prepared_statement_cache_size": 0,
            "statement_cache_size": 0,
        },
    )

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


if not _is_sqlite:
    @event.listens_for(engine.sync_engine, "checkout")
    def _on_pool_checkout(dbapi_conn, conn_record, conn_proxy) -> None:
        pool = engine.sync_engine.pool
        size = pool.size()
        checked_out = pool.checkedout()
        overflow = pool.overflow()
        if checked_out >= size + max(overflow - 2, 0):
            logger.warning(
                "DB pool near saturation: checkedout=%d pool_size=%d overflow=%d",
                checked_out,
                size,
                overflow,
            )

    @event.listens_for(engine.sync_engine, "connect")
    def _on_pool_connect(dbapi_conn, conn_record) -> None:
        pool = engine.sync_engine.pool
        logger.debug("DB pool: new connection opened (total checkedout=%d)", pool.checkedout())


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def init_db() -> None:
    import app.db.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
