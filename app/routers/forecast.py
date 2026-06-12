from fastapi import APIRouter
from app.services.weather import get_forecast

router = APIRouter()

@router.get("/forecast")
async def forecast():
    dados_clima = await get_forecast()
    return dados_clima