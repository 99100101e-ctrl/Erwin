"""
Calcul des indicateurs techniques — reproduction fidele du script Pine.
Utilise pandas + numpy uniquement (pas de dependance TA-Lib).
"""

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────
#  Fonctions utilitaires
# ─────────────────────────────────────────────────────────────

def rma(series: pd.Series, length: int) -> pd.Series:
    """Recursive Moving Average (equivalent Pine ta.rma / Wilder's smoothing)."""
    alpha = 1.0 / length
    return series.ewm(alpha=alpha, adjust=False).mean()


def donchian(high: pd.Series, low: pd.Series, length: int) -> pd.Series:
    """Donchian midline = (highest high + lowest low) / 2."""
    return (high.rolling(length).max() + low.rolling(length).min()) / 2


# ─────────────────────────────────────────────────────────────
#  Ichimoku
# ─────────────────────────────────────────────────────────────

def ichimoku(df: pd.DataFrame, kijun_len: int, tenkan_len: int):
    """Retourne kijun et tenkan Series."""
    kijun = donchian(df["high"], df["low"], kijun_len)
    tenkan = donchian(df["high"], df["low"], tenkan_len)
    return kijun, tenkan


# ─────────────────────────────────────────────────────────────
#  ADX / DI+  / DI-
# ─────────────────────────────────────────────────────────────

def calc_adx(df: pd.DataFrame, length: int):
    """Retourne adx_val, plus_di, minus_di, di_bull, di_bear."""
    high, low, close = df["high"], df["low"], df["close"]

    up_move = high - high.shift(1)
    dn_move = low.shift(1) - low

    plus_dm = np.where((up_move > dn_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((dn_move > up_move) & (dn_move > 0), dn_move, 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr_val = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr_adx = rma(tr_val, length)
    plus_di = 100 * rma(pd.Series(plus_dm, index=df.index), length) / atr_adx
    minus_di = 100 * rma(pd.Series(minus_dm, index=df.index), length) / atr_adx

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx_val = rma(dx, length)

    di_bull = plus_di > minus_di
    di_bear = minus_di > plus_di

    return adx_val, plus_di, minus_di, di_bull, di_bear


# ─────────────────────────────────────────────────────────────
#  Bollinger Width
# ─────────────────────────────────────────────────────────────

def calc_bb_width(df: pd.DataFrame, length: int, mult: float):
    """Retourne bb_width normalise (%)."""
    basis = df["close"].rolling(length).mean()
    dev = mult * df["close"].rolling(length).std(ddof=0)
    upper = basis + dev
    lower = basis - dev
    bb_width = (upper - lower) / basis
    return bb_width


# ─────────────────────────────────────────────────────────────
#  ATR
# ─────────────────────────────────────────────────────────────

def calc_atr(df: pd.DataFrame, length: int):
    """Retourne atr_val et atr_ma."""
    high, low, close = df["high"], df["low"], df["close"]
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr_val = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr_val = rma(tr_val, length)
    atr_ma = atr_val.rolling(length * 2).mean()
    return atr_val, atr_ma


# ─────────────────────────────────────────────────────────────
#  EMA / RSI / Volume
# ─────────────────────────────────────────────────────────────

def calc_ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def calc_rsi(series: pd.Series, length: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = rma(gain, length)
    avg_loss = rma(loss, length)
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_vol_ma(volume: pd.Series, length: int) -> pd.Series:
    return volume.rolling(length).mean()
