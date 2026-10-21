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
from app.media.tool import MediaTool
from app.pose.estimator import FixtureEstimator, PoseEstimator
from app.routes import jobs as jobs_routes
from app.routes import system as system_routes
from app.security import HostAllowlistMiddleware
from app.storage import LibraryPaths

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


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

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        conn = connect(paths.db)
        apply_migrations(conn)
        queue = JobQueue(paths.db)
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
    app.state.media = media
    app.state.estimator = estimator

    app.add_middleware(HostAllowlistMiddleware, settings=settings)
    install_error_handlers(app)
    app.include_router(system_routes.router)
    app.include_router(jobs_routes.router)
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
        index = FRONTEND_DIST / "index.html"
        candidate = FRONTEND_DIST / full_path if full_path else index
        if candidate.is_file():
            return FileResponse(candidate)
        if index.is_file():
            return FileResponse(index)
        raise AppError("not_found", 404, "The frontend build is not here.")


def app_factory() -> FastAPI:
    """Uvicorn factory entry: `uvicorn app.main:app_factory --factory`."""
    return create_app(Settings.from_env())
