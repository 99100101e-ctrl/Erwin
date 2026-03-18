"""
apex_live/indicators.py — Indicateurs APEX v2 (standalone, aucune dépendance externe)
"""

from collections import defaultdict
from datetime import datetime, timezone

FR_HOURS = set(range(8, 22)) - {16, 17, 18}


def _ema(values, period):
    if len(values) < period:
        return [None] * len(values)
    k = 2.0 / (period + 1)
    out = [None] * (period - 1)
    out.append(sum(values[:period]) / period)
    for v in values[period:]:
        out.append(out[-1] * (1 - k) + v * k)
    return out


def _rsi(closes, period=14):
    n = len(closes)
    out = [50.0] * n
    if n < period + 2:
        return out
    avg_g = avg_l = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        avg_g += max(d, 0)
        avg_l += max(-d, 0)
    avg_g /= period
    avg_l /= period
    out[period] = 100 - 100 / (1 + avg_g / avg_l) if avg_l > 0 else 100.0
    for i in range(period + 1, n):
        d = closes[i] - closes[i - 1]
        avg_g = (avg_g * (period - 1) + max(d, 0)) / period
        avg_l = (avg_l * (period - 1) + max(-d, 0)) / period
        out[i] = 100 - 100 / (1 + avg_g / avg_l) if avg_l > 0 else 100.0
    return out


def _atr(candles, period=14):
    n = len(candles)
    out = [0.0] * n
    if n < period + 2:
        return out
    trs = []
    for i in range(1, n):
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    val = sum(trs[:period]) / period
    out[period] = val
    for i in range(period, n - 1):
        val = (val * (period - 1) + trs[i]) / period
        out[i + 1] = val
    return out


