# 🔋 Battery Brain

A REST API built with **FastAPI** that acts as the decision-making engine for an industrial battery connected to a solar park in Groningen, Netherlands.

The API consumes real-time **solar radiation** (Open-Meteo) and **electricity price** (EnergyZero) data automatically, then returns a battery action command. **No manual inputs** — the dashboard never relies on a typed or hard-coded value.

---

## 🌐 Live Demo

https://gabemaldito.github.io/energy-dashboard/

[https://battery-brain-production.up.railway.app/docs](https://battery-brain-production.up.railway.app/docs)

## How It Works

```
Solar Radiation  ─┐
                  │  (no manual input — both come from public APIs)
NL Day-Ahead Price ┘
                  ↓
          Pandas Processing
                  ↓
       CHARGE / DISCHARGE / HOLD
```

### Decision Logic

| Condition | Action |
|---|---|
| Price < €50/MWh **and** Radiation > 400 W/m² | `CHARGE` — cheap energy + lots of sun |
| Price > €150/MWh | `DISCHARGE` — sell energy at peak price |
| Everything else | `HOLD` — wait for better conditions |

Both inputs are fetched automatically. The dashboard never sees a "typed" or stale value — if either API fails, the request returns HTTP 502 (no phantom data).

---

## 🛣️ Endpoints

### `GET /`
Health check.

```json
{ "status": "Server running" }
```

### `GET /api/v1/forecast`
Fetches solar radiation forecast for the next 6 hours in Groningen from the Open-Meteo API and returns cleaned data.

```json
{
  "location": "Groningen",
  "latitude": 53.2194,
  "longitude": 6.5665,
  "forecast": [
    { "time": "2026-06-13T10:00:00", "shortwave_radiation": 312 },
    { "time": "2026-06-13T11:00:00", "shortwave_radiation": 480 }
  ],
  "average_radiation": 396.0
}
```

### `GET /api/v1/decision`
**No body.** Combines the current solar radiation forecast with the **current Dutch day-ahead electricity price** (fetched automatically from EnergyZero) and returns the recommended battery action.

```json
{
  "action": "DISCHARGE",
  "average_radiation": 49.67,
  "current_price": 187.42,
  "hourly_forecast_price": [
    { "readingDate": "2026-06-23T14:00:00+0200", "price": 0.18742 },
    { "readingDate": "2026-06-23T15:00:00+0200", "price": 0.19000 }
  ]
}
```

> **Note:** Prices in `hourly_forecast_price` are VAT-inclusive (`inclBtw=true`). To convert to € / MWh, multiply `price` by 1000. The legacy `priceExVat` / `priceInVat` fields were removed when tracking the EnergyZero v1 API migration.
```

If the EnergyZero price API **or** the Open-Meteo solar API is unreachable, the endpoint returns **HTTP 502** — never a fabricated or cached-stale price.

---

## 🎨 Frontend Integration

This API is ready to be consumed from **any browser, mobile, or CLI client**.

### Base URLs

| Env | URL |
|---|---|
| Production | `https://battery-brain-production.up.railway.app` |
| Local dev  | `http://127.0.0.1:8000` |

### CORS

`CORSMiddleware` is enabled globally. Default allowed origins cover popular frontend dev servers out of the box:

- `http://localhost:3000` (Next.js / Create React App)
- `http://localhost:5173` (Vite)
- `http://localhost:8080` (Vue CLI)
- `http://localhost:4200` (Angular)
- `http://127.0.0.1:{3000,5173,8080,4200}`

For production, override using the `CORS_ALLOWED_ORIGINS` environment variable (comma-separated):

```bash
CORS_ALLOWED_ORIGINS="https://my-dashboard.example.com,https://www.example.com"
```

### Quick cURL

```bash
curl https://battery-brain-production.up.railway.app/api/v1/decision
```

### Generate a typed client

The full OpenAPI spec is at **`/openapi.json`**. You can generate strongly-typed clients in your preferred language:

```bash
# TypeScript (types only)
npx openapi-typescript https://battery-brain-production.up.railway.app/openapi.json \
  -o battery-brain-types.ts

# TypeScript (full axios-based client)
npx openapi-typescript-codegen \
  --input https://battery-brain-production.up.railway.app/openapi.json \
  --output ./src/api
```

Interactive docs:

- **Swagger UI** → `/docs`
- **ReDoc**      → `/redoc`

### Authentication

The current deployment is **public / unauthenticated** for demo purposes. For a production frontend, add a Bearer-token or API-key middleware to `app/main.py` before exposing publicly.

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

- **[FastAPI](https://fastapi.tiangolo.com/)** — modern Python web framework
- **[Uvicorn](https://www.uvicorn.org/)** — ASGI server
- **[httpx](https://www.python-httpx.org/)** — async HTTP client
- **[Pandas](https://pandas.pydata.org/)** — data processing
- **[Open-Meteo API](https://open-meteo.com/)** — free solar radiation forecast
- **[EnergyZero API](https://www.energyzero.nl/)** — Dutch day-ahead electricity price (public, no key)

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
│       ├── weather.py   # Open-Meteo solar radiation service
│       ├── price.py     # EnergyZero electricity price service
│       └── battery.py   # Pure decision logic (no I/O)
├── tests/
│   ├── test_battery.py
│   ├── test_weather.py
│   └── test_price.py
├── pytest.ini
├── requirements.txt
└── README.md
```

---

## 👤 Author

Gabriel Cardoso — [gabrielcardosodev.com](https://gabrielcardosodev.com) · [GitHub](https://github.com/gabemaldito)
