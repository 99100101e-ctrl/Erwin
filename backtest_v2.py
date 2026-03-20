#!/usr/bin/env python3
"""
BTC Day Trading V2 — Backtest Dual Regime (Trend + Mean Reversion)
Données réelles BTC 12-19 Mars 2026
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Réutiliser les données et le rapport de backtest.py
from backtest import fetch_btc_data, print_report

# ══════════════════════════════════════════════════════════════════════════════
# INDICATEURS
# ══════════════════════════════════════════════════════════════════════════════

def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def atr(df, period=14):
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.rolling(period).mean()

def bollinger_bands(series, period=20, mult=2.0):
    basis = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = basis + mult * std
    lower = basis - mult * std
    pct_b = (series - lower) / (upper - lower)
    width = (upper - lower) / basis * 100
    return basis, upper, lower, pct_b, width

def adx(df, period=14):
    """Calculate ADX, +DI, -DI."""
    high = df["high"]
    low = df["low"]
    close = df["close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr_val = true_range.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1/period, min_periods=period, adjust=False).mean() / atr_val
    minus_di = 100 * minus_dm.ewm(alpha=1/period, min_periods=period, adjust=False).mean() / atr_val

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx_line = dx.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

    return adx_line, plus_di, minus_di

def pivot_points(df, left=5, right=5):
    """Detect swing highs and lows."""
    swing_highs = pd.Series(np.nan, index=df.index)
    swing_lows = pd.Series(np.nan, index=df.index)

    highs = df["high"].values
    lows = df["low"].values

    for i in range(left, len(df) - right):
        # Swing high
        is_swing_high = True
        for j in range(1, left + 1):
            if highs[i] <= highs[i - j]:
                is_swing_high = False
                break
        if is_swing_high:
            for j in range(1, right + 1):
                if i + j < len(df) and highs[i] <= highs[i + j]:
                    is_swing_high = False
                    break
        if is_swing_high:
            swing_highs.iloc[i] = highs[i]

        # Swing low
        is_swing_low = True
        for j in range(1, left + 1):
            if lows[i] >= lows[i - j]:
                is_swing_low = False
                break
        if is_swing_low:
            for j in range(1, right + 1):
                if i + j < len(df) and lows[i] >= lows[i + j]:
                    is_swing_low = False
                    break
        if is_swing_low:
            swing_lows.iloc[i] = lows[i]

    return swing_highs, swing_lows


# ══════════════════════════════════════════════════════════════════════════════
# STRATÉGIE V2
# ══════════════════════════════════════════════════════════════════════════════

def run_backtest_v2(df, params=None):
    if params is None:
        params = {}

    p = {
        "ema_fast": 8, "ema_slow": 21,
        "bb_period": 20, "bb_mult": 2.0,
        "adx_period": 14, "adx_threshold": 20,
        "rsi_period": 14,
        "rsi_mr_low": 35, "rsi_mr_high": 65,
        "rsi_mom_low": 40, "rsi_mom_high": 70,
        "atr_period": 14,
        "sl_atr": 1.5, "tp1_atr": 1.5, "tp2_atr": 3.0,
        "trailing_atr": 2.0,
        "vol_ma": 20,
        "min_rr": 1.5,
        "session_start": 8, "session_end": 22,
        "use_session": True,
        "commission": 0.075,
    }
    p.update(params)

    # --- Calculs ---
    df["ema_f"] = ema(df["close"], p["ema_fast"])
    df["ema_s"] = ema(df["close"], p["ema_slow"])
    df["rsi"] = rsi(df["close"], p["rsi_period"])
    df["atr"] = atr(df, p["atr_period"])
    df["adx"], df["di_plus"], df["di_minus"] = adx(df, p["adx_period"])
    df["bb_mid"], df["bb_upper"], df["bb_lower"], df["bb_pctb"], df["bb_width"] = \
        bollinger_bands(df["close"], p["bb_period"], p["bb_mult"])
    df["vol_ma"] = df["volume"].rolling(p["vol_ma"]).mean()

    # Swing points
    sh, sl_points = pivot_points(df, 5, 5)
    df["swing_high"] = sh
    df["swing_low"] = sl_points

    # Forward-fill last swing levels
    df["last_swing_high"] = df["swing_high"].ffill()
    df["last_swing_low"] = df["swing_low"].ffill()

    df["hour"] = df.index.hour

    # --- Régime ---
    df["is_trending"] = df["adx"] > p["adx_threshold"]
    df["is_ranging"] = ~df["is_trending"]
    df["ema_bull"] = df["ema_f"] > df["ema_s"]
    df["ema_bear"] = df["ema_f"] < df["ema_s"]

    # --- Session ---
    if p["use_session"]:
        in_session = (df["hour"] >= p["session_start"]) & (df["hour"] < p["session_end"])
    else:
        in_session = pd.Series(True, index=df.index)

    df["vol_ok"] = df["volume"] > df["vol_ma"] * 0.8

    # --- MEAN REVERSION SIGNALS ---
    df["mr_long"] = (
        df["is_ranging"] &
        (df["close"] <= df["bb_lower"]) &
        (df["rsi"] < p["rsi_mr_low"]) &
        df["vol_ok"] &
        in_session
    )

    df["mr_short"] = (
        df["is_ranging"] &
        (df["close"] >= df["bb_upper"]) &
        (df["rsi"] > p["rsi_mr_high"]) &
        df["vol_ok"] &
        in_session
    )

    # --- MOMENTUM SIGNALS ---
    df["mom_long"] = (
        df["is_trending"] &
        df["ema_bull"] &
        (df["di_plus"] > df["di_minus"]) &
        (df["low"] <= df["ema_s"] * 1.002) &
        (df["close"] > df["ema_s"]) &
        (df["rsi"] > p["rsi_mom_low"]) & (df["rsi"] < p["rsi_mom_high"]) &
        in_session
    )

    df["mom_short"] = (
        df["is_trending"] &
        df["ema_bear"] &
        (df["di_minus"] > df["di_plus"]) &
        (df["high"] >= df["ema_s"] * 0.998) &
        (df["close"] < df["ema_s"]) &
        (df["rsi"] > 30) & (df["rsi"] < 60) &
        in_session
    )

    df["long_signal"] = df["mr_long"] | df["mom_long"]
    df["short_signal"] = df["mr_short"] | df["mom_short"]

    # ══════════════════════════════════════════════════════════════════════════
    # SIMULATION
    # ══════════════════════════════════════════════════════════════════════════

    capital = 10000.0
    initial_capital = capital
    position = None
    trades = []
    commission_rate = p["commission"] / 100.0

    for i in range(1, len(df)):
        row = df.iloc[i]

        if pd.isna(row["atr"]) or pd.isna(row["rsi"]) or pd.isna(row["adx"]) or row["atr"] == 0:
            continue
        if pd.isna(row["bb_upper"]) or pd.isna(row["bb_lower"]):
            continue

        # --- Gestion position ouverte ---
        if position is not None:
            exit_price = None
            exit_reason = None
            partial_exit = False

            if position["type"] == "long":
                # Trailing stop update
                if row["high"] > position.get("trail_high", position["entry"]):
                    position["trail_high"] = row["high"]
                    new_sl = position["trail_high"] - row["atr"] * p["trailing_atr"]
                    if new_sl > position["sl"]:
                        position["sl"] = new_sl

                # TP1 partial (50%)
                if not position.get("tp1_hit", False) and row["high"] >= position["tp1"]:
                    position["tp1_hit"] = True
                    # Move SL to breakeven
                    position["sl"] = position["entry"] + row["atr"] * 0.1
                    partial_exit = True
                    partial_pnl = (position["tp1"] - position["entry"]) / position["entry"] * 100
                    partial_pnl -= commission_rate * 2 * 100
                    partial_amount = capital * 0.5 * partial_pnl / 100
                    capital += partial_amount
                    position["partial_pnl"] = partial_amount

                # SL
                if row["low"] <= position["sl"]:
                    exit_price = position["sl"]
                    exit_reason = "Stop Loss" if not position.get("tp1_hit") else "BE Stop (post-TP1)"
                # TP2
                elif row["high"] >= position["tp2"]:
                    exit_price = position["tp2"]
                    exit_reason = "Take Profit 2"

            elif position["type"] == "short":
                if row["low"] < position.get("trail_low", position["entry"]):
                    position["trail_low"] = row["low"]
                    new_sl = position["trail_low"] + row["atr"] * p["trailing_atr"]
                    if new_sl < position["sl"]:
                        position["sl"] = new_sl

                # TP1 partial
                if not position.get("tp1_hit", False) and row["low"] <= position["tp1"]:
                    position["tp1_hit"] = True
                    position["sl"] = position["entry"] - row["atr"] * 0.1
                    partial_exit = True
                    partial_pnl = (position["entry"] - position["tp1"]) / position["entry"] * 100
                    partial_pnl -= commission_rate * 2 * 100
                    partial_amount = capital * 0.5 * partial_pnl / 100
                    capital += partial_amount
                    position["partial_pnl"] = partial_amount

                # SL
                if row["high"] >= position["sl"]:
                    exit_price = position["sl"]
                    exit_reason = "Stop Loss" if not position.get("tp1_hit") else "BE Stop (post-TP1)"
                # TP2
                elif row["low"] <= position["tp2"]:
                    exit_price = position["tp2"]
                    exit_reason = "Take Profit 2"

            if exit_price is not None:
                if position["type"] == "long":
                    pnl_pct = (exit_price - position["entry"]) / position["entry"] * 100
                else:
                    pnl_pct = (position["entry"] - exit_price) / position["entry"] * 100

                # If TP1 was hit, only 50% remaining
                size_mult = 0.5 if position.get("tp1_hit", False) else 1.0
                pnl_pct_adj = pnl_pct * size_mult
                pnl_pct_adj -= commission_rate * 2 * 100 * size_mult

                pnl_amount = capital * pnl_pct_adj / 100
                capital += pnl_amount

                total_pnl = pnl_amount + position.get("partial_pnl", 0)

                trades.append({
                    "entry_time": position["entry_time"],
                    "exit_time": row.name,
                    "type": position["type"].upper(),
                    "regime": position["regime"],
                    "entry": position["entry"],
                    "exit": exit_price,
                    "sl": position["original_sl"],
                    "tp1": position["tp1"],
                    "tp2": position["tp2"],
                    "tp1_hit": position.get("tp1_hit", False),
                    "pnl_pct": round(total_pnl / (capital - total_pnl) * 100, 3) if (capital - total_pnl) > 0 else 0,
                    "pnl_usd": round(total_pnl, 2),
                    "capital": round(capital, 2),
                    "reason": exit_reason,
                })
                position = None

        # --- Entrée en position ---
        if position is None:
            atr_v = row["atr"]
            is_mr = False
            is_mom = False

            if row["long_signal"]:
                is_mr = bool(row["mr_long"]) if isinstance(row["mr_long"], (bool, np.bool_)) else False
                is_mom = bool(row["mom_long"]) if isinstance(row["mom_long"], (bool, np.bool_)) else False

                if is_mr:
                    sl = min(row["close"] - atr_v * p["sl_atr"], row["bb_lower"] - atr_v * 0.3)
                    tp1 = row["bb_mid"]
                    tp2 = row["bb_upper"]
                    regime = "MR"
                else:
                    swing_sl = row["last_swing_low"] if not pd.isna(row["last_swing_low"]) else row["close"] - atr_v * 2
                    sl = max(row["close"] - atr_v * p["sl_atr"], swing_sl)
                    tp1 = row["close"] + atr_v * p["tp1_atr"]
                    tp2 = row["close"] + atr_v * p["tp2_atr"]
                    regime = "MOM"

                # Risk/Reward check
                risk = row["close"] - sl
                reward = tp2 - row["close"]
                if risk > 0 and reward / risk >= p["min_rr"]:
                    position = {
                        "type": "long", "regime": regime,
                        "entry": row["close"], "entry_time": row.name,
                        "sl": sl, "original_sl": sl,
                        "tp1": tp1, "tp2": tp2,
                        "trail_high": row["close"],
                    }

            elif row["short_signal"]:
                is_mr = bool(row["mr_short"]) if isinstance(row["mr_short"], (bool, np.bool_)) else False

                if is_mr:
                    sl = max(row["close"] + atr_v * p["sl_atr"], row["bb_upper"] + atr_v * 0.3)
                    tp1 = row["bb_mid"]
                    tp2 = row["bb_lower"]
                    regime = "MR"
                else:
                    swing_sl = row["last_swing_high"] if not pd.isna(row["last_swing_high"]) else row["close"] + atr_v * 2
                    sl = min(row["close"] + atr_v * p["sl_atr"], swing_sl)
                    tp1 = row["close"] - atr_v * p["tp1_atr"]
                    tp2 = row["close"] - atr_v * p["tp2_atr"]
                    regime = "MOM"

                risk = sl - row["close"]
                reward = row["close"] - tp2
                if risk > 0 and reward / risk >= p["min_rr"]:
                    position = {
                        "type": "short", "regime": regime,
                        "entry": row["close"], "entry_time": row.name,
                        "sl": sl, "original_sl": sl,
                        "tp1": tp1, "tp2": tp2,
                        "trail_low": row["close"],
                    }

    # Fermer position ouverte
    if position is not None:
        last = df.iloc[-1]
        if position["type"] == "long":
            pnl_pct = (last["close"] - position["entry"]) / position["entry"] * 100
        else:
            pnl_pct = (position["entry"] - last["close"]) / position["entry"] * 100

        size_mult = 0.5 if position.get("tp1_hit", False) else 1.0
        pnl_pct_adj = pnl_pct * size_mult - commission_rate * 2 * 100 * size_mult
        pnl_amount = capital * pnl_pct_adj / 100
        capital += pnl_amount
        total_pnl = pnl_amount + position.get("partial_pnl", 0)

        trades.append({
            "entry_time": position["entry_time"],
            "exit_time": last.name,
            "type": position["type"].upper(),
            "regime": position["regime"],
            "entry": position["entry"],
            "exit": last["close"],
            "sl": position["original_sl"],
            "tp1": position["tp1"],
            "tp2": position["tp2"],
            "tp1_hit": position.get("tp1_hit", False),
            "pnl_pct": round(total_pnl / max(capital - total_pnl, 1) * 100, 3),
            "pnl_usd": round(total_pnl, 2),
            "capital": round(capital, 2),
            "reason": "Fin de période",
        })

    return trades, capital, initial_capital, df


# ══════════════════════════════════════════════════════════════════════════════
# RAPPORT V2
# ══════════════════════════════════════════════════════════════════════════════

def print_report_v2(trades, final_capital, initial_capital, df):
    print("=" * 90)
    print("  BTC DAY TRADING V2 — DUAL REGIME — BACKTEST SEMAINE 12-19 MARS 2026")
    print("=" * 90)
    print()
    print(f"  Période      : {df.index[0].strftime('%Y-%m-%d %H:%M')} → {df.index[-1].strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"  Timeframe    : 15 minutes | {len(df)} bougies")
    print(f"  Prix BTC     : {df['close'].iloc[0]:,.2f}$ → {df['close'].iloc[-1]:,.2f}$")
    btc_change = (df["close"].iloc[-1] - df["close"].iloc[0]) / df["close"].iloc[0] * 100
    print(f"  Variation BTC: {btc_change:+.2f}% (Buy & Hold)")
    print()

    if not trades:
        print("  Aucun trade exécuté.")
        print("=" * 90)
        return

    total_return = (final_capital - initial_capital) / initial_capital * 100
    wins = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] <= 0]
    win_rate = len(wins) / len(trades) * 100

    avg_win = np.mean([t["pnl_usd"] for t in wins]) if wins else 0
    avg_loss = np.mean([abs(t["pnl_usd"]) for t in losses]) if losses else 0

    gross_profit = sum(t["pnl_usd"] for t in wins) if wins else 0
    gross_loss = abs(sum(t["pnl_usd"] for t in losses)) if losses else 0
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    peak = initial_capital
    max_dd = 0
    for t in trades:
        if t["capital"] > peak:
            peak = t["capital"]
        dd = (peak - t["capital"]) / peak * 100
        if dd > max_dd:
            max_dd = dd

    rr = avg_win / avg_loss if avg_loss > 0 else float("inf")

    # Par régime
    mr_trades = [t for t in trades if t["regime"] == "MR"]
    mom_trades = [t for t in trades if t["regime"] == "MOM"]
    mr_wins = [t for t in mr_trades if t["pnl_usd"] > 0]
    mom_wins = [t for t in mom_trades if t["pnl_usd"] > 0]
    tp1_hits = [t for t in trades if t.get("tp1_hit", False)]

    print("─" * 90)
    print("  RÉSULTATS GLOBAUX")
    print("─" * 90)
    print(f"  Capital initial  : {initial_capital:>12,.2f} $")
    print(f"  Capital final    : {final_capital:>12,.2f} $")
    print(f"  Rendement total  : {total_return:>+11.2f} %")
    print(f"  Alpha vs BTC     : {total_return - btc_change:>+11.2f} %")
    print()
    print(f"  Nombre de trades : {len(trades)}")
    print(f"  Trades gagnants  : {len(wins)}  ({win_rate:.1f}%)")
    print(f"  Trades perdants  : {len(losses)}  ({100-win_rate:.1f}%)")
    print(f"  TP1 touchés      : {len(tp1_hits)}  ({len(tp1_hits)/len(trades)*100:.0f}%)")
    print()
    print(f"  Gain moyen       : {avg_win:>+.2f} $")
    print(f"  Perte moyenne    : {avg_loss:>.2f} $")
    print(f"  Risk/Reward      : {rr:.2f}")
    print(f"  Profit Factor    : {pf:.2f}")
    print(f"  Max Drawdown     : {max_dd:.2f} %")
    print()

    if mr_trades:
        mr_wr = len(mr_wins)/len(mr_trades)*100
        mr_pnl = sum(t["pnl_usd"] for t in mr_trades)
        print(f"  Mean Reversion   : {len(mr_trades)} trades | WR {mr_wr:.0f}% | P&L {mr_pnl:+.2f}$")
    if mom_trades:
        mom_wr = len(mom_wins)/len(mom_trades)*100
        mom_pnl = sum(t["pnl_usd"] for t in mom_trades)
        print(f"  Momentum         : {len(mom_trades)} trades | WR {mom_wr:.0f}% | P&L {mom_pnl:+.2f}$")
    print()

    # Raisons de sortie
    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    print("  Sorties:")
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"    {reason:<25s}: {count}")
    print()

    # Détail
    print("─" * 90)
    print("  DÉTAIL DES TRADES")
    print("─" * 90)
    print(f"  {'#':>2} {'Type':>5} {'Rég':>3} {'Entrée':>10} {'Sortie':>10} {'TP1':>3} {'P&L $':>9} {'Capital':>11} {'Raison':<25} {'Date':<14}")
    print("  " + "─" * 100)

    for i, t in enumerate(trades, 1):
        tp1 = "yes" if t.get("tp1_hit") else "no"
        print(
            f"  {i:>2} {t['type']:>5} {t['regime']:>3} "
            f"{t['entry']:>10,.2f} {t['exit']:>10,.2f} "
            f"{tp1:>3} {t['pnl_usd']:>+9.2f} {t['capital']:>11,.2f} "
            f"{t['reason']:<25s} {t['entry_time'].strftime('%m/%d %H:%M')}"
        )

    # Equity curve
    print()
    print("─" * 90)
    print("  EQUITY CURVE")
    print("─" * 90)
    capitals = [initial_capital] + [t["capital"] for t in trades]
    min_c = min(capitals)
    max_c = max(capitals)
    w = 50
    for i, c in enumerate(capitals):
        if max_c == min_c:
            bar = w
        else:
            bar = int((c - min_c) / (max_c - min_c) * w)
        b = "█" * max(bar, 1)
        label = "START" if i == 0 else f"T{i}"
        marker = " <<<" if c == max_c and i > 0 else ""
        print(f"  {label:>6} {c:>10,.2f}$ |{b}{marker}")

    print()
    print("=" * 90)
    verdict = "STRATÉGIE RENTABLE" if total_return > 0 else "STRATÉGIE EN PERTE"
    print(f"  {verdict}")
    print(f"  Rendement: {total_return:+.2f}% vs Buy & Hold: {btc_change:+.2f}% | Alpha: {total_return - btc_change:+.2f}%")
    print("=" * 90)


# ══════════════════════════════════════════════════════════════════════════════
# OPTIMISATION V2
# ══════════════════════════════════════════════════════════════════════════════

def optimize_v2(df):
    configs = [
        {"name": "Balanced (défaut)", },

        {"name": "MR agressif (RSI 40/60)",
         "rsi_mr_low": 40, "rsi_mr_high": 60, "min_rr": 1.2},

        {"name": "MR + BB 1.8σ",
         "bb_mult": 1.8, "rsi_mr_low": 38, "rsi_mr_high": 62, "min_rr": 1.3},

        {"name": "Momentum pur (ADX 15)",
         "adx_threshold": 15, "rsi_mr_low": 30, "rsi_mr_high": 70, "min_rr": 1.5},

        {"name": "SL serré + TP large",
         "sl_atr": 1.0, "tp1_atr": 2.0, "tp2_atr": 4.0, "trailing_atr": 2.5, "min_rr": 1.5},

        {"name": "Scalp MR (BB 1.5σ, RR 1.0)",
         "bb_mult": 1.5, "rsi_mr_low": 42, "rsi_mr_high": 58, "min_rr": 1.0,
         "sl_atr": 0.8, "tp1_atr": 1.0, "tp2_atr": 1.8},

        {"name": "24h (pas de filtre session)",
         "use_session": False, "min_rr": 1.3},

        {"name": "Session EU+US (8-22)",
         "session_start": 8, "session_end": 22, "min_rr": 1.3,
         "rsi_mr_low": 38, "rsi_mr_high": 62},

        {"name": "ADX 18 + BB 1.8 + RR 1.2",
         "adx_threshold": 18, "bb_mult": 1.8,
         "rsi_mr_low": 40, "rsi_mr_high": 60, "min_rr": 1.2,
         "sl_atr": 1.2, "tp1_atr": 1.5, "tp2_atr": 2.5},

        {"name": "Ultra-safe (RR 2.0, RSI strict)",
         "min_rr": 2.0, "rsi_mr_low": 30, "rsi_mr_high": 70,
         "sl_atr": 1.5, "tp2_atr": 4.0},
    ]

    print("\n" + "=" * 90)
    print("  OPTIMISATION V2 — Test de 10 configurations")
    print("=" * 90)

    btc_change = (df["close"].iloc[-1] - df["close"].iloc[0]) / df["close"].iloc[0] * 100

    print(f"\n  {'#':>2} {'Config':<30} {'Trades':>6} {'Win%':>6} {'PnL%':>8} {'PF':>6} {'MaxDD':>7} {'Alpha':>7} {'TP1%':>5}")
    print("  " + "─" * 85)

    results = []
    for idx, cfg in enumerate(configs, 1):
        name = cfg.pop("name")
        df_c = df.copy()
        trades, fc, ic, _ = run_backtest_v2(df_c, cfg)
        cfg["name"] = name

        ret = (fc - ic) / ic * 100
        n = len(trades)
        wins = [t for t in trades if t["pnl_usd"] > 0]
        wr = len(wins) / n * 100 if n > 0 else 0
        gp = sum(t["pnl_usd"] for t in wins) if wins else 0
        gl = abs(sum(t["pnl_usd"] for t in trades if t["pnl_usd"] <= 0))
        pf = gp / gl if gl > 0 else float("inf")

        peak = ic
        mdd = 0
        for t in trades:
            if t["capital"] > peak: peak = t["capital"]
            dd = (peak - t["capital"]) / peak * 100
            if dd > mdd: mdd = dd

        alpha = ret - btc_change
        tp1_pct = len([t for t in trades if t.get("tp1_hit")]) / n * 100 if n > 0 else 0

        results.append({"name": name, "return": ret, "trades": n, "wr": wr, "pf": pf,
                         "mdd": mdd, "alpha": alpha, "cfg": cfg, "trade_list": trades,
                         "fc": fc, "tp1_pct": tp1_pct})

        pf_s = f"{pf:.2f}" if pf != float("inf") else "∞"
        print(f"  {idx:>2} {name:<30} {n:>6} {wr:>5.1f}% {ret:>+7.2f}% {pf_s:>6} {mdd:>6.2f}% {alpha:>+6.2f}% {tp1_pct:>4.0f}%")

    best = max(results, key=lambda x: x["return"])
    print()
    print(f"  MEILLEURE: {best['name']} → {best['return']:+.2f}% | Alpha: {best['alpha']:+.2f}%")
    print("=" * 90)

    return best, results


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n  BTC Day Trading V2 — Dual Regime Strategy\n")

    df = fetch_btc_data(interval="15m", days=8)
    print(f"  {len(df)} bougies chargées.\n")

    # Optimisation
    best, all_results = optimize_v2(df)

    # Rapport détaillé
    print("\n  Rapport détaillé — Meilleure configuration:\n")
    df_best = df.copy()
    cfg = best["cfg"].copy()
    cfg.pop("name", None)
    trades, fc, ic, df_best = run_backtest_v2(df_best, cfg)
    print_report_v2(trades, fc, ic, df_best)
