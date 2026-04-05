import logging
from collections.abc import AsyncGenerator

from sqlalchemy import event, text
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


_db_initialized = False


async def init_db() -> None:
    global _db_initialized
    if _db_initialized:
        return
    import app.db.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if not _is_sqlite:
            # Inline migrations: add ownership columns that postdate initial schema.
            await conn.execute(text("ALTER TABLE notification_deliveries ADD COLUMN IF NOT EXISTS user_id VARCHAR"))
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_notification_deliveries_user_id ON notification_deliveries (user_id)"
                )
            )
            await conn.execute(text("ALTER TABLE notification_destinations ADD COLUMN IF NOT EXISTS user_id VARCHAR"))
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_notification_destinations_user_id"
                    " ON notification_destinations (user_id)"
                )
            )

            await conn.execute(text("ALTER TABLE recon_dossiers ADD COLUMN IF NOT EXISTS user_id VARCHAR"))
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_recon_dossiers_user_id ON recon_dossiers (user_id)"
                )
            )
            await conn.execute(text("ALTER TABLE tinyfish_brief_cache ADD COLUMN IF NOT EXISTS user_id VARCHAR"))
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_tinyfish_brief_cache_user_id ON tinyfish_brief_cache (user_id)"
                )
            )

            # Inline RLS migration (FOX-106): protect newly added user-facing tables.
            await conn.execute(text("ALTER TABLE dossiers ENABLE ROW LEVEL SECURITY"))
            await conn.execute(text("ALTER TABLE foxhound_briefs ENABLE ROW LEVEL SECURITY"))
            await conn.execute(text("ALTER TABLE agent_activities ENABLE ROW LEVEL SECURITY"))
            await conn.execute(text("ALTER TABLE watchdog_checks ENABLE ROW LEVEL SECURITY"))
            await conn.execute(text("ALTER TABLE recon_dossiers ENABLE ROW LEVEL SECURITY"))
            await conn.execute(text("ALTER TABLE tinyfish_brief_cache ENABLE ROW LEVEL SECURITY"))

            await conn.execute(text("DROP POLICY IF EXISTS users_read_own_dossiers ON dossiers"))
            await conn.execute(
                text("CREATE POLICY users_read_own_dossiers ON dossiers FOR SELECT USING (user_id = auth.uid()::text)")
            )
            await conn.execute(text("DROP POLICY IF EXISTS users_read_own_briefs ON foxhound_briefs"))
            await conn.execute(
                text(
                    "CREATE POLICY users_read_own_briefs ON foxhound_briefs"
                    " FOR SELECT USING (user_id = auth.uid()::text)"
                )
            )
            await conn.execute(text("DROP POLICY IF EXISTS users_read_own_activities ON agent_activities"))
            await conn.execute(
                text(
                    "CREATE POLICY users_read_own_activities ON agent_activities"
                    " FOR SELECT USING (user_id = auth.uid()::text)"
                )
            )
            await conn.execute(text("DROP POLICY IF EXISTS users_read_own_watchdog_checks ON watchdog_checks"))
            await conn.execute(
                text(
                    "CREATE POLICY users_read_own_watchdog_checks ON watchdog_checks"
                    " FOR SELECT USING (user_id = auth.uid()::text)"
                )
            )

            await conn.execute(text("DROP POLICY IF EXISTS users_read_own_recon_dossiers ON recon_dossiers"))
            await conn.execute(
                text(
                    "CREATE POLICY users_read_own_recon_dossiers ON recon_dossiers"
                    " FOR SELECT USING (user_id = auth.uid()::text)"
                )
            )
            await conn.execute(text("DROP POLICY IF EXISTS users_read_own_tinyfish_cache ON tinyfish_brief_cache"))
            await conn.execute(
                text(
                    "CREATE POLICY users_read_own_tinyfish_cache ON tinyfish_brief_cache"
                    " FOR SELECT USING (user_id = auth.uid()::text)"
                )
            )
    _db_initialized = True
