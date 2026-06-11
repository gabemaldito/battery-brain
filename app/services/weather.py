import requests

def get_forecast():
    url= "https://api.open-meteo.com/v1/forecast?latitude=-23.55&longitude=-46.63&current_weather=true"
    response = requests.get(url)
    return response.json()


api_dados = get_forecast()