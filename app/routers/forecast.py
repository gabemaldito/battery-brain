from fastapi import APIRouter


router = APIRouter()

@router.get("/forecast")
async def forecast():
    return {"message": "forecast em breve"}