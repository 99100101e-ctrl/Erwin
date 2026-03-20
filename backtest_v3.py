#!/usr/bin/env python3
"""
BTC Day Trading V3 — Structure + Multi-Timeframe Backtest
Focus: Moins de trades, meilleure qualité, structure-based
"""

import pandas as pd
import numpy as np
from backtest import fetch_btc_data

# ══════════════════════════════════════════════════════════════════════════════
# INDICATEURS
# ══════════════════════════════════════════════════════════════════════════════

def ema(s, p):
    return s.ewm(span=p, adjust=False).mean()

def rsi(s, p=14):
    d = s.diff()
    g = d.where(d > 0, 0.0)
    l = -d.where(d < 0, 0.0)
    ag = g.ewm(alpha=1/p, min_periods=p, adjust=False).mean()
    al = l.ewm(alpha=1/p, min_periods=p, adjust=False).mean()
    return 100 - 100 / (1 + ag / al)

def atr(df, p=14):
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(p).mean()

def resample_htf(df, tf_minutes=240):
    """Resample to higher timeframe for bias."""
    rule = f"{tf_minutes}min"
    htf = df.resample(rule).agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"
    }).dropna()
    return htf


# ══════════════════════════════════════════════════════════════════════════════
# STRATÉGIE V3
# ══════════════════════════════════════════════════════════════════════════════

