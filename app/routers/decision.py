from fastapi import APIRouter
from app.services.weather import get_forecast
from app.services.battery import decide_action
from pydantic import BaseModel


router = APIRouter()
class DecisionRequest(BaseModel):
    energy_price: float
    
@router.post("/decision")
async def decision(body: DecisionRequest):
    dados_clima = await get_forecast()
    radiacao_media = dados_clima["average_radiation"]
    acao_final = decide_action(radiacao_media, body.energy_price)
    return {"action": acao_final}4                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      