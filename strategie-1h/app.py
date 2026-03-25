"""
Erwin Strategy 1H — Point d'entree principal.

Modes d'utilisation :
  1. CLI : python app.py              → affiche le signal courant
  2. API : uvicorn app:app --port 8000 → endpoint JSON /signal
"""

import json
import sys

# ── Mode CLI ──────────────────────────────────────────────────

def run_cli():
    from signals.data_feed import fetch_ohlcv
    from signals.strategy import generate_signals, get_latest_signal

    print("Erwin Strategy 1H — Analyse en cours...")
    df = fetch_ohlcv(limit=300)
    df = generate_signals(df)
    result = get_latest_signal(df)

    print(json.dumps(result, indent=2, default=str))

    sig = result["signal"]
    if sig:
        print(f"\n>>> SIGNAL {sig} detecte <<<")
        if result["sl"]:
            print(f"    Stop-Loss : {result['sl']:.2f}")
        if result["tp"]:
            print(f"    Take-Profit : {result['tp']:.2f}")
    else:
        print(f"\nPas de signal. Marche : {result['market_state']} | Score bull : {result['score_bull']}/9")

    return result


# ── Mode API (FastAPI) ────────────────────────────────────────

def create_app():
    """Cree l'application FastAPI (importee par uvicorn)."""
    try:
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
    except ImportError:
        return None

    from signals.data_feed import fetch_ohlcv
    from signals.strategy import generate_signals, get_latest_signal

    api = FastAPI(
        title="Erwin Strategy 1H",
        description="Signaux d'achat/vente BTC bases sur Ichimoku + ADX + filtres",
        version="1.0.0",
    )

    api.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @api.get("/signal")
    def signal(symbol: str = "BTCUSDT", timeframe: str = "1h", limit: int = 300):
        """Retourne le signal courant et le dashboard."""
        df = fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)
        df = generate_signals(df)
        return get_latest_signal(df)

    @api.get("/health")
    def health():
        return {"status": "ok", "strategy": "Erwin 1H"}

    return api


# FastAPI auto-detection pour uvicorn
app = create_app()

if __name__ == "__main__":
    run_cli()
