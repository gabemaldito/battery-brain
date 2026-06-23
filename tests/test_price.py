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
    """Resposta simulada do EnergyZero com horários próximos a 'agora' em Europe/Amsterdam."""
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
    return {"prices": prices}


def _make_response(status_code: int, text: str = "") -> httpx.Response:
    """Constrói Response compatível com httpx >= 0.27 (request explícito)."""
    request = httpx.Request("GET", "https://api.energyzero.nl/v1/energy/prices")
    return httpx.Response(status_code, text=text, request=request)


def _async_return(value):
    """Helper: cria uma coroutine que retorna `value`."""

    async def _coro():
        return value

    return _coro


@pytest.fixture(autouse=True)
def _clear_cache_between_tests():
    """Garante isolamento de cache entre todos os testes deste módulo."""
    clear_cache()
    yield
    clear_cache()


# ---------- 1. Serialização JSON-safe ----------
@pytest.mark.asyncio
async def test_get_current_price_returns_serializable_json(monkeypatch):
    """Timestamp tz-aware DEVE ser convertido para string ISO (JSON-safe)."""
    monkeypatch.setattr(price, "_fetch_energyzero", _async_return(_fake_energyzero_payload()))

    result = await get_current_price()

    # current_price_eur_mwh presente, derivado de priceExVat
    assert "current_price_eur_mwh" in result
    assert isinstance(result["current_price_eur_mwh"], float)
    assert result["current_price_eur_mwh"] == pytest.approx(_PRICE_EX_VAT_EUR_KWH * 1000.0)

    assert isinstance(result["hourly_forecast"], list)
    assert len(result["hourly_forecast"]) == 7  # hora atual + 6 futuras

    for entry in result["hourly_forecast"]:
        assert isinstance(entry["date"], str), (
            f"Esperava str ISO, recebi {type(entry['date'])}"
        )
        assert isinstance(entry["price"], (int, float))


# ---------- 2. Cache hit ----------
@pytest.mark.asyncio
async def test_get_current_price_caches_response(monkeypatch):
    """Segunda chamada dentro do TTL NÃO deve refazer HTTP."""
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
    """Após TTL expirar, uma nova chamada DEVE re-buscar."""
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
    assert counter["calls"] == 2  # cache expirou


# ---------- 4. Race condition / lock ----------
@pytest.mark.asyncio
async def test_concurrent_requests_fetch_only_once(monkeypatch):
    """5 requests simultâneos devem causar APENAS 1 fetch (gracas ao lock)."""
    counter = {"calls": 0}

    async def slow_fetch():
        counter["calls"] += 1
        await asyncio.sleep(0.05)
        return _fake_energyzero_payload()

    monkeypatch.setattr(price, "_fetch_energyzero", slow_fetch)

    results = await asyncio.gather(*[get_current_price() for _ in range(5)])

    assert counter["calls"] == 1, (
        f"Esperava 1 fetch para 5 requests concorrentes, obtive {counter['calls']}"
    )
    assert all("current_price_eur_mwh" in r for r in results)


# ---------- 5. Janela vazia ----------
@pytest.mark.asyncio
async def test_no_future_prices_raises_502(monkeypatch):
    """Se a EnergyZero só retorna preços passados, levanta 502 (evita preço-fantasma)."""
    payload_passado = _fake_energyzero_payload(base="past")
    monkeypatch.setattr(price, "_fetch_energyzero", _async_return(payload_passado))

    with pytest.raises(HTTPException) as exc_info:
        await get_current_price()
    assert exc_info.value.status_code == 502
    assert "futuros" in exc_info.value.detail.lower()


# ---------- 6. Conversão de unidades ----------
@pytest.mark.asyncio
async def test_price_conversion_uses_price_ex_vat_when_available(monkeypatch):
    """Se energyzero retorna priceExVat, usamos ele (mercado atacadista)."""
    payload = _fake_energyzero_payload(missing_price_ex_vat=False)
    monkeypatch.setattr(price, "_fetch_energyzero", _async_return(payload))

    result = await get_current_price()

    # 0.075 €/kWh * 1000 = 75 €/MWh
    assert result["current_price_eur_mwh"] == pytest.approx(75.0)


@pytest.mark.asyncio
async def test_price_conversion_falls_back_to_price_field(monkeypatch):
    """Se priceExVat ausente, usa o campo `price` (fallback)."""
    payload = _fake_energyzero_payload(missing_price_ex_vat=True)
    monkeypatch.setattr(price, "_fetch_energyzero", _async_return(payload))

    result = await get_current_price()

    # 0.08234 €/kWh * 1000 = 82.34 €/MWh (arredondado)
    assert result["current_price_eur_mwh"] == pytest.approx(82.34)


# ---------- 7. Erros de rede / HTTP ----------
@pytest.mark.asyncio
async def test_network_error_raises_502(monkeypatch):
    """httpx.RequestError deve ser convertido em HTTPException 502."""

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
    assert "rede" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_non_2xx_response_raises_502(monkeypatch):
    """Status não-2xx da EnergyZero deve ser convertido em HTTPException 502."""

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


# ---------- 8. Payload malformado ----------
@pytest.mark.asyncio
async def test_unexpected_payload_raises_502(monkeypatch):
    """Resposta JSON válida mas com estrutura inesperada → 502."""
    bad_payload = {"unexpected_key": []}  # sem "prices"
    monkeypatch.setattr(price, "_fetch_energyzero", _async_return(bad_payload))

    with pytest.raises(HTTPException) as exc_info:
        await get_current_price()
    assert exc_info.value.status_code == 502


# ---------- 9. Helper unitário ----------
def test_pick_price_per_kwh_uses_price_ex_vat():
    """_pick_price_per_kwh prefere priceExVat (mercado atacadista)."""
    entry = {"price": 0.10, "priceExVat": 0.075}
    assert _pick_price_per_kwh(entry) == pytest.approx(0.075)


def test_pick_price_per_kwh_falls_back_to_price():
    """_pick_price_per_kwh faz fallback em `price` se priceExVat ausente."""
    entry = {"price": 0.08234}
    assert _pick_price_per_kwh(entry) == pytest.approx(0.08234)


# ---------- 10. Resposta não-JSON (path ValueError) ----------
@pytest.mark.asyncio
async def test_invalid_json_response_raises_502(monkeypatch):
    """response.json() lança ValueError quando recebe texto não-JSON → 502."""

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            # Status 200 mas corpo inválido: dispara ValueError em response.json()
            return _make_response(200, text="not json {{{")

    monkeypatch.setattr(price.httpx, "AsyncClient", FakeClient)

    with pytest.raises(HTTPException) as exc_info:
        await _fetch_energyzero()
    assert exc_info.value.status_code == 502
    assert "inv" in exc_info.value.detail.lower() or "esperada" in exc_info.value.detail.lower() or "json" in exc_info.value.detail.lower()
