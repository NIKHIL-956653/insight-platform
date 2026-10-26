"""FastAPI application factory and the `insight-api` entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from insight import __version__
from insight.api.v1 import auth as auth_routes
from insight.config import Settings, get_settings
from insight.db.session import create_engine, create_session_factory, dispose_engine
from insight.logging import configure_logging, get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    log.info(
        "starting",
        version=__version__,
        env=settings.app_env,
        embedding_model=settings.embedding_model,
        embedding_dimension=settings.embedding_dimension,
        generation_model=settings.litellm_generation_model,
    )
    # create_async_engine does not connect eagerly, so building it here is
    # cheap and the app still starts when Postgres is briefly unavailable.
    engine = create_engine(settings)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    log.info("database pool ready", pool_size=settings.db_pool_size)

    try:
        yield
    finally:
        await dispose_engine(engine)
        log.info("stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    Settings are injectable so tests can construct an app without a .env.
    """
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.emit_json_logs)

    app = FastAPI(
        title="InSight Platform",
        version=__version__,
        description="Enterprise meeting intelligence.",
        lifespan=lifespan,
        # No interactive docs in production: the schema describes every
        # endpoint holding board material.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.state.settings = settings

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, Any]:
        """Liveness only - is the process up.

        Readiness (Postgres, Redis, SpiceDB reachable) arrives with those
        clients. Do not conflate the two: a liveness probe that checks
        dependencies restarts a healthy app when the database blips.
        """
        return {
            "status": "ok",
            "version": __version__,
            "env": settings.app_env,
        }

    app.include_router(auth_routes.router)
    return app


def run() -> None:
    """Console entry point: `insight-api`."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "insight.main:create_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
        reload=not settings.is_production,
        log_config=None,  # structlog owns logging
    )


if __name__ == "__main__":
    run()
