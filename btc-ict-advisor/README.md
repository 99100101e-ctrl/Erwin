# BTC ICT Advisor

Mobile-first BTC analysis dashboard using HugoFX ICT/SMC method.

## Stack
- Backend: FastAPI + uvicorn (Python 3.11, default port 8001)
- Frontend: React (port 3000)
- Data: Binance REST + Futures + Fear & Greed API

## Run (Windows)
1. `install.bat`
2. `LAUNCH.bat`

## API
- `GET /health`
- `GET /api/state`
- `GET /api/indicators`
- `POST /api/indicators`
- `GET /api/chart/{tf}` (`15m|1h|4h|1d|1w`)
- `GET /api/sessions`
- `GET /api/derivatives`
- `GET /api/onchain`
- `GET /api/backtest`
- `GET /api/history/status`

## Troubleshooting (offline / 503 / no chart)
1. Verify backend is reachable:
   - `http://localhost:8001/health`
   - `http://localhost:8001/api/state`
2. Frontend now tries multiple backend URLs automatically:
   - `http://<host>:8001` then `http://<host>:8000`, then localhost fallbacks.
3. If backend is not reachable, re-run `install.bat` (Python 3.11 required).
4. Backend starts immediately and loads history in background; during loading, frontend stays active and shows progress.
5. If Binance/Fear&Greed are blocked, backend auto-generates fallback candles so chart still appears.

> Not financial advice — for informational purposes only.
