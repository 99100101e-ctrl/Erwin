"""
BTC Trading Advisor — FastAPI Backend
Connects to Binance WebSocket for live BTCUSDT spot data.
Calculates indicators and emits trading signals every 60 seconds.
"""
import asyncio
import json
import logging
import random
import socket
import time
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

import httpx
import uvicorn
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from indicators import calculate_all_indicators
from signal_engine import SignalEngine

# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("btc-advisor")

app = FastAPI(title="BTC Trading Advisor", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Candle storage — rolling windows
MAX_CANDLES = 250  # enough for EMA200


class CandleStore:
    def __init__(self):
        self.candles_1h: deque = deque(maxlen=MAX_CANDLES)
        self.candles_4h: deque = deque(maxlen=MAX_CANDLES)
        # Each candle: {ts, open, high, low, close, volume}
        self._current_1h: Optional[Dict] = None
        self._current_4h: Optional[Dict] = None

    def update_from_kline(self, candle_data: Dict, interval_sec: int):
        """Process a kline update. Prices are already in USD (no conversion needed)."""
        ts = candle_data.get("t", 0)  # open time in seconds
        o = float(candle_data.get("o", 0))
        h = float(candle_data.get("h", 0))
        l = float(candle_data.get("l", 0))
        c = float(candle_data.get("c", 0))
        v = float(candle_data.get("v", 0))
        is_closed = candle_data.get("closed", False)

        if c < 1000:  # sanity check — ignore garbage data
            return

        candle = {"ts": ts, "open": o, "high": h, "low": l, "close": c, "volume": v}

        if interval_sec == 3600:
            if is_closed:
                self.candles_1h.append(candle)
            self._current_1h = candle
        elif interval_sec == 14400:
            if is_closed:
                self.candles_4h.append(candle)
            self._current_4h = candle

    def get_lists(self):
        """Return (closes_1h, highs_1h, lows_1h, vols_1h, closes_4h, ...) as lists."""
        c1 = list(self.candles_1h)
        c4 = list(self.candles_4h)
        if self._current_1h:
            c1 = c1 + [self._current_1h]
        if self._current_4h:
            c4 = c4 + [self._current_4h]

        def extract(candles, key):
            return [x[key] for x in candles]

        return (
            extract(c1, "close"),
            extract(c1, "high"),
            extract(c1, "low"),
            extract(c1, "volume"),
            extract(c4, "close"),
            extract(c4, "high"),
            extract(c4, "low"),
            extract(c4, "volume"),
        )


candle_store = CandleStore()
signal_engine = SignalEngine()

# Current state broadcast to all WebSocket clients
state: Dict = {
    "price": None,
    "price_change_24h": None,
    "volume_24h": None,
    "indicators": {},
    "signal": {},
    "fear_greed": None,
    "market_phase": "Unknown",
    "trend_1h": "Neutral",
    "trend_4h": "Neutral",
    "trend_1d": "Neutral",
    "volatility_level": "Low",
    "signal_history": [],
    "candles_1h": [],
    "candles_4h": [],
    "last_update": None,
    "connected": False,
}

connected_clients: Set[WebSocket] = set()

# ---------------------------------------------------------------------------
# Historical data seeding


async def seed_historical_data():
    """Seed candle store with historical OHLCV data before WS connects."""
    log.info("=== Seeding historical candle data ===")

    # --- Primary: Binance REST API ---
    log.info("Fetching 1h candles from Binance REST...")
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            # 1h candles
            resp = await client.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": "BTCUSDT", "interval": "1h", "limit": 200},
            )
            rows = resp.json()
            # Format: [open_time_ms, open, high, low, close, volume, ...]
            for row in rows:
                if len(row) >= 6:
                    ts_ms = row[0]
                    o, h, l, c, v = float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])
                    if c > 1000:
                        candle_store.candles_1h.append({
                            "ts": ts_ms // 1000,
                            "open": o, "high": h, "low": l, "close": c, "volume": v,
                        })
            log.info(f"Binance REST: seeded {len(candle_store.candles_1h)} 1h candles")

            if len(candle_store.candles_1h) >= 30:
                # 4h candles
                resp4h = await client.get(
                    "https://api.binance.com/api/v3/klines",
                    params={"symbol": "BTCUSDT", "interval": "4h", "limit": 200},
                )
                rows4h = resp4h.json()
                for row in rows4h:
                    if len(row) >= 6:
                        ts_ms = row[0]
                        o, h, l, c, v = float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])
                        if c > 1000:
                            candle_store.candles_4h.append({
                                "ts": ts_ms // 1000,
                                "open": o, "high": h, "low": l, "close": c, "volume": v,
                            })
                log.info(f"Binance REST: seeded {len(candle_store.candles_4h)} 4h candles")
                log.info("Binance historical data ready — calculating initial indicators")
                await update_indicators_and_signal()
                return

    except Exception as e:
        log.warning(f"Binance REST seed failed: {e}")

    # --- Fallback: CoinGecko OHLC ---
    log.info("Falling back to CoinGecko for historical data...")
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                "https://api.coingecko.com/api/v3/coins/bitcoin/ohlc",
                params={"vs_currency": "usd", "days": 30},
            )
            ohlc = resp.json()
            # Format: [[timestamp_ms, open, high, low, close], ...]
            for row in ohlc:
                if len(row) >= 5:
                    ts_ms, o, h, l, c = row[:5]
                    if float(c) > 1000:
                        candle_store.candles_1h.append({
                            "ts": ts_ms // 1000,
                            "open": float(o), "high": float(h),
                            "low": float(l), "close": float(c), "volume": 0.0,
                        })
            log.info(f"CoinGecko: seeded {len(candle_store.candles_1h)} candles")

            if len(candle_store.candles_1h) >= 30:
                c1_list = list(candle_store.candles_1h)
                for i in range(0, len(c1_list) - 3, 4):
                    chunk = c1_list[i:i + 4]
                    candle_store.candles_4h.append({
                        "ts": chunk[0]["ts"],
                        "open": chunk[0]["open"],
                        "high": max(x["high"] for x in chunk),
                        "low": min(x["low"] for x in chunk),
                        "close": chunk[-1]["close"],
                        "volume": sum(x["volume"] for x in chunk),
                    })
                log.info(f"CoinGecko: derived {len(candle_store.candles_4h)} 4h candles")
                await update_indicators_and_signal()
                return
    except Exception as e:
        log.warning(f"CoinGecko seed failed: {e}")

    # --- Last resort: synthetic data for UI demo ---
    log.warning("All external APIs unavailable — generating synthetic demo data")
    random.seed(42)
    base_ts = int(time.time()) - 200 * 3600
    price = 83000.0
    for i in range(200):
        ts = base_ts + i * 3600
        price = price * (1 + random.gauss(0, 0.008))
        spread = price * random.uniform(0.002, 0.008)
        c = price * (1 + random.gauss(0, 0.003))
        candle_store.candles_1h.append({
            "ts": ts, "open": price,
            "high": price + spread, "low": price - spread,
            "close": c, "volume": random.uniform(500, 2000),
        })
        price = c
    c1_list = list(candle_store.candles_1h)
    for i in range(0, len(c1_list) - 3, 4):
        chunk = c1_list[i:i + 4]
        candle_store.candles_4h.append({
            "ts": chunk[0]["ts"], "open": chunk[0]["open"],
            "high": max(x["high"] for x in chunk),
            "low": min(x["low"] for x in chunk),
            "close": chunk[-1]["close"],
            "volume": sum(x["volume"] for x in chunk),
        })
    log.info(f"Synthetic: {len(candle_store.candles_1h)} 1h + {len(candle_store.candles_4h)} 4h candles")
    state["price"] = candle_store.candles_1h[-1]["close"]
    await update_indicators_and_signal()


