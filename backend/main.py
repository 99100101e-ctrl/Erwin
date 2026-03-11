"""
BTC Trading Advisor — FastAPI Backend
Connects to Phemex WebSocket for live BTCUSD perpetual futures data.
Calculates indicators and emits trading signals every 60 seconds.
"""
import asyncio
import json
import logging
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
        """Process a kline update from Phemex."""
        ts = candle_data.get("t", 0)  # open time in seconds
        o = float(candle_data.get("o", 0))
        h = float(candle_data.get("h", 0))
        l = float(candle_data.get("l", 0))
        c = float(candle_data.get("c", 0))
        v = float(candle_data.get("v", 0))
        is_closed = candle_data.get("closed", False)

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
        # Append current (live) candle if available
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
# Phemex WebSocket connection

PHEMEX_WS_URL = "wss://phemex.com/ws"
SYMBOL = "BTCUSD"


async def phemex_connect():
    """Maintain persistent connection to Phemex WebSocket."""
    backoff = 2
    while True:
        try:
            log.info(f"Connecting to Phemex WebSocket: {PHEMEX_WS_URL}")
            async with websockets.connect(
                PHEMEX_WS_URL,
                ping_interval=20,
                ping_timeout=30,
                close_timeout=10,
            ) as ws:
                state["connected"] = True
                backoff = 2  # reset on success
                log.info("Connected to Phemex WebSocket")

                # Subscribe to klines and ticker
                subs = [
                    {
                        "id": 1,
                        "method": "kline.subscribe",
                        "params": [SYMBOL, 3600],  # 1h
                    },
                    {
                        "id": 2,
                        "method": "kline.subscribe",
                        "params": [SYMBOL, 14400],  # 4h
                    },
                    {
                        "id": 3,
                        "method": "market24h.subscribe",
                        "params": [],
                    },
                    {
                        "id": 4,
                        "method": "trade.subscribe",
                        "params": [SYMBOL],
                    },
                ]
                for sub in subs:
                    await ws.send(json.dumps(sub))
                    await asyncio.sleep(0.1)

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        await handle_phemex_message(msg)
                    except Exception as e:
                        log.error(f"Error handling Phemex message: {e}")

        except Exception as e:
            state["connected"] = False
            log.error(f"Phemex WS error: {e}. Reconnecting in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


async def handle_phemex_message(msg: Dict):
    """Process incoming Phemex WebSocket message."""
    # Heartbeat
    if msg.get("id") and not msg.get("result") is None:
        return

    # Kline data
    if "kline" in msg:
        symbol = msg.get("symbol", "")
        if symbol != SYMBOL:
            return
        klines = msg.get("kline", [])
        msg_type = msg.get("type", "")
        for kline in klines:
            # Phemex kline format: [timestamp, interval, last_close, open, high, low, close, volume, turnover]
            if len(kline) >= 9:
                ts, interval, _, o, h, l, c, v, _ = kline[:9]
                # Convert price (Phemex uses integer cents for inverse contracts)
                # BTCUSD perpetual: prices in USD per contract, volume in contracts
                candle = {
                    "t": ts,
                    "o": o,
                    "h": h,
                    "l": l,
                    "c": c,
                    "v": v,
                    "closed": msg_type == "snapshot",
                }
                candle_store.update_from_kline(candle, interval)

        await update_indicators_and_signal()

    # Market 24h ticker
    if "market24h" in msg:
        ticker = msg.get("market24h", {})
        if ticker:
            # Phemex inverse: markPrice is in price scale
            price = ticker.get("markPrice") or ticker.get("lastPrice")
            if price:
                state["price"] = int(price) / 10000 if int(price) > 10000000 else float(price)
            state["price_change_24h"] = ticker.get("priceChangeRatio")
            state["volume_24h"] = ticker.get("volume24h")

    # Trade data — update live price
    if "trades" in msg:
        trades = msg.get("trades", [])
        if trades:
            last_trade = trades[-1]
            # [timestamp, side, price, qty]
            if len(last_trade) >= 3:
                raw_price = last_trade[2]
                # Phemex BTCUSD: price is integer, divide by 10000
                price = float(raw_price) / 10000 if int(raw_price) > 1000000 else float(raw_price)
                if price > 1000:  # sanity check
                    state["price"] = price
                    state["last_update"] = datetime.now(timezone.utc).isoformat()
                    await broadcast({"type": "price", "price": price, "ts": time.time()})


async def update_indicators_and_signal():
    """Recalculate all indicators and evaluate signal."""
    (
        closes_1h, highs_1h, lows_1h, vols_1h,
        closes_4h, highs_4h, lows_4h, vols_4h,
    ) = candle_store.get_lists()

    if len(closes_1h) < 30:
        log.info(f"Not enough candles yet: {len(closes_1h)} 1h candles")
        return

    try:
        indicators = calculate_all_indicators(
            closes_1h, highs_1h, lows_1h, vols_1h,
            closes_4h, highs_4h, lows_4h, vols_4h,
        )
        state["indicators"] = indicators

        # Trend assessment
        emas_1h = indicators.get("emas_1h") or {}
        emas_4h = indicators.get("emas_4h") or {}
        state["trend_1h"] = _assess_trend(emas_1h, closes_1h[-1] if closes_1h else None)
        state["trend_4h"] = _assess_trend(emas_4h, closes_4h[-1] if closes_4h else None)
        state["market_phase"] = indicators.get("market_phase", "Unknown")

        # Volatility level
        atr_pct = indicators.get("atr_pct")
        if atr_pct is None:
            state["volatility_level"] = "Low"
        elif atr_pct < 1.0:
            state["volatility_level"] = "Low"
        elif atr_pct < 1.5:
            state["volatility_level"] = "Medium"
        elif atr_pct < 2.5:
            state["volatility_level"] = "High"
        else:
            state["volatility_level"] = "Extreme"

        # Signal evaluation
        price = state.get("price") or (closes_1h[-1] if closes_1h else None)
        if price:
            signal = signal_engine.evaluate(indicators, price)
            state["signal"] = signal
            state["signal_history"] = signal_engine.signal_history

        # Store candle data for chart (last 100 candles)
        state["candles_1h"] = list(candle_store.candles_1h)[-100:]

        state["last_update"] = datetime.now(timezone.utc).isoformat()

        await broadcast({
            "type": "update",
            "price": price,
            "indicators": _serialize_indicators(indicators),
            "signal": signal if price else {},
            "market_phase": state["market_phase"],
            "trend_1h": state["trend_1h"],
            "trend_4h": state["trend_4h"],
            "volatility_level": state["volatility_level"],
            "signal_history": state["signal_history"],
            "candles_1h": state["candles_1h"],
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
    """Return current full state (for initial page load)."""
    return JSONResponse(content={
        "price": state["price"],
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
    return {"status": "ok", "connected": state["connected"], "price": state["price"]}


@app.get("/api/fear-greed")
async def get_fear_greed():
    """Return latest Fear & Greed index value."""
    fg = state.get("fear_greed")
    if fg is None:
        # Attempt a live fetch on demand
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
    """
    Return OHLCV candles for a given timeframe.
    Supported: 1h, 4h
    """
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
# WebSocket endpoint

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    log.info(f"Client connected. Total: {len(connected_clients)}")
    try:
        # Send current state immediately on connect
        await websocket.send_text(json.dumps({
            "type": "init",
            "price": state["price"],
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
            await websocket.receive_text()  # keep alive, ignore pings
    except WebSocketDisconnect:
        pass
    finally:
        connected_clients.discard(websocket)
        log.info(f"Client disconnected. Total: {len(connected_clients)}")


# ---------------------------------------------------------------------------
# Startup

@app.on_event("startup")
async def startup_event():
    # Print network IP for iPhone access
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
    print("=" * 60)
    print("  ⚠  NOT FINANCIAL ADVICE — For informational purposes only")
    print("=" * 60 + "\n")

    # Start background tasks
    asyncio.create_task(phemex_connect())
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
