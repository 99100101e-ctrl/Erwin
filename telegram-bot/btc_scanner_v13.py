"""
Phantom Edge V13 — Autonomous Scanner (Local Telegram Bot)
Reproduit la logique phantom_edge_v13.pine sans TradingView.
Utilise l'API Binance (gratuite, sans clé).

Logique identique au Pine Script V13 :
  LONGS (4H) : SuperTrend bull + EMA 21>50 + pullback EMA 21 + bougie haussière
    → SL = ATR x 2, trailing ATR x 2
  SHORTS (4H) : SuperTrend bear + EMA 21<50 + pullback EMA 21 (rally rejeté)
    + bougie baissière + prix < EMA200
    → SL = ATR x 3, sortie SuperTrend flip

Usage:
  cp .env.example .env   # remplir TELEGRAM_TOKEN + TELEGRAM_CHAT_ID
  pip install -r requirements.txt
  python btc_scanner_v13.py
"""

import os
import time
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import requests
from dotenv import load_dotenv

load_dotenv()

# ── Config ──
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

SYMBOL = "BTCUSDT"
STATE_FILE = Path(__file__).parent / "scanner_state_v13.json"

# ── Paramètres identiques au Pine V13 ──
# SuperTrend
ST_FACTOR = 3.0
ST_PERIOD = 10

# EMAs
EMA_FAST_LEN = 21
EMA_SLOW_LEN = 50
EMA_MACRO_LEN = 200
EMA_PB_LEN = 21
PB_ZONE_PCT = 0.5

# Long risk
ATR_LEN = 14
LONG_SL_MULT = 2.0
LONG_TRAIL_MULT = 2.0
LONG_TP_RR = 3.0

# Short risk (asymétrique — V13)
SHORT_SL_MULT = 3.0   # Plus large : BTC bounces violents en baisse
SHORT_EXIT = "ST Flip"  # Sortie sur SuperTrend flip

# Session
MAX_DAILY = 3

# Scan toutes les 5 minutes
SCAN_INTERVAL = 300

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)


# ══════════════════════════════════════════════════════════════════════════════
# BINANCE API
# ══════════════════════════════════════════════════════════════════════════════

def fetch_klines(symbol: str, interval: str, limit: int = 300) -> np.ndarray:
    """Récupère les klines Binance. Retourne array [timestamp, O, H, L, C, V]."""
    url = "https://api.binance.com/api/v3/klines"
    resp = requests.get(url, params={
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    arr = np.array([
        [float(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])]
        for k in data
    ])
    return arr


# ══════════════════════════════════════════════════════════════════════════════
# INDICATEURS
# ══════════════════════════════════════════════════════════════════════════════

def ema(src: np.ndarray, length: int) -> np.ndarray:
    """Exponential Moving Average."""
    result = np.full_like(src, np.nan, dtype=float)
    k = 2.0 / (length + 1)
    result[0] = src[0]
    for i in range(1, len(src)):
        result[i] = src[i] * k + result[i - 1] * (1 - k)
    return result


def rma(src: np.ndarray, length: int) -> np.ndarray:
    """Wilder's smoothing (RMA) — alpha = 1/length."""
    result = np.full_like(src, np.nan, dtype=float)
    result[length - 1] = np.mean(src[:length])
    k = 1.0 / length
    for i in range(length, len(src)):
        result[i] = src[i] * k + result[i - 1] * (1 - k)
    return result


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int) -> np.ndarray:
    """Average True Range (Wilder's RMA)."""
    tr = np.empty(len(high))
    tr[0] = high[0] - low[0]
    for i in range(1, len(high)):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    return rma(tr, length)


