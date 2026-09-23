from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.api import auth, chat, documents, settings as settings_api, system
from app.bootstrap import bootstrap
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.services.runtime_settings import get_merged, resolved_settings


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await bootstrap()
    async with SessionLocal() as session:
        await get_merged(session)
    yield


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
                },
            )
        response = await call_next(request)
        if origin in allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
        return response


def create_app() -> FastAPI:
    cfg = get_settings()
    app = FastAPI(title=cfg.app_name, lifespan=lifespan)
    app.add_middleware(DynamicCORSMiddleware)
    app.include_router(auth.router)
    app.include_router(documents.router)
    app.include_router(chat.router)
    app.include_router(settings_api.router)
    app.include_router(system.router)
    return app


app = create_app()
