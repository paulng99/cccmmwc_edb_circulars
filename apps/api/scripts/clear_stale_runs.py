"""Mark stale running crawl runs as failed after a deploy."""
import asyncio

from app.core.db import SessionLocal
from app.services.crawl_events import ORPHAN_RUN_REASON, close_orphaned_runs


async def main() -> None:
    async with SessionLocal() as session:
        updated = await close_orphaned_runs(session, reason=ORPHAN_RUN_REASON)
        print("updated", updated)


if __name__ == "__main__":
    asyncio.run(main())
