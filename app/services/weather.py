import httpx
import pandas as pd

async def get_forecast():
    url= "https://api.open-meteo.com/v1/forecast?latitude=53.2194&longitude=6.5665&hourly=shortwave_radiation&forecast_days=1"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        dados = response.json()
        df =pd.DataFrame(dados["hourly"])
        df['time'] = pd.to_datetime(df['time'])
        
        agora = pd.Timestamp.now()
        limite = agora + pd.Timedelta(hours=6)
        
        prox_6h =df[(df['time'] >= agora) & (df['time'] <= limite)]
        
        return {
            "location": "Groningen",
            "forecast": prox_6h.to_dict(orient="records"),
            "average_radiation": prox_6h["shortwave_radiation"].mean()
        }



