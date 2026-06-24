"""
Entry point for the Smart Battery Controller API.

This module exposes:
  - FastAPI app (uvicorn entry point: `uvicorn app.main:app`)
  - OpenAPI/Swagger UIs at `/docs`, `/redoc`, and raw spec at `/openapi.json`
  - CORS middleware (env-configurable allow_origins; safe dev defaults inline)
  - Versioned router namespace `/api/v1`
  - System endpoints: `/` (legacy health) and `/health` (explicit health probe)

Frontend integration:
  Set CORS_ALLOWED_ORIGINS env var to a comma-separated list of allowed origins
  for production, e.g.:
    CORS_ALLOWED_ORIGINS="https://my-dashboard.example.com,https://www.example.com"
  If unset, the dev-friendly defaults (localhost:3000, 5173, 8080) are used.
"""

import logging
import os
from datetime import datetime, timezone
from typing import List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers.decision import router as decision_router
from app.routers.forecast import router as forecast_router

# Basic logging configuration — visible in production (Railway) and locally
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------- CORS configuration ----------------
# Dev-friendly defaults: popular frontend dev servers.
# Production: set CORS_ALLOWED_ORIGINS env var as a comma-separated list of origins.
DEFAULT_CORS_ORIGINS: List[str] = [
    "http://localhost:3000",   # Next.js / Create React App
    "http://localhost:5173",   # Vite
    "http://localhost:8080",   # Vue CLI / general
    "http://localhost:4200",   # Angular
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8080",
    "http://127.0.0.1:4200",
]


def _load_cors_origins() -> List[str]:
    """Reads CORS_ALLOWED_ORIGINS env var (comma-separated) or returns dev defaults."""
    env_value = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
    if not env_value:
        return DEFAULT_CORS_ORIGINS
    origins = [o.strip() for o in env_value.split(",") if o.strip()]
    if not origins:
        logger.warning(
            "CORS_ALLOWED_ORIGINS env var was set but empty after parsing; using dev defaults."
        )
        return DEFAULT_CORS_ORIGINS
    logger.info("Loaded %d CORS origins from CORS_ALLOWED_ORIGINS env: %s", len(origins), origins)
    return origins


# ---------------- FastAPI app ----------------
app = FastAPI(
    title="Smart Battery Controller",
    description=(
        "Decision API for a Netherlands solar battery. Pulls live solar radiation "
        "(Open-Meteo) and live electricity prices (EnergyZero), then returns a "
        "CHARGE / DISCHARGE / HOLD verdict based on the current price and the next "
        "few hours of irradiance. No manual input is required.\n\n"
        "Frontend integration:\n"
        "- OpenAPI spec: GET /openapi.json\n"
        "- Swagger UI:   GET /docs\n"
        "- ReDoc:        GET /redoc\n"
        "- All business endpoints live under the `/api/v1` prefix."
    ),
    version="1.1",
    openapi_tags=[
        {
            "name": "decision",
            "description": "Operations combining solar and price data into a battery action.",
        },
        {
            "name": "forecast",
            "description": "Operations exposing raw solar-radiation forecast data.",
        },
        {
            "name": "system",
            "description": "Health and operational endpoints (no auth required).",
        },
    ],
)


# ---------------- Middleware (CORS) ----------------
# Apply globally so that every route (including future ones) is reachable from
# a browser-based frontend. Allow credentials so cookies / Bearer headers can
# be sent if the frontend adds auth later.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://gabemaldito.github.io"], 
    allow_credentials=True,
    allow_methods=["GET", "OPTIONS"], 
    allow_headers=["*"], # Alterado para "*" para eliminar problemas com headers
)


# ---------------- Routers ----------------
app.include_router(forecast_router, prefix="/api/v1", tags=["forecast"])
app.include_router(decision_router, prefix="/api/v1", tags=["decision"])


# ---------------- System endpoints ----------------
@app.get("/", tags=["system"])
async def root():
    """Legacy health check. Returns 200 if the process is up."""
    logger.debug("Health check accessed via /")
    return {"status": "Server running", "api_version": app.version}


@app.get("/health", tags=["system"])
async def health():
    """
    Explicit health endpoint suitable for liveness probes (Railway, Kubernetes).
    Returns 200 with current UTC timestamp while the process is up.
    """
    return {
        "status": "ok",
        "api_version": app.version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
