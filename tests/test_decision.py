"""
Integration tests for the public GET /api/v1/decision endpoint.

Validate that:
  - weather.get_forecast + price.get_current_price + battery.decide_action
    are correctly chained
  - Failure in any upstream service results in HTTP 502 (no phantom price)
"""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.routers import decision as decision_router


def _fake_clima_payload():
    """Realistic mock of get_forecast()."""
    return {
        "location": "Groningen",
        "latitude": 53.2194,
        "longitude": 6.5665,
        "forecast": [],
        "average_radiation": 405.0,  # > 400 to enable CHARGE
    }


def _fake_preco_payload(price_eur_mwh: float = 30.0):
    """Realistic mock of get_current_price()."""
    return {
        "current_price_eur_mwh": price_eur_mwh,
        "hourly_forecast": [
            {"date": "2026-06-23T14:00:00+0200", "price": 0.03, "priceInVat": 0.0363, "priceExVat": 0.03},
            {"date": "2026-06-23T15:00:00+0200", "price": 0.04, "priceInVat": 0.0484, "priceExVat": 0.04},
        ],
    }


@pytest.fixture
def client():
    """FastAPI TestClient for the main app."""
    return TestClient(app)


@pytest.fixture
def patch_decision_dependencies(monkeypatch):
    """
    Yields a helper that patches the REFERENCES inside app.routers.decision (the consumer).

    Important: `from x import y` creates a reference in the importing module.
    Patching the SOURCE module does NOT update that reference — hence we patch the target.
    """
    def _patch(forecast=None, current_price=None):
        if forecast is not None:
            monkeypatch.setattr(decision_router, "get_forecast", forecast)
        if current_price is not None:
            monkeypatch.setattr(decision_router, "get_current_price", current_price)
    return _patch


# ---------- 1. Success: happy path ----------
def test_decision_success_returns_action_and_extras(client, patch_decision_dependencies):
    """Perfect mock -> /decision returns action + average_radiation + current_price + hourly_forecast_price."""

    async def fake_forecast():
        return _fake_clima_payload()

    async def fake_price():
        return _fake_preco_payload(price_eur_mwh=30.0)

    patch_decision_dependencies(forecast=fake_forecast, current_price=fake_price)

    response = client.get("/api/v1/decision")

    assert response.status_code == 200
    body = response.json()
    # 30 < 50 AND 405 > 400 -> CHARGE
    assert body["action"] == "CHARGE"
    assert body["average_radiation"] == 405.0
    assert body["current_price"] == pytest.approx(30.0)
    assert isinstance(body["hourly_forecast_price"], list)
    assert len(body["hourly_forecast_price"]) == 2


def test_decision_success_discharge(client, patch_decision_dependencies):
    """High price -> DISCHARGE."""

    async def fake_forecast():
        return {**_fake_clima_payload(), "average_radiation": 100.0}

    async def fake_price():
        return _fake_preco_payload(price_eur_mwh=200.0)

    patch_decision_dependencies(forecast=fake_forecast, current_price=fake_price)

    response = client.get("/api/v1/decision")

    assert response.status_code == 200
    assert response.json()["action"] == "DISCHARGE"


def test_decision_success_hold(client, patch_decision_dependencies):
    """Neutral price and radiation -> HOLD."""

    async def fake_forecast():
        return {**_fake_clima_payload(), "average_radiation": 200.0}

    async def fake_price():
        return _fake_preco_payload(price_eur_mwh=80.0)

    patch_decision_dependencies(forecast=fake_forecast, current_price=fake_price)

    response = client.get("/api/v1/decision")

    assert response.status_code == 200
    assert response.json()["action"] == "HOLD"


# ---------- 2. Price failure -> 502 (no phantom price) ----------
def test_decision_propagates_502_when_price_service_fails(client, patch_decision_dependencies):
    """EnergyZero failure -> transparent 502, NEVER an invented price."""

    async def fake_forecast():
        return _fake_clima_payload()

    async def fake_price_failure():
        raise HTTPException(status_code=502, detail="EnergyZero crashed")

    patch_decision_dependencies(forecast=fake_forecast, current_price=fake_price_failure)

    response = client.get("/api/v1/decision")

    assert response.status_code == 502
    # Ensures the response has NO fabricated fields (no fake price/action)
    assert response.json() == {"detail": "EnergyZero crashed"}


# ---------- 3. Weather failure -> 502 ----------
def test_decision_propagates_502_when_weather_service_fails(client, patch_decision_dependencies):
    """Open-Meteo failure -> transparent 502."""

    async def fake_forecast_failure():
        raise HTTPException(status_code=502, detail="Open-Meteo crashed")

    async def fake_price():
        return _fake_preco_payload()

    patch_decision_dependencies(forecast=fake_forecast_failure, current_price=fake_price)

    response = client.get("/api/v1/decision")

    assert response.status_code == 502


# ---------- 4. No body endpoint (does not accept POST) ----------
def test_decision_does_not_accept_post_body(client):
    """Confirms /decision is GET-only — no manual input possible via POST."""
    response = client.post("/api/v1/decision", json={"energy_price": 200.0})
    # FastAPI returns 405 Method Not Allowed when route is GET-only
    assert response.status_code == 405
