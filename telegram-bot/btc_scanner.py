"""
BTC Autonomous Scanner — Reproduit la logique V3 (Structure + Multi-Timeframe)
sans TradingView. Utilise l'API Binance (gratuite, sans clé).

Logique identique au Pine Script btc_daytrading_v3.pine :
  - Biais HTF : EMA 50 sur 4H
  - Consolidation + Breakout
  - Pivot S/R + Bounce
  - RSI + Volume spike
  - Filtre session (London/NY/Overlap)
  - Max trades/jour
  - SL/TP basés sur la structure

Usage:
  cp .env.example .env   # remplir TELEGRAM_TOKEN + TELEGRAM_CHAT_ID
  pip install -r requirements.txt
  python btc_scanner.py
"""

import os
import time
import logging
from datetime import datetime, timezone
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
LTF = "15m"       # timeframe d'entrée
HTF = "4h"        # timeframe biais

# Paramètres identiques au Pine V3
EMA_HTF_LEN = 50
LOOKBACK = 20
BREAKOUT_MULT = 0.5
CONSOL_BARS = 8
CONSOL_WIDTH = 1.5
RSI_LEN = 14
VOL_MULT = 1.3
VOL_MA_LEN = 20
ATR_LEN = 14
SL_BUFFER = 0.3
TP1_RR = 1.5
TP2_RR = 3.0
MAX_TRADES_DAY = 3
PIVOT_LEN = 10

# Intervalle de scan (secondes) — toutes les 60s
SCAN_INTERVAL = 60

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)


# ══════════════════════════════════════════════════════════════════════════════
# BINANCE API (gratuite, sans clé)
# ══════════════════════════════════════════════════════════════════════════════

def fetch_klines(symbol: str, interval: str, limit: int = 200) -> np.ndarray:
    """Récupère les klines Binance. Retourne array [timestamp, O, H, L, C, V]."""
    url = "https://api.binance.com/api/v3/klines"
    resp = requests.get(url, params={
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    # [open_time, open, high, low, close, volume, ...]
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
    result = np.full_like(src, np.nan)
    k = 2.0 / (length + 1)
    result[0] = src[0]
    for i in range(1, len(src)):
        result[i] = src[i] * k + result[i - 1] * (1 - k)
    return result


def sma(src: np.ndarray, length: int) -> np.ndarray:
    """Simple Moving Average."""
    result = np.full_like(src, np.nan)
    for i in range(length - 1, len(src)):
        result[i] = np.mean(src[i - length + 1:i + 1])
    return result


def rsi(src: np.ndarray, length: int) -> np.ndarray:
    """Relative Strength Index."""
    result = np.full_like(src, np.nan)
    deltas = np.diff(src)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[:length])
    avg_loss = np.mean(losses[:length])

    for i in range(length, len(deltas)):
        avg_gain = (avg_gain * (length - 1) + gains[i]) / length
        avg_loss = (avg_loss * (length - 1) + losses[i]) / length
        if avg_loss == 0:
            result[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = 100.0 - 100.0 / (1.0 + rs)

    return result


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int) -> np.ndarray:
    """Average True Range."""
    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(np.abs(high[1:] - close[:-1]),
                               np.abs(low[1:] - close[:-1])))
    tr = np.concatenate([[high[0] - low[0]], tr])
    # RMA (Wilder's smoothing = EMA with alpha=1/length)
    result = np.full_like(tr, np.nan)
    result[length - 1] = np.mean(tr[:length])
    k = 1.0 / length
    for i in range(length, len(tr)):
        result[i] = tr[i] * k + result[i - 1] * (1 - k)
    return result


def highest(src: np.ndarray, length: int) -> np.ndarray:
    """Rolling highest."""
    result = np.full_like(src, np.nan)
    for i in range(length - 1, len(src)):
        result[i] = np.max(src[i - length + 1:i + 1])
    return result


