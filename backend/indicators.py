"""
Technical indicator calculations for BTC Trading Advisor.
All functions accept list/numpy arrays and return float or dict.
"""
import numpy as np
from typing import List, Optional, Dict


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    """Exponential Moving Average using standard multiplier."""
    result = np.full(len(values), np.nan)
    if len(values) < period:
        return result
    result[period - 1] = np.mean(values[:period])
    k = 2.0 / (period + 1)
    for i in range(period, len(values)):
        result[i] = values[i] * k + result[i - 1] * (1 - k)
    return result


def _wilder_smooth(values: np.ndarray, period: int) -> np.ndarray:
    """Wilder's smoothing (used in RSI, ATR, ADX)."""
    result = np.full(len(values), np.nan)
    if len(values) < period:
        return result
    result[period - 1] = np.mean(values[:period])
    k = 1.0 / period
    for i in range(period, len(values)):
        result[i] = values[i] * k + result[i - 1] * (1 - k)
    return result


def calculate_rsi(closes: List[float], period: int = 14) -> Optional[float]:
    arr = np.array(closes, dtype=float)
    if len(arr) < period + 1:
        return None
    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = _wilder_smooth(gains, period)
    avg_loss = _wilder_smooth(losses, period)
    last_gain = avg_gain[-1]
    last_loss = avg_loss[-1]
    if np.isnan(last_gain) or np.isnan(last_loss):
        return None
    if last_loss == 0:
        return 100.0
    rs = last_gain / last_loss
    return round(100 - (100 / (1 + rs)), 2)


