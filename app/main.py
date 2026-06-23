import logging

from fastapi import FastAPI

from app.routers.forecast import router as forecast_router
from app.routers.decision import router as decision_router

# Basic logging configuration — visible in production (Railway) and locally
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


app = FastAPI(
    title="Smart Battery Controller",
    description="API for Smart Battery Controller",
    version="1.1",
)

app.include_router(forecast_router, prefix="/api/v1")
app.include_router(decision_router, prefix="/api/v1")


@app.get("/")
async def root():
    logger.debug("Health check accessed")
    return {"status": "Server running"}
