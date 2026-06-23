"""
Serviço de preço de eletricidade — espelha o padrão gold de `weather.py`:
  - httpx.AsyncClient com timeout
  - cache em memória + asyncio.Lock + double-checked locking
  - tratamento de erros com HTTPException 502
  - logging estruturado

A API escolhida é a **EnergyZero** (https://api.energyzero.nl/v1/energy/prices):
  - pública, sem necessidade de chave/token
  - fuso Europe/Amsterdam nativo
  - retorna preços day-ahead do mercado NL em €/kWh (incl e excl VAT)

Como a lógica de decisão (`decide_action`) opera em €/MWh (50 e 150 €/MWh),
fazemos a conversão €/kWh -> €/MWh multiplicando por 1000.
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

_BASE_URL = "https://api.energyzero.nl/v1/energy/prices"
_AMSTERDAM_TZ = zoneinfo.ZoneInfo("Europe/Amsterdam")

# Cache em memória + lock para evitar race condition entre requests concorrentes.
_CACHE_TTL_SECONDS: float = 15 * 60  # 15 minutos

_cached_raw: Optional[dict] = None
_cached_expires_at: float = 0.0
_cache_lock: asyncio.Lock = asyncio.Lock()


def _build_url() -> str:
    """Monta a URL cobrindo hoje + amanhã em Europe/Amsterdam (formatado em UTC)."""
    now_local = datetime.now(_AMSTERDAM_TZ)
    start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=2)
    start_utc = start.astimezone(timezone.utc)
    end_utc = end.astimezone(timezone.utc)
    return (
        f"{_BASE_URL}"
        f"?fromDate={start_utc.strftime('%Y-%m-%dT%H:%M:%S.000Z')}"
        f"&tillDate={end_utc.strftime('%Y-%m-%dT%H:%M:%S.000Z')}"
        f"&intervalType=hour&priceType=ALL_IN&outputMode=JSON"
    )


async def _fetch_energyzero() -> dict:
    """Busca a resposta bruta do EnergyZero com tratamento robusto de erros."""
    url = _build_url()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError:
        logger.exception("EnergyZero retornou status não-2xx")
        raise HTTPException(
            status_code=502,
            detail="EnergyZero retornou resposta de erro",
        )
    except httpx.RequestError:
        logger.exception("Falha de rede/timeout ao contatar EnergyZero")
        raise HTTPException(
            status_code=502,
            detail="Falha de rede ao obter preço de eletricidade",
        )
    except ValueError:
        # response.json() lança ValueError para payloads não-JSON
        logger.exception("Resposta inesperada do EnergyZero (não-JSON)")
        raise HTTPException(
            status_code=502,
            detail="Resposta inválida da API de preço",
        )


def _pick_price_per_kwh(entry: dict) -> float:
    """
    Retorna o preço por kWh. Prefere `priceExVat` para alinhar com mercado
    industrial (€/MWh reflete preço atacadista, sem VAT do consumidor).
    Faz fallback para `price` se o campo não existir (resposta reduzida).
    """
    if "priceExVat" in entry and entry["priceExVat"] is not None:
        return float(entry["priceExVat"])
    return float(entry["price"])


def _build_response(raw: dict) -> dict:
    """Extrai `current_price` + `hourly_forecast` da resposta EnergyZero."""
    try:
        prices_list = raw["prices"]
        if not isinstance(prices_list, list) or len(prices_list) == 0:
            raise ValueError("Lista de preços vazia")
        df = pd.DataFrame(prices_list)
        df["date"] = pd.to_datetime(df["date"])
    except (ValueError, KeyError):
        logger.exception("Estrutura inesperada na resposta do EnergyZero")
        raise HTTPException(
            status_code=502,
            detail="Estrutura inesperada na resposta da API de preço",
        )

    # Filtra a partir da hora atual em Europe/Amsterdam (7 entradas: hora atual + 6 futuras)
    agora_local = pd.Timestamp.now(tz=_AMSTERDAM_TZ.key).floor("h")
    prox_horas = df[df["date"] >= agora_local].head(7).copy()

    if prox_horas.empty:
        logger.error("Nenhum preço futuro retornado pelo EnergyZero (janela expirada?)")
        raise HTTPException(
            status_code=502,
            detail="Sem preços futuros na resposta da API de preço",
        )

    # Converte Timestamp tz-aware → string ISO (JSON-safe)
    prox_horas["date"] = prox_horas["date"].dt.strftime("%Y-%m-%dT%H:%M:%S%z")

    # current_price: primeira entrada (= hora atual) em €/MWh (price_eur_kwh * 1000)
    current_price_eur_mwh = _pick_price_per_kwh(prox_horas.iloc[0].to_dict()) * 1000.0

    return {
        "current_price_eur_mwh": current_price_eur_mwh,
        "hourly_forecast": prox_horas.to_dict(orient="records"),
    }


async def get_current_price() -> dict:
    """
    Retorna o preço atual de eletricidade em €/MWh + forecast horário (7h).
    Cache com TTL via double-checked locking para reduzir chamadas à EnergyZero.
    """
    global _cached_raw, _cached_expires_at

    now = time.monotonic()
    if _cached_raw is not None and now < _cached_expires_at:
        return _build_response(_cached_raw)

    async with _cache_lock:
        # Re-checar dentro do lock para evitar fetches duplicados em concorrência
        now = time.monotonic()
        if _cached_raw is not None and now < _cached_expires_at:
            return _build_response(_cached_raw)

        logger.info("Cache de preço expirado ou vazio — buscando EnergyZero")
        raw = await _fetch_energyzero()
        _cached_raw = raw
        _cached_expires_at = now + _CACHE_TTL_SECONDS
        return _build_response(raw)


def clear_cache() -> None:
    """Limpa o cache de preços (util para testes)."""
    global _cached_raw, _cached_expires_at
    _cached_raw = None
    _cached_expires_at = 0.0
