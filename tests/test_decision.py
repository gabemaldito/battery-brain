"""
Testes de integração do endpoint público GET /api/v1/decision.

Valida que:
  - weather.get_forecast + price.get_current_price + battery.decide_action
    estão corretamente encadeados
  - Falha em qualquer serviço upstream resulta em HTTP 502 (sem preço-fantasma)
"""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.routers import decision as decision_router


def _fake_clima_payload():
    """Mock realista de get_forecast()."""
    return {
        "location": "Groningen",
        "latitude": 53.2194,
        "longitude": 6.5665,
        "forecast": [],
        "average_radiation": 405.0,  # > 400 para viabilizar CHARGE
    }


def _fake_preco_payload(price_eur_mwh: float = 30.0):
    """Mock realista de get_current_price()."""
    return {
        "current_price_eur_mwh": price_eur_mwh,
        "hourly_forecast": [
            {"date": "2026-06-23T14:00:00+0200", "price": 0.03, "priceInVat": 0.0363, "priceExVat": 0.03},
            {"date": "2026-06-23T15:00:00+0200", "price": 0.04, "priceInVat": 0.0484, "priceExVat": 0.04},
        ],
    }


@pytest.fixture
def client():
    """TestClient do FastAPI para o app principal."""
    return TestClient(app)


@pytest.fixture
def patch_decision_dependencies(monkeypatch):
    """
    Yield helper que patcha as REFERÊNCIAS em app.routers.decision (o consumidor).

    Importante: `from x import y` cria uma referência no módulo importador. Patchar
    no módulo fonte NÃO atualiza essa referência — por isso patchamos no destino.
    """
    def _patch(forecast=None, current_price=None):
        if forecast is not None:
            monkeypatch.setattr(decision_router, "get_forecast", forecast)
        if current_price is not None:
            monkeypatch.setattr(decision_router, "get_current_price", current_price)
    return _patch


# ---------- 1. Sucesso: encadeamento feliz ----------
def test_decision_success_returns_action_and_extras(client, patch_decision_dependencies):
    """Mock perfeito → /decision retorna action + average_radiation + current_price + hourly_forecast_price."""

    async def fake_forecast():
        return _fake_clima_payload()

    async def fake_price():
        return _fake_preco_payload(price_eur_mwh=30.0)

    patch_decision_dependencies(forecast=fake_forecast, current_price=fake_price)

    response = client.get("/api/v1/decision")

    assert response.status_code == 200
    body = response.json()
    # 30 < 50 AND 405 > 400 → CHARGE
    assert body["action"] == "CHARGE"
    assert body["average_radiation"] == 405.0
    assert body["current_price"] == pytest.approx(30.0)
    assert isinstance(body["hourly_forecast_price"], list)
    assert len(body["hourly_forecast_price"]) == 2


def test_decision_success_discharge(client, patch_decision_dependencies):
    """Preço alto → DISCHARGE."""

    async def fake_forecast():
        return {**_fake_clima_payload(), "average_radiation": 100.0}

    async def fake_price():
        return _fake_preco_payload(price_eur_mwh=200.0)

    patch_decision_dependencies(forecast=fake_forecast, current_price=fake_price)

    response = client.get("/api/v1/decision")

    assert response.status_code == 200
    assert response.json()["action"] == "DISCHARGE"


def test_decision_success_hold(client, patch_decision_dependencies):
    """Preço e radiação neutros → HOLD."""

    async def fake_forecast():
        return {**_fake_clima_payload(), "average_radiation": 200.0}

    async def fake_price():
        return _fake_preco_payload(price_eur_mwh=80.0)

    patch_decision_dependencies(forecast=fake_forecast, current_price=fake_price)

    response = client.get("/api/v1/decision")

    assert response.status_code == 200
    assert response.json()["action"] == "HOLD"


# ---------- 2. Falha em price → 502 (sem preço-fantasma) ----------
def test_decision_propagates_502_when_price_service_fails(client, patch_decision_dependencies):
    """Falha da EnergyZero → 502 transparente, NUNCA preço inventado."""

    async def fake_forecast():
        return _fake_clima_payload()

    async def fake_price_failure():
        raise HTTPException(status_code=502, detail="EnergyZero caiu")

    patch_decision_dependencies(forecast=fake_forecast, current_price=fake_price_failure)

    response = client.get("/api/v1/decision")

    assert response.status_code == 502
    # Garante que a resposta NÃO tem campos fabricador (preço/ação falsos)
    assert response.json() == {"detail": "EnergyZero caiu"}


# ---------- 3. Falha em weather → 502 ----------
def test_decision_propagates_502_when_weather_service_fails(client, patch_decision_dependencies):
    """Falha da Open-Meteo → 502 transparente."""

    async def fake_forecast_failure():
        raise HTTPException(status_code=502, detail="Open-Meteo caiu")

    async def fake_price():
        return _fake_preco_payload()

    patch_decision_dependencies(forecast=fake_forecast_failure, current_price=fake_price)

    response = client.get("/api/v1/decision")

    assert response.status_code == 502


# ---------- 4. Endpoint sem body (não aceita POST) ----------
def test_decision_does_not_accept_post_body(client):
    """Confirma que /decision é GET-only — sem input manual possível via POST."""
    response = client.post("/api/v1/decision", json={"energy_price": 200.0})
    # FastAPI retorna 405 Method Not Allowed quando rota é só GET
    assert response.status_code == 405