def supertrend(high: np.ndarray, low: np.ndarray, close: np.ndarray,
               factor: float, period: int):
    """SuperTrend. Retourne (st_value, st_dir) — dir<0 = bull, dir>0 = bear."""
    atr_vals = atr(high, low, close, period)
    hl2 = (high + low) / 2.0
    n = len(close)

    upper_band = np.full(n, np.nan)
    lower_band = np.full(n, np.nan)
    st_dir = np.zeros(n)
    st_value = np.full(n, np.nan)

    for i in range(n):
        if np.isnan(atr_vals[i]):
            continue
        up = hl2[i] + factor * atr_vals[i]
        dn = hl2[i] - factor * atr_vals[i]

        if i == 0 or np.isnan(upper_band[i - 1]):
            upper_band[i] = up
            lower_band[i] = dn
            st_dir[i] = -1 if close[i] > up else 1
        else:
            lower_band[i] = max(dn, lower_band[i - 1]) if close[i - 1] > lower_band[i - 1] else dn
            upper_band[i] = min(up, upper_band[i - 1]) if close[i - 1] < upper_band[i - 1] else up

            prev_dir = st_dir[i - 1]
            if prev_dir < 0:  # was bull
                if close[i] < lower_band[i]:
                    st_dir[i] = 1  # flip bear
                else:
                    st_dir[i] = -1
            else:  # was bear
                if close[i] > upper_band[i]:
                    st_dir[i] = -1  # flip bull
                else:
                    st_dir[i] = 1

        st_value[i] = lower_band[i] if st_dir[i] < 0 else upper_band[i]

    return st_value, st_dir


# ══════════════════════════════════════════════════════════════════════════════
# ÉTAT PERSISTANT (position, trailing, etc.)
# ══════════════════════════════════════════════════════════════════════════════

class ScannerState:
    """État persistant du scanner — sauvé en JSON entre les scans."""

    def __init__(self):
        # Position
        self.position: str = "FLAT"  # "FLAT", "LONG", "SHORT"
        self.entry_price: float = 0
        self.entry_time: str = ""

        # Long trailing
        self.trail_long: float = 0

        # Short SL
        self.short_sl: float = 0

        # Daily counter
        self.day_trades: int = 0
        self.last_day: int = 0

        # Dedup — empêche le même signal en boucle
        self.last_signal_time: float = 0

    def save(self):
        STATE_FILE.write_text(json.dumps(self.__dict__, indent=2))

    @classmethod
    def load(cls) -> "ScannerState":
        state = cls()
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text())
            for k, v in data.items():
                if hasattr(state, k):
                    setattr(state, k, v)
        return state


# ══════════════════════════════════════════════════════════════════════════════
# ANALYSE — Phantom Edge V13
# ══════════════════════════════════════════════════════════════════════════════

class Signal:
    def __init__(self, direction: str, timeframe: str, entry: float,
                 sl: float = 0, tp: float = 0,
                 st_dir: str = "", ema_align: str = "",
                 exit_method: str = ""):
        self.direction = direction
        self.timeframe = timeframe
        self.entry = entry
        self.sl = sl
        self.tp = tp
        self.st_dir = st_dir
        self.ema_align = ema_align
        self.exit_method = exit_method


def check_long(klines: np.ndarray, tf_label: str) -> Optional[Signal]:
    """Détecte un signal LONG — identique V11/V13."""
    close = klines[:, 4]
    high_ = klines[:, 2]
    low_ = klines[:, 3]
    open_ = klines[:, 1]

    # Indicateurs
    st_val, st_dir = supertrend(high_, low_, close, ST_FACTOR, ST_PERIOD)
    ema_f = ema(close, EMA_FAST_LEN)
    ema_s = ema(close, EMA_SLOW_LEN)
    ema_pb = ema(close, EMA_PB_LEN)
    atr_val = atr(high_, low_, close, ATR_LEN)

    # Dernière bougie fermée (pas celle en cours)
    idx = -2

    if any(np.isnan(x[idx]) for x in [st_val, ema_f, ema_s, ema_pb, atr_val]):
        return None

    # Conditions V13 (identiques au Pine)
    st_bull = st_dir[idx] < 0
    ema_bull = ema_f[idx] > ema_s[idx]
    trend_up = st_bull and ema_bull

    # Pullback EMA21 : prix touche EMA21 par le bas → rebondit (bougie verte)
    pb_zone = ema_pb[idx] * PB_ZONE_PCT / 100
    pb_long = (low_[idx] <= ema_pb[idx] + pb_zone and
               close[idx] > ema_pb[idx] and
               close[idx] > open_[idx])

    if trend_up and pb_long:
        sl = close[idx] - atr_val[idx] * LONG_SL_MULT
        risk = close[idx] - sl
        if risk > 0:
            tp = close[idx] + risk * LONG_TP_RR
            return Signal(
                direction="LONG",
                timeframe=tf_label,
                entry=close[idx],
                sl=sl,
                tp=tp,
                st_dir="BULL",
                ema_align="21 > 50",
                exit_method="Trailing ATR x 2",
            )
    return None


