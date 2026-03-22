"""
Phantom Edge V14 — Enhanced Autonomous Scanner

Basé sur V13 (logique identique) + améliorations :
  - Position sizing dynamique (risk % par trade)
  - Circuit breaker (pause après pertes consécutives / drawdown)
  - Filtre ADX (régime de marché)
  - Score de confiance par signal
  - Trade tracking complet (CSV + stats)
  - Résumé P&L quotidien automatique
  - Commandes Telegram enrichies (/stats, /resume, /equity)
  - Notifications enrichies (R:R, confiance, taille position)

⚠️  Branche de développement — ne tourne PAS sur Render.
    Le bot V13 en production reste intact.

Usage:
  cp .env.example .env   # remplir TELEGRAM_TOKEN + TELEGRAM_CHAT_ID
  pip install -r requirements.txt
  python btc_scanner_v14.py
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

from risk_manager import (
    RiskConfig, CircuitBreaker, calculate_position_size,
    check_market_regime, calculate_confidence,
)
from trade_tracker import (
    log_entry, log_exit, compute_stats, format_stats_telegram,
    format_daily_summary,
)
from alert_manager import AlertManager, AlertConfig

load_dotenv()

# ── Config ──
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

SYMBOL = "BTCUSDT"
STATE_FILE = Path(__file__).parent / "scanner_state_v14.json"

# ── Paramètres identiques au Pine V13 ──
ST_FACTOR = 3.0
ST_PERIOD = 10
EMA_FAST_LEN = 21
EMA_SLOW_LEN = 50
EMA_MACRO_LEN = 200
EMA_PB_LEN = 21
PB_ZONE_PCT = 0.5
ATR_LEN = 14
LONG_SL_MULT = 2.0
LONG_TRAIL_MULT = 2.0
LONG_TP_RR = 3.0
SHORT_SL_MULT = 3.0
SHORT_EXIT = "ST Flip"
MAX_DAILY = 3
SCAN_INTERVAL = 300

# ── Risk Config (V14 nouveau) ──
RISK_CONFIG = RiskConfig(
    risk_per_trade_pct=2.0,
    max_position_pct=50.0,
    min_position_usd=100.0,
    max_consecutive_losses=3,
    max_daily_loss_pct=5.0,
    max_drawdown_pct=15.0,
    cooldown_hours=24,
    adx_min=20.0,
    adx_period=14,
    min_confidence=3,
)

INITIAL_EQUITY = float(os.environ.get("INITIAL_EQUITY", "10000"))

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
    return np.array([
        [float(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])]
        for k in data
    ])


# ══════════════════════════════════════════════════════════════════════════════
# INDICATEURS (identiques V13)
# ══════════════════════════════════════════════════════════════════════════════

def ema(src: np.ndarray, length: int) -> np.ndarray:
    result = np.full_like(src, np.nan, dtype=float)
    k = 2.0 / (length + 1)
    result[0] = src[0]
    for i in range(1, len(src)):
        result[i] = src[i] * k + result[i - 1] * (1 - k)
    return result


def rma(src: np.ndarray, length: int) -> np.ndarray:
    result = np.full_like(src, np.nan, dtype=float)
    result[length - 1] = np.mean(src[:length])
    k = 1.0 / length
    for i in range(length, len(src)):
        result[i] = src[i] * k + result[i - 1] * (1 - k)
    return result


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int) -> np.ndarray:
    tr = np.empty(len(high))
    tr[0] = high[0] - low[0]
    for i in range(1, len(high)):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    return rma(tr, length)


def supertrend(high: np.ndarray, low: np.ndarray, close: np.ndarray,
               factor: float, period: int):
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
            if prev_dir < 0:
                st_dir[i] = 1 if close[i] < lower_band[i] else -1
            else:
                st_dir[i] = -1 if close[i] > upper_band[i] else 1
        st_value[i] = lower_band[i] if st_dir[i] < 0 else upper_band[i]

    return st_value, st_dir


# ══════════════════════════════════════════════════════════════════════════════
# ÉTAT PERSISTANT (V14 — enrichi)
# ══════════════════════════════════════════════════════════════════════════════

class ScannerState:
    def __init__(self):
        self.position: str = "FLAT"
        self.entry_price: float = 0
        self.entry_time: str = ""
        self.trail_long: float = 0
        self.short_sl: float = 0
        self.day_trades: int = 0
        self.last_day: int = 0
        self.last_signal_time: float = 0

        # V14 — nouveaux champs
        self.equity: float = INITIAL_EQUITY
        self.current_trade_id: int = 0
        self.position_size_usd: float = 0
        self.position_size_btc: float = 0
        self.risk_pct: float = 0
        self.circuit_breaker: dict = {}
        self.daily_summary_sent: bool = False
        self.alert_state: dict = {}

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
# ANALYSE — Phantom Edge V14 (logique V13 + confiance + ADX)
# ══════════════════════════════════════════════════════════════════════════════

class Signal:
    def __init__(self, direction: str, timeframe: str, entry: float,
                 sl: float = 0, tp: float = 0,
                 st_dir: str = "", ema_align: str = "",
                 exit_method: str = "", confidence: dict = None):
        self.direction = direction
        self.timeframe = timeframe
        self.entry = entry
        self.sl = sl
        self.tp = tp
        self.st_dir = st_dir
        self.ema_align = ema_align
        self.exit_method = exit_method
        self.confidence = confidence or {}


def check_long(klines: np.ndarray, tf_label: str) -> Optional[Signal]:
    close = klines[:, 4]
    high_ = klines[:, 2]
    low_ = klines[:, 3]
    open_ = klines[:, 1]

    st_val, st_dir = supertrend(high_, low_, close, ST_FACTOR, ST_PERIOD)
    ema_f = ema(close, EMA_FAST_LEN)
    ema_s = ema(close, EMA_SLOW_LEN)
    ema_pb = ema(close, EMA_PB_LEN)
    atr_val = atr(high_, low_, close, ATR_LEN)

    idx = -2
    if any(np.isnan(x[idx]) for x in [st_val, ema_f, ema_s, ema_pb, atr_val]):
        return None

    st_bull = st_dir[idx] < 0
    ema_bull = ema_f[idx] > ema_s[idx]
    trend_up = st_bull and ema_bull

    pb_zone = ema_pb[idx] * PB_ZONE_PCT / 100
    pb_long = (low_[idx] <= ema_pb[idx] + pb_zone and
               close[idx] > ema_pb[idx] and
               close[idx] > open_[idx])

    # V14 — ADX filter
    regime = check_market_regime(high_, low_, close, RISK_CONFIG)
    adx_ok = regime["can_trade"]

    # V14 — Volume spike (simple: volume > 1.3x MA20)
    vol = klines[:, 5]
    vol_ma = np.mean(vol[max(0, idx - 20):idx]) if idx > 20 else np.mean(vol[:idx])
    vol_spike = vol[idx] > vol_ma * 1.3

    if trend_up and pb_long:
        sl = close[idx] - atr_val[idx] * LONG_SL_MULT
        risk = close[idx] - sl
        if risk > 0:
            tp = close[idx] + risk * LONG_TP_RR
            conf = calculate_confidence(
                direction="LONG",
                st_aligned=st_bull,
                ema_aligned=ema_bull,
                pullback_valid=pb_long,
                adx_trending=adx_ok,
                volume_spike=vol_spike,
                macro_filter=True,
            )
            return Signal(
                direction="LONG", timeframe=tf_label,
                entry=close[idx], sl=sl, tp=tp,
                st_dir="BULL", ema_align="21 > 50",
                exit_method="Trailing ATR x 2",
                confidence=conf,
            )
    return None


def check_short(klines: np.ndarray, tf_label: str) -> Optional[Signal]:
    close = klines[:, 4]
    high_ = klines[:, 2]
    low_ = klines[:, 3]
    open_ = klines[:, 1]

    st_val, st_dir = supertrend(high_, low_, close, ST_FACTOR, ST_PERIOD)
    ema_f = ema(close, EMA_FAST_LEN)
    ema_s = ema(close, EMA_SLOW_LEN)
    ema_macro = ema(close, EMA_MACRO_LEN)
    ema_pb = ema(close, EMA_PB_LEN)
    atr_val = atr(high_, low_, close, ATR_LEN)

    idx = -2
    if any(np.isnan(x[idx]) for x in [st_val, ema_f, ema_s, ema_macro, ema_pb, atr_val]):
        return None

    st_bear = st_dir[idx] > 0
    ema_bear = ema_f[idx] < ema_s[idx]
    trend_down = st_bear and ema_bear
    short_macro = close[idx] < ema_macro[idx]

    pb_zone = ema_pb[idx] * PB_ZONE_PCT / 100
    pb_short = (high_[idx] >= ema_pb[idx] - pb_zone and
                close[idx] < ema_pb[idx] and
                close[idx] < open_[idx])

    # V14 — ADX filter
    regime = check_market_regime(high_, low_, close, RISK_CONFIG)
    adx_ok = regime["can_trade"]

    if trend_down and pb_short and short_macro:
        sl = close[idx] + atr_val[idx] * SHORT_SL_MULT
        risk = sl - close[idx]
        if risk > 0:
            conf = calculate_confidence(
                direction="SHORT",
                st_aligned=st_bear,
                ema_aligned=ema_bear,
                pullback_valid=pb_short,
                adx_trending=adx_ok,
                volume_spike=False,
                macro_filter=short_macro,
            )
            return Signal(
                direction="SHORT", timeframe=tf_label,
                entry=close[idx], sl=sl, tp=0,
                st_dir="BEAR", ema_align="21 < 50",
                exit_method="SuperTrend Flip",
                confidence=conf,
            )
    return None


# ══════════════════════════════════════════════════════════════════════════════
# GESTION DE POSITION (identique V13)
# ══════════════════════════════════════════════════════════════════════════════

def manage_long(state: ScannerState, klines_4h: np.ndarray) -> Optional[str]:
    close = klines_4h[:, 4]
    high_ = klines_4h[:, 2]
    low_ = klines_4h[:, 3]
    idx = -2
    cur_close = close[idx]
    atr_val = atr(high_, low_, close, ATR_LEN)
    st_val, st_dir = supertrend(high_, low_, close, ST_FACTOR, ST_PERIOD)

    if np.isnan(atr_val[idx]):
        return None

    if st_dir[idx] > 0:
        state.position = "FLAT"
        state.trail_long = 0
        pnl = (cur_close - state.entry_price) / state.entry_price * 100
        return f"SuperTrend Flip \u25bc | PnL: {pnl:+.2f}%"

    if state.trail_long > 0:
        new_trail = cur_close - atr_val[idx] * LONG_TRAIL_MULT
        state.trail_long = max(state.trail_long, new_trail)
        if cur_close <= state.trail_long:
            pnl = (cur_close - state.entry_price) / state.entry_price * 100
            state.position = "FLAT"
            state.trail_long = 0
            return f"Trailing Stop Long | PnL: {pnl:+.2f}%"

    return None


def manage_short(state: ScannerState, klines_daily: np.ndarray) -> Optional[str]:
    close = klines_daily[:, 4]
    high_ = klines_daily[:, 2]
    low_ = klines_daily[:, 3]
    idx = -2
    cur_close = close[idx]
    st_val, st_dir = supertrend(high_, low_, close, ST_FACTOR, ST_PERIOD)

    if st_dir[idx] < 0:
        state.position = "FLAT"
        state.short_sl = 0
        pnl = (state.entry_price - cur_close) / state.entry_price * 100
        return f"SuperTrend Flip \u25b2 | PnL: {pnl:+.2f}%"

    if state.short_sl > 0 and cur_close >= state.short_sl:
        pnl = (state.entry_price - cur_close) / state.entry_price * 100
        state.position = "FLAT"
        state.short_sl = 0
        return f"SL Short (ATR x {SHORT_SL_MULT}) | PnL: {pnl:+.2f}%"

    return None


# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM (V14 — messages enrichis)
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


def format_long_alert(sig: Signal, pos_info: dict) -> str:
    risk = sig.entry - sig.sl
    rr = (sig.tp - sig.entry) / risk if risk > 0 else 0
    conf = sig.confidence
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
        f"\n"
        f"\U0001F4B0 <b>Position</b>: ${pos_info['position_usd']:,.0f} "
        f"({pos_info['position_btc']:.4f} BTC)\n"
        f"\U0001F6A8 Risque: ${pos_info['risk_usd']:,.0f} ({pos_info['risk_pct']:.1f}%)\n"
        f"\n"
        f"{conf.get('stars', '')} Confiance: {conf.get('score', 0)}/5\n"
        f"\U0000231A {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC"
    )


def format_short_alert(sig: Signal, pos_info: dict) -> str:
    conf = sig.confidence
    return (
        "\U0001F534 <b>SHORT BTC</b> \u2014 Pullback EMA21\n"
        f"\n"
        f"\U0001F4CD Entry: <code>{sig.entry:,.2f}</code>\n"
        f"\U0001F6D1 SL: <code>{sig.sl:,.2f}</code> (ATR x {SHORT_SL_MULT})\n"
        f"\n"
        f"\U0001F4C8 SuperTrend: {sig.st_dir} | EMA: {sig.ema_align}\n"
        f"\U0001F4CA TF: {sig.timeframe} | Filtre: prix < EMA200\n"
        f"\U0001F6AA Exit: {sig.exit_method}\n"
        f"\n"
        f"\U0001F4B0 <b>Position</b>: ${pos_info['position_usd']:,.0f} "
        f"({pos_info['position_btc']:.4f} BTC)\n"
        f"\U0001F6A8 Risque: ${pos_info['risk_usd']:,.0f} ({pos_info['risk_pct']:.1f}%)\n"
        f"\n"
        f"{conf.get('stars', '')} Confiance: {conf.get('score', 0)}/5\n"
        f"\U0000231A {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC"
    )


def format_exit_alert(direction: str, reason: str, entry: float,
                      pnl_usd: float, equity: float) -> str:
    arrow = "\U00002705" if "PnL: +" in reason else "\U0000274C"
    return (
        f"{arrow} <b>FERMETURE {direction}</b>\n"
        f"\n"
        f"\U0001F4CD Entr\u00e9e: <code>{entry:,.2f}</code>\n"
        f"\U0001F4CB Raison: {reason}\n"
        f"\U0001F4B0 P&L: <code>${pnl_usd:+,.2f}</code>\n"
        f"\U0001F4B5 Equity: <code>${equity:,.2f}</code>\n"
        f"\U0000231A {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC"
    )


def format_circuit_breaker_alert(reason: str) -> str:
    return (
        "\U0001F6A8 <b>CIRCUIT BREAKER ACTIV\u00c9</b>\n"
        f"\n"
        f"\U000026A0 {reason}\n"
        f"\n"
        f"Le bot est en pause. Utilisez /resume pour reprendre.\n"
        f"\U0000231A {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC"
    )


# ══════════════════════════════════════════════════════════════════════════════
# BOUCLE PRINCIPALE
# ══════════════════════════════════════════════════════════════════════════════

def process_exit(state: ScannerState, cb: CircuitBreaker,
                 direction: str, exit_msg: str, cur_price: float):
    """Traite une sortie de position : calcul P&L, log, circuit breaker."""
    if direction == "LONG":
        pnl_pct = (cur_price - state.entry_price) / state.entry_price * 100
    else:
        pnl_pct = (state.entry_price - cur_price) / state.entry_price * 100

    pnl_usd = state.position_size_usd * pnl_pct / 100
    state.equity += pnl_usd

    # Log dans le tracker
    log_exit(
        trade_id=state.current_trade_id,
        exit_price=cur_price,
        exit_reason=exit_msg,
        pnl_pct=pnl_pct,
        pnl_usd=pnl_usd,
        equity_after=state.equity,
    )

    # Telegram
    msg = format_exit_alert(direction, exit_msg, state.entry_price,
                            pnl_usd, state.equity)
    send_telegram(msg)
    logging.info("EXIT %s: %s | P&L: $%.2f", direction, exit_msg, pnl_usd)

    # Circuit breaker check
    triggered = cb.update_after_trade(pnl_pct, state.equity, INITIAL_EQUITY)
    if triggered:
        send_telegram(format_circuit_breaker_alert(cb.pause_reason))

    # Reset position
    state.position = "FLAT"
    state.trail_long = 0
    state.short_sl = 0
    state.position_size_usd = 0
    state.position_size_btc = 0
    state.current_trade_id = 0
    state.circuit_breaker = cb.to_dict()
    state.save()


def main():
    logging.info("Phantom Edge V14 Scanner demarr\u00e9 \u2014 Scan toutes les %ds", SCAN_INTERVAL)

    # ── Alert Manager ──
    alert_config = AlertConfig(
        heartbeat_interval_hours=4.0,
        drawdown_warn_pct=5.0,
        drawdown_critical_pct=10.0,
        max_consecutive_errors=3,
        error_cooldown_seconds=300,
        position_update_hours=2.0,
    )
    alerts = AlertManager(config=alert_config, send_fn=send_telegram)

    send_telegram(
        "\U0001F47B <b>Phantom Edge V14 Scanner</b>\n"
        "\n"
        "Toutes les am\u00e9liorations V14 :\n"
        "\U0001F4B0 Position sizing dynamique (2% risque/trade)\n"
        "\U0001F6A8 Circuit breaker (3 pertes, 5% daily, 15% DD)\n"
        "\U0001F4CA Filtre ADX (pas de trade en range)\n"
        "\U00002B50 Score de confiance par signal\n"
        "\U0001F4C8 Tracking complet + /stats\n"
        "\U0001F49A Heartbeat + alertes temps r\u00e9el\n"
        f"\n"
        f"\U0001F4B5 Equity: ${INITIAL_EQUITY:,.0f}\n"
        f"Max {MAX_DAILY} trades/jour\n"
        "\n"
        "<i>V14 = V13 + Risk Management + Tracking + Alertes</i>"
    )

    state = ScannerState.load()
    if state.equity <= 0:
        state.equity = INITIAL_EQUITY

    cb = CircuitBreaker.from_dict(state.circuit_breaker, RISK_CONFIG)
    if state.equity > cb.peak_equity:
        cb.peak_equity = state.equity

    # Restaurer l'etat des alertes si disponible
    if hasattr(state, 'alert_state') and state.alert_state:
        alerts.load_from_dict(state.alert_state)

    while True:
        try:
            now = datetime.now(timezone.utc)

            # Reset compteur journalier
            if now.day != state.last_day:
                state.day_trades = 0
                state.last_day = now.day
                state.daily_summary_sent = False
                cb.reset_daily()
                logging.info("Nouveau jour \u2014 compteurs reset")

            # Résumé quotidien automatique (23h UTC)
            if now.hour >= 23 and not state.daily_summary_sent:
                summary = format_daily_summary()
                send_telegram(summary)
                state.daily_summary_sent = True
                logging.info("R\u00e9sum\u00e9 quotidien envoy\u00e9")

            can_trade = state.day_trades < MAX_DAILY

            # Circuit breaker check
            cb_ok, cb_reason = cb.can_trade()
            if not cb_ok:
                logging.info("Circuit breaker actif: %s", cb_reason)
                # Heartbeat meme en pause
                alerts.check_heartbeat(state.position, state.equity, state.day_trades)
                state.circuit_breaker = cb.to_dict()
                state.save()
                time.sleep(SCAN_INTERVAL)
                continue

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
                    cur_price = klines_4h[-2, 4]
                    process_exit(state, cb, "LONG", exit_msg, cur_price)

            elif state.position == "SHORT":
                exit_msg = manage_short(state, klines_1d)
                if exit_msg:
                    cur_price = klines_1d[-2, 4]
                    process_exit(state, cb, "SHORT", exit_msg, cur_price)

            # ── Détection nouveaux signaux (uniquement si FLAT) ──
            if state.position == "FLAT" and can_trade and cb_ok:

                # V14 — Filtre ADX sur 4H
                regime_4h = check_market_regime(
                    klines_4h[:, 2], klines_4h[:, 3], klines_4h[:, 4], RISK_CONFIG
                )
                if not regime_4h["can_trade"]:
                    logging.info("ADX 4H = %.1f (choppy) — pas de trade", regime_4h["adx"])
                    state.save()
                    time.sleep(SCAN_INTERVAL)
                    continue

                # Vérifier LONG sur 4H, puis Daily
                long_sig = check_long(klines_4h, "4H")
                if long_sig is None:
                    long_sig = check_long(klines_1d, "1D")

                if long_sig:
                    # V14 — Confiance minimum
                    if long_sig.confidence.get("score", 0) < RISK_CONFIG.min_confidence:
                        logging.info("LONG rejet\u00e9: confiance %d/5 < %d",
                                     long_sig.confidence["score"], RISK_CONFIG.min_confidence)
                        alerts.alert_signal_missed("LONG", f"Confiance {long_sig.confidence['score']}/5 < {RISK_CONFIG.min_confidence}")
                    else:
                        # V14 — Position sizing
                        pos = calculate_position_size(
                            state.equity, long_sig.entry, long_sig.sl, RISK_CONFIG
                        )
                        msg = format_long_alert(long_sig, pos)
                        if send_telegram(msg):
                            trade_id = log_entry(
                                "LONG", long_sig.timeframe, long_sig.entry,
                                long_sig.sl, long_sig.tp, pos["risk_pct"], state.equity,
                            )
                            state.position = "LONG"
                            state.entry_price = long_sig.entry
                            state.entry_time = now.isoformat()
                            state.trail_long = long_sig.sl
                            state.day_trades += 1
                            state.last_signal_time = time.time()
                            state.current_trade_id = trade_id
                            state.position_size_usd = pos["position_usd"]
                            state.position_size_btc = pos["position_btc"]
                            state.risk_pct = pos["risk_pct"]
                            logging.info("LONG @ %.2f | Pos: $%.0f | Risk: %.1f%%",
                                         long_sig.entry, pos["position_usd"], pos["risk_pct"])
                            state.save()

                elif state.position == "FLAT":
                    # Vérifier SHORT sur Daily
                    short_sig = check_short(klines_1d, "1D")
                    if short_sig:
                        if short_sig.confidence.get("score", 0) < RISK_CONFIG.min_confidence:
                            logging.info("SHORT rejet\u00e9: confiance %d/5 < %d",
                                         short_sig.confidence["score"], RISK_CONFIG.min_confidence)
                            alerts.alert_signal_missed("SHORT", f"Confiance {short_sig.confidence['score']}/5 < {RISK_CONFIG.min_confidence}")
                        else:
                            pos = calculate_position_size(
                                state.equity, short_sig.entry, short_sig.sl, RISK_CONFIG
                            )
                            msg = format_short_alert(short_sig, pos)
                            if send_telegram(msg):
                                trade_id = log_entry(
                                    "SHORT", short_sig.timeframe, short_sig.entry,
                                    short_sig.sl, 0, pos["risk_pct"], state.equity,
                                )
                                state.position = "SHORT"
                                state.entry_price = short_sig.entry
                                state.entry_time = now.isoformat()
                                state.short_sl = short_sig.sl
                                state.day_trades += 1
                                state.last_signal_time = time.time()
                                state.current_trade_id = trade_id
                                state.position_size_usd = pos["position_usd"]
                                state.position_size_btc = pos["position_btc"]
                                state.risk_pct = pos["risk_pct"]
                                logging.info("SHORT @ %.2f | Pos: $%.0f | Risk: %.1f%%",
                                             short_sig.entry, pos["position_usd"], pos["risk_pct"])
                                state.save()

            # ── Scan reussi ──
            alerts.record_scan()

            # ── Alertes periodiques ──
            cur_price = klines_4h[-2, 4]

            # Heartbeat
            alerts.check_heartbeat(state.position, state.equity, state.day_trades)

            # Drawdown
            alerts.check_drawdown(state.equity, cb.peak_equity)

            # Position live update
            if state.position != "FLAT":
                alerts.check_position_update(
                    position=state.position,
                    entry_price=state.entry_price,
                    current_price=cur_price,
                    equity=state.equity,
                    trail_stop=state.trail_long,
                    short_sl=state.short_sl,
                    position_size_usd=state.position_size_usd,
                )

            # Log status
            if state.position != "FLAT":
                if state.position == "LONG":
                    pnl = (cur_price - state.entry_price) / state.entry_price * 100
                    trail_info = f"Trail: {state.trail_long:.2f}"
                else:
                    pnl = (state.entry_price - cur_price) / state.entry_price * 100
                    trail_info = f"SL: {state.short_sl:.2f}"
                logging.info("Position: %s @ %.2f | PnL: %+.2f%% | %s | Equity: $%.2f",
                             state.position, state.entry_price, pnl, trail_info, state.equity)
            else:
                logging.info("FLAT \u2014 Trades: %d/%d | Equity: $%.2f | ADX 4H: %s",
                             state.day_trades, MAX_DAILY, state.equity,
                             regime_4h.get("adx", "?") if "regime_4h" in dir() else "?")

            state.circuit_breaker = cb.to_dict()
            state.alert_state = alerts.to_dict()
            state.save()

        except requests.exceptions.RequestException as e:
            logging.warning("Erreur r\u00e9seau: %s \u2014 retry dans 30s", e)
            alerts.record_error("Reseau", str(e))
            alerts.alert_connection_lost("Binance", str(e))
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