def calculate_macd(closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Optional[Dict]:
    arr = np.array(closes, dtype=float)
    if len(arr) < slow + signal:
        return None
    ema_fast = _ema(arr, fast)
    ema_slow = _ema(arr, slow)
    macd_line = ema_fast - ema_slow
    valid_start = slow - 1
    if len(macd_line[valid_start:]) < signal:
        return None
    sig = _ema(macd_line[valid_start:], signal)
    signal_full = np.full(len(arr), np.nan)
    signal_full[valid_start:] = sig
    hist = macd_line - signal_full
    if np.isnan(macd_line[-1]) or np.isnan(signal_full[-1]):
        return None
    bullish_cross = bearish_cross = False
    if len(macd_line) >= 2 and not np.isnan(macd_line[-2]) and not np.isnan(signal_full[-2]):
        bullish_cross = (macd_line[-2] < signal_full[-2]) and (macd_line[-1] > signal_full[-1])
        bearish_cross = (macd_line[-2] > signal_full[-2]) and (macd_line[-1] < signal_full[-1])
    return {
        "macd": round(float(macd_line[-1]), 4),
        "signal": round(float(signal_full[-1]), 4),
        "histogram": round(float(hist[-1]), 4),
        "bullish_cross": bullish_cross,
        "bearish_cross": bearish_cross,
    }


def calculate_bollinger_bands(closes: List[float], period: int = 20, std_dev: float = 2.0) -> Optional[Dict]:
    arr = np.array(closes, dtype=float)
    if len(arr) < period:
        return None
    middle = np.mean(arr[-period:])
    std = np.std(arr[-period:], ddof=1)
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    price = arr[-1]
    bandwidth = (upper - lower) / middle * 100 if middle != 0 else 0
    pct_b = (price - lower) / (upper - lower) if (upper - lower) != 0 else 0.5
    return {
        "upper": round(upper, 2), "middle": round(middle, 2), "lower": round(lower, 2),
        "pct_b": round(pct_b, 4), "bandwidth": round(bandwidth, 4),
    }


def calculate_ema(closes: List[float], period: int) -> Optional[float]:
    arr = np.array(closes, dtype=float)
    if len(arr) < period:
        return None
    result = _ema(arr, period)
    val = result[-1]
    return round(float(val), 2) if not np.isnan(val) else None


def calculate_emas(closes: List[float]) -> Dict:
    return {
        "ema20": calculate_ema(closes, 20),
        "ema50": calculate_ema(closes, 50),
        "ema200": calculate_ema(closes, 200),
    }


def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Optional[float]:
    h = np.array(highs, dtype=float)
    l = np.array(lows, dtype=float)
    c = np.array(closes, dtype=float)
    if len(c) < period + 1:
        return None
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    atr = _wilder_smooth(tr, period)
    val = atr[-1]
    return round(float(val), 2) if not np.isnan(val) else None


def calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Optional[Dict]:
    """
    Average Directional Index (ADX) with DI+/DI-.
    ADX > 25 signals a trending market. Returns dict or None.
    """
    h = np.array(highs, dtype=float)
    l = np.array(lows, dtype=float)
    c = np.array(closes, dtype=float)
    if len(c) < period * 2 + 2:
        return None

    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    up_move = h[1:] - h[:-1]
    down_move = l[:-1] - l[1:]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    atr_s = _wilder_smooth(tr, period)
    plus_di_s = _wilder_smooth(plus_dm, period)
    minus_di_s = _wilder_smooth(minus_dm, period)

    eps = 1e-10
    plus_di = 100.0 * plus_di_s / np.where(atr_s == 0, eps, atr_s)
    minus_di = 100.0 * minus_di_s / np.where(atr_s == 0, eps, atr_s)
    di_sum = plus_di + minus_di
    dx = 100.0 * np.abs(plus_di - minus_di) / np.where(di_sum == 0, eps, di_sum)
    adx = _wilder_smooth(dx, period)

    adx_val = adx[-1]
    if np.isnan(adx_val):
        return None
    return {
        "adx": round(float(adx_val), 2),
        "plus_di": round(float(plus_di[-1]), 2) if not np.isnan(plus_di[-1]) else None,
        "minus_di": round(float(minus_di[-1]), 2) if not np.isnan(minus_di[-1]) else None,
        "trending": float(adx_val) > 25.0,
    }


def calculate_stochastic_rsi(
    closes: List[float], rsi_period: int = 14, stoch_period: int = 14,
    k_period: int = 3, d_period: int = 3,
) -> Optional[Dict]:
    arr = np.array(closes, dtype=float)
    min_len = rsi_period + stoch_period + k_period + d_period + 5
    if len(arr) < min_len:
        return None

    rsi_series = []
    for i in range(rsi_period, len(arr) + 1):
        val = calculate_rsi(list(arr[:i]), rsi_period)
        if val is not None:
            rsi_series.append(val)

    if len(rsi_series) < stoch_period + k_period + d_period:
        return None

    rsi_arr = np.array(rsi_series)
    stoch_k_raw = []
    for i in range(stoch_period - 1, len(rsi_arr)):
        window = rsi_arr[i - stoch_period + 1 : i + 1]
        lo, hi = np.min(window), np.max(window)
        stoch_k_raw.append((rsi_arr[i] - lo) / (hi - lo) * 100 if hi - lo != 0 else 50.0)

    if len(stoch_k_raw) < k_period + d_period:
        return None

    stoch_k_arr = np.array(stoch_k_raw)
    k_smooth = [np.mean(stoch_k_arr[i - k_period + 1 : i + 1]) for i in range(k_period - 1, len(stoch_k_arr))]
    if len(k_smooth) < d_period:
        return None
    k_arr = np.array(k_smooth)
    d_arr = [np.mean(k_arr[i - d_period + 1 : i + 1]) for i in range(d_period - 1, len(k_arr))]
    return {"k": round(float(k_arr[-1]), 2), "d": round(float(d_arr[-1]), 2)}


def calculate_volume_ratio(volumes: List[float], period: int = 20) -> Optional[float]:
    if len(volumes) < period + 1:
        return None
    avg = np.mean(volumes[-period - 1 : -1])
    if avg == 0:
        return None
    return round(float(volumes[-1]) / avg, 4)


def detect_support_resistance(highs: List[float], lows: List[float], closes: List[float], lookback: int = 50) -> Dict:
    if len(closes) < lookback:
        lookback = len(closes)
    h = np.array(highs[-lookback:])
    l = np.array(lows[-lookback:])
    c = np.array(closes[-lookback:])
    current_price = c[-1]
    pivot_highs, pivot_lows = [], []
    window = 3
    for i in range(window, len(h) - window):
        if h[i] == max(h[i - window : i + window + 1]):
            pivot_highs.append(h[i])
        if l[i] == min(l[i - window : i + window + 1]):
            pivot_lows.append(l[i])
    above = [p for p in pivot_highs if p > current_price * 1.001]
    below = [p for p in pivot_lows if p < current_price * 0.999]
    resistance = round(min(above), 2) if above else round(float(np.max(h)), 2)
    support = round(max(below), 2) if below else round(float(np.min(l)), 2)
    return {
        "support": support,
        "resistance": resistance,
        "near_support": current_price <= support * 1.005 if support else False,
        "near_resistance": current_price >= resistance * 0.995 if resistance else False,
    }


def detect_liquidity_sweep(highs: List[float], lows: List[float], closes: List[float], lookback: int = 30) -> Dict:
    """
    ICT Liquidity Sweep detection.
    Bullish: last bar's wick sweeps below the prior-N-bar low then closes above it.
    Bearish: last bar's wick sweeps above the prior-N-bar high then closes below it.
    """
    if len(closes) < lookback + 2:
        return {"detected": False, "direction": None, "level": None}
    h = np.array(highs, dtype=float)
    l = np.array(lows, dtype=float)
    c = np.array(closes, dtype=float)
    prev_low = float(np.min(l[-lookback - 1 : -1]))
    prev_high = float(np.max(h[-lookback - 1 : -1]))
    cur_low, cur_high, cur_close = float(l[-1]), float(h[-1]), float(c[-1])
    if cur_low < prev_low and cur_close > prev_low:
        return {"detected": True, "direction": "bullish", "level": round(prev_low, 2)}
    if cur_high > prev_high and cur_close < prev_high:
        return {"detected": True, "direction": "bearish", "level": round(prev_high, 2)}
    return {"detected": False, "direction": None, "level": None}


def calculate_poc(closes: List[float], volumes: List[float], lookback: int = 300) -> Optional[float]:
    """
    Point of Control: price level with highest traded volume in the last N bars.
    """
    if len(closes) < 20:
        return None
    n = min(lookback, len(closes))
    c = np.array(closes[-n:], dtype=float)
    v = np.array(volumes[-n:], dtype=float) if len(volumes) >= n else np.ones(n)
    if len(v) < n:
        v = np.pad(v, (n - len(v), 0), constant_values=1.0)
    bins = 50
    p_min, p_max = float(np.min(c)), float(np.max(c))
    if p_min == p_max:
        return round(p_min, 2)
    edges = np.linspace(p_min, p_max, bins + 1)
    idx = np.clip(np.digitize(c, edges) - 1, 0, bins - 1)
    bin_vol = np.zeros(bins)
    for i in range(len(c)):
        bin_vol[idx[i]] += v[i]
    poc_bin = int(np.argmax(bin_vol))
    return round(float((edges[poc_bin] + edges[poc_bin + 1]) / 2), 2)


def calculate_liquidation_zone(highs: List[float], closes: List[float], lookback: int = 50) -> Optional[Dict]:
    """
    Short liquidation zone = rolling max of highs.
    Shorts placed below this level face liquidation when price approaches.
    """
    if len(highs) < lookback:
        return None
    zone = float(np.max(np.array(highs[-lookback:], dtype=float)))
    current_price = float(closes[-1]) if closes else zone
    proximity_pct = (zone - current_price) / current_price * 100
    return {
        "zone": round(zone, 2),
        "proximity_pct": round(proximity_pct, 4),
        "near": proximity_pct < 2.0,
    }


def detect_fvgs(highs: List[float], lows: List[float], timestamps: List[int], lookback: int = 60) -> List[Dict]:
    """
    Fair Value Gaps (FVG / Imbalances) — ICT concept.
    BISI (bullish): low[i] > high[i-2]
    SIBI (bearish): high[i] < low[i-2]
    Returns up to last 20 FVGs with ts, top, bottom, type.
    """
    n = min(lookback, len(highs))
    h = highs[-n:]
    l = lows[-n:]
    ts = timestamps[-n:] if timestamps else list(range(n))
    fvgs = []
    for i in range(2, len(h)):
        if l[i] > h[i - 2]:  # BISI
            fvgs.append({"type": "BISI", "top": round(float(l[i]), 2),
                          "bottom": round(float(h[i - 2]), 2), "ts": int(ts[i - 1])})
        elif h[i] < l[i - 2]:  # SIBI
            fvgs.append({"type": "SIBI", "top": round(float(l[i - 2]), 2),
                          "bottom": round(float(h[i]), 2), "ts": int(ts[i - 1])})
    return fvgs[-20:]


def detect_market_phase(closes: List[float], volumes: List[float]) -> str:
    if len(closes) < 50:
        return "Unknown"
    c = np.array(closes[-50:])
    v = np.array(volumes[-50:]) if len(volumes) >= 50 else np.array(volumes)
    ema20_now = calculate_ema(list(c), 20)
    ema50_now = calculate_ema(list(c), 50)
    if ema20_now is None or ema50_now is None:
        return "Unknown"
    price_trend_up = ema20_now > ema50_now
    vol_first = np.mean(v[: len(v) // 2]) if len(v) > 0 else 1
    vol_second = np.mean(v[len(v) // 2 :]) if len(v) > 0 else 1
    vol_increasing = vol_second > vol_first
    if price_trend_up and vol_increasing:
        return "Markup"
    elif price_trend_up and not vol_increasing:
        return "Distribution"
    elif not price_trend_up and vol_increasing:
        return "Markdown"
    else:
        return "Accumulation"


def calculate_all_indicators(
    closes_1h: List[float],
    highs_1h: List[float],
    lows_1h: List[float],
    volumes_1h: List[float],
    closes_4h: List[float],
    highs_4h: List[float],
    lows_4h: List[float],
    volumes_4h: List[float],
    timestamps_1h: Optional[List[int]] = None,
) -> Dict:
    """Calculate all indicators for 1h and 4h timeframes."""
    result = {}

    # ── 1H ───────────────────────────────────────────────────────────────────
    result["rsi_1h"] = calculate_rsi(closes_1h)
    result["macd_1h"] = calculate_macd(closes_1h)
    result["bb_1h"] = calculate_bollinger_bands(closes_1h)
    result["emas_1h"] = calculate_emas(closes_1h)
    result["atr_1h"] = calculate_atr(highs_1h, lows_1h, closes_1h)
    result["adx_1h"] = calculate_adx(highs_1h, lows_1h, closes_1h)
    result["stoch_rsi_1h"] = calculate_stochastic_rsi(closes_1h)
    result["volume_ratio_1h"] = calculate_volume_ratio(volumes_1h)
    result["sr_1h"] = detect_support_resistance(highs_1h, lows_1h, closes_1h)
    result["sweep_1h"] = detect_liquidity_sweep(highs_1h, lows_1h, closes_1h)
    result["poc_1h"] = calculate_poc(closes_1h, volumes_1h)
    result["liq_zone_1h"] = calculate_liquidation_zone(highs_1h, closes_1h)

    ts = timestamps_1h if timestamps_1h else list(range(len(highs_1h)))
    result["fvgs_1h"] = detect_fvgs(highs_1h, lows_1h, ts)

    # ── 4H ───────────────────────────────────────────────────────────────────
    result["rsi_4h"] = calculate_rsi(closes_4h)
    result["macd_4h"] = calculate_macd(closes_4h)
    result["bb_4h"] = calculate_bollinger_bands(closes_4h)
    result["emas_4h"] = calculate_emas(closes_4h)
    result["atr_4h"] = calculate_atr(highs_4h, lows_4h, closes_4h)
    result["adx_4h"] = calculate_adx(highs_4h, lows_4h, closes_4h)
    result["stoch_rsi_4h"] = calculate_stochastic_rsi(closes_4h)
    result["volume_ratio_4h"] = calculate_volume_ratio(volumes_4h)

    # ── Shared ────────────────────────────────────────────────────────────────
    result["market_phase"] = detect_market_phase(closes_1h, volumes_1h)
    if result["atr_1h"] and closes_1h:
        result["atr_pct"] = round(result["atr_1h"] / closes_1h[-1] * 100, 4)
    else:
        result["atr_pct"] = None

    return result
