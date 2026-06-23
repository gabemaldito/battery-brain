import asyncio
from datetime import datetime, timedelta
from typing import Optional

import httpx
import pandas as pd
import pytest
import zoneinfo
from fastapi import HTTPException

from app.services import price
from app.services.price import _fetch_energyzero, _pick_price_per_kwh, clear_cache, get_current_price

_AMSTERDAM = zoneinfo.ZoneInfo("Europe/Amsterdam")
_PRICE_EX_VAT_EUR_KWH = 0.07500  # 0.075 €/kWh * 1000 = 75 €/MWh


def _fake_energyzero_payload(
    *,
    missing_price_ex_vat: bool = False,
    hours_ahead: int = 8,
    base: str = "now",
) -> dict:
    """Simulated EnergyZero response with timestamps near 'now' in Europe/Amsterdam."""
    if base == "now":
        start = pd.Timestamp.now(tz=_AMSTERDAM).floor("h")
    elif base == "past":
        start = pd.Timestamp.now(tz=_AMSTERDAM).floor("h") - pd.Timedelta(days=2)
    else:
        raise ValueError(base)
    prices = []
    for i in range(hours_ahead):
        ts = start + pd.Timedelta(hours=i)
        entry = {
            "date": ts.isoformat(),
            "price": 0.08234,
            "priceInVat": 0.08234,
        }
        if not missing_price_ex_vat:
            entry["priceExVat"] = _PRICE_EX_VAT_EUR_KWH
        prices.append(entry)
    return {"Prices": prices}


def _make_response(status_code: int, text: str = "") -> httpx.Response:
    """Builds a Response compatible with httpx >= 0.27 (explicit request)."""
    request = httpx.Request("GET", "https://api.energyzero.nl/v1/energyprices")
    return httpx.Response(status_code, text=text, request=request)


def _async_return(value):
    """Helper: creates a coroutine that returns `value`."""

    async def _coro():
        return value

    return _coro


@pytest.fixture(autouse=True)
def _clear_cache_between_tests():
    """Ensures cache isolation across all tests in this module."""
    clear_cache()
    yield
    clear_cache()


# ---------- 1. JSON-safe serialization ----------
@pytest.mark.asyncio
async def test_get_current_price_returns_serializable_json(monkeypatch):
    """tz-aware Timestamp MUST be converted to ISO string (JSON-safe)."""
    monkeypatch.setattr(price, "_fetch_energyzero", _async_return(_fake_energyzero_payload()))

    result = await get_current_price()

    # current_price_eur_mwh present, derived from priceExVat
    assert "current_price_eur_mwh" in result
    assert isinstance(result["current_price_eur_mwh"], float)
    assert result["current_price_eur_mwh"] == pytest.approx(_PRICE_EX_VAT_EUR_KWH * 1000.0)

    assert isinstance(result["hourly_forecast"], list)
    assert len(result["hourly_forecast"]) == 7  # current hour + 6 future

    for entry in result["hourly_forecast"]:
        assert isinstance(entry["date"], str), (
            f"Expected ISO str, got {type(entry['date'])}"
        )
        assert isinstance(entry["price"], (int, float))


# ---------- 2. Cache hit ----------
@pytest.mark.asyncio
async def test_get_current_price_caches_response(monkeypatch):
    """Second call within TTL MUST NOT re-run HTTP."""
    counter = {"calls": 0}

    async def fake_fetch():
        counter["calls"] += 1
        return _fake_energyzero_payload()

    monkeypatch.setattr(price, "_fetch_energyzero", fake_fetch)

    result1 = await get_current_price()
    result2 = await get_current_price()

    assert counter["calls"] == 1
    assert result1 == result2


# ---------- 3. Cache TTL ----------
@pytest.mark.asyncio
async def test_cache_expires_after_ttl(monkeypatch):
    """After TTL expires, a new call MUST re-fetch."""
    counter = {"calls": 0}

    async def fake_fetch():
        counter["calls"] += 1
        return _fake_energyzero_payload()

    monkeypatch.setattr(price, "_fetch_energyzero", fake_fetch)
    monkeypatch.setattr(price, "_CACHE_TTL_SECONDS", 0.05)

    await get_current_price()
    assert counter["calls"] == 1

    await get_current_price()
    assert counter["calls"] == 1  # cache hit

    await asyncio.sleep(0.1)
    await get_current_price()
    assert counter["calls"] == 2  # cache expired


