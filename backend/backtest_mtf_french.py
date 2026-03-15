"""
Backtest MTF (multi-timeframe) sur heures françaises uniquement.
Heures françaises : 8h-21h UTC (9h-22h CET / 10h-23h CEST)
Objectif : trouver la meilleure stratégie sans trader la nuit.
"""
import numpy as np
from bt_common import load_real_candles, stats, sim_E, TRADE_SIZE
from indicators import calculate_all_indicators, calculate_supertrend
from signal_engine import SignalEngine

# ──────────────────────────────────────────────────────────────────
# Heures autorisées (UTC)
# 8h-21h UTC = 9h-22h CET hiver = 10h-23h CEST été
# On exclut aussi 16-18h UTC (US open noise, déjà validé)
# ──────────────────────────────────────────────────────────────────
FR_HOURS = set(range(8, 22)) - {16, 17, 18}  # {8,9,10,11,12,13,14,15,19,20,21}

# ──────────────────────────────────────────────────────────────────
# Daily trend (agrégé depuis 1h)
# ──────────────────────────────────────────────────────────────────
def daily_trend(closes_1h, n_days=7):
    """Trend journalier simple : price vs SMA7 journalière."""
    if len(closes_1h) < 24 * n_days:
        return "sideways"
    # Une bougie daily = 24 bougies 1h
    daily = [np.mean(closes_1h[i:i+24]) for i in range(0, len(closes_1h) - 23, 24)]
    if len(daily) < n_days:
        return "sideways"
    sma = np.mean(daily[-n_days:])
    last = daily[-1]
    if last > sma * 1.005:   return "bull"
    elif last < sma * 0.995: return "bear"
    else:                     return "sideways"


def precompute(candles, warmup=200, step=4):
    sigs = []; errors = 0
    print("  Precompute...", end="", flush=True)
    for i in range(warmup, len(candles) - 73, step):
        w = candles[max(0, i - 249):i + 1]
        c = [x["close"] for x in w]; h = [x["high"] for x in w]
        l = [x["low"]   for x in w]; v = [x["volume"] for x in w]
        ts = [x["ts"]   for x in w]
        c4=c[::4]; h4=h[::4]; l4=l[::4]; v4=v[::4]
        if len(c4) < 15: continue
        try:
            ind = calculate_all_indicators(c, h, l, v, c4, h4, l4, v4, timestamps_1h=ts)
        except Exception:
            errors += 1; continue
        sig = SignalEngine().evaluate(ind, c[-1])
        if sig.get("score", 0) < 60: continue
        if not sig.get("stop_loss") or not sig.get("tp1"): continue
        atr = ind.get("atr_1h") or 0
        if atr <= 0: continue

        hour = (candles[i]["ts"] % 86400) // 3600

        # ── EMA 1h trend ──
        emas1 = ind.get("emas_1h") or {}
        e20, e50, e200 = emas1.get("ema20"), emas1.get("ema50"), emas1.get("ema200")
        if e20 and e50 and e200:
            if   e20 > e50 > e200: ema1_trend = "bull"
            elif e20 < e50 < e200: ema1_trend = "bear"
            else:                  ema1_trend = "sideways"
        else:
            ema1_trend = "sideways"

        # ── EMA 4h trend ──
        emas4 = ind.get("emas_4h") or {}
        e20_4, e50_4, e200_4 = emas4.get("ema20"), emas4.get("ema50"), emas4.get("ema200")
        if e20_4 and e50_4 and e200_4:
            if   e20_4 > e50_4 > e200_4: ema4_trend = "bull"
            elif e20_4 < e50_4 < e200_4: ema4_trend = "bear"
            else:                         ema4_trend = "sideways"
        elif e20_4 and e50_4:
            ema4_trend = "bull" if e20_4 > e50_4 else "bear"
        else:
            ema4_trend = "sideways"

        # ── SuperTrend 1h ──
        st1 = calculate_supertrend(h, l, c, period=10, factor=3.0)
        st1_dir = st1["direction"] if st1 else None

        # ── SuperTrend 4h ──
        st4 = calculate_supertrend(h4, l4, c4, period=10, factor=3.0)
        st4_dir = st4["direction"] if st4 else None

        # ── RSI 4h ──
        rsi4 = ind.get("rsi_4h")

        # ── ADX 4h ──
        adx4_raw = ind.get("adx_4h") or {}
        adx4 = adx4_raw.get("adx", 0) if isinstance(adx4_raw, dict) else (adx4_raw or 0)

        # ── Daily trend ──
        d_trend = daily_trend(c)

        sigs.append({
            "idx": i, "score": sig["score"], "direction": sig["direction"],
            "price": c[-1], "atr": atr, "hour": hour,
            "ema1_trend": ema1_trend, "ema4_trend": ema4_trend,
            "st1_dir": st1_dir, "st4_dir": st4_dir,
            "rsi4": rsi4, "adx4": adx4, "d_trend": d_trend,
        })
        if len(sigs) % 100 == 0: print(".", end="", flush=True)
    print(f" {len(sigs)} signaux ({errors} err)")
    return sigs


