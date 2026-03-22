"""
Phantom Edge V11 — Autonomous Scanner
Reproduit la logique phantom_edge_v11.pine sans TradingView.
Utilise l'API Binance (gratuite, sans clé).

Logique identique au Pine Script :
  LONGS (4H + Daily) : SuperTrend bull + EMA 21>50 + pullback EMA 21 + bougie haussière
    → SL = ATR x 2, trailing ATR x 2, breakeven à +5%
  SHORTS (Daily only) : EMA 21/50 bearish cross + ADX ≥ 20 + DI- > DI+
    → Breakeven +5%, time stop 15 bars, trailing 10%/12%, EMA re-cross exit

Usage:
  cp .env.example .env   # remplir TELEGRAM_TOKEN + TELEGRAM_CHAT_ID
  pip install -r requirements.txt
  python btc_scanner.py
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

from alert_manager import AlertManager

load_dotenv()

# ── Config ──
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

SYMBOL = "BTCUSDT"
STATE_FILE = Path(__file__).parent / "scanner_state.json"

# ── Paramètres identiques au Pine V11 ──
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
LONG_BE_PCT = 5.0

# Short ADX
SHORT_ADX_LEN = 14
SHORT_ADX_MIN = 20.0

# Short protection
SHORT_BE_PCT = 5.0
SHORT_TIME_BARS = 15
SHORT_TRAIL_ACT = 10.0
SHORT_TRAIL_PCT = 12.0
SHORT_MIN_BARS = 10

# Session
MAX_DAILY = 3

# Scan toutes les 5 minutes (les bougies 4H changent lentement)
SCAN_INTERVAL = 300

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)


# ══════════════════════════════════════════════════════════════════════════════
# BINANCE API
# ══════════════════════════════════════════════════════════════════════════════

def fetch_klines(symbol: str, interval: str, limit: int = 200) -> np.ndarray:
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


def dmi(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int):
    """Directional Movement Index. Retourne (di_plus, di_minus, adx)."""
    n = len(high)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)

    for i in range(1, n):
        up_move = high[i] - high[i - 1]
        dn_move = low[i - 1] - low[i]
        plus_dm[i] = up_move if (up_move > dn_move and up_move > 0) else 0
        minus_dm[i] = dn_move if (dn_move > up_move and dn_move > 0) else 0
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))

    tr[0] = high[0] - low[0]
    smoothed_tr = rma(tr, length)
    smoothed_plus = rma(plus_dm, length)
    smoothed_minus = rma(minus_dm, length)

    di_plus = np.where(smoothed_tr > 0, 100 * smoothed_plus / smoothed_tr, 0)
    di_minus = np.where(smoothed_tr > 0, 100 * smoothed_minus / smoothed_tr, 0)

    dx = np.where((di_plus + di_minus) > 0,
                  100 * np.abs(di_plus - di_minus) / (di_plus + di_minus), 0)
    adx = rma(dx, length)

    return di_plus, di_minus, adx


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

        # Long management
        self.trail_long: float = 0
        self.long_be_reached: bool = False

        # Short management
        self.short_lowest: float = 0
        self.short_be_reached: bool = False
        self.short_trail_active: bool = False
        self.short_bars_in: int = 0
        self.short_bars_since: int = 999

        # Daily counter
        self.day_trades: int = 0
        self.last_day: int = 0

        # Dedup
        self.last_signal_time: float = 0

        # Résumé quotidien
        self.daily_summary_sent: bool = False
        self.signals_today: list = []

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
# ANALYSE — Phantom Edge V11
# ══════════════════════════════════════════════════════════════════════════════

class Signal:
    def __init__(self, direction: str, timeframe: str, entry: float,
                 sl: float = 0, tp: float = 0, adx: float = 0,
                 st_dir: str = "", ema_align: str = ""):
        self.direction = direction
        self.timeframe = timeframe
        self.entry = entry
        self.sl = sl
        self.tp = tp
        self.adx = adx
        self.st_dir = st_dir
        self.ema_align = ema_align


def check_long(klines: np.ndarray, tf_label: str) -> Optional[Signal]:
    """Détecte un signal LONG sur les données fournies (4H ou 1D)."""
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

    # Dernière bougie fermée
    idx = -2

    if any(np.isnan(x[idx]) for x in [st_val, ema_f, ema_s, ema_pb, atr_val]):
        return None

    # Conditions (identiques au Pine)
    st_bull = st_dir[idx] < 0
    ema_bull = ema_f[idx] > ema_s[idx]
    trend_up = st_bull and ema_bull

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
            )
    return None


def check_short(klines_daily: np.ndarray) -> Optional[Signal]:
    """Détecte un signal SHORT sur daily uniquement."""
    close = klines_daily[:, 4]
    high_ = klines_daily[:, 2]
    low_ = klines_daily[:, 3]

    ema_f = ema(close, EMA_FAST_LEN)
    ema_s = ema(close, EMA_SLOW_LEN)
    di_plus, di_minus, adx_val = dmi(high_, low_, close, SHORT_ADX_LEN)

    idx = -2

    if any(np.isnan(x[idx]) for x in [ema_f, ema_s, adx_val]):
        return None

    # EMA 21/50 bearish cross : ema_f passe sous ema_s
    bearish_cross = ema_f[idx] < ema_s[idx] and ema_f[idx - 1] >= ema_s[idx - 1]

    # ADX + DI
    adx_ok = adx_val[idx] >= SHORT_ADX_MIN
    di_ok = di_minus[idx] > di_plus[idx]

    if bearish_cross and adx_ok and di_ok:
        return Signal(
            direction="SHORT",
            timeframe="1D",
            entry=close[idx],
            adx=adx_val[idx],
            ema_align="21 < 50 (cross)",
        )
    return None


# ══════════════════════════════════════════════════════════════════════════════
# GESTION DE POSITION (trailing, BE, time stop, etc.)
# ══════════════════════════════════════════════════════════════════════════════

def manage_long(state: ScannerState, klines_4h: np.ndarray) -> Optional[str]:
    """Gère une position LONG ouverte. Retourne un message de sortie ou None."""
    close = klines_4h[:, 4]
    high_ = klines_4h[:, 2]
    low_ = klines_4h[:, 3]
    idx = -2

    cur_close = close[idx]
    atr_val = atr(high_, low_, close, ATR_LEN)
    st_val, st_dir = supertrend(high_, low_, close, ST_FACTOR, ST_PERIOD)

    if np.isnan(atr_val[idx]):
        return None

    # SuperTrend flip bear → fermer
    if st_dir[idx] > 0:
        state.position = "FLAT"
        state.trail_long = 0
        state.long_be_reached = False
        pnl = (cur_close - state.entry_price) / state.entry_price * 100
        return f"SuperTrend Flip \u25bc | PnL: {pnl:+.2f}%"

    # Breakeven
    if state.entry_price > 0:
        profit_pct = (cur_close - state.entry_price) / state.entry_price * 100
        if profit_pct >= LONG_BE_PCT:
            state.long_be_reached = True
        if state.long_be_reached and cur_close <= state.entry_price:
            state.position = "FLAT"
            state.trail_long = 0
            state.long_be_reached = False
            return "BE Stop Long | PnL: ~0%"

    # Trailing
    if state.trail_long > 0:
        floor = state.entry_price if state.long_be_reached else state.trail_long
        state.trail_long = max(floor, cur_close - atr_val[idx] * LONG_TRAIL_MULT)
        if cur_close <= state.trail_long:
            pnl = (cur_close - state.entry_price) / state.entry_price * 100
            state.position = "FLAT"
            state.trail_long = 0
            state.long_be_reached = False
            return f"Trailing Stop Long | PnL: {pnl:+.2f}%"

    return None


def manage_short(state: ScannerState, klines_daily: np.ndarray) -> Optional[str]:
    """Gère une position SHORT ouverte. Retourne un message de sortie ou None."""
    close = klines_daily[:, 4]
    idx = -2
    cur_close = close[idx]

    state.short_bars_in += 1

    ema_f = ema(close, EMA_FAST_LEN)
    ema_s = ema(close, EMA_SLOW_LEN)

    # EMA re-cross haussier → sortie
    bullish_cross = ema_f[idx] > ema_s[idx] and ema_f[idx - 1] <= ema_s[idx - 1]
    if bullish_cross:
        pnl = (state.entry_price - cur_close) / state.entry_price * 100
        state.position = "FLAT"
        return f"Trend Exit Short (EMA re-cross) | PnL: {pnl:+.2f}%"

    # Breakeven
    if state.entry_price > 0:
        profit_pct = (state.entry_price - cur_close) / state.entry_price * 100
        if profit_pct >= SHORT_BE_PCT:
            state.short_be_reached = True
        if state.short_be_reached and cur_close >= state.entry_price:
            state.position = "FLAT"
            return "BE Stop Short | PnL: ~0%"

    # Time stop
    if state.short_bars_in >= SHORT_TIME_BARS:
        profit_pct = (state.entry_price - cur_close) / state.entry_price * 100
        if profit_pct <= 0:
            state.position = "FLAT"
            return f"Time Stop Short ({state.short_bars_in} bars) | PnL: {profit_pct:+.2f}%"

    # Trailing
    if state.short_lowest == 0 or cur_close < state.short_lowest:
        state.short_lowest = cur_close
    if state.entry_price > 0:
        profit_from_low = (state.entry_price - state.short_lowest) / state.entry_price * 100
        if profit_from_low >= SHORT_TRAIL_ACT:
            state.short_trail_active = True
        if state.short_trail_active:
            trail_level = state.short_lowest * (1 + SHORT_TRAIL_PCT / 100)
            if cur_close >= trail_level:
                pnl = (state.entry_price - cur_close) / state.entry_price * 100
                state.position = "FLAT"
                return f"Trailing Exit Short | PnL: {pnl:+.2f}%"

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
        "\U0001F7E2 <b>LONG BTC</b> — Pullback\n"
        f"\n"
        f"\U0001F4CD Entry: <code>{sig.entry:,.2f}</code>\n"
        f"\U0001F6D1 SL: <code>{sig.sl:,.2f}</code> (ATR x {LONG_SL_MULT})\n"
        f"\U0001F3AF TP: <code>{sig.tp:,.2f}</code> ({LONG_TP_RR}R)\n"
        f"\n"
        f"\U0001F4C8 SuperTrend: {sig.st_dir} | EMA: {sig.ema_align}\n"
        f"\U0001F4CA TF: {sig.timeframe} | R:R = 1:{rr:.1f}\n"
        f"\U0001F6E1 Trail: ATR x {LONG_TRAIL_MULT} | BE: +{LONG_BE_PCT}%\n"
        f"\U0000231A {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC"
    )


def format_short_alert(sig: Signal) -> str:
    return (
        "\U0001F534 <b>SHORT BTC</b> — EMA Cross (Daily)\n"
        f"\n"
        f"\U0001F4CD Entry: <code>{sig.entry:,.2f}</code>\n"
        f"\U0001F4C9 ADX: {sig.adx:.1f} | EMA: {sig.ema_align}\n"
        f"\n"
        f"\U0001F6E1 BE: +{SHORT_BE_PCT}% | Time: {SHORT_TIME_BARS} bars\n"
        f"\U0001F504 Trail: act. +{SHORT_TRAIL_ACT}%, offset {SHORT_TRAIL_PCT}%\n"
        f"\U0001F6AA Exit: EMA re-cross haussier\n"
        f"\U0000231A {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC"
    )


def format_exit_alert(direction: str, reason: str, entry: float) -> str:
    arrow = "\U00002705" if "PnL: +" in reason or "PnL: ~0" in reason else "\U0000274C"
    return (
        f"{arrow} <b>FERMETURE {direction}</b>\n"
        f"\n"
        f"\U0001F4CD Entrée était: <code>{entry:,.2f}</code>\n"
        f"\U0001F4CB Raison: {reason}\n"
        f"\U0000231A {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC"
    )


# ══════════════════════════════════════════════════════════════════════════════
# BOUCLE PRINCIPALE
# ══════════════════════════════════════════════════════════════════════════════

def format_daily_summary(state: ScannerState) -> str:
    """Resume du jour : signaux envoyes."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    signals = state.signals_today

    if not signals:
        return (
            f"\U0001F4C5 <b>Resume du jour</b> \u2014 {today}\n"
            "\n"
            "Aucun signal aujourd'hui.\n"
            f"\U0001F4C8 Position: {state.position}"
        )

    details = []
    for s in signals:
        emoji = "\U0001F7E2" if s["direction"] == "LONG" else "\U0001F534"
        details.append(f"  {emoji} {s['direction']} @ {s['entry']:,.2f} ({s['tf']})")

    pos_info = ""
    if state.position != "FLAT":
        pos_info = f"\n\U0001F4CB Position en cours: {state.position} @ {state.entry_price:,.2f}"

    return (
        f"\U0001F4C5 <b>Resume du jour</b> \u2014 {today}\n"
        "\n"
        f"\U0001F4CA {len(signals)} signal(s) envoye(s):\n"
        + "\n".join(details)
        + f"\n{pos_info}"
    )