def _adx(candles, period=14):
    n = len(candles)
    out = [0.0] * n
    if n < period * 2 + 5:
        return out
    trs, pdms, mdms = [], [], []
    for i in range(1, n):
        h, l   = candles[i]["high"],   candles[i]["low"]
        ph, pl = candles[i-1]["high"], candles[i-1]["low"]
        pc     = candles[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        up, dn = h - ph, pl - l
        pdms.append(up if up > dn and up > 0 else 0.0)
        mdms.append(dn if dn > up and dn > 0 else 0.0)

    def _wilder(vals):
        s = [0.0] * len(vals)
        s[period - 1] = sum(vals[:period])
        for i in range(period, len(vals)):
            s[i] = s[i-1] - s[i-1] / period + vals[i]
        return s

    str_ = _wilder(trs)
    spdm = _wilder(pdms)
    smdm = _wilder(mdms)
    dx_vals = []
    for i in range(period - 1, len(str_)):
        if str_[i] == 0:
            dx_vals.append(0.0)
            continue
        pdi = 100 * spdm[i] / str_[i]
        mdi = 100 * smdm[i] / str_[i]
        denom = pdi + mdi
        dx_vals.append(100 * abs(pdi - mdi) / denom if denom > 0 else 0.0)
    adx_vals = _wilder(dx_vals)
    offset = 2 * (period - 1) + 1
    for i, v in enumerate(adx_vals):
        idx = offset + i
        if idx < n:
            out[idx] = v
    return out


def _vol_sma(candles, period=20):
    vols = [c["volume"] for c in candles]
    out  = [0.0] * len(vols)
    for i in range(period - 1, len(vols)):
        out[i] = sum(vols[i - period + 1 : i + 1]) / period
    return out


def _daily_ema100_trend(candles):
    daily_close = defaultdict(list)
    for c in candles:
        dt = datetime.fromtimestamp(c["ts"], tz=timezone.utc)
        daily_close[(dt.year, dt.month, dt.day)].append(c["close"])
    sorted_days   = sorted(daily_close.keys())
    day_closes    = [daily_close[d][-1] for d in sorted_days]
    ema100_series = _ema(day_closes, 100)
    day_ema       = {d: ema100_series[i] for i, d in enumerate(sorted_days)}
    out = []
    for c in candles:
        dt  = datetime.fromtimestamp(c["ts"], tz=timezone.utc)
        key = (dt.year, dt.month, dt.day)
        ev  = day_ema.get(key)
        if ev is None:
            out.append("neutral")
        elif c["close"] > ev:
            out.append("bull")
        else:
            out.append("bear")
    return out


def _bos(candles, i, direction, lookback):
    if i < lookback:
        return False
    close = candles[i]["close"]
    if direction == "BUY":
        return close > max(c["high"] for c in candles[i - lookback : i])
    else:
        return close < min(c["low"]  for c in candles[i - lookback : i])


def _atr_squeeze(atrs, i, lookback=20, ratio=1.25):
    if i < lookback + 3:
        return False
    window = atrs[i - lookback : i]
    if not window or max(window) == 0:
        return False
    median = sorted(window)[len(window) // 2]
    if median == 0:
        return False
    compressed = sum(1 for a in atrs[i - 3 : i] if a < median)
    return compressed >= 2 and atrs[i] > median * ratio


def _volume_surge(candles, vol_sma, i, ratio=1.5):
    return vol_sma[i] > 0 and candles[i]["volume"] > vol_sma[i] * ratio


def _rsi_zone(rsi_vals, i, direction):
    r = rsi_vals[i]
    return (45 <= r <= 68) if direction == "BUY" else (32 <= r <= 55)


def _ema_stack(ema20, ema50, i, direction):
    if ema20[i] is None or ema50[i] is None:
        return False
    return ema20[i] > ema50[i] if direction == "BUY" else ema20[i] < ema50[i]


def _engulfing(candles, i, direction):
    if i < 1:
        return False
    c, p = candles[i], candles[i - 1]
    body_now  = abs(c["close"] - c["open"])
    body_prev = abs(p["close"] - p["open"])
    if body_prev == 0:
        return False
    if direction == "BUY":
        return c["close"] > c["open"] and body_now > body_prev * 1.3
    else:
        return c["close"] < c["open"] and body_now > body_prev * 1.3


def _macd(closes, fast=12, slow=26, signal=9):
    n      = len(closes)
    ema_f  = _ema(closes, fast)
    ema_s  = _ema(closes, slow)
    macd_l = [None] * n
    for i in range(n):
        if ema_f[i] is not None and ema_s[i] is not None:
            macd_l[i] = ema_f[i] - ema_s[i]
    valid_idx = next((i for i, v in enumerate(macd_l) if v is not None), n)
    sig_vals  = [v for v in macd_l if v is not None]
    sig_ema   = _ema(sig_vals, signal) if len(sig_vals) >= signal else [None] * len(sig_vals)
    sig_line  = [None] * n
    vi = 0
    for i in range(valid_idx, n):
        if vi < len(sig_ema):
            sig_line[i] = sig_ema[vi]
        vi += 1
    return macd_l, sig_line


def _rsi4h(candles):
    n = len(candles)
    closes_4h     = [candles[i]["close"] for i in range(0, n, 4)]
    rsi_4h_series = _rsi(closes_4h, 14)
    return [rsi_4h_series[min(i // 4, len(rsi_4h_series) - 1)] for i in range(n)]


def _ema4h(candles, period):
    n = len(candles)
    closes_4h = [candles[i]["close"] for i in range(0, n, 4)]
    ema_4h    = _ema(closes_4h, period)
    return [ema_4h[min(i // 4, len(ema_4h) - 1)] for i in range(n)]


def _macd_cross(macd_l, sig_line, i, direction):
    if i < 1:
        return False
    m0, m1 = macd_l[i - 1], macd_l[i]
    s0, s1 = sig_line[i - 1], sig_line[i]
    if None in (m0, m1, s0, s1):
        return False
    return (m0 < s0 and m1 > s1) if direction == "BUY" else (m0 > s0 and m1 < s1)


def _buy_not_extended(price, ema50_val, atr_val, max_atr=5.0):
    if ema50_val is None or atr_val <= 0:
        return True
    return (price - ema50_val) / atr_val <= max_atr
