import asyncio
import logging
import time
from typing import Optional

import httpx
import pandas as pd
from fastapi import HTTPException

logger = logging.getLogger(__name__)

_LATITUDE = 53.2194
_LONGITUDE = 6.5665

_API_URL = (
    f"https://api.open-meteo.com/v1/forecast"
    f"?latitude={_LATITUDE}&longitude={_LONGITUDE}"
    f"&hourly=shortwave_radiation&forecast_days=1"
)

# In-memory cache + lock to avoid race conditions between concurrent requests.
# Pandas runs on every request so the "next 6 hours" calculation stays accurate.
_CACHE_TTL_SECONDS: float = 15 * 60  # 15 minutes

_cached_raw: Optional[dict] = None
_cached_expires_at: float = 0.0
_cache_lock: asyncio.Lock = asyncio.Lock()


async def _fetch_open_meteo() -> dict:
    """Fetches the raw response from Open-Meteo with robust error handling."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(_API_URL)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError:
        logger.exception("Open-Meteo returned non-2xx status")
        raise HTTPException(
            status_code=502,
            detail="Open-Meteo returned an error response",
        )
    except httpx.RequestError:
        logger.exception("Network/timeout failure contacting Open-Meteo")
        raise HTTPException(
            status_code=502,
            detail="Network failure obtaining solar radiation forecast",
        )
    except ValueError:
        # response.json() raises ValueError for non-JSON payloads
        logger.exception("Unexpected response from Open-Meteo (non-JSON)")
        raise HTTPException(
            status_code=502,
            detail="Invalid response from weather API",
        )


def _build_response(raw: dict) -> dict:
    """Filters 'next 6 hours' from the raw Open-Meteo response and converts to JSON-safe."""
    try:
        df = pd.DataFrame(raw["hourly"])
        df["time"] = pd.to_datetime(df["time"])

        now = pd.Timestamp.now()
        limit = now + pd.Timedelta(hours=6)
        next_6h = df[(df["time"] >= now) & (df["time"] <= limit)].copy()
    except (ValueError, KeyError):
        logger.exception("Unexpected structure in Open-Meteo response")
        raise HTTPException(
            status_code=502,
            detail="Unexpected structure in weather API response",
        )

    # Convert pd.Timestamp -> ISO string for JSON serialization
    if not next_6h.empty:
        next_6h["time"] = next_6h["time"].dt.strftime("%Y-%m-%dT%H:%M:%S")

    return {
        "location": "Groningen",
        "latitude": _LATITUDE,
        "longitude": _LONGITUDE,
        "forecast": next_6h.to_dict(orient="records"),
        "average_radiation": (
            float(next_6h["shortwave_radiation"].mean()) if not next_6h.empty else 0.0
        ),
    }


async def get_forecast() -> dict:
    """
    Returns the solar radiation forecast for Groningen for the next 6 hours.
    Uses a TTL cache (double-checked locking) to reduce calls to Open-Meteo.
    """
    global _cached_raw, _cached_expires_at

    now = time.monotonic()
    if _cached_raw is not None and now < _cached_expires_at:
        return _build_response(_cached_raw)

    async with _cache_lock:
        # Re-check inside the lock to prevent duplicate fetches under concurrency
        now = time.monotonic()
        if _cached_raw is not None and now < _cached_expires_at:
            return _build_response(_cached_raw)

        logger.info("Forecast cache expired or empty — fetching Open-Meteo")
        raw = await _fetch_open_meteo()
        _cached_raw = raw
        _cached_expires_at = now + _CACHE_TTL_SECONDS
        return _build_response(raw)


def clear_cache() -> None:
    """Clears the forecast cache (useful for tests)."""
    global _cached_raw, _cached_expires_at
    _cached_raw = None
    _cached_expires_at = 0.0
