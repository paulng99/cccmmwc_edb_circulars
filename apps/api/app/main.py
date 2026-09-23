from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, chat, documents, settings as settings_api, system
from app.bootstrap import bootstrap
from app.core.config import get_settings


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await bootstrap()
    yield


def create_app() -> FastAPI:
    cfg = get_settings()
    app = FastAPI(title=cfg.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth.router)
    app.include_router(documents.router)
    app.include_router(chat.router)
    app.include_router(settings_api.router)
    app.include_router(system.router)
    return app


app = create_app()
