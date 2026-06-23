import asyncio
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi import HTTPException

from app.services import weather
from app.services.weather import _API_URL, _fetch_open_meteo, clear_cache, get_forecast


def _fake_raw_payload():
    """Simulated Open-Meteo response with timestamps near 'now'."""
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    return {
        "hourly": {
            "time": [
                (now + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M")
                for i in range(8)
            ],
            "shortwave_radiation": [100, 200, 350, 480, 520, 460, 300, 150],
        }
    }


def _make_response(status_code: int, text: str = "") -> httpx.Response:
    """Builds a Response compatible with httpx >= 0.27 (explicit request)."""
    request = httpx.Request("GET", _API_URL)
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


@pytest.mark.asyncio
async def test_get_forecast_returns_serializable_json(monkeypatch):
    """pd.Timestamp MUST be converted to ISO string (critical production bug)."""
    monkeypatch.setattr(weather, "_fetch_open_meteo", _async_return(_fake_raw_payload()))

    result = await get_forecast()

    assert result["location"] == "Groningen"
    assert isinstance(result["forecast"], list)
    assert len(result["forecast"]) > 0

    for entry in result["forecast"]:
        assert isinstance(entry["time"], str), (
            f"Expected ISO str, got {type(entry['time'])}"
        )
        assert isinstance(entry["shortwave_radiation"], (int, float))


@pytest.mark.asyncio
async def test_get_forecast_caches_response(monkeypatch):
    """Second call within TTL MUST NOT re-run HTTP."""
    counter = {"calls": 0}

    async def fake_fetch():
        counter["calls"] += 1
        return _fake_raw_payload()

    monkeypatch.setattr(weather, "_fetch_open_meteo", fake_fetch)

    result1 = await get_forecast()
    result2 = await get_forecast()

    assert counter["calls"] == 1
    assert result1 == result2


@pytest.mark.asyncio
async def test_cache_expires_after_ttl(monkeypatch):
    """After TTL expires, a new call MUST re-fetch."""
    counter = {"calls": 0}

    async def fake_fetch():
        counter["calls"] += 1
        return _fake_raw_payload()

    monkeypatch.setattr(weather, "_fetch_open_meteo", fake_fetch)
    monkeypatch.setattr(weather, "_CACHE_TTL_SECONDS", 0.05)

    await get_forecast()
    assert counter["calls"] == 1

    await get_forecast()
    assert counter["calls"] == 1  # cache hit

    await asyncio.sleep(0.1)
    await get_forecast()
    assert counter["calls"] == 2  # cache expired


@pytest.mark.asyncio
async def test_concurrent_requests_fetch_only_once(monkeypatch):
    """Race condition: 5 concurrent requests should cause ONLY 1 fetch (thanks to lock)."""
    counter = {"calls": 0}

    async def slow_fetch():
        counter["calls"] += 1
        await asyncio.sleep(0.05)  # simulate network latency
        return _fake_raw_payload()

    monkeypatch.setattr(weather, "_fetch_open_meteo", slow_fetch)

    results = await asyncio.gather(*[get_forecast() for _ in range(5)])

    assert counter["calls"] == 1, (
        f"Expected 1 fetch for 5 concurrent requests, got {counter['calls']}"
    )
    assert all(r["location"] == "Groningen" for r in results)


@pytest.mark.asyncio
async def test_empty_window_returns_zero_average(monkeypatch):
    """If the 6h window has no data, average_radiation must be 0.0 (not NaN)."""
    old_payload = {
        "hourly": {
            "time": ["2000-01-01T10:00", "2000-01-01T11:00"],
            "shortwave_radiation": [500, 600],
        }
    }
    monkeypatch.setattr(weather, "_fetch_open_meteo", _async_return(old_payload))

    result = await get_forecast()

    assert result["forecast"] == []
    assert result["average_radiation"] == 0.0


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

    monkeypatch.setattr(weather.httpx, "AsyncClient", FakeClient)

    with pytest.raises(HTTPException) as exc_info:
        await _fetch_open_meteo()
    assert exc_info.value.status_code == 502
    assert "Network failure" in exc_info.value.detail


@pytest.mark.asyncio
async def test_non_2xx_response_raises_502(monkeypatch):
    """Non-2xx status from Open-Meteo must be converted to HTTPException 502."""

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            return _make_response(500, "internal error")

    monkeypatch.setattr(weather.httpx, "AsyncClient", FakeClient)

    with pytest.raises(HTTPException) as exc_info:
        await _fetch_open_meteo()
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_unexpected_payload_raises_502(monkeypatch):
    """Valid JSON but unexpected structure -> 502."""
    bad_payload = {"unexpected_key": []}  # missing "hourly"
    monkeypatch.setattr(weather, "_fetch_open_meteo", _async_return(bad_payload))

    with pytest.raises(HTTPException) as exc_info:
        await get_forecast()
    assert exc_info.value.status_code == 502
