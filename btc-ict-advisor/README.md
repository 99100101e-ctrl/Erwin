# BTC ICT Advisor

Mobile-first BTC analysis dashboard using HugoFX ICT/SMC method.

## Stack
- Backend: FastAPI + uvicorn (Python 3.11, port 8001)
- Frontend: React (port 3000)
- Data: Binance REST + Futures + Fear & Greed API

## Run (Windows)
1. `install.bat`
2. `LAUNCH.bat`

## API
- `GET /api/state`
- `GET /api/indicators`
- `POST /api/indicators`
- `GET /api/chart/{tf}` (`15m|1h|4h|1d|1w`)
- `GET /api/sessions`
- `GET /api/derivatives`
- `GET /api/onchain`
- `GET /api/backtest`
- `GET /api/history/status`

## Troubleshooting
- If Binance/Fear&Greed APIs are unreachable, backend now generates fallback candles so the app still shows chart data.
- In UI header:
  - `API: ONLINE/OFFLINE` = frontend can/cannot reach backend.
  - `Feed: ONLINE/OFFLINE` = backend data feed status.
- Make sure the project path is exactly `D:\btc-ict-advisor` when using the provided `.bat` scripts.

> Not financial advice — for informational purposes only.
