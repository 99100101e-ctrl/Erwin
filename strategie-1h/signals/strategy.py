"""
Moteur de la strategie Erwin 1H.
Prend un DataFrame OHLCV et retourne les signaux d'achat / vente.
Reproduction fidele de la logique Pine TradingView.
"""

import pandas as pd
from . import config as cfg
from .indicators import (
    ichimoku, calc_adx, calc_bb_width, calc_atr,
    calc_ema, calc_rsi, calc_vol_ma,
)


def crossover(a: pd.Series, b: pd.Series) -> pd.Series:
    """True quand 'a' croise au-dessus de 'b'."""
    return (a > b) & (a.shift(1) <= b.shift(1))


def crossunder(a: pd.Series, b: pd.Series) -> pd.Series:
    """True quand 'a' croise en-dessous de 'b'."""
    return (a < b) & (a.shift(1) >= b.shift(1))


def detect_flat(adx_val, bb_width, atr_val, atr_ma):
    """Detecte les phases flat / trending selon le mode choisi."""
    mode = cfg.FLAT_MODE

    if mode == "ADX seul":
        is_flat = adx_val < cfg.ADX_FLAT
        is_trending = adx_val >= cfg.ADX_TREND
    elif mode == "Bollinger Width":
        is_flat = bb_width < cfg.BB_THRESH
        is_trending = bb_width >= cfg.BB_THRESH * 1.5
    else:  # ADX + ATR combine
        adx_ok = adx_val >= cfg.ADX_TREND
        atr_ok = atr_val >= atr_ma * cfg.ATR_RATIO
        is_flat = ~adx_ok & ~atr_ok
        is_trending = adx_ok & atr_ok

    return is_flat, is_trending


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Analyse un DataFrame OHLCV et ajoute les colonnes de signaux.

    Colonnes attendues : open, high, low, close, volume
    Colonnes ajoutees :
        - signal      : "LONG", "SHORT" ou None
        - signal_type : "full" ou "partial"
        - kijun, tenkan, ema200, rsi, adx, bb_width, atr
        - is_flat, is_trending, di_bull
        - score_bull  : nombre de conditions bull remplies (sur 9)
        - market_state: "TENDANCE BULL", "TENDANCE BEAR", "RANGE / FLAT", "TRANSITION"
        - sl, tp      : niveaux stop-loss et take-profit sugggeres
    """
    df = df.copy()

    # ── Ichimoku ──────────────────────────────────────────────
    kijun, tenkan = ichimoku(df, cfg.KIJUN_LEN, cfg.TENKAN_LEN)
    df["kijun"] = kijun
    df["tenkan"] = tenkan

    # ── ADX ───────────────────────────────────────────────────
    adx_val, plus_di, minus_di, di_bull, di_bear = calc_adx(df, cfg.ADX_LEN)
    df["adx"] = adx_val
    df["di_bull"] = di_bull

    # ── Bollinger Width ───────────────────────────────────────
    bb_width = calc_bb_width(df, cfg.BB_LEN, cfg.BB_MULT)
    df["bb_width"] = bb_width

    # ── ATR ───────────────────────────────────────────────────
    atr_val, atr_ma = calc_atr(df, cfg.ATR_LEN)
    df["atr"] = atr_val

    # ── Flat / Trending ───────────────────────────────────────
    is_flat, is_trending = detect_flat(adx_val, bb_width, atr_val, atr_ma)
    df["is_flat"] = is_flat
    df["is_trending"] = is_trending

    # ── Filtres supplementaires ───────────────────────────────
    ema200 = calc_ema(df["close"], cfg.EMA_LEN)
    df["ema200"] = ema200
    rsi_val = calc_rsi(df["close"], cfg.RSI_LEN)
    df["rsi"] = rsi_val
    vol_ma = calc_vol_ma(df["volume"], cfg.VOL_LEN)

    f_ema_bull = (df["close"] > ema200) if cfg.USE_EMA else True
    f_ema_bear = (df["close"] < ema200) if cfg.USE_EMA else True
    f_rsi_bull = (rsi_val < cfg.RSI_OB) if cfg.USE_RSI else True
    f_rsi_bear = (rsi_val > cfg.RSI_OS) if cfg.USE_RSI else True
    f_vol = (df["volume"] > vol_ma) if cfg.USE_VOL else True

    # ── Conditions de signal ──────────────────────────────────
    tk_bull = crossover(tenkan, kijun)
    tk_bear = crossunder(tenkan, kijun)
    price_above_kijun = df["close"] > kijun
    price_below_kijun = df["close"] < kijun
    chikou_bull = df["close"] > df["close"].shift(cfg.DISPLACEMENT)
    chikou_bear = df["close"] < df["close"].shift(cfg.DISPLACEMENT)

    base_bull = tk_bull & price_above_kijun & chikou_bull
    base_bear = tk_bear & price_below_kijun & chikou_bear

    signal_bull = base_bull & is_trending & di_bull & f_ema_bull & f_rsi_bull & f_vol
    signal_bear = base_bear & is_trending & di_bear & f_ema_bear & f_rsi_bear & f_vol

    partial_bull = base_bull & ~signal_bull
    partial_bear = base_bear & ~signal_bear

    no_flat_ok = ~is_flat if cfg.EXCLUDE_FLAT else True

    if cfg.USE_PARTIAL:
        entry_bull = (signal_bull | partial_bull) & no_flat_ok
        entry_bear = (signal_bear | partial_bear) & no_flat_ok
    else:
        entry_bull = signal_bull & no_flat_ok
        entry_bear = signal_bear & no_flat_ok

    # ── Construction des colonnes de sortie ───────────────────
    df["signal"] = None
    df.loc[entry_bull, "signal"] = "LONG"
    df.loc[entry_bear, "signal"] = "SHORT"

    df["signal_type"] = None
    df.loc[signal_bull & entry_bull, "signal_type"] = "full"
    df.loc[partial_bull & entry_bull, "signal_type"] = "partial"
    df.loc[signal_bear & entry_bear, "signal_type"] = "full"
    df.loc[partial_bear & entry_bear, "signal_type"] = "partial"

    # ── Stop-loss / Take-profit ───────────────────────────────
    df["sl"] = None
    df["tp"] = None
    if cfg.USE_SL:
        df.loc[entry_bull, "sl"] = df.loc[entry_bull, "close"] * (1 - cfg.SL_PCT / 100)
        df.loc[entry_bear, "sl"] = df.loc[entry_bear, "close"] * (1 + cfg.SL_PCT / 100)
    if cfg.USE_TP:
        df.loc[entry_bull, "tp"] = df.loc[entry_bull, "close"] * (1 + cfg.TP_PCT / 100)
        df.loc[entry_bear, "tp"] = df.loc[entry_bear, "close"] * (1 - cfg.TP_PCT / 100)

    # ── Score bull (dashboard) ────────────────────────────────
    score = (
        (tenkan > kijun).astype(int)
        + (df["close"] > kijun).astype(int)
        + chikou_bull.astype(int)
        + is_trending.astype(int)
        + di_bull.astype(int)
        + (f_ema_bull if isinstance(f_ema_bull, pd.Series) else pd.Series(1, index=df.index)).astype(int)
        + (f_vol if isinstance(f_vol, pd.Series) else pd.Series(1, index=df.index)).astype(int)
        + (f_rsi_bull if isinstance(f_rsi_bull, pd.Series) else pd.Series(1, index=df.index)).astype(int)
        + (~is_flat).astype(int)
    )
    df["score_bull"] = score

    # ── Market state ──────────────────────────────────────────
    conditions = [
        is_flat,
        is_trending & di_bull,
        is_trending & di_bear,
    ]
    choices = ["RANGE / FLAT", "TENDANCE BULL", "TENDANCE BEAR"]
    df["market_state"] = pd.Series(
        pd.Categorical(
            pd.array(["TRANSITION"] * len(df)),
            categories=choices + ["TRANSITION"],
        ),
        index=df.index,
    )
    for cond, label in zip(conditions, choices):
        df.loc[cond, "market_state"] = label

    return df


def get_latest_signal(df: pd.DataFrame) -> dict:
    """
    Retourne un dict resume de la derniere bougie analysee.
    Pratique pour un endpoint API ou un webhook.
    """
    last = df.iloc[-1]

    # Detail des 9 conditions pour le dashboard
    conditions_detail = [
        {"nom": "TK Cross (Tenkan > Kijun)", "ok": bool(last["tenkan"] > last["kijun"])},
        {"nom": "Prix > Kijun", "ok": bool(last["close"] > last["kijun"])},
        {"nom": "Chikou > Prix -26", "ok": bool(last["close"] > df["close"].iloc[-cfg.DISPLACEMENT - 1]) if len(df) > cfg.DISPLACEMENT else False},
        {"nom": f"Tendance (ADX {round(float(last['adx']), 1)})", "ok": bool(last["is_trending"])},
        {"nom": "DI+ > DI-", "ok": bool(last["di_bull"])},
        {"nom": f"EMA {cfg.EMA_LEN}", "ok": bool(last["close"] > last["ema200"]) if cfg.USE_EMA else True},
        {"nom": f"Volume > Moy.{cfg.VOL_LEN}", "ok": bool(last["volume"] > df["volume"].rolling(cfg.VOL_LEN).mean().iloc[-1]) if cfg.USE_VOL else True},
        {"nom": f"RSI {round(float(last['rsi']), 1)} (< {cfg.RSI_OB})", "ok": bool(last["rsi"] < cfg.RSI_OB) if cfg.USE_RSI else True},
        {"nom": "Hors zone FLAT", "ok": not bool(last["is_flat"])},
    ]

    return {
        "timestamp": str(last.name),
        "close": float(last["close"]),
        "signal": last["signal"],
        "signal_type": last["signal_type"],
        "market_state": last["market_state"],
        "score_bull": int(last["score_bull"]),
        "adx": round(float(last["adx"]), 2),
        "rsi": round(float(last["rsi"]), 2),
        "atr": round(float(last["atr"]), 4),
        "bb_width": round(float(last["bb_width"]) * 100, 2),
        "is_flat": bool(last["is_flat"]),
        "is_trending": bool(last["is_trending"]),
        "di_bull": bool(last["di_bull"]),
        "kijun": round(float(last["kijun"]), 2),
        "tenkan": round(float(last["tenkan"]), 2),
        "ema200": round(float(last["ema200"]), 2),
        "sl": last["sl"],
        "tp": last["tp"],
        "conditions": conditions_detail,
    }