def check_short(klines: np.ndarray, tf_label: str) -> Optional[Signal]:
    """Détecte un signal SHORT V13 — pullback EMA21 dans un downtrend."""
    close = klines[:, 4]
    high_ = klines[:, 2]
    low_ = klines[:, 3]
    open_ = klines[:, 1]

    # Indicateurs
    st_val, st_dir = supertrend(high_, low_, close, ST_FACTOR, ST_PERIOD)
    ema_f = ema(close, EMA_FAST_LEN)
    ema_s = ema(close, EMA_SLOW_LEN)
    ema_macro = ema(close, EMA_MACRO_LEN)
    ema_pb = ema(close, EMA_PB_LEN)
    atr_val = atr(high_, low_, close, ATR_LEN)

    # Dernière bougie fermée
    idx = -2

    if any(np.isnan(x[idx]) for x in [st_val, ema_f, ema_s, ema_macro, ema_pb, atr_val]):
        return None

    # Conditions V13 (identiques au Pine)
    st_bear = st_dir[idx] > 0
    ema_bear = ema_f[idx] < ema_s[idx]
    trend_down = st_bear and ema_bear

    # Filtre macro : prix sous EMA200 obligatoire (vrai bear market)
    short_macro = close[idx] < ema_macro[idx]

    # Pullback EMA21 : prix remonte vers EMA21 → rejet (bougie rouge)
    pb_zone = ema_pb[idx] * PB_ZONE_PCT / 100
    pb_short = (high_[idx] >= ema_pb[idx] - pb_zone and
                close[idx] < ema_pb[idx] and
                close[idx] < open_[idx])

    if trend_down and pb_short and short_macro:
        sl = close[idx] + atr_val[idx] * SHORT_SL_MULT
        risk = sl - close[idx]
        if risk > 0:
            # Pas de TP fixe en mode "ST Flip" — sortie sur SuperTrend flip
            return Signal(
                direction="SHORT",
                timeframe=tf_label,
                entry=close[idx],
                sl=sl,
                tp=0,  # pas de TP fixe, sortie sur ST flip
                st_dir="BEAR",
                ema_align="21 < 50",
                exit_method="SuperTrend Flip",
            )
    return None


# ══════════════════════════════════════════════════════════════════════════════
# GESTION DE POSITION
# ══════════════════════════════════════════════════════════════════════════════

def manage_long(state: ScannerState, klines_4h: np.ndarray) -> Optional[str]:
    """Gère un LONG ouvert — trailing + sortie SuperTrend flip."""
    close = klines_4h[:, 4]
    high_ = klines_4h[:, 2]
    low_ = klines_4h[:, 3]
    idx = -2

    cur_close = close[idx]
    atr_val = atr(high_, low_, close, ATR_LEN)
    st_val, st_dir = supertrend(high_, low_, close, ST_FACTOR, ST_PERIOD)

    if np.isnan(atr_val[idx]):
        return None

    # SuperTrend flip bear → fermer immédiatement (protection V13)
    if st_dir[idx] > 0:
        state.position = "FLAT"
        state.trail_long = 0
        pnl = (cur_close - state.entry_price) / state.entry_price * 100
        return f"SuperTrend Flip \u25bc | PnL: {pnl:+.2f}%"

    # Trailing stop (ATR x 2)
    if state.trail_long > 0:
        new_trail = cur_close - atr_val[idx] * LONG_TRAIL_MULT
        state.trail_long = max(state.trail_long, new_trail)
        if cur_close <= state.trail_long:
            pnl = (cur_close - state.entry_price) / state.entry_price * 100
            state.position = "FLAT"
            state.trail_long = 0
            return f"Trailing Stop Long | PnL: {pnl:+.2f}%"

    return None


