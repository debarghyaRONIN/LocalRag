import os
from pathlib import Path
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import event
from backend.app.core.config import settings
from backend.app.db.models import Base

# Engine configuration
is_sqlite = settings.DATABASE_URL.startswith("sqlite")

engine_kwargs = {"echo": False}
if is_sqlite:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
    # Ensure database directory exists before connecting, resolving relative to writable DATA_DIR
    try:
        raw_db_path = settings.DATABASE_URL.split(":///")[-1]
        resolved_db_path = Path(raw_db_path)
        if not resolved_db_path.is_absolute():
            resolved_db_path = settings.DATA_DIR / resolved_db_path.name
        resolved_db_path.parent.mkdir(parents=True, exist_ok=True)
        active_db_url = f"sqlite+aiosqlite:///{resolved_db_path.as_posix()}"
    except Exception as e:
        print(f"[Warning] Could not resolve SQLite directory: {e}")
        active_db_url = settings.DATABASE_URL
else:
    active_db_url = settings.DATABASE_URL

engine = create_async_engine(active_db_url, **engine_kwargs)

# For SQLite, enable WAL mode for high-concurrency read/writes
if is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


async def init_db():
    """Create all database tables on application startup and apply lightweight migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        def run_migrations(sync_conn):
            from sqlalchemy import inspect, text
            inspector = inspect(sync_conn)
            table_names = inspector.get_table_names()

            if "documents" in table_names:
                doc_cols = [c["name"] for c in inspector.get_columns("documents")]
                if "clearance_level" not in doc_cols:
                    sync_conn.execute(text("ALTER TABLE documents ADD COLUMN clearance_level INTEGER NOT NULL DEFAULT 1"))
                if "allowed_departments" not in doc_cols:
                    sync_conn.execute(text("ALTER TABLE documents ADD COLUMN allowed_departments JSON DEFAULT '[]'"))
                if "owner" not in doc_cols:
                    sync_conn.execute(text("ALTER TABLE documents ADD COLUMN owner VARCHAR(64) NOT NULL DEFAULT 'default_user'"))
                if "status" not in doc_cols:
                    sync_conn.execute(text("ALTER TABLE documents ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'indexed'"))
                if "source_path" not in doc_cols:
                    sync_conn.execute(text("ALTER TABLE documents ADD COLUMN source_path TEXT"))

            if "feedbacks" in table_names:
                fb_cols = [c["name"] for c in inspector.get_columns("feedbacks")]
                if "request_id" not in fb_cols:
                    sync_conn.execute(text("ALTER TABLE feedbacks ADD COLUMN request_id VARCHAR(64)"))
                if "reason_code" not in fb_cols:
                    sync_conn.execute(text("ALTER TABLE feedbacks ADD COLUMN reason_code VARCHAR(64)"))

            if "parent_chunks" in table_names:
                chunk_cols = [c["name"] for c in inspector.get_columns("parent_chunks")]
                if "clearance_level" not in chunk_cols:
                    sync_conn.execute(text("ALTER TABLE parent_chunks ADD COLUMN clearance_level INTEGER NOT NULL DEFAULT 1"))
                if "allowed_departments" not in chunk_cols:
                    sync_conn.execute(text("ALTER TABLE parent_chunks ADD COLUMN allowed_departments JSON DEFAULT '[]'"))

            if is_sqlite:
                sync_conn.execute(text("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS parent_chunks_fts USING fts5(
                        parent_id UNINDEXED,
                        doc_id UNINDEXED,
                        filename,
                        content,
                        clearance_level UNINDEXED,
                        tokenize='porter unicode61'
                    );
                """))

        await conn.run_sync(run_migrations)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for obtaining an async session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
