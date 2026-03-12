from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from models import IndicatorSettingsUpdate
from services.engine import AdvisorEngine

app = FastAPI(title="BTC ICT Advisor", version="0.1.0")
engine = AdvisorEngine()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    await engine.initialize()


@app.get("/api/state")
async def get_state() -> dict:
    return await engine.get_state()


@app.get("/api/indicators")
async def get_indicators() -> dict:
    return engine.indicator_registry()


@app.post("/api/indicators")
async def post_indicators(payload: IndicatorSettingsUpdate) -> dict:
    return engine.update_indicator_settings(payload)


@app.get("/api/chart/{tf}")
async def get_chart(tf: str) -> dict:
    if tf not in {"15m", "1h", "4h", "1d", "1w"}:
        raise HTTPException(status_code=400, detail="Unsupported timeframe")
    return await engine.chart_data(tf)


@app.get("/api/sessions")
async def get_sessions() -> dict:
    return engine.session_info()


@app.get("/api/derivatives")
async def get_derivatives() -> dict:
    return await engine.derivatives_state()


@app.get("/api/onchain")
async def get_onchain() -> dict:
    return await engine.onchain_state()


@app.get("/api/backtest")
async def get_backtest() -> dict:
    return await engine.backtest_summary()


@app.get("/api/history/status")
async def get_history_status() -> dict:
    return engine.history_status()
