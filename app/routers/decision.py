import asyncio

from fastapi import APIRouter

from app.services.battery import decide_action
from app.services.price import get_current_price
from app.services.weather import get_forecast

router = APIRouter()


@router.get("/decision")
async def decision():
    """
    Returns the battery decision by combining:
      - current solar radiation + next 6h (Open-Meteo, via weather.get_forecast)
      - current electricity price + next 7h (EnergyZero, via price.get_current_price)

    No manual input — both data points come from external APIs.
    On API failure, returns HTTPException 502 transparently.
    The two HTTP calls are independent and parallelized via asyncio.gather.
    """
    weather_data, price_data = await asyncio.gather(
        get_forecast(),
        get_current_price(),
    )

    average_radiation = weather_data["average_radiation"]
    current_price = price_data["current_price_eur_mwh"]

    final_action = decide_action(current_price, average_radiation)

    return {
        "action": final_action,
        "average_radiation": average_radiation,
        "current_price": current_price,
        "hourly_forecast_price": price_data["hourly_forecast"],
    }
