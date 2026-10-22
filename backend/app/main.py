"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings
from app.db import apply_migrations, connect
from app.errors import AppError, install_error_handlers
from app.jobs.queue import JobQueue
from app.media.ffmpeg import FfmpegTool
from app.media.tool import MediaTool
from app.pose.estimator import FixtureEstimator, PoseEstimator
from app.routes import include_routers
from app.security import HostAllowlistMiddleware
from app.services.attempts import make_cut_handler
from app.services.ingest import make_ingest_handler
from app.services.pose_service import bind_pose_runtime
from app.storage import LibraryPaths, safe_join

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def spa_target(full_path: str, dist: Path = FRONTEND_DIST) -> Path:
    """Resolve a SPA path. Raise AppError if the result leaves dist."""
    if not full_path:
        return safe_join(dist, "index.html")
    return safe_join(dist, full_path)


def create_app(
    settings: Settings,
    media: MediaTool | None = None,
    estimator: PoseEstimator | None = None,
) -> FastAPI:
    """Build the app. Tests inject FakeMediaTool and FixtureEstimator."""
    paths = LibraryPaths(settings.library_dir)
    paths.ensure()

    if estimator is None and settings.pose_backend == "fixture":
        estimator = FixtureEstimator()
    if media is None:
        media = FfmpegTool(settings.ffmpeg_bin, settings.ffprobe_bin)
    resolved_media: MediaTool = media
    bind_pose_runtime(settings=settings, paths=paths, estimator=estimator)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        conn = connect(paths.db)
        apply_migrations(conn)
        queue = JobQueue(paths.db)
        queue.register("ingest", make_ingest_handler(paths, resolved_media, queue))
        queue.register("cut", make_cut_handler(paths, resolved_media))
        recovered = queue.recover()
        if recovered:
            app.state.log_recovered = recovered
        paths.clear_tmp()
        app.state.db_conn = conn
        app.state.queue = queue
        queue.start()
        try:
            yield
        finally:
            queue.stop()
            queue.close()
            conn.close()

    docs_url = "/docs" if settings.dev else None
    openapi_url = "/openapi.json" if settings.dev else None
    app = FastAPI(
        title="Climbing Coach",
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=None,
        openapi_url=openapi_url,
    )
    app.state.settings = settings
    app.state.paths = paths
    app.state.media = resolved_media
    app.state.estimator = estimator

    app.add_middleware(HostAllowlistMiddleware, settings=settings)
    install_error_handlers(app)
    include_routers(app)
    _install_spa(app)
    return app


def _install_spa(app: FastAPI) -> None:
    assets = FRONTEND_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}")
    def spa_fallback(request: Request, full_path: str) -> Any:
        del request
        reserved = {"health", "auth/launch", "docs", "openapi.json"}
        if full_path.startswith("api/") or full_path in reserved:
            raise AppError("not_found", 404, "The page is not here.")
        index = spa_target("", FRONTEND_DIST)
        if full_path:
            candidate = spa_target(full_path, FRONTEND_DIST)
            if candidate.is_file():
                return FileResponse(candidate)
        if index.is_file():
            return FileResponse(index)
        raise AppError("not_found", 404, "The frontend build is not here.")


def app_factory() -> FastAPI:
    """Uvicorn factory entry: `uvicorn app.main:app_factory --factory`."""
    return create_app(Settings.from_env())