def manage_short(state: ScannerState, klines_4h: np.ndarray) -> Optional[str]:
    """Gère un SHORT ouvert — SL fixe + sortie SuperTrend flip."""
    close = klines_4h[:, 4]
    high_ = klines_4h[:, 2]
    low_ = klines_4h[:, 3]
    idx = -2

    cur_close = close[idx]
    st_val, st_dir = supertrend(high_, low_, close, ST_FACTOR, ST_PERIOD)

    # SuperTrend flip bull → fermer (sortie principale V13)
    if st_dir[idx] < 0:
        state.position = "FLAT"
        state.short_sl = 0
        pnl = (state.entry_price - cur_close) / state.entry_price * 100
        return f"SuperTrend Flip \u25b2 | PnL: {pnl:+.2f}%"

    # SL fixe touché (ATR x 3)
    if state.short_sl > 0 and cur_close >= state.short_sl:
        pnl = (state.entry_price - cur_close) / state.entry_price * 100
        state.position = "FLAT"
        state.short_sl = 0
        return f"SL Short (ATR x {SHORT_SL_MULT}) | PnL: {pnl:+.2f}%"

    return None


# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════════════════

def send_telegram(text: str) -> bool:
    try:
        resp = requests.post(TELEGRAM_API, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
        }, timeout=10)
        return resp.ok
    except Exception as e:
        logging.error("Erreur Telegram: %s", e)
        return False


def format_long_alert(sig: Signal) -> str:
    risk = sig.entry - sig.sl
    rr = (sig.tp - sig.entry) / risk if risk > 0 else 0
    return (
        "\U0001F7E2 <b>LONG BTC</b> \u2014 Pullback EMA21\n"
        f"\n"
        f"\U0001F4CD Entry: <code>{sig.entry:,.2f}</code>\n"
        f"\U0001F6D1 SL: <code>{sig.sl:,.2f}</code> (ATR x {LONG_SL_MULT})\n"
        f"\U0001F3AF TP: <code>{sig.tp:,.2f}</code> ({LONG_TP_RR}R)\n"
        f"\n"
        f"\U0001F4C8 SuperTrend: {sig.st_dir} | EMA: {sig.ema_align}\n"
        f"\U0001F4CA TF: {sig.timeframe} | R:R = 1:{rr:.1f}\n"
        f"\U0001F6E1 Trail: ATR x {LONG_TRAIL_MULT}\n"
        f"\U0001F6AA Exit: Trailing stop ou SuperTrend flip\n"
        f"\U0000231A {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC"
    )


def format_short_alert(sig: Signal) -> str:
    return (
        "\U0001F534 <b>SHORT BTC</b> \u2014 Pullback EMA21\n"
        f"\n"
        f"\U0001F4CD Entry: <code>{sig.entry:,.2f}</code>\n"
        f"\U0001F6D1 SL: <code>{sig.sl:,.2f}</code> (ATR x {SHORT_SL_MULT})\n"
        f"\n"
        f"\U0001F4C8 SuperTrend: {sig.st_dir} | EMA: {sig.ema_align}\n"
        f"\U0001F4CA TF: {sig.timeframe} | Filtre: prix < EMA200\n"
        f"\U0001F6AA Exit: {sig.exit_method}\n"
        f"\U0000231A {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC"
    )


def format_exit_alert(direction: str, reason: str, entry: float) -> str:
    arrow = "\U00002705" if "PnL: +" in reason or "PnL: ~0" in reason else "\U0000274C"
    return (
        f"{arrow} <b>FERMETURE {direction}</b>\n"
        f"\n"
        f"\U0001F4CD Entr\u00e9e \u00e9tait: <code>{entry:,.2f}</code>\n"
        f"\U0001F4CB Raison: {reason}\n"
        f"\U0000231A {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC"
    )


# ══════════════════════════════════════════════════════════════════════════════
# BOUCLE PRINCIPALE
# ══════════════════════════════════════════════════════════════════════════════