def run_backtest_v3(df, params=None):
    if params is None:
        params = {}

    p = {
        "htf_ema": 50, "htf_minutes": 240,
        "lookback": 20, "consol_bars": 8, "consol_width_atr": 1.5,
        "breakout_min_atr": 0.5,
        "rsi_period": 14,
        "vol_mult": 1.3, "vol_ma": 20,
        "atr_period": 14, "sl_buffer_atr": 0.3,
        "tp1_rr": 1.5, "tp2_rr": 3.0,
        "trailing": True, "trail_activation_rr": 1.5, "trail_offset_rr": 0.8,
        "max_trades_day": 3,
        "session_start": 8, "session_end": 17,
        "use_session": True,
        "commission": 0.075,
        # Bounce S/R params
        "sr_proximity_pct": 0.003,  # 0.3% near S/R
        "rsi_bounce_low": 40, "rsi_bounce_high": 60,
    }
    p.update(params)

    # === HTF Bias ===
    htf = resample_htf(df, p["htf_minutes"])
    htf["ema"] = ema(htf["close"], p["htf_ema"])
    htf["bias_bull"] = htf["close"] > htf["ema"]
    htf["bias_bear"] = htf["close"] < htf["ema"]

    # Map HTF bias to LTF
    # For each 15m bar, use the LAST COMPLETED HTF bar
    df["htf_bias_bull"] = False
    df["htf_bias_bear"] = False
    for idx in df.index:
        htf_before = htf[htf.index <= idx]
        if len(htf_before) > 0:
            df.loc[idx, "htf_bias_bull"] = bool(htf_before["bias_bull"].iloc[-1])
            df.loc[idx, "htf_bias_bear"] = bool(htf_before["bias_bear"].iloc[-1])

    # === LTF Indicators ===
    df["rsi"] = rsi(df["close"], p["rsi_period"])
    df["atr"] = atr(df, p["atr_period"])
    df["vol_ma"] = df["volume"].rolling(p["vol_ma"]).mean()

    # === Structure: Range & Consolidation ===
    lb = p["lookback"]
    df["range_high"] = df["high"].rolling(lb).max()
    df["range_low"] = df["low"].rolling(lb).min()
    df["range_width"] = df["range_high"] - df["range_low"]

    # Consolidation: range_width < consol_width * ATR for consol_bars bars
    df["is_narrow"] = df["range_width"] < p["consol_width_atr"] * df["atr"]
    df["narrow_count"] = df["is_narrow"].rolling(p["consol_bars"]).sum()
    df["in_consolidation"] = df["narrow_count"] >= p["consol_bars"]

    # Breakout detection
    df["breakout_up"] = (
        df["in_consolidation"].shift(1).fillna(False) &
        (df["close"] > df["range_high"].shift(1)) &
        ((df["close"] - df["range_high"].shift(1)) > df["atr"] * p["breakout_min_atr"])
    )
    df["breakout_dn"] = (
        df["in_consolidation"].shift(1).fillna(False) &
        (df["close"] < df["range_low"].shift(1)) &
        ((df["range_low"].shift(1) - df["close"]) > df["atr"] * p["breakout_min_atr"])
    )

    # === Swing S/R ===
    df["pivot_high"] = pd.Series(np.nan, index=df.index)
    df["pivot_low"] = pd.Series(np.nan, index=df.index)
    pivot_win = 10
    highs = df["high"].values
    lows = df["low"].values
    for i in range(pivot_win, len(df) - pivot_win):
        is_ph = all(highs[i] > highs[i-j] for j in range(1, pivot_win+1)) and \
                all(highs[i] > highs[i+j] for j in range(1, min(pivot_win+1, len(df)-i)))
        is_pl = all(lows[i] < lows[i-j] for j in range(1, pivot_win+1)) and \
                all(lows[i] < lows[i+j] for j in range(1, min(pivot_win+1, len(df)-i)))
        if is_ph:
            df.iloc[i, df.columns.get_loc("pivot_high")] = highs[i]
        if is_pl:
            df.iloc[i, df.columns.get_loc("pivot_low")] = lows[i]

    df["sr_resist"] = df["pivot_high"].ffill()
    df["sr_support"] = df["pivot_low"].ffill()

    # Near S/R
    prox = p["sr_proximity_pct"]
    df["near_support"] = (~df["sr_support"].isna()) & (df["low"] <= df["sr_support"] * (1 + prox)) & (df["close"] > df["sr_support"])
    df["near_resist"] = (~df["sr_resist"].isna()) & (df["high"] >= df["sr_resist"] * (1 - prox)) & (df["close"] < df["sr_resist"])

    # === Volume spike ===
    df["vol_spike"] = df["volume"] > df["vol_ma"] * p["vol_mult"]

    # === Session ===
    df["hour"] = df.index.hour
    if p["use_session"]:
        in_sess = (df["hour"] >= p["session_start"]) & (df["hour"] < p["session_end"])
    else:
        in_sess = pd.Series(True, index=df.index)

    # === SIGNALS ===
    # LONG breakout
    df["long_breakout"] = (
        df["breakout_up"] & df["htf_bias_bull"] & df["vol_spike"] &
        (df["rsi"] > 50) & (df["rsi"] < 75)
    )
    # LONG S/R bounce
    df["long_bounce"] = (
        df["near_support"] & df["htf_bias_bull"] &
        (df["rsi"] < p["rsi_bounce_low"]) & (df["volume"] > df["vol_ma"])
    )
    df["long_signal"] = (df["long_breakout"] | df["long_bounce"]) & in_sess

    # SHORT breakout
    df["short_breakout"] = (
        df["breakout_dn"] & df["htf_bias_bear"] & df["vol_spike"] &
        (df["rsi"] < 50) & (df["rsi"] > 25)
    )
    # SHORT S/R bounce
    df["short_bounce"] = (
        df["near_resist"] & df["htf_bias_bear"] &
        (df["rsi"] > p["rsi_bounce_high"]) & (df["volume"] > df["vol_ma"])
    )
    df["short_signal"] = (df["short_breakout"] | df["short_bounce"]) & in_sess

    # ══════════════════════════════════════════════════════════════════════════
    # SIMULATION
    # ══════════════════════════════════════════════════════════════════════════

    capital = 10000.0
    initial_capital = capital
    position = None
    trades = []
    comm = p["commission"] / 100.0
    trades_today_count = 0
    current_day = None

    for i in range(1, len(df)):
        row = df.iloc[i]

        if pd.isna(row["atr"]) or row["atr"] == 0 or pd.isna(row["rsi"]):
            continue

        # Reset daily counter
        day = row.name.date()
        if day != current_day:
            current_day = day
            trades_today_count = 0

        # === Manage open position ===
        if position is not None:
            exit_price = None
            exit_reason = None
            risk = position["risk"]

            if position["type"] == "long":
                # Track high for trailing
                if row["high"] > position.get("max_price", position["entry"]):
                    position["max_price"] = row["high"]

                # Trailing stop: activate after trail_activation * risk profit
                if position["max_price"] - position["entry"] >= risk * p["trail_activation_rr"]:
                    trail_sl = position["max_price"] - risk * p["trail_offset_rr"]
                    if trail_sl > position["sl"]:
                        position["sl"] = trail_sl

                # TP1 partial
                if not position.get("tp1_hit") and row["high"] >= position["tp1"]:
                    position["tp1_hit"] = True
                    # Move SL to breakeven + small profit
                    position["sl"] = max(position["sl"], position["entry"] + risk * 0.1)
                    # Book 50% profit at TP1
                    partial_pnl_pct = (position["tp1"] - position["entry"]) / position["entry"] * 100
                    partial_pnl_pct -= comm * 2 * 100
                    position["partial_pnl"] = capital * 0.5 * partial_pnl_pct / 100
                    capital += position["partial_pnl"]

                # Check SL
                if row["low"] <= position["sl"]:
                    exit_price = position["sl"]
                    exit_reason = "Trailing SL" if position.get("tp1_hit") else "Stop Loss"
                # Check TP2
                elif row["high"] >= position["tp2"]:
                    exit_price = position["tp2"]
                    exit_reason = "Take Profit 2"

            else:  # short
                if row["low"] < position.get("min_price", position["entry"]):
                    position["min_price"] = row["low"]

                if position["entry"] - position["min_price"] >= risk * p["trail_activation_rr"]:
                    trail_sl = position["min_price"] + risk * p["trail_offset_rr"]
                    if trail_sl < position["sl"]:
                        position["sl"] = trail_sl

                if not position.get("tp1_hit") and row["low"] <= position["tp1"]:
                    position["tp1_hit"] = True
                    position["sl"] = min(position["sl"], position["entry"] - risk * 0.1)
                    partial_pnl_pct = (position["entry"] - position["tp1"]) / position["entry"] * 100
                    partial_pnl_pct -= comm * 2 * 100
                    position["partial_pnl"] = capital * 0.5 * partial_pnl_pct / 100
                    capital += position["partial_pnl"]

                if row["high"] >= position["sl"]:
                    exit_price = position["sl"]
                    exit_reason = "Trailing SL" if position.get("tp1_hit") else "Stop Loss"
                elif row["low"] <= position["tp2"]:
                    exit_price = position["tp2"]
                    exit_reason = "Take Profit 2"

            if exit_price is not None:
                if position["type"] == "long":
                    pnl_pct = (exit_price - position["entry"]) / position["entry"] * 100
                else:
                    pnl_pct = (position["entry"] - exit_price) / position["entry"] * 100

                size = 0.5 if position.get("tp1_hit") else 1.0
                pnl_adj = pnl_pct * size - comm * 2 * 100 * size
                pnl_amount = capital * pnl_adj / 100
                capital += pnl_amount
                total_pnl = pnl_amount + position.get("partial_pnl", 0)

                trades.append({
                    "entry_time": position["entry_time"],
                    "exit_time": row.name,
                    "type": position["type"].upper(),
                    "signal": position["signal"],
                    "entry": position["entry"],
                    "exit": exit_price,
                    "sl_orig": position["sl_orig"],
                    "tp1": position["tp1"],
                    "tp2": position["tp2"],
                    "tp1_hit": position.get("tp1_hit", False),
                    "risk_r": round(risk, 2),
                    "pnl_usd": round(total_pnl, 2),
                    "capital": round(capital, 2),
                    "reason": exit_reason,
                    "htf_bias": "BULL" if position.get("htf_bull") else "BEAR",
                    "rr_actual": round(abs(total_pnl) / (capital * risk / position["entry"] + 0.01), 2) if risk > 0 else 0,
                })
                position = None

        # === New entries ===
        if position is None and trades_today_count < p["max_trades_day"]:
            atr_v = row["atr"]

            if row["long_signal"]:
                is_bk = bool(row["long_breakout"])
                sig = "BK" if is_bk else "SR"

                # SL: below range low or support
                sl_base = min(
                    row["range_low"] if not pd.isna(row["range_low"]) else row["close"] - atr_v * 2,
                    row["sr_support"] if not pd.isna(row["sr_support"]) else row["close"] - atr_v * 2
                )
                sl = sl_base - atr_v * p["sl_buffer_atr"]
                risk = row["close"] - sl

                if risk > 0 and risk < atr_v * 3:
                    tp1 = row["close"] + risk * p["tp1_rr"]
                    tp2 = row["close"] + risk * p["tp2_rr"]

                    position = {
                        "type": "long", "signal": sig,
                        "entry": row["close"], "entry_time": row.name,
                        "sl": sl, "sl_orig": sl,
                        "tp1": tp1, "tp2": tp2,
                        "risk": risk, "max_price": row["close"],
                        "htf_bull": True,
                    }
                    trades_today_count += 1

            elif row["short_signal"]:
                is_bk = bool(row["short_breakout"])
                sig = "BK" if is_bk else "SR"

                sl_base = max(
                    row["range_high"] if not pd.isna(row["range_high"]) else row["close"] + atr_v * 2,
                    row["sr_resist"] if not pd.isna(row["sr_resist"]) else row["close"] + atr_v * 2
                )
                sl = sl_base + atr_v * p["sl_buffer_atr"]
                risk = sl - row["close"]

                if risk > 0 and risk < atr_v * 3:
                    tp1 = row["close"] - risk * p["tp1_rr"]
                    tp2 = row["close"] - risk * p["tp2_rr"]

                    position = {
                        "type": "short", "signal": sig,
                        "entry": row["close"], "entry_time": row.name,
                        "sl": sl, "sl_orig": sl,
                        "tp1": tp1, "tp2": tp2,
                        "risk": risk, "min_price": row["close"],
                        "htf_bull": False,
                    }
                    trades_today_count += 1

    # Close open position at end
    if position is not None:
        last = df.iloc[-1]
        if position["type"] == "long":
            pnl_pct = (last["close"] - position["entry"]) / position["entry"] * 100
        else:
            pnl_pct = (position["entry"] - last["close"]) / position["entry"] * 100
        size = 0.5 if position.get("tp1_hit") else 1.0
        pnl_adj = pnl_pct * size - comm * 2 * 100 * size
        pnl_amount = capital * pnl_adj / 100
        capital += pnl_amount
        total_pnl = pnl_amount + position.get("partial_pnl", 0)
        trades.append({
            "entry_time": position["entry_time"],
            "exit_time": last.name,
            "type": position["type"].upper(),
            "signal": position["signal"],
            "entry": position["entry"],
            "exit": last["close"],
            "sl_orig": position["sl_orig"],
            "tp1": position["tp1"], "tp2": position["tp2"],
            "tp1_hit": position.get("tp1_hit", False),
            "risk_r": round(position["risk"], 2),
            "pnl_usd": round(total_pnl, 2),
            "capital": round(capital, 2),
            "reason": "Fin de période",
            "htf_bias": "BULL" if position.get("htf_bull") else "BEAR",
            "rr_actual": 0,
        })

    return trades, capital, initial_capital, df


