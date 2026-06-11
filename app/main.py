from fastapi import FastAPI
from app.routers.forecast import router
from app.routers.decision import router as decision


app = FastAPI(
    title="Smart Battery Controller",
    description="API for Smart Battery Controller",
    version="1.0",
)

app.include_router(router, prefix="/api/v1")
app.include_router(decision, prefix="/api/v1")
@app.get("/")
async def root():
    return {"status": "Servidor ativo"}

