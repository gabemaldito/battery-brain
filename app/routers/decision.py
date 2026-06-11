from fastapi import APIRouter


router = APIRouter()

@router.post("/decision")
async def decision():
    return {"action": "HOLD"}