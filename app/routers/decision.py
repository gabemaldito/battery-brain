import asyncio

from fastapi import APIRouter

from app.services.battery import decide_action
from app.services.price import get_current_price
from app.services.weather import get_forecast

router = APIRouter()


@router.get("/decision")
async def decision():
    """
    Retorna a decisão da bateria cruzando:
      - radiação solar atual + próximas 6h (Open-Meteo, via weather.get_forecast)
      - preço atual de eletricidade + próximas 7h (EnergyZero, via price.get_current_price)

    Sem input manual — ambos os dados vêm de APIs externas.
    Em caso de falha da API, retorna HTTPException 502 transparentemente.
    As duas chamadas HTTP são independentes e paralelizadas via asyncio.gather.
    """
    dados_clima, dados_preco = await asyncio.gather(
        get_forecast(),
        get_current_price(),
    )

    radiacao_media = dados_clima["average_radiation"]
    preco_atual = dados_preco["current_price_eur_mwh"]

    acao_final = decide_action(preco_atual, radiacao_media)

    return {
        "action": acao_final,
        "average_radiation": radiacao_media,
        "current_price": preco_atual,
        "hourly_forecast_price": dados_preco["hourly_forecast"],
    }
