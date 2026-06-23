"""
Electricity price service — mirrors the gold pattern of weather.py:
  - httpx.AsyncClient with timeout
  - in-memory cache + asyncio.Lock + double-checked locking
  - error handling with HTTPException 502
  - structured logging

The chosen API is EnergyZero (https://api.energyzero.nl/v1/energyprices):
  - public, no key/token required
  - native Europe/Amsterdam timezone
  - returns NL day-ahead prices per hour in €/kWh

We control VAT through the `inclBtw` URL param (we use inclBtw=true: the price
consumers actually pay). The decision logic works in €/MWh; we convert €/kWh
-> €/MWh by multiplying by 1000.

EnergyZero verified live against the public API on 2026-06-23.
"""

import asyncio
import logging
import time
import zoneinfo
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import pandas as pd
from fastapi import HTTPException

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.energyzero.nl/v1/energyprices"
_AMSTERDAM_TZ = zoneinfo.ZoneInfo("Europe/Amsterdam")

# In-memory cache + lock to avoid race conditions between concurrent requests.
_CACHE_TTL_SECONDS: float = 15 * 60  # 15 minutes

_cached_raw: Optional[dict] = None
_cached_expires_at: float = 0.0
_cache_lock: asyncio.Lock = asyncio.Lock()


def _build_url() -> str:
    """
    Builds the URL covering today + tomorrow in Europe/Amsterdam (formatted as UTC).

    EnergyZero v1 schema (verified live, replaces the legacy intervalType/priceType/outputMode
    trio that silently returns an empty Prices list):
      interval=4      numeric code (3 = 15min, 4 = 1hour)
      usageType=1     1 = Electricity, 3 = Gas
      inclBtw=true    include VAT (price consumers actually pay)
    """
    now_local = datetime.now(_AMSTERDAM_TZ)
    start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    # Window: [today 00:00 NL, day-after-tomorrow 23:59:59 NL]
    end_local = start + timedelta(days=2) - timedelta(microseconds=1)
    start_utc = start.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)
    return (
        f"{_BASE_URL}"
        f"?fromDate={start_utc.strftime('%Y-%m-%dT%H:%M:%S.000Z')}"
        f"&tillDate={end_utc.strftime('%Y-%m-%dT%H:%M:%S.000Z')}"
        f"&interval=4&usageType=1&inclBtw=true"
    )


async def _fetch_energyzero() -> dict:
    """Fetches the raw response from EnergyZero with robust error handling."""
    url = _build_url()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError:
        logger.exception("EnergyZero returned non-2xx status")
        raise HTTPException(
            status_code=502,
            detail="EnergyZero returned an error response",
        )
    except httpx.RequestError:
        logger.exception("Network/timeout failure contacting EnergyZero")
        raise HTTPException(
            status_code=502,
            detail="Network failure obtaining electricity price",
        )
    except ValueError:
        # response.json() raises ValueError for non-JSON payloads
        logger.exception("Unexpected response from EnergyZero (non-JSON)")
        raise HTTPException(
            status_code=502,
            detail="Invalid response from price API",
        )


def _pick_price_per_kwh(entry: dict) -> float:
    """
    Returns the €/kWh price from one EnergyZero entry.
    The current v1 API exposes a single `price` field per entry (VAT policy is
    controlled by the `inclBtw` URL parameter, not by field selection).
    """
    return float(entry["price"])


def _build_response(raw: dict) -> dict:
    """Extracts `current_price` + `hourly_forecast` from the EnergyZero response."""
    try:
        prices_list = raw["Prices"]
        if not isinstance(prices_list, list) or len(prices_list) == 0:
            raise ValueError("Empty prices list")
        df = pd.DataFrame(prices_list)
        df["readingDate"] = pd.to_datetime(df["readingDate"])
    except (ValueError, KeyError):
        logger.exception("Unexpected structure in EnergyZero response")
        raise HTTPException(
            status_code=502,
            detail="Unexpected structure in price API response",
        )

    # Filter from the current hour in Europe/Amsterdam (7 entries: current hour + 6 future)
    now_local = pd.Timestamp.now(tz=_AMSTERDAM_TZ.key).floor("h")
    next_hours = df[df["readingDate"] >= now_local].head(7).copy()

    if next_hours.empty:
        logger.error("No future price returned by EnergyZero (stale window?)")
        raise HTTPException(
            status_code=502,
            detail="No future prices in the price API response",
        )

    # Convert tz-aware Timestamp -> ISO string (JSON-safe)
    next_hours["readingDate"] = next_hours["readingDate"].dt.strftime("%Y-%m-%dT%H:%M:%S%z")

    # current_price: first entry (= current hour) in €/MWh (price_eur_kwh * 1000)
    current_price_eur_mwh = _pick_price_per_kwh(next_hours.iloc[0].to_dict()) * 1000.0

    return {
        "current_price_eur_mwh": current_price_eur_mwh,
        "hourly_forecast": next_hours.to_dict(orient="records"),
        "vat_included": True,
    }


async def get_current_price() -> dict:
    """
    Returns the current electricity price in €/MWh + hourly forecast (7h).
    TTL-cached via double-checked locking to reduce calls to EnergyZero.
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

        logger.info("Price cache expired or empty — fetching EnergyZero")
        raw = await _fetch_energyzero()
        _cached_raw = raw
        _cached_expires_at = now + _CACHE_TTL_SECONDS
        return _build_response(raw)


def clear_cache() -> None:
    """Clears the price cache (useful for tests)."""
    global _cached_raw, _cached_expires_at
    _cached_raw = None
    _cached_expires_at = 0.0
