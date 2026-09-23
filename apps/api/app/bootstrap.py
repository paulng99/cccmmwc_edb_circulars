from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import Base, engine
from app.core.security import hash_password
from app.models import (  # noqa: F401
    AppSetting,
    ChatMessage,
    ChatSession,
    CrawlRun,
    Document,
    DocumentChunk,
    Source,
    User,
)
from app.services.pipeline import sync_sources_table
from app.services.runtime_settings import ensure_seeded
from app.services.storage import ensure_bucket


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
