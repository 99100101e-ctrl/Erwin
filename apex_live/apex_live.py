"""
apex_live/apex_live.py

APEX Bot v2 — Trading live BTC/USDT sur Binance Futures
=========================================================
Stratégie validée en backtest sur 2 ans :
  123 trades | WR 58.5% | Sharpe +2.45 | MDD -7.4% | +1067€ (2000€/trade)

DÉMARRAGE RAPIDE :
  1. Remplis apex_live/config.py (Telegram token pour les alertes)
  2. SIGNAL_ONLY = True  → alerte uniquement, tu décides manuellement (par défaut)
  3. python apex_live/apex_live.py
  4. Reçois les alertes et entre en position manuellement sur Binance
  5. Quand confiant dans les signaux → SIGNAL_ONLY = False, PAPER_TRADING = True
  6. Puis PAPER_TRADING = False pour le trading réel

MODES :
  • SIGNAL_ONLY = True   → bot détecte + alerte (entrée / SL / TP calculés)
                           tu places les ordres toi-même sur Binance
  • PAPER_TRADING = True → simulation automatique locale, 0 ordre réel
  • PAPER_TRADING = False → ordres réels sur Binance Futures (⚠️ argent réel)
"""

import sys, os, json, time, hmac, hashlib, logging, traceback
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as CFG
from indicators import (
    FR_HOURS,
    _ema, _rsi, _atr, _adx, _vol_sma, _daily_ema100_trend,
    _bos, _atr_squeeze, _volume_surge, _rsi_zone, _ema_stack, _engulfing,
    _macd, _rsi4h, _ema4h, _macd_cross, _buy_not_extended,
)

try:
    import requests
except ImportError:
    print("ERREUR : installe requests → pip install requests")
    sys.exit(1)

# ══════════════════════════════════════════════════════════════════════════════
#  LOGGING
# ══════════════════════════════════════════════════════════════════════════════

