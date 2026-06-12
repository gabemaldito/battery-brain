import httpx
import pandas from pandas
async def get_forecast():
    url= "https://api.open-meteo.com/v1/forecast?latitude=53.2194&longitude=6.5665&hourly=shortwave_radiation&forecast_days=1"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        return response.json()



