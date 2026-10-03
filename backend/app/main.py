import logging
import time
import uuid
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.middleware.base import RequestResponseEndpoint

from backend.app.config import AppConfig, validate_server_environment
from backend.app.database.connection import get_engine

from backend.app.player_analysis import router as player_analysis_router
from backend.app.recommendation.runtime import (
    close_recommendation_runtime,
    get_recommendation_runtime,
)
from backend.app.recommendations import router as recommendations_router
from backend.app.top_plays import router as top_plays_router

logger = logging.getLogger("osumapscout.requests")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    validate_server_environment()
    get_recommendation_runtime()
    try:
        yield
    finally:
        await close_recommendation_runtime()


app = FastAPI(title="osu!ditto API", lifespan=lifespan)
config = AppConfig.from_environment()
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(config.cors_origins),
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["Content-Type", "X-Request-ID"],
    expose_headers=["X-Recommendation-Cache", "X-Request-ID"],
)
app.include_router(top_plays_router)
app.include_router(player_analysis_router)
app.include_router(recommendations_router)


@app.middleware("http")
async def request_logging(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_complete request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        (time.perf_counter() - started) * 1000,
    )
    return response


@app.get("/health")
def health() -> dict[str, str]:
    """Report whether the backend application is running."""
    return {"status": "ok"}


@app.get("/ready")
def readiness() -> dict[str, str]:
    """Confirm configured database connectivity without calling osu!."""
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ready"}