def lowest(src: np.ndarray, length: int) -> np.ndarray:
    """Rolling lowest."""
    result = np.full_like(src, np.nan)
    for i in range(length - 1, len(src)):
        result[i] = np.min(src[i - length + 1:i + 1])
    return result


def pivot_high(high: np.ndarray, left: int, right: int) -> np.ndarray:
    """Détecte les pivot highs (confirmés après 'right' barres)."""
    result = np.full_like(high, np.nan)
    for i in range(left, len(high) - right):
        val = high[i]
        if all(high[j] < val for j in range(i - left, i)) and \
           all(high[j] < val for j in range(i + 1, i + right + 1)):
            result[i + right] = val  # confirmé 'right' barres plus tard
    return result


def pivot_low(low: np.ndarray, left: int, right: int) -> np.ndarray:
    """Détecte les pivot lows (confirmés après 'right' barres)."""
    result = np.full_like(low, np.nan)
    for i in range(left, len(low) - right):
        val = low[i]
        if all(low[j] > val for j in range(i - left, i)) and \
           all(low[j] > val for j in range(i + 1, i + right + 1)):
            result[i + right] = val
    return result


# ══════════════════════════════════════════════════════════════════════════════
# STRATÉGIE V3
# ══════════════════════════════════════════════════════════════════════════════

class SignalResult:
    def __init__(self):
        self.direction: Optional[str] = None  # "LONG" ou "SHORT"
        self.signal_type: Optional[str] = None  # "Breakout" ou "S/R Bounce"
        self.entry: float = 0
        self.sl: float = 0
        self.tp1: float = 0
        self.tp2: float = 0
        self.risk: float = 0
        self.rsi: float = 0
        self.htf_bias: str = ""
        self.consolidation: bool = False