# ---------- 4. Race condition / lock ----------
@pytest.mark.asyncio
async def test_concurrent_requests_fetch_only_once(monkeypatch):
    """5 concurrent requests should cause ONLY 1 fetch (thanks to lock)."""
    counter = {"calls": 0}

    async def slow_fetch():
        counter["calls"] += 1
        await asyncio.sleep(0.05)
        return _fake_energyzero_payload()

    monkeypatch.setattr(price, "_fetch_energyzero", slow_fetch)

    results = await asyncio.gather(*[get_current_price() for _ in range(5)])

    assert counter["calls"] == 1, (
        f"Expected 1 fetch for 5 concurrent requests, got {counter['calls']}"
    )
    assert all("current_price_eur_mwh" in r for r in results)


# ---------- 5. Empty window ----------
@pytest.mark.asyncio
async def test_no_future_prices_raises_502(monkeypatch):
    """If EnergyZero only returns past prices, raise 502 (avoid phantom price)."""
    payload_past = _fake_energyzero_payload(base="past")
    monkeypatch.setattr(price, "_fetch_energyzero", _async_return(payload_past))

    with pytest.raises(HTTPException) as exc_info:
        await get_current_price()
    assert exc_info.value.status_code == 502
    assert "future" in exc_info.value.detail.lower()


# ---------- 6. Unit conversion ----------
@pytest.mark.asyncio
async def test_price_conversion_uses_price_ex_vat_when_available(monkeypatch):
    """If EnergyZero returns priceExVat, use it (wholesale market)."""
    payload = _fake_energyzero_payload(missing_price_ex_vat=False)
    monkeypatch.setattr(price, "_fetch_energyzero", _async_return(payload))

    result = await get_current_price()

    # 0.075 €/kWh * 1000 = 75 €/MWh
    assert result["current_price_eur_mwh"] == pytest.approx(75.0)


@pytest.mark.asyncio
async def test_price_conversion_falls_back_to_price_field(monkeypatch):
    """If priceExVat is absent, fall back to the price field."""
    payload = _fake_energyzero_payload(missing_price_ex_vat=True)
    monkeypatch.setattr(price, "_fetch_energyzero", _async_return(payload))

    result = await get_current_price()

    # 0.08234 €/kWh * 1000 = 82.34 €/MWh (rounded)
    assert result["current_price_eur_mwh"] == pytest.approx(82.34)


# ---------- 7. Network / HTTP errors ----------
@pytest.mark.asyncio
async def test_network_error_raises_502(monkeypatch):
    """httpx.RequestError must be converted to HTTPException 502."""

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(price.httpx, "AsyncClient", FakeClient)

    with pytest.raises(HTTPException) as exc_info:
        await _fetch_energyzero()
    assert exc_info.value.status_code == 502
    assert "network" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_non_2xx_response_raises_502(monkeypatch):
    """Non-2xx status from EnergyZero must be converted to HTTPException 502."""

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            return _make_response(500, "internal error")

    monkeypatch.setattr(price.httpx, "AsyncClient", FakeClient)

    with pytest.raises(HTTPException) as exc_info:
        await _fetch_energyzero()
    assert exc_info.value.status_code == 502


# ---------- 8. Malformed payload ----------
@pytest.mark.asyncio
async def test_unexpected_payload_raises_502(monkeypatch):
    """Valid JSON but unexpected structure -> 502."""
    bad_payload = {"unexpected_key": []}  # missing "Prices"
    monkeypatch.setattr(price, "_fetch_energyzero", _async_return(bad_payload))

    with pytest.raises(HTTPException) as exc_info:
        await get_current_price()
    assert exc_info.value.status_code == 502


# ---------- 9. Unit helper ----------
def test_pick_price_per_kwh_uses_price_ex_vat():
    """_pick_price_per_kwh prefers priceExVat (wholesale market)."""
    entry = {"price": 0.10, "priceExVat": 0.075}
    assert _pick_price_per_kwh(entry) == pytest.approx(0.075)


def test_pick_price_per_kwh_falls_back_to_price():
    """_pick_price_per_kwh falls back to price if priceExVat is absent."""
    entry = {"price": 0.08234}
    assert _pick_price_per_kwh(entry) == pytest.approx(0.08234)


# ---------- 10. Non-JSON response (ValueError path) ----------
@pytest.mark.asyncio
async def test_invalid_json_response_raises_502(monkeypatch):
    """response.json() raises ValueError when receiving non-JSON text -> 502."""

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            # Status 200 but invalid body: triggers ValueError in response.json()
            return _make_response(200, text="not json {{{")

    monkeypatch.setattr(price.httpx, "AsyncClient", FakeClient)

    with pytest.raises(HTTPException) as exc_info:
        await _fetch_energyzero()
    assert exc_info.value.status_code == 502
    assert "invalid" in exc_info.value.detail.lower() or "json" in exc_info.value.detail.lower()