os.makedirs("apex_live", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("apex_live/apex_live.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
#  BINANCE FUTURES API
# ══════════════════════════════════════════════════════════════════════════════

BASE_URL = "https://fapi.binance.com"


def _sign(params: dict) -> str:
    """Signature HMAC-SHA256 pour les endpoints Binance signés."""
    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    sig = hmac.new(
        CFG.API_SECRET.encode(), query.encode(), hashlib.sha256
    ).hexdigest()
    return query + f"&signature={sig}"


def _headers() -> dict:
    return {"X-MBX-APIKEY": CFG.API_KEY}


def api_get(path, params=None, signed=False):
    p = params or {}
    if signed:
        p["timestamp"] = _get_server_time()
        url = f"{BASE_URL}{path}?{_sign(p)}"
        r = requests.get(url, headers=_headers(), timeout=10)
    else:
        r = requests.get(f"{BASE_URL}{path}", params=p, timeout=10)
    r.raise_for_status()
    return r.json()


def api_post(path, params: dict):
    params["timestamp"] = _get_server_time()
    query = _sign(params)
    r = requests.post(
        f"{BASE_URL}{path}", data=query, headers=_headers(), timeout=10
    )
    r.raise_for_status()
    return r.json()


def api_delete(path, params: dict):
    params["timestamp"] = _get_server_time()
    query = _sign(params)
    r = requests.delete(
        f"{BASE_URL}{path}", data=query, headers=_headers(), timeout=10
    )
    r.raise_for_status()
    return r.json()


def _get_server_time() -> int:
    r = requests.get(f"{BASE_URL}/fapi/v1/time", timeout=10)
    return r.json()["serverTime"]


def get_candles(limit=350) -> list:
    """Fetch les dernières `limit` bougies 1h depuis Binance Futures."""
    data = api_get(
        "/fapi/v1/klines",
        {"symbol": CFG.SYMBOL, "interval": "1h", "limit": limit},
    )
    return [
        {
            "ts":     int(x[0]) // 1000,
            "open":   float(x[1]),
            "high":   float(x[2]),
            "low":    float(x[3]),
            "close":  float(x[4]),
            "volume": float(x[5]),
        }
        for x in data
    ]


def get_mark_price() -> float:
    d = api_get("/fapi/v1/ticker/price", {"symbol": CFG.SYMBOL})
    return float(d["price"])


def get_usdt_balance() -> float:
    d = api_get("/fapi/v2/account", signed=True)
    for asset in d.get("assets", []):
        if asset["asset"] == "USDT":
            return float(asset["availableBalance"])
    return 0.0


def set_leverage():
    if CFG.PAPER_TRADING:
        return
    try:
        api_post(
            "/fapi/v1/leverage",
            {"symbol": CFG.SYMBOL, "leverage": CFG.LEVERAGE},
        )
        log.info(f"Levier configuré : {CFG.LEVERAGE}x")
    except Exception as e:
        log.warning(f"Levier déjà configuré ou erreur : {e}")


def _round_price(p: float) -> str:
    """Arrondi à 1 décimale (tick size BTCUSDT = 0.1)."""
    return f"{round(p * 10) / 10:.1f}"


def _round_qty(q: float) -> str:
    """Arrondi à 3 décimales (step size BTCUSDT = 0.001)."""
    return f"{round(q * 1000) / 1000:.3f}"


def place_order(side, order_type, quantity, price=None, stop_price=None,
                reduce_only=False) -> dict:
    """
    Place un ordre Binance Futures.
    En paper trading : log uniquement, retourne un faux order_id.
    """
    qty_str = _round_qty(quantity)
    if CFG.PAPER_TRADING:
        msg = (f"[PAPER] {side} {order_type} {qty_str} BTC"
               f"{' @' + _round_price(price) if price else ''}"
               f"{' stop=' + _round_price(stop_price) if stop_price else ''}")
        log.info(msg)
        return {"orderId": int(time.time() * 1000), "paper": True}

    params = {
        "symbol":   CFG.SYMBOL,
        "side":     side,
        "type":     order_type,
        "quantity": qty_str,
    }
    if price:
        params["price"]       = _round_price(price)
        params["timeInForce"] = "GTC"
    if stop_price:
        params["stopPrice"] = _round_price(stop_price)
    if reduce_only:
        params["reduceOnly"] = "true"

    return api_post("/fapi/v1/order", params)


def cancel_order(order_id: int):
    if CFG.PAPER_TRADING or not order_id:
        return
    try:
        api_delete("/fapi/v1/order",
                   {"symbol": CFG.SYMBOL, "orderId": order_id})
    except Exception as e:
        log.warning(f"Annulation ordre {order_id} : {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  INDICATEURS & SIGNAL APEX v2
# ══════════════════════════════════════════════════════════════════════════════

def compute_indicators(candles: list) -> dict:
    """Calcule tous les indicateurs APEX v2 sur l'historique complet."""
    closes = [c["close"] for c in candles]
    macd_l, sig_line = _macd(closes)
    return {
        "ema20":    _ema(closes, 20),
        "ema50":    _ema(closes, 50),
        "rsi14":    _rsi(closes, 14),
        "atrs":     _atr(candles, 14),
        "adxs":     _adx(candles, 14),
        "vol_sma":  _vol_sma(candles, 20),
        "trend":    _daily_ema100_trend(candles),
        "rsi4h":    _rsi4h(candles),
        "ema4h20":  _ema4h(candles, 20),
        "ema4h50":  _ema4h(candles, 50),
        "macd_l":   macd_l,
        "sig_line": sig_line,
    }


def check_signal(candles: list, ind: dict, state: dict):
    """
    Vérifie s'il y a un signal APEX v2 sur la dernière bougie fermée.
    Retourne un dict signal ou None.
    Utilise candles[-2] = dernière bougie complète ([-1] est en cours).
    """
    i = len(candles) - 2   # dernière bougie fermée

    ts = candles[i]["ts"]
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)

    # Filtre heure FR
    if dt.hour not in FR_HOURS:
        return None
    # Pas de dimanche
    if dt.weekday() == 6:
        return None

    for direction in ("BUY", "SELL"):

        # 1. EMA100d
        macro = ind["trend"][i]
        if macro == "neutral":
            continue
        if macro == "bull" and direction != "BUY":
            continue
        if macro == "bear" and direction != "SELL":
            continue

        # 2. ADX
        adx_min = CFG.ADX_BUY if direction == "BUY" else CFG.ADX_SELL
        if ind["adxs"][i] < adx_min:
            continue

        # 3. BOS
        if not _bos(candles, i, direction, CFG.BOS_LB):
            continue

        # 4. Filtres BUY spécifiques
        if direction == "BUY":
            rsi4h_val = ind["rsi4h"][i]
            if not (45 <= rsi4h_val <= 72):
                continue
            price = candles[i]["close"]
            if not _buy_not_extended(
                price, ind["ema50"][i], ind["atrs"][i], CFG.EXT_ATR
            ):
                continue

        # 5. Cooldown
        last_ts = state["last_signal_ts"].get(direction, 0)
        if (ts - last_ts) < CFG.COOLDOWN_H * 3600:
            continue

        # 6. Scoring
        s1 = int(_atr_squeeze(ind["atrs"],   i))
        s2 = int(_volume_surge(candles, ind["vol_sma"], i))
        s3 = int(_rsi_zone(ind["rsi14"],     i, direction))
        s4 = int(_ema_stack(ind["ema20"],    ind["ema50"], i, direction))
        s5 = int(_engulfing(candles,         i, direction))

        if direction == "BUY":
            s6    = int(_macd_cross(ind["macd_l"], ind["sig_line"], i, direction))
            score = s1 + s2 + s3 + s4 + s5 + s6
            s_min = CFG.SCORE_BUY
        else:
            score = s1 + s2 + s3 + s4 + s5
            s_min = CFG.SCORE_SELL

        if score < s_min:
            continue

        atr_val = ind["atrs"][i]
        if atr_val <= 0:
            continue

        confirm_labels = {
            "BUY":  ["ATR Squeeze", "Volume Surge", "RSI Zone",
                     "EMA Stack", "Engulfing", "MACD Cross"],
            "SELL": ["ATR Squeeze", "Volume Surge", "RSI Zone",
                     "EMA Stack", "Engulfing"],
        }
        confirm_vals = [s1, s2, s3, s4, s5] + ([s6] if direction == "BUY" else [])

        return {
            "direction":   direction,
            "candle_ts":   ts,
            "candle_close": candles[i]["close"],
            "atr":         atr_val,
            "score":       score,
            "score_max":   6 if direction == "BUY" else 5,
            "adx":         ind["adxs"][i],
            "rsi":         ind["rsi14"][i],
            "rsi4h":       ind["rsi4h"][i] if direction == "BUY" else None,
            "trend":       ind["trend"][i],
            "confirmateurs": list(zip(confirm_labels[direction], confirm_vals)),
        }

    return None


# ══════════════════════════════════════════════════════════════════════════════
#  GESTION ÉTAT & LOGS
# ══════════════════════════════════════════════════════════════════════════════

_DEFAULT_STATE = {
    "position": {
        "active":       False,
        "direction":    None,
        "entry_price":  None,
        "entry_time":   None,
        "entry_qty":    None,
        "atr":          None,
        "sl_price":     None,
        "tp1_price":    None,
        "tp2_price":    None,
        "tp3_price":    None,
        "tp1_done":     False,
        "tp2_done":     False,
        "remaining_qty": None,
        "order_sl_id":  None,
    },
    "last_signal_ts":  {"BUY": 0, "SELL": 0},
    "last_candle_hour": 0,
    "paper_balance":   10000.0,
    "stats": {"n": 0, "wins": 0, "pnl_eur": 0.0},
}


def load_state() -> dict:
    if os.path.exists(CFG.STATE_FILE):
        with open(CFG.STATE_FILE, "r") as f:
            return json.load(f)
    return json.loads(json.dumps(_DEFAULT_STATE))   # deep copy


def save_state(state: dict):
    with open(CFG.STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def log_trade(trade: dict):
    with open(CFG.LOG_FILE, "a") as f:
        f.write(json.dumps(trade) + "\n")


def log_signal(signal: dict, sl: float, tp1: float, tp2: float, tp3: float, mode: str):
    """Enregistre chaque signal détecté dans signals.jsonl (SIGNAL_ONLY + trades)."""
    entry = {
        "ts":        int(time.time()),
        "candle_ts": signal["candle_ts"],
        "direction": signal["direction"],
        "entry":     signal["candle_close"],
        "sl":        round(sl,  1),
        "tp1":       round(tp1, 1),
        "tp2":       round(tp2, 1),
        "tp3":       round(tp3, 1),
        "score":     signal["score"],
        "score_max": signal["score_max"],
        "adx":       round(signal["adx"], 1),
        "rsi":       round(signal["rsi"], 1),
        "rsi4h":     round(signal["rsi4h"], 1) if signal.get("rsi4h") else None,
        "trend":     signal["trend"],
        "mode":      mode,
        "confirmateurs": {lbl: bool(v) for lbl, v in signal["confirmateurs"]},
    }
    with open(CFG.SIGNALS_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def notify(msg: str):
    """Notification Telegram (optionnel)."""
    log.info(f"📢 {msg}")
    if not CFG.TELEGRAM_TOKEN or not CFG.TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{CFG.TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CFG.TELEGRAM_CHAT_ID, "text": msg},
            timeout=5,
        )
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  ALERTE SIGNAL (mode SIGNAL_ONLY)
# ══════════════════════════════════════════════════════════════════════════════

def send_signal_alert(signal: dict, state: dict):
    """
    Envoie une alerte détaillée avec tous les niveaux à placer manuellement.
    N'entre pas en position — tu décides toi-même.
    """
    direction = signal["direction"]
    atr       = signal["atr"]
    R         = CFG.SL_MULT * atr
    entry     = signal["candle_close"]   # prix de clôture de la bougie signal

    if direction == "BUY":
        sl  = entry - R
        tp1 = entry + CFG.TP1_R * R
        tp2 = entry + CFG.TP2_R * R
        tp3 = entry + CFG.TP3_R * R
    else:
        sl  = entry + R
        tp1 = entry - CFG.TP1_R * R
        tp2 = entry - CFG.TP2_R * R
        tp3 = entry - CFG.TP3_R * R

    sign    = 1 if direction == "BUY" else -1
    pct_sl  = (sl  - entry) / entry * 100
    pct_tp1 = (tp1 - entry) / entry * 100 * sign
    pct_tp2 = (tp2 - entry) / entry * 100 * sign
    pct_tp3 = (tp3 - entry) / entry * 100 * sign

    trend_str = {"bull": "HAUSSIÈRE", "bear": "BAISSIÈRE"}.get(signal["trend"], "neutre")
    arrow     = "▲" if direction == "BUY" else "▼"

    # Détail confirmateurs
    conf_lines = []
    for label, val in signal["confirmateurs"]:
        conf_lines.append(f"  {'✅' if val else '❌'} {label}")
    conf_str = "\n".join(conf_lines)

    rsi4h_line = (f"\n  RSI 4h  : {signal['rsi4h']:.1f}"
                  if signal.get("rsi4h") is not None else "")

    msg = (
        f"{arrow} SIGNAL APEX v2 — {direction} {CFG.SYMBOL}\n"
        f"{'─' * 36}\n"
        f"Bougie : {datetime.fromtimestamp(signal['candle_ts'], tz=timezone.utc).strftime('%Y-%m-%d %H:00')} UTC\n"
        f"Tendance macro : {trend_str}\n"
        f"\n"
        f"NIVEAUX SUGGÉRÉS :\n"
        f"  Entrée  : {entry:,.1f} $\n"
        f"  SL      : {sl:,.1f} $  ({pct_sl:+.2f}% | R = {R:.0f} $)\n"
        f"  TP1     : {tp1:,.1f} $  (+{pct_tp1:.1f}% | {CFG.TP1_R}R → ferme 40%)\n"
        f"  TP2     : {tp2:,.1f} $  (+{pct_tp2:.1f}% | {CFG.TP2_R}R → ferme 35%)\n"
        f"  TP3     : {tp3:,.1f} $  (+{pct_tp3:.1f}% | {CFG.TP3_R}R → ferme 25%)\n"
        f"\n"
        f"CONFIRMATEURS ({signal['score']}/{signal['score_max']}) :\n"
        f"{conf_str}\n"
        f"\n"
        f"INDICATEURS :\n"
        f"  ADX     : {signal['adx']:.1f}\n"
        f"  RSI 14  : {signal['rsi']:.1f}"
        f"{rsi4h_line}\n"
        f"  ATR     : {atr:.0f} $\n"
        f"\n"
        f"→ Décision manuelle requise."
    )

    log.info("\n" + "=" * 50 + "\n" + msg + "\n" + "=" * 50)
    notify(msg)
    log_signal(signal, sl, tp1, tp2, tp3, mode="SIGNAL_ONLY")

    # Mettre à jour le cooldown pour éviter une re-alerte sur la même bougie
    state["last_signal_ts"][direction] = signal["candle_ts"]


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRÉE EN POSITION
# ══════════════════════════════════════════════════════════════════════════════

def enter_trade(signal: dict, state: dict):
    """
    Entre en position sur le signal APEX v2.
    Place l'ordre marché + SL initial.
    TP1/TP2/TP3 sont gérés manuellement dans manage_position().
    """
    direction = signal["direction"]
    atr       = signal["atr"]
    R         = CFG.SL_MULT * atr

    # Prix d'entrée (market → approximation au prix actuel)
    entry_price = get_mark_price() if not CFG.PAPER_TRADING else (
        float(signal.get("candle_close", get_mark_price()))
    )

    # Calcul de la quantité
    qty = CFG.TRADE_SIZE_USDT / entry_price

    # Niveaux SL / TP
    if direction == "BUY":
        sl  = entry_price - R
        tp1 = entry_price + CFG.TP1_R * R
        tp2 = entry_price + CFG.TP2_R * R
        tp3 = entry_price + CFG.TP3_R * R
        side_entry = "BUY"
        side_exit  = "SELL"
    else:
        sl  = entry_price + R
        tp1 = entry_price - CFG.TP1_R * R
        tp2 = entry_price - CFG.TP2_R * R
        tp3 = entry_price - CFG.TP3_R * R
        side_entry = "SELL"
        side_exit  = "BUY"

    mode = "PAPER" if CFG.PAPER_TRADING else "LIVE"
    log_signal(signal, sl, tp1, tp2, tp3, mode=mode)

    log.info(
        f"▶ ENTRÉE {direction} | Prix {entry_price:.1f} | ATR {atr:.1f} | R {R:.1f}"
    )
    log.info(
        f"  SL={sl:.1f} | TP1={tp1:.1f} | TP2={tp2:.1f} | TP3={tp3:.1f}"
    )

    # Ordre marché
    place_order(side_entry, "MARKET", qty)

    # Stop Loss
    sl_order = place_order(
        side_exit, "STOP_MARKET", qty,
        stop_price=sl, reduce_only=True,
    )

    # Mise à jour de l'état
    pos = state["position"]
    pos.update({
        "active":        True,
        "direction":     direction,
        "entry_price":   entry_price,
        "entry_time":    int(time.time()),
        "entry_qty":     qty,
        "atr":           atr,
        "sl_price":      sl,
        "tp1_price":     tp1,
        "tp2_price":     tp2,
        "tp3_price":     tp3,
        "tp1_done":      False,
        "tp2_done":      False,
        "remaining_qty": qty,
        "order_sl_id":   sl_order.get("orderId"),
    })
    state["last_signal_ts"][direction] = signal["candle_ts"]

    notify(
        f"APEX BOT — {direction} {CFG.SYMBOL}\n"
        f"Entrée : {entry_price:.1f} | SL : {sl:.1f}\n"
        f"TP1 : {tp1:.1f} | TP2 : {tp2:.1f} | TP3 : {tp3:.1f}\n"
        f"Score : {signal['score']} | ADX : {signal['adx']:.1f}"
    )


# ══════════════════════════════════════════════════════════════════════════════
#  GESTION DE LA POSITION OUVERTE
# ══════════════════════════════════════════════════════════════════════════════

def _price_hit(current: float, target: float, direction: str, side: str) -> bool:
    """
    Vérifie si `target` a été atteint.
    side='profit'  → TP direction
    side='loss'    → SL direction
    """
    if direction == "BUY":
        return current >= target if side == "profit" else current <= target
    else:
        return current <= target if side == "profit" else current >= target


def manage_position(state: dict, current_price: float):
    """
    Vérifie les niveaux SL/TP et ferme les fractions appropriées.
    Appelé à chaque cycle (toutes les minutes).
    """
    pos = state["position"]
    if not pos["active"]:
        return

    direction = pos["direction"]
    entry     = pos["entry_price"]
    atr       = pos["atr"]
    R         = CFG.SL_MULT * atr
    rem_qty   = pos["remaining_qty"]
    now_ts    = int(time.time())

    # ── Timeout ────────────────────────────────────────────────────────────
    elapsed_h = (now_ts - pos["entry_time"]) / 3600
    if elapsed_h >= CFG.TIMEOUT_H:
        log.info(f"⏱ TIMEOUT ({CFG.TIMEOUT_H}h) — fermeture position")
        _close_all(state, current_price, "timeout")
        return

    # ── SL hit ─────────────────────────────────────────────────────────────
    if _price_hit(current_price, pos["sl_price"], direction, "loss"):
        pnl_pct = (pos["sl_price"] - entry) / entry
        if direction == "SELL":
            pnl_pct = -pnl_pct
        log.info(f"🔴 SL atteint @ {current_price:.1f} | PnL : {pnl_pct*100:+.2f}%")
        _close_all(state, pos["sl_price"], "SL")
        return

    # ── TP1 ────────────────────────────────────────────────────────────────
    if not pos["tp1_done"] and _price_hit(
        current_price, pos["tp1_price"], direction, "profit"
    ):
        qty_tp1 = rem_qty * 0.40
        side_exit = "SELL" if direction == "BUY" else "BUY"
        place_order(side_exit, "MARKET", qty_tp1, reduce_only=True)

        # Annuler l'ancien SL, placer SL au BE
        cancel_order(pos["order_sl_id"])
        sl_be = entry
        new_qty = rem_qty - qty_tp1
        sl_order = place_order(
            side_exit, "STOP_MARKET", new_qty,
            stop_price=sl_be, reduce_only=True,
        )

        pnl_tp1 = abs(pos["tp1_price"] - entry) / entry * 0.40
        log.info(
            f"🟡 TP1 @ {pos['tp1_price']:.1f} | -40% position | SL → BE {sl_be:.1f}"
        )
        notify(
            f"APEX — TP1 atteint {direction}\n"
            f"TP1 : {pos['tp1_price']:.1f} | SL → BE : {sl_be:.1f}"
        )

        pos["tp1_done"]      = True
        pos["remaining_qty"] = new_qty
        pos["sl_price"]      = sl_be
        pos["order_sl_id"]   = sl_order.get("orderId")

    # ── TP2 ────────────────────────────────────────────────────────────────
    if pos["tp1_done"] and not pos["tp2_done"] and _price_hit(
        current_price, pos["tp2_price"], direction, "profit"
    ):
        qty_tp2 = rem_qty * 0.35
        side_exit = "SELL" if direction == "BUY" else "BUY"
        place_order(side_exit, "MARKET", qty_tp2, reduce_only=True)

        log.info(f"🟢 TP2 @ {pos['tp2_price']:.1f} | -35% position")
        notify(f"APEX — TP2 atteint {direction} @ {pos['tp2_price']:.1f}")

        pos["tp2_done"]      = True
        pos["remaining_qty"] = rem_qty - qty_tp2

    # ── TP3 ────────────────────────────────────────────────────────────────
    if pos["tp2_done"] and _price_hit(
        current_price, pos["tp3_price"], direction, "profit"
    ):
        log.info(f"🏆 TP3 @ {pos['tp3_price']:.1f} | Fermeture totale")
        _close_all(state, pos["tp3_price"], "TP3")


def _close_all(state: dict, exit_price: float, reason: str):
    """Ferme toute la position restante et met à jour les stats."""
    pos       = state["position"]
    direction = pos["direction"]
    entry     = pos["entry_price"]
    rem_qty   = pos["remaining_qty"]

    if rem_qty and rem_qty > 0.001:
        side_exit = "SELL" if direction == "BUY" else "BUY"
        place_order(side_exit, "MARKET", rem_qty, reduce_only=True)

    cancel_order(pos["order_sl_id"])

    # Calcul P&L
    sign  = 1 if direction == "BUY" else -1
    # P&L partiel (TP1 + TP2 déjà fermés)
    tp1_pnl = sign * (pos["tp1_price"] - entry) / entry * 0.40 if pos["tp1_done"] else 0
    tp2_pnl = sign * (pos["tp2_price"] - entry) / entry * 0.35 if pos["tp2_done"] else 0
    # P&L partie restante
    rem_frac = (1.0
                - (0.40 if pos["tp1_done"] else 0)
                - (0.35 if pos["tp2_done"] else 0))
    rem_pnl  = sign * (exit_price - entry) / entry * rem_frac
    total_pnl_pct = (tp1_pnl + tp2_pnl + rem_pnl) * 100
    total_pnl_eur = total_pnl_pct / 100 * CFG.TRADE_SIZE_USDT

    won = total_pnl_eur > 0
    state["stats"]["n"]       += 1
    state["stats"]["wins"]    += int(won)
    state["stats"]["pnl_eur"] += total_pnl_eur
    if CFG.PAPER_TRADING:
        state["paper_balance"] += total_pnl_eur

    wr = state["stats"]["wins"] / state["stats"]["n"] * 100
    log.info(
        f"{'✅' if won else '❌'} CLÔTURE {direction} [{reason}]"
        f" | PnL {total_pnl_pct:+.2f}% ({total_pnl_eur:+.0f}€)"
        f" | Stats: {state['stats']['n']} trades | WR {wr:.0f}%"
        f" | Total {state['stats']['pnl_eur']:+.0f}€"
    )
    notify(
        f"APEX — Clôture {direction} [{reason}]\n"
        f"PnL : {total_pnl_pct:+.2f}% ({total_pnl_eur:+.0f}€)\n"
        f"Stats : {state['stats']['n']} trades | WR {wr:.0f}%"
    )

    trade_record = {
        "ts":         int(time.time()),
        "direction":  direction,
        "entry":      entry,
        "exit":       exit_price,
        "reason":     reason,
        "pnl_pct":    total_pnl_pct,
        "pnl_eur":    total_pnl_eur,
        "tp1":        pos["tp1_done"],
        "tp2":        pos["tp2_done"],
    }
    log_trade(trade_record)

    # Réinitialiser la position
    state["position"] = json.loads(json.dumps(_DEFAULT_STATE["position"]))


# ══════════════════════════════════════════════════════════════════════════════
#  BOUCLE PRINCIPALE
# ══════════════════════════════════════════════════════════════════════════════

def run_cycle(state: dict):
    """Un cycle complet du bot (appelé toutes les minutes)."""
    now_ts  = int(time.time())
    now_dt  = datetime.fromtimestamp(now_ts, tz=timezone.utc)
    cur_hour = now_dt.hour

    # ── Gestion position ouverte ─────────────────────────────────────────
    if state["position"]["active"]:
        try:
            price = get_mark_price()
            manage_position(state, price)
        except Exception as e:
            log.error(f"Erreur manage_position : {e}")
        return

    # ── Vérification signal (1× par heure, à la fermeture) ───────────────
    new_hour = cur_hour != state.get("last_candle_hour", -1)
    if not new_hour:
        return

    # Attendre la 2e minute de l'heure (bougie vraiment fermée)
    if now_dt.minute < 2:
        return

    state["last_candle_hour"] = cur_hour
    log.info(f"── Nouvelle bougie 1h | {now_dt.strftime('%Y-%m-%d %H:%M')} UTC ──")

    try:
        candles = get_candles(350)
        ind     = compute_indicators(candles)
        signal  = check_signal(candles, ind, state)

        if signal:
            log.info(
                f"SIGNAL {signal['direction']} détecté"
                f" | score={signal['score']}/{signal['score_max']}"
                f" | ADX={signal['adx']:.1f} | RSI={signal['rsi']:.1f}"
            )
            if getattr(CFG, "SIGNAL_ONLY", False):
                send_signal_alert(signal, state)
            else:
                enter_trade(signal, state)
        else:
            log.info("Pas de signal.")
    except Exception as e:
        log.error(f"Erreur check_signal : {e}\n{traceback.format_exc()}")


def main():
    signal_only = getattr(CFG, "SIGNAL_ONLY", False)
    if signal_only:
        mode = "SIGNAL ONLY (alertes uniquement — pas d'ordres)"
    elif CFG.PAPER_TRADING:
        mode = "PAPER TRADING (simulation)"
    else:
        mode = "TRADING REEL"
    log.info("=" * 60)
    log.info(f"  APEX Bot v2 — {CFG.SYMBOL} — MODE : {mode}")
    log.info(f"  Taille position : {CFG.TRADE_SIZE_USDT} USDT | Levier : {CFG.LEVERAGE}x")
    log.info(f"  Config : BOS={CFG.BOS_LB} | SL={CFG.SL_MULT}× ATR"
             f" | TP1={CFG.TP1_R}R | TP2={CFG.TP2_R}R | TP3={CFG.TP3_R}R")
    log.info("=" * 60)

    if not signal_only and not CFG.PAPER_TRADING:
        if not CFG.API_KEY or not CFG.API_SECRET:
            log.error("API_KEY ou API_SECRET manquant dans config.py !")
            sys.exit(1)
        set_leverage()
        bal = get_usdt_balance()
        log.info(f"Balance Binance Futures : {bal:.2f} USDT")
        if bal < CFG.TRADE_SIZE_USDT:
            log.warning(
                f"Solde ({bal:.0f} USDT) < taille trade ({CFG.TRADE_SIZE_USDT} USDT) !"
            )

    state = load_state()
    log.info(
        f"État chargé : {state['stats']['n']} trades précédents"
        f" | P&L total {state['stats']['pnl_eur']:+.0f}€"
    )
    if state["position"]["active"]:
        log.info(
            f"Position active restaurée : {state['position']['direction']}"
            f" @ {state['position']['entry_price']:.1f}"
        )

    log.info("Bot démarré. Cycle toutes les 60 secondes.")

    while True:
        try:
            run_cycle(state)
            save_state(state)
        except KeyboardInterrupt:
            log.info("Arrêt demandé (Ctrl+C)")
            save_state(state)
            break
        except Exception as e:
            log.error(f"Erreur inattendue : {e}\n{traceback.format_exc()}")
        time.sleep(60)


if __name__ == "__main__":
    main()
