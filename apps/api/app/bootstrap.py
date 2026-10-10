from __future__ import annotations

import logging

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import Base, engine
from app.core.security import hash_password
from app.models import (  # noqa: F401
    ApiUsage,
    AppSetting,
    ChatMessage,
    ChatSession,
    CrawlEvent,
    CrawlRun,
    Document,
    DocumentChunk,
    Source,
    User,
)
from app.services.activity_dates import prepare_llm_activity_backfill
from app.services.doc_dates import backfill_document_dates
from app.services.pipeline import sync_sources_table
from app.services.runtime_settings import ensure_seeded
from app.services.storage import ensure_bucket

logger = logging.getLogger(__name__)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        # create_all does not add columns to existing tables
        await conn.execute(
            text(
                "ALTER TABLE crawl_runs "
                "ADD COLUMN IF NOT EXISTS progress_message TEXT"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE crawl_runs "
                "ADD COLUMN IF NOT EXISTS cancel_requested BOOLEAN DEFAULT FALSE"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE crawl_runs "
                "ADD COLUMN IF NOT EXISTS celery_task_id VARCHAR(64)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE crawl_runs "
                "ADD COLUMN IF NOT EXISTS skipped INTEGER DEFAULT 0"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_documents_file_url "
                "ON documents (file_url)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE documents "
                "ADD COLUMN IF NOT EXISTS programme VARCHAR(32) DEFAULT 'other'"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE documents "
                "ADD COLUMN IF NOT EXISTS topics JSONB DEFAULT '[]'::jsonb"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_documents_programme "
                "ON documents (programme)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE chat_sessions "
                "ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE chat_sessions "
                "ADD COLUMN IF NOT EXISTS focus_document_id UUID "
                "REFERENCES documents(id) ON DELETE SET NULL"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chat_sessions_focus_document_id "
                "ON chat_sessions (focus_document_id)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE chat_messages "
                "ADD COLUMN IF NOT EXISTS attachments JSONB"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE chat_messages "
                "ADD COLUMN IF NOT EXISTS truncated BOOLEAN DEFAULT FALSE"
            )
        )
        await conn.execute(
            text(
                "UPDATE chat_sessions AS s "
                "SET updated_at = COALESCE("
                "  (SELECT MAX(m.created_at) FROM chat_messages AS m WHERE m.session_id = s.id),"
                "  s.created_at,"
                "  NOW()"
                ")"
            )
        )
        await conn.execute(
            text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS revised_at DATE")
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_documents_revised_at "
                "ON documents (revised_at)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE documents "
                "ADD COLUMN IF NOT EXISTS activities JSONB DEFAULT '[]'::jsonb"
            )
        )


async def seed_admin(session: AsyncSession) -> None:
    settings = get_settings()
    existing = await session.scalar(select(User).where(User.username == settings.admin_username))
    if existing:
        return
    user = User(
        username=settings.admin_username,
        password_hash=hash_password(settings.admin_password),
        role="admin",
        auth_provider="password",
    )
    session.add(user)
    await session.commit()


async def bootstrap() -> None:
    await init_db()
    try:
        ensure_bucket()
    except Exception:
        # MinIO may not be ready on first tick; API health still works
        pass
    from app.core.db import SessionLocal

    async with SessionLocal() as session:
        await seed_admin(session)
        await ensure_seeded(session)
        await sync_sources_table(session)
        try:
            await backfill_document_dates(session)
        except Exception:
            logger.exception("document date backfill failed")
            await session.rollback()
        try:
            # Clear stale local regex activities and mark dates_updating before
            # the API serves traffic. LLM extraction runs in the background.
            await prepare_llm_activity_backfill(session)
        except Exception:
            logger.exception("document activity backfill prepare failed")
            await session.rollback()
