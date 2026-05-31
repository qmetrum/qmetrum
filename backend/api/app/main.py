"""ASPIS Smoke Detection Platform -- FastAPI application."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.common.config.settings import get_settings

settings = get_settings()
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown."""
    logger.info("ASPIS API starting", environment=settings.environment)
    # TODO: initialize DB connection pool, Redis, etc.
    yield
    logger.info("ASPIS API shutting down")
    # TODO: cleanup connections


app = FastAPI(
    title="ASPIS Smoke Detection API",
    description=(
        "Backend API for the ASPIS automated drone-based smoke and fire detection platform."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -- Health checks --

@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    """Liveness probe for Kubernetes."""
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
async def readiness_check() -> dict[str, str]:
    """Readiness probe -- checks DB and Redis connectivity."""
    # TODO: check DB and Redis connections
    return {"status": "ready"}


# -- Routers (will be added in Sprint 2) --
# from backend.api.app.routers import (
#     sites, docks, missions, detections, alerts, auth, telemetry, media,
# )
# app.include_router(sites.router, prefix="/api/v1", tags=["sites"])
# app.include_router(docks.router, prefix="/api/v1", tags=["docks"])
# app.include_router(missions.router, prefix="/api/v1", tags=["missions"])
# app.include_router(detections.router, prefix="/api/v1", tags=["detections"])
# app.include_router(alerts.router, prefix="/api/v1", tags=["alerts"])
# app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
# app.include_router(telemetry.router, prefix="/api/v1", tags=["telemetry"])
# app.include_router(media.router, prefix="/api/v1", tags=["media"])