def run(candles, sigs, thresh=70,
        buy_hours=FR_HOURS, sell_hours=FR_HOURS,
        buy_ema4=None, sell_ema4=None,
        buy_st4=None,  sell_st4=None,
        buy_st1=None,  sell_st1=None,
        buy_rsi4_max=None,  sell_rsi4_min=None,
        buy_adx4_min=None,  sell_adx4_min=None,
        buy_daily=None,     sell_daily=None):
    trades = []; end_idx = 0; prev = 0
    for s in sigs:
        if s["idx"] < end_idx: prev = s["score"]; continue
        if not (prev < thresh <= s["score"]): prev = s["score"]; continue
        prev = s["score"]
        d = s["direction"]; h = s.get("hour", 0)

        if d == "BUY":
            if buy_hours is not None and h not in buy_hours: continue
            if buy_ema4     and s.get("ema4_trend") != buy_ema4: continue
            if buy_st4      and s.get("st4_dir")    != buy_st4:  continue
            if buy_st1      and s.get("st1_dir")    != buy_st1:  continue
            if buy_rsi4_max and (s.get("rsi4") or 99) > buy_rsi4_max: continue
            if buy_adx4_min and (s.get("adx4") or 0) < buy_adx4_min: continue
            if buy_daily    and s.get("d_trend")    != buy_daily: continue
        else:
            if sell_hours is not None and h not in sell_hours: continue
            if sell_ema4     and s.get("ema4_trend") != sell_ema4: continue
            if sell_st4      and s.get("st4_dir")    != sell_st4:  continue
            if sell_st1      and s.get("st1_dir")    != sell_st1:  continue
            if sell_rsi4_min and (s.get("rsi4") or 0) < sell_rsi4_min: continue
            if sell_adx4_min and (s.get("adx4") or 0) < sell_adx4_min: continue
            if sell_daily    and s.get("d_trend")    != sell_daily: continue

        pnl, rsn, bars = sim_E(candles, s["idx"], d, s["atr"])
        if rsn == "skip": continue
        trades.append({**s, "pnl_pct": pnl*100, "pnl_eur": pnl*TRADE_SIZE,
                       "reason": rsn, "bars": bars})
        end_idx = s["idx"] + bars + 4
    return trades


HDR = f"  {'Config':<55} | {'N':>5} | {'Win%':>6} | {'Sharpe':>7} | {'Net':>8}"

def row(label, trades, best_wr, best_sh):
    s = stats(trades)
    if not s or s["n"] < 5:
        print(f"  {label:<55} |  <5   |   -    |    -    |    -")
        return best_wr, best_sh
    flags = []
    if s["wr"] > best_wr: flags.append("WR↑"); best_wr = s["wr"]
    if s["sh"] > best_sh: flags.append("SH↑"); best_sh = s["sh"]
    tag = " ◄ " + " ".join(flags) if flags else ""
    print(f"  {label:<55} | {s['n']:5d} | {s['wr']:5.1f}% | {s['sh']:+6.2f} | {s['net_eur']:+7.0f}€{tag}")
    return best_wr, best_sh


