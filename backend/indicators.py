"""
Technical indicator calculations for BTC Trading Advisor.
All functions accept list/numpy arrays and return float or dict.
"""
import numpy as np
from typing import List, Optional, Tuple, Dict


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    """Exponential Moving Average using Wilder's multiplier."""
    result = np.full(len(values), np.nan)
    if len(values) < period:
        return result
    # Seed with SMA
    result[period - 1] = np.mean(values[:period])
    k = 2.0 / (period + 1)
    for i in range(period, len(values)):
        result[i] = values[i] * k + result[i - 1] * (1 - k)
    return result


def _wilder_smooth(values: np.ndarray, period: int) -> np.ndarray:
    """Wilder's smoothing (used in RSI, ATR)."""
    result = np.full(len(values), np.nan)
    if len(values) < period:
        return result
    result[period - 1] = np.mean(values[:period])
    k = 1.0 / period
    for i in range(period, len(values)):
        result[i] = values[i] * k + result[i - 1] * (1 - k)
    return result


def calculate_rsi(closes: List[float], period: int = 14) -> Optional[float]:
    """RSI using Wilder's smoothing. Returns last value or None."""
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


def calculate_macd(
    closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> Optional[Dict]:
    """MACD line, signal line, histogram. Returns dict or None."""
    arr = np.array(closes, dtype=float)
    if len(arr) < slow + signal:
        return None
    ema_fast = _ema(arr, fast)
    ema_slow = _ema(arr, slow)
    macd_line = ema_fast - ema_slow
    # Signal line is EMA of MACD line (only valid values)
    valid_start = slow - 1
    if len(macd_line[valid_start:]) < signal:
        return None
    sig = _ema(macd_line[valid_start:], signal)
    # Align back
    signal_full = np.full(len(arr), np.nan)
    signal_full[valid_start:] = sig
    hist = macd_line - signal_full

    if np.isnan(macd_line[-1]) or np.isnan(signal_full[-1]):
        return None

    # Detect crossover: previous bar MACD < signal, current MACD > signal
    bullish_cross = False
    bearish_cross = False
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


def calculate_bollinger_bands(
    closes: List[float], period: int = 20, std_dev: float = 2.0
) -> Optional[Dict]:
    """Bollinger Bands. Returns dict with upper, middle, lower, %b, bandwidth."""
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
        "upper": round(upper, 2),
        "middle": round(middle, 2),
        "lower": round(lower, 2),
        "pct_b": round(pct_b, 4),
        "bandwidth": round(bandwidth, 4),
    }


def calculate_ema(closes: List[float], period: int) -> Optional[float]:
    """Single EMA value for given period."""
    arr = np.array(closes, dtype=float)
    if len(arr) < period:
        return None
    result = _ema(arr, period)
    val = result[-1]
    return round(float(val), 2) if not np.isnan(val) else None


def calculate_emas(closes: List[float]) -> Dict:
    """Calculate EMA 20, 50, 200."""
    return {
        "ema20": calculate_ema(closes, 20),
        "ema50": calculate_ema(closes, 50),
        "ema200": calculate_ema(closes, 200),
    }


def calculate_atr(
    highs: List[float], lows: List[float], closes: List[float], period: int = 14
) -> Optional[float]:
    """Average True Range."""
    h = np.array(highs, dtype=float)
    l = np.array(lows, dtype=float)
    c = np.array(closes, dtype=float)
    if len(c) < period + 1:
        return None
    tr = np.maximum(
        h[1:] - l[1:],
        np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])),
    )
    atr = _wilder_smooth(tr, period)
    val = atr[-1]
    return round(float(val), 2) if not np.isnan(val) else None


def calculate_stochastic_rsi(
    closes: List[float],
    rsi_period: int = 14,
    stoch_period: int = 14,
    k_period: int = 3,
    d_period: int = 3,
) -> Optional[Dict]:
    """Stochastic RSI. Returns %K and %D."""
    arr = np.array(closes, dtype=float)
    min_len = rsi_period + stoch_period + k_period + d_period + 5
    if len(arr) < min_len:
        return None

    # Calculate RSI series
    rsi_series = []
    for i in range(rsi_period, len(arr) + 1):
        val = calculate_rsi(list(arr[:i]), rsi_period)
        if val is not None:
            rsi_series.append(val)

    if len(rsi_series) < stoch_period + k_period + d_period:
        return None

    rsi_arr = np.array(rsi_series)
    # Stochastic of RSI
    stoch_k_raw = []
    for i in range(stoch_period - 1, len(rsi_arr)):
        window = rsi_arr[i - stoch_period + 1 : i + 1]
        lo = np.min(window)
        hi = np.max(window)
        if hi - lo == 0:
            stoch_k_raw.append(50.0)
        else:
            stoch_k_raw.append((rsi_arr[i] - lo) / (hi - lo) * 100)

    if len(stoch_k_raw) < k_period + d_period:
        return None

    stoch_k_arr = np.array(stoch_k_raw)
    # Smooth %K
    k_smooth = []
    for i in range(k_period - 1, len(stoch_k_arr)):
        k_smooth.append(np.mean(stoch_k_arr[i - k_period + 1 : i + 1]))

    if len(k_smooth) < d_period:
        return None

    k_arr = np.array(k_smooth)
    # %D is SMA of %K
    d_arr = []
    for i in range(d_period - 1, len(k_arr)):
        d_arr.append(np.mean(k_arr[i - d_period + 1 : i + 1]))

    k_val = round(float(k_arr[-1]), 2)
    d_val = round(float(d_arr[-1]), 2)
    return {"k": k_val, "d": d_val}