def analyze(ltf_klines: np.ndarray, htf_klines: np.ndarray) -> Optional[SignalResult]:
    """Analyse les données et retourne un signal si détecté."""
    # ── HTF : Biais directionnel ──
    htf_close = htf_klines[:, 4]
    ema_htf = ema(htf_close, EMA_HTF_LEN)

    bias_bull = htf_close[-1] > ema_htf[-1]
    bias_bear = htf_close[-1] < ema_htf[-1]

    # ── LTF : Indicateurs ──
    close = ltf_klines[:, 4]
    high_ = ltf_klines[:, 2]
    low_ = ltf_klines[:, 3]
    vol = ltf_klines[:, 5]

    rsi_val = rsi(close, RSI_LEN)
    atr_val = atr(high_, low_, close, ATR_LEN)
    vol_ma = sma(vol, VOL_MA_LEN)

    i = -1  # dernière bougie complète = avant-dernière (la dernière est en cours)
    # On utilise -2 pour la dernière bougie fermée
    idx = -2

    if np.isnan(atr_val[idx]) or np.isnan(rsi_val[idx]) or np.isnan(vol_ma[idx]):
        return None

    cur_close = close[idx]
    cur_high = high_[idx]
    cur_low = low_[idx]
    cur_rsi = rsi_val[idx]
    cur_atr = atr_val[idx]
    cur_vol = vol[idx]
    cur_vol_ma = vol_ma[idx]

    # ── Consolidation ──
    range_h = highest(high_, LOOKBACK)
    range_l = lowest(low_, LOOKBACK)

    if np.isnan(range_h[idx]) or np.isnan(range_l[idx]):
        return None

    range_width = range_h[idx] - range_l[idx]

    # Vérifier consolidation sur les N dernières barres
    narrow_count = 0
    for j in range(CONSOL_BARS):
        k = idx - j
        if k < LOOKBACK:
            break
        rw = range_h[k] - range_l[k]
        if rw < CONSOL_WIDTH * atr_val[k]:
            narrow_count += 1

    in_consol = narrow_count >= CONSOL_BARS

    # Consolidation à la barre précédente (pour breakout)
    narrow_count_prev = 0
    for j in range(CONSOL_BARS):
        k = idx - 1 - j
        if k < LOOKBACK:
            break
        rw = range_h[k] - range_l[k]
        if not np.isnan(atr_val[k]) and rw < CONSOL_WIDTH * atr_val[k]:
            narrow_count_prev += 1

    in_consol_prev = narrow_count_prev >= CONSOL_BARS

    # ── Breakout ──
    prev_range_h = range_h[idx - 1]
    prev_range_l = range_l[idx - 1]

    breakout_up = (in_consol_prev and
                   cur_close > prev_range_h and
                   (cur_close - prev_range_h) > cur_atr * BREAKOUT_MULT)

    breakout_dn = (in_consol_prev and
                   cur_close < prev_range_l and
                   (prev_range_l - cur_close) > cur_atr * BREAKOUT_MULT)

    # ── Pivot S/R ──
    ph = pivot_high(high_, PIVOT_LEN, PIVOT_LEN)
    pl = pivot_low(low_, PIVOT_LEN, PIVOT_LEN)

    sr_resist = np.nan
    sr_support = np.nan
    # Chercher les derniers pivots valides
    for j in range(len(ph) - 1, -1, -1):
        if not np.isnan(ph[j]):
            sr_resist = ph[j]
            break
    for j in range(len(pl) - 1, -1, -1):
        if not np.isnan(pl[j]):
            sr_support = pl[j]
            break

    # ── Bounce S/R ──
    near_support = (not np.isnan(sr_support) and
                    cur_low <= sr_support * 1.003 and
                    cur_close > sr_support)
    near_resist = (not np.isnan(sr_resist) and
                   cur_high >= sr_resist * 0.997 and
                   cur_close < sr_resist)

    # ── Volume ──
    vol_spike = cur_vol > cur_vol_ma * VOL_MULT

    # ── Signaux ──
    result = SignalResult()
    result.rsi = cur_rsi
    result.htf_bias = "BULL" if bias_bull else "BEAR" if bias_bear else "NEUTRE"
    result.consolidation = in_consol

    # LONG
    long_breakout = breakout_up and bias_bull and vol_spike and 50 < cur_rsi < 75
    long_bounce = near_support and bias_bull and cur_rsi < 40 and cur_vol > cur_vol_ma

    if long_breakout or long_bounce:
        sl_level = min(prev_range_l, sr_support if not np.isnan(sr_support) else prev_range_l) - cur_atr * SL_BUFFER
        risk = cur_close - sl_level
        if 0 < risk < cur_atr * 3:
            result.direction = "LONG"
            result.signal_type = "Breakout" if long_breakout else "S/R Bounce"
            result.entry = cur_close
            result.sl = sl_level
            result.tp1 = cur_close + risk * TP1_RR
            result.tp2 = cur_close + risk * TP2_RR
            result.risk = risk
            return result

    # SHORT
    short_breakout = breakout_dn and bias_bear and vol_spike and 25 < cur_rsi < 50
    short_bounce = near_resist and bias_bear and cur_rsi > 60 and cur_vol > cur_vol_ma

    if short_breakout or short_bounce:
        sl_level = max(prev_range_h, sr_resist if not np.isnan(sr_resist) else prev_range_h) + cur_atr * SL_BUFFER
        risk = sl_level - cur_close
        if 0 < risk < cur_atr * 3:
            result.direction = "SHORT"
            result.signal_type = "Breakout" if short_breakout else "S/R Bounce"
            result.entry = cur_close
            result.sl = sl_level
            result.tp1 = cur_close - risk * TP1_RR
            result.tp2 = cur_close - risk * TP2_RR
            result.risk = risk
            return result

    return None


# ══════════════════════════════════════════════════════════════════════════════
# SESSION
# ══════════════════════════════════════════════════════════════════════════════

