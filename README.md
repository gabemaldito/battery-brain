#  Battery Brain

A REST API built with **FastAPI** that acts as the decision-making engine for an industrial battery connected to a solar park in Groningen, Netherlands.

The API collects real-time solar radiation forecasts, crosses that data with current energy market prices, and returns an action command for the battery.

---

## How It Works

```
Solar Forecast (Open-Meteo API)
        +
Energy Market Price (POST body)
        ↓
    Pandas Processing
        ↓
  CHARGE / DISCHARGE / HOLD
```

### Decision Logic

| Condition | Action |
|---|---|
| Price < €50/MWh **and** Radiation > 400 W/m² | `CHARGE`   cheap energy + lots of sun |
| Price > €150/MWh | `DISCHARGE` — sell energy at peak price |
| Everything else | `HOLD`   wait for better conditions |

---

## 🛣️ Endpoints

### `GET /`
Health check.

```json
{ "status": "Servidor ativo" }
```

### `GET /api/v1/forecast`
Fetches solar radiation forecast for the next 6 hours in Groningen from the Open-Meteo API and returns cleaned data.

```json
{
  "location": "Groningen",
  "forecast": [
    { "time": "2026-06-13T10:00:00", "shortwave_radiation": 312 },
    { "time": "2026-06-13T11:00:00", "shortwave_radiation": 480 }
  ],
  "average_radiation": 396.0
}
```

### `POST /api/v1/decision`
Receives the current energy market price, fetches the solar forecast, and returns the battery action.

**Request body:**
```json
{ "energy_price": 200.0 }
```

**Response:**
```json
{
  "action": "DISCHARGE",
  "average_radiation": 49.67
}
```

---

## 🚀 Running Locally

**1. Clone the repository**
```bash
git clone https://github.com/gabemaldito/battery-brain.git
cd battery-brain
```

**2. Create and activate virtual environment**
```bash
python -m venv .venv

# macOS/Linux
source .venv/bin/activate

# Windows
.venv\Scripts\Activate.ps1
```

**3. Install dependencies**
```bash
pip install -r requirements.txt
```

**4. Start the server**
```bash
uvicorn app.main:app --reload
```

**5. Open the interactive docs**
```
http://127.0.0.1:8000/docs
```

---

## 🧰 Tech Stack

- **[FastAPI](https://fastapi.tiangolo.com/)**  modern Python web framework
- **[Uvicorn](https://www.uvicorn.org/)**  ASGI server
- **[httpx](https://www.python-httpx.org/)**  async HTTP client
- **[Pandas](https://pandas.pydata.org/)**  data processing
- **[Open-Meteo API](https://open-meteo.com/)**  free solar radiation forecast

---

## 📁 Project Structure

```
battery-brain/
├── app/
│   ├── main.py
│   ├── routers/
│   │   ├── forecast.py
│   │   └── decision.py
│   └── services/
│       ├── weather.py
│       └── battery.py
├── requirements.txt
└── README.md
```

---

## 👤 Author

Gabriel Cardoso — [gabrielcardosodev.com](https://gabrielcardosodev.com) · [GitHub](https://github.com/gabemaldito)
