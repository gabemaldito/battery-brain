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

# Cache em memória + lock para evitar race condition entre requests concorrentes.
# Pandas roda a cada request para que o cálculo "próximas 6h" permaneça preciso.
_CACHE_TTL_SECONDS: float = 15 * 60  # 15 minutos

_cached_raw: Optional[dict] = None
_cached_expires_at: float = 0.0
_cache_lock: asyncio.Lock = asyncio.Lock()


async def _fetch_open_meteo() -> dict:
    """Busca a resposta bruta da Open-Meteo com tratamento robusto de erros."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(_API_URL)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError:
        logger.exception(
            "Open-Meteo retornou status não-2xx"
        )
        raise HTTPException(
            status_code=502,
            detail="Open-Meteo retornou resposta de erro",
        )
    except httpx.RequestError:
        logger.exception("Falha de rede/timeout ao contatar Open-Meteo")
        raise HTTPException(
            status_code=502,
            detail="Falha de rede ao obter previsão de radiação solar",
        )
    except ValueError:
        # response.json() lança ValueError para payloads não-JSON
        logger.exception("Resposta inesperada da Open-Meteo (não-JSON)")
        raise HTTPException(
            status_code=502,
            detail="Resposta inválida da API de clima",
        )


def _build_response(raw: dict) -> dict:
    """Filtra 'próximas 6h' da resposta bruta Open-Meteo e converte para JSON-safe."""
    try:
        df = pd.DataFrame(raw["hourly"])
        df["time"] = pd.to_datetime(df["time"])

        agora = pd.Timestamp.now()
        limite = agora + pd.Timedelta(hours=6)
        prox_6h = df[(df["time"] >= agora) & (df["time"] <= limite)].copy()
    except (ValueError, KeyError):
        logger.exception("Estrutura inesperada na resposta da Open-Meteo")
        raise HTTPException(
            status_code=502,
            detail="Estrutura inesperada na resposta da API de clima",
        )

    # Converte pd.Timestamp -> string ISO para serialização JSON
    if not prox_6h.empty:
        prox_6h["time"] = prox_6h["time"].dt.strftime("%Y-%m-%dT%H:%M:%S")

    return {
        "location": "Groningen",
        "latitude": _LATITUDE,
        "longitude": _LONGITUDE,
        "forecast": prox_6h.to_dict(orient="records"),
        "average_radiation": (
            float(prox_6h["shortwave_radiation"].mean()) if not prox_6h.empty else 0.0
        ),
    }


async def get_forecast() -> dict:
    """
    Retorna a previsão de radiação solar para Groningen para as próximas 6 horas.
    Usa cache com TTL (double-checked locking) para reduzir chamadas à Open-Meteo.
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

        logger.info("Cache de forecast expirado ou vazio — buscando Open-Meteo")
        raw = await _fetch_open_meteo()
        _cached_raw = raw
        _cached_expires_at = now + _CACHE_TTL_SECONDS
        return _build_response(raw)


def clear_cache() -> None:
    """Limpa o cache de forecast (util para testes)."""
    global _cached_raw, _cached_expires_at
    _cached_raw = None
    _cached_expires_at = 0.0