def main():
    logging.info("Phantom Edge V11 Scanner demarr\u00e9 — Scan toutes les %ds", SCAN_INTERVAL)

    # Alert Manager
    alerts = AlertManager(send_fn=send_telegram)

    send_telegram(
        "\U0001F47B <b>Phantom Edge V11 Scanner</b>\n"
        "Scan toutes les 5 min sur Binance\n"
        "\U0001F7E2 LONG: 4H + Daily (SuperTrend + EMA pullback)\n"
        "\U0001F534 SHORT: Daily (EMA cross + ADX)\n"
        "Max 3 trades/jour\n"
        "\n"
        "\U0001F49A Heartbeat toutes les 4h\n"
        "\U0001F504 Alerte SuperTrend flip\n"
        "\U0001F4C5 Resume du jour a 21h UTC"
    )

    state = ScannerState.load()

    while True:
        try:
            now = datetime.now(timezone.utc)

            # Reset compteur journalier
            if now.day != state.last_day:
                state.day_trades = 0
                state.last_day = now.day
                state.daily_summary_sent = False
                state.signals_today = []
                logging.info("Nouveau jour \u2014 compteurs reset")

            # Resume quotidien a 21h UTC
            if now.hour >= 21 and not state.daily_summary_sent:
                summary = format_daily_summary(state)
                send_telegram(summary)
                state.daily_summary_sent = True
                logging.info("Resume quotidien envoye")

            can_trade = state.day_trades < MAX_DAILY

            # ── Fetch données ──
            klines_4h = fetch_klines(SYMBOL, "4h", limit=300)
            klines_1d = fetch_klines(SYMBOL, "1d", limit=300)

            # ── SuperTrend flip detection ──
            st_val_4h, st_dir_4h = supertrend(klines_4h[:, 2], klines_4h[:, 3], klines_4h[:, 4], ST_FACTOR, ST_PERIOD)
            st_val_1d, st_dir_1d = supertrend(klines_1d[:, 2], klines_1d[:, 3], klines_1d[:, 4], ST_FACTOR, ST_PERIOD)
            alerts.check_supertrend_flip(st_dir_4h[-2], st_dir_1d[-2], state.position)

            # ── Gestion de position existante ──
            if state.position == "LONG":
                exit_msg = manage_long(state, klines_4h)
                if exit_msg:
                    msg = format_exit_alert("LONG", exit_msg, state.entry_price)
                    send_telegram(msg)
                    logging.info("EXIT LONG: %s", exit_msg)
                    state.save()

            elif state.position == "SHORT":
                exit_msg = manage_short(state, klines_1d)
                if exit_msg:
                    msg = format_exit_alert("SHORT", exit_msg, state.entry_price)
                    send_telegram(msg)
                    logging.info("EXIT SHORT: %s", exit_msg)
                    # Reset short vars
                    state.short_lowest = 0
                    state.short_trail_active = False
                    state.short_be_reached = False
                    state.short_bars_in = 0
                    state.save()

            # ── Détection nouveaux signaux (uniquement si FLAT) ──
            if state.position == "FLAT" and can_trade:
                # Short cooldown
                state.short_bars_since += 1

                # Vérifier LONG sur 4H
                long_sig = check_long(klines_4h, "4H")
                if long_sig is None:
                    # Aussi vérifier LONG sur Daily
                    long_sig = check_long(klines_1d, "1D")

                if long_sig:
                    msg = format_long_alert(long_sig)
                    if send_telegram(msg):
                        state.position = "LONG"
                        state.entry_price = long_sig.entry
                        state.entry_time = now.isoformat()
                        state.trail_long = long_sig.sl
                        state.long_be_reached = False
                        state.day_trades += 1
                        state.last_signal_time = time.time()
                        state.signals_today.append({"direction": "LONG", "entry": long_sig.entry, "tf": long_sig.timeframe})
                        logging.info("ALERTE LONG envoyée @ %.2f (%s)", long_sig.entry, long_sig.timeframe)
                        state.save()

                # Vérifier SHORT sur Daily (si pas déjà long)
                elif state.short_bars_since >= SHORT_MIN_BARS:
                    short_sig = check_short(klines_1d)
                    if short_sig:
                        msg = format_short_alert(short_sig)
                        if send_telegram(msg):
                            state.position = "SHORT"
                            state.entry_price = short_sig.entry
                            state.entry_time = now.isoformat()
                            state.short_lowest = short_sig.entry
                            state.short_be_reached = False
                            state.short_trail_active = False
                            state.short_bars_in = 0
                            state.short_bars_since = 0
                            state.day_trades += 1
                            state.last_signal_time = time.time()
                            state.signals_today.append({"direction": "SHORT", "entry": short_sig.entry, "tf": "1D"})
                            logging.info("ALERTE SHORT envoyée @ %.2f", short_sig.entry)
                            state.save()

            # ── Scan reussi ──
            alerts.record_scan()

            # ── Heartbeat (toutes les 4h, pas entre 23h-6h) ──
            alerts.check_heartbeat(state.position, state.day_trades)

            # Log status
            if state.position != "FLAT":
                cur_price = klines_4h[-2, 4]
                if state.position == "LONG":
                    pnl = (cur_price - state.entry_price) / state.entry_price * 100
                else:
                    pnl = (state.entry_price - cur_price) / state.entry_price * 100
                logging.info("Position: %s @ %.2f | PnL: %+.2f%% | Trail: %.2f",
                             state.position, state.entry_price, pnl,
                             state.trail_long if state.position == "LONG" else state.short_lowest)
            else:
                logging.info("FLAT \u2014 Trades: %d/%d", state.day_trades, MAX_DAILY)

            state.save()

        except requests.exceptions.RequestException as e:
            logging.warning("Erreur r\u00e9seau: %s \u2014 retry dans 30s", e)
            alerts.record_error("Reseau", str(e))
            alerts.alert_connection_lost(str(e))
            time.sleep(30)
            continue
        except Exception as e:
            logging.error("Erreur inattendue: %s", e, exc_info=True)
            alerts.record_error("Inattendue", str(e))
            time.sleep(30)
            continue

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