# ══════════════════════════════════════════════════════════════════════════════
# RAPPORT
# ══════════════════════════════════════════════════════════════════════════════

def print_report_v3(trades, fc, ic, df):
    print("=" * 95)
    print("  BTC DAY TRADING V3 — STRUCTURE + MTF — BACKTEST 12-19 MARS 2026")
    print("=" * 95)
    print()
    print(f"  Période   : {df.index[0].strftime('%Y-%m-%d %H:%M')} → {df.index[-1].strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"  Timeframe : 15m (LTF) + 4H (HTF) | {len(df)} bougies")
    btc_ch = (df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0] * 100
    print(f"  BTC       : {df['close'].iloc[0]:,.2f}$ → {df['close'].iloc[-1]:,.2f}$ ({btc_ch:+.2f}%)")
    print()

    if not trades:
        print("  Aucun trade exécuté.")

        # Debug: check signals
        sig_l = df["long_signal"].sum()
        sig_s = df["short_signal"].sum()
        consol = df["in_consolidation"].sum()
        bk_up = df["breakout_up"].sum()
        bk_dn = df["breakout_dn"].sum()
        bull = df["htf_bias_bull"].sum()
        bear = df["htf_bias_bear"].sum()
        bounce_l = df["long_bounce"].sum()
        bounce_s = df["short_bounce"].sum()
        bk_l = df["long_breakout"].sum()
        bk_s = df["short_breakout"].sum()

        print()
        print("  DEBUG — Pourquoi aucun signal?")
        print(f"  HTF Bias Bull  : {bull} bars | Bear: {bear} bars")
        print(f"  Consolidations : {consol} bars")
        print(f"  Breakout Up    : {bk_up} | Breakout Down: {bk_dn}")
        print(f"  Long Breakout  : {bk_l} | Short Breakout: {bk_s}")
        print(f"  Near Support   : {df['near_support'].sum()} | Near Resist: {df['near_resist'].sum()}")
        print(f"  Long Bounce    : {bounce_l} | Short Bounce: {bounce_s}")
        print(f"  Vol Spikes     : {df['vol_spike'].sum()}")
        print(f"  Long Signals   : {sig_l} | Short Signals: {sig_s}")
        print("=" * 95)
        return

    ret = (fc - ic) / ic * 100
    wins = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] <= 0]
    wr = len(wins) / len(trades) * 100

    avg_w = np.mean([t["pnl_usd"] for t in wins]) if wins else 0
    avg_l = np.mean([abs(t["pnl_usd"]) for t in losses]) if losses else 0

    gp = sum(t["pnl_usd"] for t in wins) if wins else 0
    gl = abs(sum(t["pnl_usd"] for t in losses)) if losses else 0
    pf = gp / gl if gl > 0 else float("inf")

    peak = ic; mdd = 0
    for t in trades:
        if t["capital"] > peak: peak = t["capital"]
        dd = (peak - t["capital"]) / peak * 100
        if dd > mdd: mdd = dd

    rr = avg_w / avg_l if avg_l > 0 else float("inf")

    bk_trades = [t for t in trades if t["signal"] == "BK"]
    sr_trades = [t for t in trades if t["signal"] == "SR"]
    tp1_hits = [t for t in trades if t.get("tp1_hit")]

    print("─" * 95)
    print("  RÉSULTATS")
    print("─" * 95)
    print(f"  Capital        : {ic:>12,.2f}$ → {fc:>12,.2f}$")
    print(f"  Rendement      : {ret:>+10.2f}% | Alpha: {ret - btc_ch:>+.2f}%")
    print()
    print(f"  Trades         : {len(trades):>3}  (moy {len(trades)/8:.1f}/jour)")
    print(f"  Win Rate       : {wr:>5.1f}%  ({len(wins)}W / {len(losses)}L)")
    print(f"  TP1 touchés    : {len(tp1_hits):>3}  ({len(tp1_hits)/len(trades)*100:.0f}%)")
    print(f"  Gain moyen     : {avg_w:>+10.2f}$")
    print(f"  Perte moyenne  : {avg_l:>10.2f}$")
    print(f"  Risk/Reward    : {rr:>5.2f}")
    print(f"  Profit Factor  : {pf:>5.2f}")
    print(f"  Max Drawdown   : {mdd:>5.2f}%")
    print()

    if bk_trades:
        bk_w = [t for t in bk_trades if t["pnl_usd"] > 0]
        print(f"  Breakout       : {len(bk_trades)} trades | WR {len(bk_w)/len(bk_trades)*100:.0f}% | P&L {sum(t['pnl_usd'] for t in bk_trades):+.2f}$")
    if sr_trades:
        sr_w = [t for t in sr_trades if t["pnl_usd"] > 0]
        print(f"  S/R Bounce     : {len(sr_trades)} trades | WR {len(sr_w)/len(sr_trades)*100:.0f}% | P&L {sum(t['pnl_usd'] for t in sr_trades):+.2f}$")
    print()

    # Sorties
    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    print("  Sorties:")
    for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"    {r:<25}: {c}")
    print()

    # Détail
    print("─" * 95)
    print("  DÉTAIL")
    print("─" * 95)
    print(f"  {'#':>2} {'Type':>5} {'Sig':>3} {'HTF':>4} {'Entrée':>10} {'Sortie':>10} {'TP1':>3} {'P&L $':>9} {'Capital':>11} {'Raison':<20} {'Date':<14}")
    print("  " + "─" * 105)

    for i, t in enumerate(trades, 1):
        tp1 = "✓" if t.get("tp1_hit") else "✗"
        print(
            f"  {i:>2} {t['type']:>5} {t['signal']:>3} {t['htf_bias']:>4} "
            f"{t['entry']:>10,.2f} {t['exit']:>10,.2f} "
            f"{tp1:>3} {t['pnl_usd']:>+9.2f} {t['capital']:>11,.2f} "
            f"{t['reason']:<20} {t['entry_time'].strftime('%m/%d %H:%M')}"
        )

    # Equity
    print()
    print("─" * 95)
    caps = [ic] + [t["capital"] for t in trades]
    mn, mx = min(caps), max(caps)
    w = 50
    for i, c in enumerate(caps):
        bar = int((c - mn) / (mx - mn) * w) if mx > mn else w
        b = "█" * max(bar, 1)
        lb = "START" if i == 0 else f"T{i}"
        print(f"  {lb:>6} {c:>10,.2f}$ |{b}")

    print()
    print("=" * 95)
    v = "STRATÉGIE RENTABLE ✓" if ret > 0 else "STRATÉGIE EN PERTE ✗"
    print(f"  {v}")
    print(f"  {ret:+.2f}% vs BH {btc_ch:+.2f}% | Alpha {ret-btc_ch:+.2f}%")
    if ret <= 0:
        print()
        print("  ⚠ NOTE: Cette stratégie nécessite des DONNÉES RÉELLES pour être évaluée correctement.")
        print("    Les données synthétiques n'ont pas les patterns de prix/volume réalistes.")
        print("    → Importe btc_daytrading_v3.pine dans TradingView pour un vrai backtest.")
    print("=" * 95)