def analyse_heures_fr(candles, sigs):
    """WR par heure, restreint aux heures françaises, sans filtre direction."""
    print(f"\n{'─'*72}")
    print("  Win rate par heure (heures françaises 8h-21h UTC, sans 16-18h)")
    print(f"{'─'*72}")
    t_all = run(candles, sigs, buy_hours=FR_HOURS, sell_hours=FR_HOURS)
    from collections import defaultdict
    by_h_buy  = defaultdict(list)
    by_h_sell = defaultdict(list)
    for t in t_all:
        if t["direction"] == "BUY":  by_h_buy[t["hour"]].append(t["pnl_pct"])
        else:                        by_h_sell[t["hour"]].append(t["pnl_pct"])
    print(f"\n  BUY  :")
    for h in sorted(FR_HOURS):
        g = by_h_buy.get(h, [])
        if not g: continue
        wr = sum(1 for p in g if p > 0) / len(g) * 100
        bar = ("█" if wr >= 50 else "░") * min(int(wr/10), 10)
        print(f"    {h:02d}h : {len(g):3d}t | {wr:5.1f}% WR  {bar}")
    print(f"\n  SELL :")
    for h in sorted(FR_HOURS):
        g = by_h_sell.get(h, [])
        if not g: continue
        wr = sum(1 for p in g if p > 0) / len(g) * 100
        bar = ("█" if wr >= 50 else "░") * min(int(wr/10), 10)
        print(f"    {h:02d}h : {len(g):3d}t | {wr:5.1f}% WR  {bar}")
    s = stats(t_all)
    if s:
        print(f"\n  TOTAL FR sans filtre: {s['n']}t | {s['wr']:.1f}% WR | {s['sh']:+.2f} Sharpe | {s['net_eur']:+.0f}€")