def in_session() -> bool:
    """Vérifie si on est en session active (London/NY/Overlap)."""
    hr = datetime.now(timezone.utc).hour
    london = 8 <= hr < 12
    ny = 13 <= hr < 17
    overlap = 12 <= hr < 16
    return london or ny or overlap


# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════════════════

def send_telegram(text: str) -> bool:
    """Envoie un message Telegram."""
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


def format_alert(sig: SignalResult) -> str:
    """Formate l'alerte en message lisible."""
    arrow = "\U0001F7E2" if sig.direction == "LONG" else "\U0001F534"
    rr = abs(sig.tp2 - sig.entry) / sig.risk if sig.risk > 0 else 0

    return (
        f"{arrow} <b>{sig.direction} BTC</b> — {sig.signal_type}\n"
        f"\n"
        f"\U0001F4CD Entry: <code>{sig.entry:,.2f}</code>\n"
        f"\U0001F6D1 SL: <code>{sig.sl:,.2f}</code>\n"
        f"\U0001F3AF TP1: <code>{sig.tp1:,.2f}</code> ({TP1_RR}R)\n"
        f"\U0001F3AF TP2: <code>{sig.tp2:,.2f}</code> ({TP2_RR}R)\n"
        f"\n"
        f"\U0001F4CA RSI: {sig.rsi:.1f} | Biais 4H: {sig.htf_bias}\n"
        f"\U0001F4B0 Risk: <code>{sig.risk:,.2f}</code> | R:R = 1:{rr:.1f}\n"
        f"\U0000231A {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC"
    )


# ══════════════════════════════════════════════════════════════════════════════
# BOUCLE PRINCIPALE
# ══════════════════════════════════════════════════════════════════════════════

def main():
    logging.info("BTC Scanner V3 démarré — Scan toutes les %ds", SCAN_INTERVAL)
    send_telegram("\U0001F916 <b>BTC Scanner V3 démarré</b>\nScan toutes les 60s sur Binance\nSessions: London / NY / Overlap")

    trades_today = 0
    last_day = datetime.now(timezone.utc).day
    last_signal_time = 0  # éviter les doublons

    while True:
        try:
            now = datetime.now(timezone.utc)

            # Reset compteur journalier
            if now.day != last_day:
                trades_today = 0
                last_day = now.day
                logging.info("Nouveau jour — compteur trades reset")

            # Vérifier session
            if not in_session():
                logging.debug("Hors session — skip")
                time.sleep(SCAN_INTERVAL)
                continue

            # Vérifier max trades
            if trades_today >= MAX_TRADES_DAY:
                logging.debug("Max trades atteint (%d/%d)", trades_today, MAX_TRADES_DAY)
                time.sleep(SCAN_INTERVAL)
                continue

            # Fetch données
            ltf_klines = fetch_klines(SYMBOL, LTF, limit=200)
            htf_klines = fetch_klines(SYMBOL, HTF, limit=100)

            # Analyser
            signal = analyze(ltf_klines, htf_klines)

            if signal is not None:
                # Éviter les doublons (pas 2 alertes en moins de 15 min)
                now_ts = time.time()
                if now_ts - last_signal_time < 900:
                    logging.info("Signal %s détecté mais cooldown actif", signal.direction)
                else:
                    msg = format_alert(signal)
                    if send_telegram(msg):
                        trades_today += 1
                        last_signal_time = now_ts
                        logging.info("ALERTE %s envoyée — %s @ %.2f",
                                     signal.direction, signal.signal_type, signal.entry)
                    else:
                        logging.error("Échec envoi alerte")
            else:
                logging.debug("Pas de signal")

        except requests.exceptions.RequestException as e:
            logging.warning("Erreur réseau: %s — retry dans 30s", e)
            time.sleep(30)
            continue
        except Exception as e:
            logging.error("Erreur inattendue: %s", e, exc_info=True)
            time.sleep(30)
            continue

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