# ══════════════════════════════════════════════════════════════════════════════
# OPTIMISATION
# ══════════════════════════════════════════════════════════════════════════════

def optimize_v3(df):
    configs = [
        {"name": "Default"},
        {"name": "Relaxed consol (2.0x ATR)", "consol_width_atr": 2.0, "breakout_min_atr": 0.3},
        {"name": "Relaxed breakout (0.2x ATR)", "breakout_min_atr": 0.2, "consol_width_atr": 2.0},
        {"name": "Wide S/R (0.5%)", "sr_proximity_pct": 0.005, "rsi_bounce_low": 45, "rsi_bounce_high": 55},
        {"name": "No session filter", "use_session": False},
        {"name": "HTF 2H", "htf_minutes": 120, "htf_ema": 50},
        {"name": "HTF 1H", "htf_minutes": 60, "htf_ema": 50},
        {"name": "Max 5 trades/day", "max_trades_day": 5, "consol_width_atr": 2.0, "breakout_min_atr": 0.2},
        {"name": "Aggressive entry", "consol_width_atr": 2.5, "breakout_min_atr": 0.15,
         "sr_proximity_pct": 0.005, "rsi_bounce_low": 45, "rsi_bounce_high": 55,
         "use_session": False, "max_trades_day": 5},
        {"name": "TP 2/4 RR", "tp1_rr": 2.0, "tp2_rr": 4.0, "consol_width_atr": 2.0, "breakout_min_atr": 0.2},
    ]

    btc_ch = (df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0] * 100

    print("\n" + "=" * 95)
    print("  OPTIMISATION V3 — 10 configurations")
    print("=" * 95)
    print(f"\n  {'#':>2} {'Config':<35} {'Trades':>6} {'Win%':>6} {'PnL%':>8} {'PF':>6} {'MaxDD':>7} {'Alpha':>7}")
    print("  " + "─" * 85)

    results = []
    for idx, cfg in enumerate(configs, 1):
        name = cfg.pop("name")
        df_c = df.copy()
        trades, fc, ic, _ = run_backtest_v3(df_c, cfg)
        cfg["name"] = name

        ret = (fc - ic) / ic * 100
        n = len(trades)
        wins = [t for t in trades if t["pnl_usd"] > 0]
        wr = len(wins) / n * 100 if n > 0 else 0
        gp = sum(t["pnl_usd"] for t in wins) if wins else 0
        gl = abs(sum(t["pnl_usd"] for t in trades if t["pnl_usd"] <= 0))
        pf = gp / gl if gl > 0 else float("inf")

        peak = ic; mdd = 0
        for t in trades:
            if t["capital"] > peak: peak = t["capital"]
            dd = (peak - t["capital"]) / peak * 100
            if dd > mdd: mdd = dd

        alpha = ret - btc_ch

        results.append({"name": name, "return": ret, "trades": n, "wr": wr, "pf": pf,
                         "mdd": mdd, "alpha": alpha, "cfg": cfg, "fc": fc})

        pf_s = f"{pf:.2f}" if pf != float("inf") else "∞"
        print(f"  {idx:>2} {name:<35} {n:>6} {wr:>5.1f}% {ret:>+7.2f}% {pf_s:>6} {mdd:>6.2f}% {alpha:>+6.2f}%")

    # Trier par rendement
    best = max(results, key=lambda x: x["return"])
    print()
    print(f"  MEILLEURE: {best['name']} → {best['return']:+.2f}% | Alpha: {best['alpha']:+.2f}%")
    print("=" * 95)

    return best, results


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n  BTC Day Trading V3 — Structure + Multi-Timeframe\n")
    df = fetch_btc_data(interval="15m", days=8)
    print(f"  {len(df)} bougies chargées.\n")

    best, all_results = optimize_v3(df)

    print("\n  Rapport détaillé — Meilleure configuration:\n")
    df_best = df.copy()
    cfg = best["cfg"].copy()
    cfg.pop("name", None)
    trades, fc, ic, df_best = run_backtest_v3(df_best, cfg)
    print_report_v3(trades, fc, ic, df_best)
