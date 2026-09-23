"""Mark stale running crawl runs as failed after a deploy."""
import asyncio
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.core.db import SessionLocal
from app.models.entities import CrawlRun


async def main() -> None:
    async with SessionLocal() as session:
        result = await session.execute(
            update(CrawlRun)
            .where(CrawlRun.status == "running")
            .values(
                status="failed",
                error_message="Interrupted by service restart — please Crawl again",
                finished_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        print("updated", result.rowcount)


if __name__ == "__main__":
    asyncio.run(main())
