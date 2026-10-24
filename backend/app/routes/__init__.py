"""HTTP routes. Routes call services only."""

from __future__ import annotations

from fastapi import FastAPI


def include_routers(app: FastAPI) -> None:
    """Mount Phase 1 and Phase 2 D routers."""
    from app.routes import attempts as attempts_routes
    from app.routes import boulders as boulders_routes
    from app.routes import jobs as jobs_routes
    from app.routes import media as media_routes
    from app.routes import pose as pose_routes
    from app.routes import proposals as proposals_routes
    from app.routes import scene as scene_routes
    from app.routes import sessions as sessions_routes
    from app.routes import settings as settings_routes
    from app.routes import system as system_routes
    from app.routes import trash as trash_routes
    from app.routes import videos as videos_routes

    app.include_router(system_routes.router)
    app.include_router(jobs_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(boulders_routes.router)
    app.include_router(sessions_routes.router)
    app.include_router(videos_routes.router)
    app.include_router(media_routes.router)
    app.include_router(attempts_routes.router)
    app.include_router(trash_routes.router)
    app.include_router(pose_routes.router)
    app.include_router(scene_routes.router)
    app.include_router(proposals_routes.router)