def main():
    logging.info("Phantom Edge V13 Scanner d\u00e9marr\u00e9 \u2014 Scan toutes les %ds", SCAN_INTERVAL)
    send_telegram(
        "\U0001F47B <b>Phantom Edge V13 Scanner</b>\n"
        "Scan toutes les 5 min sur Binance\n"
        "\U0001F7E2 LONG: 4H (SuperTrend + EMA pullback)\n"
        "\U0001F534 SHORT: 4H (Pullback EMA21 + EMA200 filter)\n"
        f"Max {MAX_DAILY} trades/jour\n"
        "\n"
        "<i>V13 = Best of V11 + V12</i>"
    )

    state = ScannerState.load()

    while True:
        try:
            now = datetime.now(timezone.utc)

            # Reset compteur journalier
            if now.day != state.last_day:
                state.day_trades = 0
                state.last_day = now.day
                logging.info("Nouveau jour \u2014 compteur trades reset")

            can_trade = state.day_trades < MAX_DAILY

            # ── Fetch données 4H ──
            klines_4h = fetch_klines(SYMBOL, "4h", limit=300)

            # ── Gestion de position existante ──
            if state.position == "LONG":
                exit_msg = manage_long(state, klines_4h)
                if exit_msg:
                    msg = format_exit_alert("LONG", exit_msg, state.entry_price)
                    send_telegram(msg)
                    logging.info("EXIT LONG: %s", exit_msg)
                    state.save()

            elif state.position == "SHORT":
                exit_msg = manage_short(state, klines_4h)
                if exit_msg:
                    msg = format_exit_alert("SHORT", exit_msg, state.entry_price)
                    send_telegram(msg)
                    logging.info("EXIT SHORT: %s", exit_msg)
                    state.short_sl = 0
                    state.save()

            # ── Détection nouveaux signaux (uniquement si FLAT) ──
            if state.position == "FLAT" and can_trade:
                # Vérifier LONG sur 4H
                long_sig = check_long(klines_4h, "4H")

                if long_sig:
                    msg = format_long_alert(long_sig)
                    if send_telegram(msg):
                        state.position = "LONG"
                        state.entry_price = long_sig.entry
                        state.entry_time = now.isoformat()
                        state.trail_long = long_sig.sl
                        state.day_trades += 1
                        state.last_signal_time = time.time()
                        logging.info("ALERTE LONG envoy\u00e9e @ %.2f (4H)", long_sig.entry)
                        state.save()

                else:
                    # Vérifier SHORT sur 4H (V13 : pullback, pas cross)
                    short_sig = check_short(klines_4h, "4H")
                    if short_sig:
                        msg = format_short_alert(short_sig)
                        if send_telegram(msg):
                            state.position = "SHORT"
                            state.entry_price = short_sig.entry
                            state.entry_time = now.isoformat()
                            state.short_sl = short_sig.sl
                            state.day_trades += 1
                            state.last_signal_time = time.time()
                            logging.info("ALERTE SHORT envoy\u00e9e @ %.2f (4H)", short_sig.entry)
                            state.save()

            # Log status
            if state.position != "FLAT":
                cur_price = klines_4h[-2, 4]
                if state.position == "LONG":
                    pnl = (cur_price - state.entry_price) / state.entry_price * 100
                    trail_info = f"Trail: {state.trail_long:.2f}"
                else:
                    pnl = (state.entry_price - cur_price) / state.entry_price * 100
                    trail_info = f"SL: {state.short_sl:.2f}"
                logging.info("Position: %s @ %.2f | PnL: %+.2f%% | %s",
                             state.position, state.entry_price, pnl, trail_info)
            else:
                logging.info("FLAT \u2014 Trades: %d/%d", state.day_trades, MAX_DAILY)

            state.save()

        except requests.exceptions.RequestException as e:
            logging.warning("Erreur r\u00e9seau: %s \u2014 retry dans 30s", e)
            time.sleep(30)
            continue
        except Exception as e:
            logging.error("Erreur inattendue: %s", e, exc_info=True)
            time.sleep(30)
            continue

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