def main():
    print("\n" + "=" * 80)
    print("  MTF — Heures françaises (8h-21h UTC, sans 16-18h)")
    print("=" * 80)
    candles = load_real_candles()
    sigs    = precompute(candles)

    analyse_heures_fr(candles, sigs)

    print(f"\n{HDR}")
    print("  " + "─" * 88)
    best_wr = 0; best_sh = -999

    # ── Références ──
    print("  ── Références ──")
    t = run(candles, sigs)
    best_wr, best_sh = row("Heures FR, aucun filtre direction", t, best_wr, best_sh)

    t = run(candles, sigs, buy_hours=set(), sell_hours=FR_HOURS)
    best_wr, best_sh = row("SELL only, heures FR", t, best_wr, best_sh)

    # ── Filtres 4h EMA ──
    print("  ── MTF : EMA 4h ──")
    t = run(candles, sigs, buy_ema4="bull")
    best_wr, best_sh = row("BUY 4h EMA bull + SELL libre", t, best_wr, best_sh)

    t = run(candles, sigs, sell_ema4="bear")
    best_wr, best_sh = row("SELL 4h EMA bear + BUY libre", t, best_wr, best_sh)

    t = run(candles, sigs, buy_ema4="bull", sell_ema4="bear")
    best_wr, best_sh = row("BUY 4h bull + SELL 4h bear", t, best_wr, best_sh)

    t = run(candles, sigs, buy_ema4="sideways", sell_ema4="bear")
    best_wr, best_sh = row("BUY 4h sideways + SELL 4h bear", t, best_wr, best_sh)

    # ── Filtres SuperTrend 4h ──
    print("  ── MTF : SuperTrend 4h ──")
    t = run(candles, sigs, buy_st4="UP")
    best_wr, best_sh = row("BUY ST4=UP + SELL libre", t, best_wr, best_sh)

    t = run(candles, sigs, sell_st4="DOWN")
    best_wr, best_sh = row("SELL ST4=DOWN + BUY libre", t, best_wr, best_sh)

    t = run(candles, sigs, buy_st4="UP", sell_st4="DOWN")
    best_wr, best_sh = row("BUY ST4=UP + SELL ST4=DOWN", t, best_wr, best_sh)

    # ── Combo EMA4 + ST4 ──
    print("  ── MTF : EMA4 + ST4 combo ──")
    t = run(candles, sigs, sell_ema4="bear", sell_st4="DOWN")
    best_wr, best_sh = row("SELL 4h EMA=bear+ST=DOWN + BUY libre", t, best_wr, best_sh)

    t = run(candles, sigs, buy_ema4="bull", buy_st4="UP", sell_ema4="bear", sell_st4="DOWN")
    best_wr, best_sh = row("BUY+SELL alignés 4h EMA+ST", t, best_wr, best_sh)

    t = run(candles, sigs, buy_ema4="sideways", buy_st4="UP", sell_ema4="bear")
    best_wr, best_sh = row("BUY 4h sideways+UP + SELL 4h bear", t, best_wr, best_sh)

    # ── RSI 4h ──
    print("  ── MTF : RSI 4h ──")
    t = run(candles, sigs, buy_rsi4_max=50)
    best_wr, best_sh = row("BUY RSI4<50 + SELL libre", t, best_wr, best_sh)

    t = run(candles, sigs, sell_rsi4_min=50)
    best_wr, best_sh = row("SELL RSI4>50 + BUY libre", t, best_wr, best_sh)

    t = run(candles, sigs, buy_rsi4_max=50, sell_rsi4_min=50)
    best_wr, best_sh = row("BUY RSI4<50 + SELL RSI4>50", t, best_wr, best_sh)

    t = run(candles, sigs, buy_rsi4_max=45, sell_rsi4_min=55)
    best_wr, best_sh = row("BUY RSI4<45 + SELL RSI4>55", t, best_wr, best_sh)

    # ── ADX 4h (force de la tendance) ──
    print("  ── MTF : ADX 4h (force tendance) ──")
    t = run(candles, sigs, buy_adx4_min=20)
    best_wr, best_sh = row("BUY ADX4>20 + SELL libre", t, best_wr, best_sh)

    t = run(candles, sigs, sell_adx4_min=20)
    best_wr, best_sh = row("SELL ADX4>20 + BUY libre", t, best_wr, best_sh)

    t = run(candles, sigs, buy_adx4_min=25, sell_adx4_min=25)
    best_wr, best_sh = row("BUY+SELL ADX4>25", t, best_wr, best_sh)

    # ── Daily trend ──
    print("  ── Daily trend ──")
    t = run(candles, sigs, buy_daily="bull")
    best_wr, best_sh = row("BUY daily=bull + SELL libre", t, best_wr, best_sh)

    t = run(candles, sigs, sell_daily="bear")
    best_wr, best_sh = row("SELL daily=bear + BUY libre", t, best_wr, best_sh)

    t = run(candles, sigs, buy_daily="bull", sell_daily="bear")
    best_wr, best_sh = row("BUY daily=bull + SELL daily=bear", t, best_wr, best_sh)

    t = run(candles, sigs, buy_hours=set(), sell_daily="bear")
    best_wr, best_sh = row("SELL only + daily=bear", t, best_wr, best_sh)

    # ── Meilleures combos ──
    print("  ── Meilleures combos MTF ──")
    t = run(candles, sigs, sell_daily="bear", sell_ema4="bear")
    best_wr, best_sh = row("SELL daily=bear + EMA4=bear + BUY libre", t, best_wr, best_sh)

    t = run(candles, sigs, sell_daily="bear", sell_st4="DOWN")
    best_wr, best_sh = row("SELL daily=bear + ST4=DOWN + BUY libre", t, best_wr, best_sh)

    t = run(candles, sigs, sell_daily="bear", sell_ema4="bear", sell_st4="DOWN")
    best_wr, best_sh = row("SELL daily=bear+EMA4=bear+ST4=DOWN + BUY libre", t, best_wr, best_sh)

    t = run(candles, sigs, buy_rsi4_max=50, sell_daily="bear", sell_ema4="bear")
    best_wr, best_sh = row("BUY RSI4<50 + SELL daily=bear+EMA4=bear", t, best_wr, best_sh)

    t = run(candles, sigs, buy_adx4_min=20, sell_daily="bear", sell_ema4="bear")
    best_wr, best_sh = row("BUY ADX4>20 + SELL daily=bear+EMA4=bear", t, best_wr, best_sh)

    t = run(candles, sigs, buy_hours=set(), sell_daily="bear", sell_ema4="bear")
    best_wr, best_sh = row("SELL only + daily=bear+EMA4=bear", t, best_wr, best_sh)

    print(f"\n{'='*80}")
    print(f"  Meilleur Win Rate : {best_wr:.1f}%")
    print(f"  Meilleur Sharpe   : {best_sh:+.2f}")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
