import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.api import auth, chat, documents, settings as settings_api, sources as sources_api, system, usage as usage_api
from app.bootstrap import bootstrap
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.services.runtime_settings import get_merged, resolved_settings

logger = logging.getLogger(__name__)


async def _run_llm_activity_backfill_background() -> None:
    """Complete full-library LLM date backfill without blocking API startup.

    Idempotent per document (activities_parsed=llm-1). Runs in-process on
    lifespan so a stopped Celery worker cannot leave the UI stuck on「日期更新中」.
    """
    from app.services.activity_dates import backfill_document_activities

    try:
        async with SessionLocal() as session:
            await backfill_document_activities(session)
    except Exception:
        logger.exception("in-process LLM activity backfill failed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await bootstrap()
    async with SessionLocal() as session:
        await get_merged(session)
    task = asyncio.create_task(_run_llm_activity_backfill_background())
    try:
        yield
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


class DynamicCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        origin = request.headers.get("origin")
        rs = resolved_settings()
        allowed = [o.strip() for o in str(rs.get("cors_origins", "")).split(",") if o.strip()]
        if request.method == "OPTIONS" and origin in allowed:
            return Response(
                status_code=200,
                headers={
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Credentials": "true",
                    "Access-Control-Allow-Methods": "*",
                    "Access-Control-Allow-Headers": "*",
                    "Vary": "Origin",
                },
            )
        response = await call_next(request)
        if origin in allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Vary"] = "Origin"
        return response


def create_app() -> FastAPI:
    cfg = get_settings()
    app = FastAPI(title=cfg.app_name, lifespan=lifespan)
    app.add_middleware(DynamicCORSMiddleware)
    app.include_router(auth.router)
    app.include_router(documents.router)
    app.include_router(chat.router)
    app.include_router(settings_api.router)
    app.include_router(sources_api.router)
    app.include_router(system.router)
    app.include_router(usage_api.router)
    return app


app = create_app()