def calculate_volume_ratio(volumes: List[float], period: int = 20) -> Optional[float]:
    """Current volume vs N-period average. Returns ratio (1.3 = 130%)."""
    if len(volumes) < period + 1:
        return None
    avg = np.mean(volumes[-period - 1 : -1])
    if avg == 0:
        return None
    return round(float(volumes[-1]) / avg, 4)


def detect_support_resistance(
    highs: List[float], lows: List[float], closes: List[float], lookback: int = 50
) -> Dict:
    """
    Auto-detect key support and resistance levels using pivot points.
    Returns nearest support below price and nearest resistance above price.
    """
    if len(closes) < lookback:
        lookback = len(closes)

    h = np.array(highs[-lookback:])
    l = np.array(lows[-lookback:])
    c = np.array(closes[-lookback:])
    current_price = c[-1]

    # Pivot highs (resistance) and pivot lows (support)
    pivot_highs = []
    pivot_lows = []
    window = 3

    for i in range(window, len(h) - window):
        if h[i] == max(h[i - window : i + window + 1]):
            pivot_highs.append(h[i])
        if l[i] == min(l[i - window : i + window + 1]):
            pivot_lows.append(l[i])

    # Find nearest levels
    resistance = None
    support = None

    above = [p for p in pivot_highs if p > current_price * 1.001]
    if above:
        resistance = round(min(above), 2)

    below = [p for p in pivot_lows if p < current_price * 0.999]
    if below:
        support = round(max(below), 2)

    # Fallback: use recent high/low
    if resistance is None:
        resistance = round(float(np.max(h)), 2)
    if support is None:
        support = round(float(np.min(l)), 2)

    return {
        "support": support,
        "resistance": resistance,
        "near_support": current_price <= support * 1.005 if support else False,
        "near_resistance": current_price >= resistance * 0.995 if resistance else False,
    }


def detect_market_phase(
    closes: List[float], volumes: List[float]
) -> str:
    """
    Detect market phase: Accumulation, Markup, Distribution, Markdown.
    Based on price trend and volume pattern.
    """
    if len(closes) < 50:
        return "Unknown"

    c = np.array(closes[-50:])
    v = np.array(volumes[-50:]) if len(volumes) >= 50 else np.array(volumes)

    ema20_now = calculate_ema(list(c), 20)
    ema50_now = calculate_ema(list(c), 50)

    if ema20_now is None or ema50_now is None:
        return "Unknown"

    price_trend_up = ema20_now > ema50_now
    price_trend_down = ema20_now < ema50_now

    # Volume trend
    vol_first_half = np.mean(v[: len(v) // 2]) if len(v) > 0 else 1
    vol_second_half = np.mean(v[len(v) // 2 :]) if len(v) > 0 else 1
    vol_increasing = vol_second_half > vol_first_half

    if price_trend_up and vol_increasing:
        return "Markup"
    elif price_trend_up and not vol_increasing:
        return "Distribution"
    elif price_trend_down and vol_increasing:
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
) -> Dict:
    """Calculate all indicators for 1h and 4h timeframes."""
    result = {}

    # 1H indicators
    result["rsi_1h"] = calculate_rsi(closes_1h)
    result["macd_1h"] = calculate_macd(closes_1h)
    result["bb_1h"] = calculate_bollinger_bands(closes_1h)
    result["emas_1h"] = calculate_emas(closes_1h)
    result["atr_1h"] = calculate_atr(highs_1h, lows_1h, closes_1h)
    result["stoch_rsi_1h"] = calculate_stochastic_rsi(closes_1h)
    result["volume_ratio_1h"] = calculate_volume_ratio(volumes_1h)
    result["sr_1h"] = detect_support_resistance(highs_1h, lows_1h, closes_1h)

    # 4H indicators
    result["rsi_4h"] = calculate_rsi(closes_4h)
    result["macd_4h"] = calculate_macd(closes_4h)
    result["bb_4h"] = calculate_bollinger_bands(closes_4h)
    result["emas_4h"] = calculate_emas(closes_4h)
    result["atr_4h"] = calculate_atr(highs_4h, lows_4h, closes_4h)
    result["stoch_rsi_4h"] = calculate_stochastic_rsi(closes_4h)
    result["volume_ratio_4h"] = calculate_volume_ratio(volumes_4h)

    # Market phase uses 1H data
    result["market_phase"] = detect_market_phase(closes_1h, volumes_1h)

    # Volatility (ATR as % of price)
    if result["atr_1h"] and closes_1h:
        result["atr_pct"] = round(result["atr_1h"] / closes_1h[-1] * 100, 4)
    else:
        result["atr_pct"] = None

    return result
