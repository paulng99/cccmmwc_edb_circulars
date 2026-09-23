"""One-shot: LLM-classify documents currently tagged only as other."""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.db import SessionLocal
from app.models.entities import Document
from app.services.classify import apply_classification
from app.services.runtime_settings import ensure_seeded, get_merged, invalidate_cache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("classify_other")


async def main() -> None:
    async with SessionLocal() as session:
        invalidate_cache()
        await ensure_seeded(session)
        await get_merged(session)
        rows = list((await session.scalars(select(Document))).all())
        targets = [d for d in rows if list(d.topics or []) == ["other"]]
        logger.info("other_count=%s", len(targets))
        for i, doc in enumerate(targets):
            result = await apply_classification(doc, use_llm=True, force_topics=True)
            flag_modified(doc, "topics")
            if (i + 1) % 10 == 0:
                await session.commit()
                logger.info(
                    "progress %s/%s topics=%s title=%s",
                    i + 1,
                    len(targets),
                    result.get("topics"),
                    (doc.title or "")[:40],
                )
        await session.commit()
        logger.info("done %s", len(targets))


if __name__ == "__main__":
    asyncio.run(main())