# ---------------------------------------------------------------------------
# Fear & Greed


async def fetch_fear_greed():
    """Fetch Fear & Greed index from alternative.me."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://api.alternative.me/fng/?limit=1")
            data = resp.json()
            entry = data["data"][0]
            return {
                "value": int(entry["value"]),
                "classification": entry["value_classification"],
                "timestamp": entry["timestamp"],
            }
    except Exception as e:
        log.warning(f"Fear & Greed fetch failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Broadcast helpers


async def broadcast(message: Dict):
    """Send JSON message to all connected WebSocket clients."""
    if not connected_clients:
        return
    data = json.dumps(message)
    dead = set()
    for ws in list(connected_clients):
        try:
            await ws.send_text(data)
        except Exception:
            dead.add(ws)
    connected_clients.difference_update(dead)


# ---------------------------------------------------------------------------
# Binance WebSocket connection
#
# Combined stream: ticker (live price + 24h stats) + 1h kline + 4h kline
# URL format: wss://stream.binance.com:9443/stream?streams=<s1>/<s2>/...
# Each message: {"stream": "<name>", "data": {...}}

BINANCE_WS_URL = (
    "wss://stream.binance.com:9443/stream"
    "?streams=btcusdt@ticker/btcusdt@kline_1h/btcusdt@kline_4h"
)


async def binance_connect():
    """Maintain persistent connection to Binance WebSocket combined stream."""
    backoff = 2
    while True:
        try:
            log.info("Connecting to Binance WebSocket combined stream...")
            async with websockets.connect(
                BINANCE_WS_URL,
                ping_interval=20,
                ping_timeout=30,
                close_timeout=10,
            ) as ws:
                state["connected"] = True
                backoff = 2
                log.info("Connected: btcusdt@ticker + btcusdt@kline_1h + btcusdt@kline_4h")

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        await handle_binance_message(msg)
                    except Exception as e:
                        log.error(f"Error handling Binance message: {e}")

        except Exception as e:
            state["connected"] = False
            log.error(f"Binance WS error: {e}. Reconnecting in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


async def handle_binance_message(msg: Dict):
    """Process incoming Binance combined stream message."""
    stream = msg.get("stream", "")
    data = msg.get("data", msg)  # combined stream wraps in {stream, data}
    event = data.get("e", "")

    # --- 24hr ticker — live price, 24h change, volume ---
    # stream: btcusdt@ticker  |  event: 24hrTicker
    if event == "24hrTicker":
        price_str = data.get("c", "0")  # last price
        price = float(price_str)
        if price > 1000:
            state["price"] = price
            state["last_update"] = datetime.now(timezone.utc).isoformat()
            change_pct = data.get("P")  # percent change string, e.g. "1.23"
            state["price_change_24h"] = float(change_pct) / 100 if change_pct else None
            state["volume_24h"] = data.get("v")  # base asset volume string
            log.debug(f"Ticker: {price:.2f} ({change_pct}%)")
            await broadcast({"type": "price", "price": price, "ts": time.time()})
        return

    # --- Kline update — 1h and 4h candles ---
    # stream: btcusdt@kline_1h or btcusdt@kline_4h  |  event: kline
    if event == "kline":
        k = data.get("k", {})
        interval = k.get("i", "")  # "1h" or "4h"
        if interval == "1h":
            interval_sec = 3600
        elif interval == "4h":
            interval_sec = 14400
        else:
            return

        candle = {
            "t": k["t"] // 1000,   # open time ms → seconds
            "o": k.get("o", "0"),
            "h": k.get("h", "0"),
            "l": k.get("l", "0"),
            "c": k.get("c", "0"),
            "v": k.get("v", "0"),
            "closed": k.get("x", False),  # True when candle is closed/complete
        }
        candle_store.update_from_kline(candle, interval_sec)
        log.info(
            f"Kline {interval} — closed={k.get('x')}, close={k.get('c')}, "
            f"1h_count={len(candle_store.candles_1h)}"
        )
        await update_indicators_and_signal()
        return


async def update_indicators_and_signal():
    """Recalculate all indicators and evaluate signal."""
    (
        closes_1h, highs_1h, lows_1h, vols_1h,
        closes_4h, highs_4h, lows_4h, vols_4h,
    ) = candle_store.get_lists()

    if len(closes_1h) < 30:
        log.info(f"Not enough candles yet: {len(closes_1h)} 1h (need 30)")
        return

    try:
        indicators = calculate_all_indicators(
            closes_1h, highs_1h, lows_1h, vols_1h,
            closes_4h, highs_4h, lows_4h, vols_4h,
        )
        state["indicators"] = indicators

        emas_1h = indicators.get("emas_1h") or {}
        emas_4h = indicators.get("emas_4h") or {}
        state["trend_1h"] = _assess_trend(emas_1h, closes_1h[-1] if closes_1h else None)
        state["trend_4h"] = _assess_trend(emas_4h, closes_4h[-1] if closes_4h else None)
        state["market_phase"] = indicators.get("market_phase", "Unknown")

        atr_pct = indicators.get("atr_pct")
        if atr_pct is None or atr_pct < 1.0:
            state["volatility_level"] = "Low"
        elif atr_pct < 1.5:
            state["volatility_level"] = "Medium"
        elif atr_pct < 2.5:
            state["volatility_level"] = "High"
        else:
            state["volatility_level"] = "Extreme"

        price = state.get("price") or (closes_1h[-1] if closes_1h else None)
        if price and not state["price"]:
            state["price"] = price

        signal = {}
        if price:
            signal = signal_engine.evaluate(indicators, price)
            state["signal"] = signal
            state["signal_history"] = signal_engine.signal_history

        state["candles_1h"] = list(candle_store.candles_1h)[-100:]
        state["last_update"] = datetime.now(timezone.utc).isoformat()

        price_str = f"{price:.0f}" if price else "N/A"
        log.info(
            f"Indicators updated — price={price_str}, "
            f"1h={len(closes_1h)}, 4h={len(closes_4h)}, "
            f"trend={state['trend_1h']}, phase={state['market_phase']}"
        )

        await broadcast({
            "type": "update",
            "price": price,
            "indicators": _serialize_indicators(indicators),
            "signal": signal,
            "market_phase": state["market_phase"],
            "trend_1h": state["trend_1h"],
            "trend_4h": state["trend_4h"],
            "volatility_level": state["volatility_level"],
            "signal_history": state["signal_history"],
            "candles_1h": state["candles_1h"],
            "connected": state["connected"],
            "ts": time.time(),
        })

    except Exception as e:
        log.error(f"Indicator calculation error: {e}", exc_info=True)


def _assess_trend(emas: Dict, price: Optional[float]) -> str:
    e20 = emas.get("ema20")
    e50 = emas.get("ema50")
    e200 = emas.get("ema200")
    if e20 and e50 and e200 and price:
        if e20 > e50 > e200 and price > e50:
            return "Bullish"
        elif e20 < e50 < e200 and price < e50:
            return "Bearish"
        elif e20 > e50:
            return "Mildly Bullish"
        elif e20 < e50:
            return "Mildly Bearish"
    return "Neutral"


def _serialize_indicators(ind: Dict) -> Dict:
    """Convert numpy types to plain Python for JSON serialization."""
    result = {}
    for k, v in ind.items():
        if v is None:
            result[k] = None
        elif isinstance(v, dict):
            result[k] = {
                kk: (
                    float(vv) if hasattr(vv, "item") else
                    bool(vv) if isinstance(vv, bool) else vv
                )
                for kk, vv in v.items()
            }
        elif hasattr(v, "item"):
            result[k] = v.item()
        else:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# Fear & Greed periodic fetch


async def fear_greed_loop():
    """Fetch Fear & Greed index every 5 minutes."""
    while True:
        fg = await fetch_fear_greed()
        if fg:
            state["fear_greed"] = fg
            await broadcast({"type": "fear_greed", "data": fg})
        await asyncio.sleep(300)


# ---------------------------------------------------------------------------
# REST API


@app.get("/api/state")
async def get_state():
    """Return full state — polled by frontend every 3 seconds."""
    return JSONResponse(content={
        "price": state["price"],
        "price_change_24h": state.get("price_change_24h"),
        "volume_24h": state.get("volume_24h"),
        "indicators": _serialize_indicators(state.get("indicators", {})),
        "signal": state.get("signal", {}),
        "fear_greed": state.get("fear_greed"),
        "market_phase": state.get("market_phase", "Unknown"),
        "trend_1h": state.get("trend_1h", "Neutral"),
        "trend_4h": state.get("trend_4h", "Neutral"),
        "volatility_level": state.get("volatility_level", "Low"),
        "signal_history": state.get("signal_history", []),
        "candles_1h": state.get("candles_1h", []),
        "connected": state.get("connected", False),
        "last_update": state.get("last_update"),
    })


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "connected": state["connected"],
        "price": state["price"],
        "candles_1h": len(candle_store.candles_1h),
        "candles_4h": len(candle_store.candles_4h),
    }


@app.get("/api/fear-greed")
async def get_fear_greed():
    """Return latest Fear & Greed index value."""
    fg = state.get("fear_greed")
    if fg is None:
        fg = await fetch_fear_greed()
        if fg:
            state["fear_greed"] = fg
    return JSONResponse(content=fg or {"value": None, "classification": "Unknown"})


@app.get("/api/portfolio")
async def get_portfolio():
    """Return portfolio-related state: price, 24h change, volume."""
    return JSONResponse(content={
        "price": state.get("price"),
        "price_change_24h": state.get("price_change_24h"),
        "volume_24h": state.get("volume_24h"),
        "volatility_level": state.get("volatility_level", "Low"),
        "market_phase": state.get("market_phase", "Unknown"),
        "trend_1h": state.get("trend_1h", "Neutral"),
        "trend_4h": state.get("trend_4h", "Neutral"),
        "last_update": state.get("last_update"),
    })


@app.get("/api/candles/{timeframe}")
async def get_candles(timeframe: str):
    """Return OHLCV candles for a given timeframe. Supported: 1h, 4h."""
    if timeframe == "1h":
        candles = list(candle_store.candles_1h)
        if candle_store._current_1h:
            candles = candles + [candle_store._current_1h]
    elif timeframe == "4h":
        candles = list(candle_store.candles_4h)
        if candle_store._current_4h:
            candles = candles + [candle_store._current_4h]
    else:
        return JSONResponse(
            status_code=400,
            content={"error": f"Unsupported timeframe '{timeframe}'. Use 1h or 4h."},
        )
    return JSONResponse(content={"timeframe": timeframe, "candles": candles, "count": len(candles)})


@app.get("/api/signals/history")
async def get_signals_history():
    """Return last 20 trading signals."""
    return JSONResponse(content={
        "history": signal_engine.signal_history,
        "count": len(signal_engine.signal_history),
    })


# ---------------------------------------------------------------------------
# WebSocket endpoint (frontend clients)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    log.info(f"Frontend client connected. Total: {len(connected_clients)}")
    try:
        price = state["price"] or (
            candle_store.candles_1h[-1]["close"] if candle_store.candles_1h else None
        )
        await websocket.send_text(json.dumps({
            "type": "init",
            "price": price,
            "indicators": _serialize_indicators(state.get("indicators", {})),
            "signal": state.get("signal", {}),
            "fear_greed": state.get("fear_greed"),
            "market_phase": state.get("market_phase", "Unknown"),
            "trend_1h": state.get("trend_1h", "Neutral"),
            "trend_4h": state.get("trend_4h", "Neutral"),
            "volatility_level": state.get("volatility_level", "Low"),
            "signal_history": state.get("signal_history", []),
            "candles_1h": state.get("candles_1h", []),
            "connected": state.get("connected", False),
        }))
        while True:
            await websocket.receive_text()  # keep-alive; client pings are ignored
    except WebSocketDisconnect:
        pass
    finally:
        connected_clients.discard(websocket)
        log.info(f"Frontend client disconnected. Total: {len(connected_clients)}")


# ---------------------------------------------------------------------------
# Startup


@app.on_event("startup")
async def startup_event():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "127.0.0.1"

    print("\n" + "=" * 60)
    print("  BTC Trading Advisor — Backend Started")
    print("=" * 60)
    print(f"  Local:    http://localhost:8000")
    print(f"  Network:  http://{local_ip}:8000  (iPhone access)")
    print(f"  Frontend: http://localhost:3000")
    print(f"  API docs: http://localhost:8000/docs")
    print(f"  Source:   Binance BTCUSDT (highest global volume)")
    print("=" * 60)
    print("  NOT FINANCIAL ADVICE — For informational purposes only")
    print("=" * 60 + "\n")

    # Seed historical data first so candles are available immediately
    await seed_historical_data()

    # Start background tasks
    asyncio.create_task(binance_connect())
    asyncio.create_task(fear_greed_loop())


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
