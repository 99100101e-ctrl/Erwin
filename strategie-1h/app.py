"""
Erwin Strategy 1H — Web Service + Scanner Telegram.

Le scanner tourne dans un thread d'arriere-plan au demarrage.
Le Web Service expose /health et /signal pour garder le service actif.

Deploiement Render :
  Build  : pip install -r requirements.txt
  Start  : uvicorn app:app --host 0.0.0.0 --port $PORT
"""

import os
import threading

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

from signals.data_feed import fetch_ohlcv
from signals.strategy import generate_signals, get_latest_signal
from signals import config as cfg

# ── FastAPI ──────────────────────────────────────────────────

app = FastAPI(
    title="Erwin Strategy 1H",
    description="Signaux d'achat/vente BTC bases sur Ichimoku + ADX + filtres",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health", response_class=PlainTextResponse)
def health():
    return "OK"


@app.get("/signal")
def signal(symbol: str = "BTCUSDT", timeframe: str = "1h", limit: int = 300):
    """Retourne le signal courant et le dashboard."""
    df = fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)
    df = generate_signals(df)
    return get_latest_signal(df)


# ── Scanner en arriere-plan ──────────────────────────────────

def start_scanner_thread():
    """Lance le scanner dans un thread daemon."""
    from scanner import run_scanner
    thread = threading.Thread(target=run_scanner, daemon=True)
    thread.start()
    print("[APP] Scanner Telegram demarre en arriere-plan.")


@app.on_event("startup")
def on_startup():
    """Au demarrage du Web Service, lance le scanner Telegram."""
    if cfg.TELEGRAM_TOKEN and cfg.TELEGRAM_CHAT_ID:
        start_scanner_thread()
    else:
        print("[APP] TELEGRAM_TOKEN / TELEGRAM_CHAT_ID manquants — scanner non demarre.")


# ── Mode CLI ─────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
