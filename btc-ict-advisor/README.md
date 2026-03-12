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

## Troubleshooting (offline / no chart)
1. Verify backend is reachable:
   - Open `http://localhost:8001/api/state`
   - Open `http://localhost:8001/api/history/status`
2. If backend is not reachable, re-run `install.bat` (Python 3.11 required).
3. The backend now starts instantly and loads history in background; during loading, frontend stays online and shows progress.
4. If Binance/Fear&Greed are blocked, backend auto-generates fallback candles so chart still appears.
5. Frontend API host is auto-detected from current hostname (`http://<host>:8001`).

> Not financial advice — for informational purposes only.
