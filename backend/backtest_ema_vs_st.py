"""
Backtest comparatif : EMA20>50>200 vs SuperTrend vs les deux
Question : quel filtre de direction est le plus utile, et faut-il les combiner ?
"""
import numpy as np
from collections import defaultdict
from bt_common import load_real_candles, stats, sim_E, TRADE_SIZE
from indicators import calculate_all_indicators, calculate_supertrend
from signal_engine import SignalEngine


def precompute(candles, warmup=200, step=4):
    sigs = []; errors = 0
    print(f"  Precompute...", end="", flush=True)
    _cur_trend = "sideways"; _trend_since_i = warmup

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

        # EMA trend
        emas = ind.get("emas_1h") or {}
        e20, e50, e200 = emas.get("ema20"), emas.get("ema50"), emas.get("ema200")
        if e20 and e50 and e200:
            if e20 > e50 > e200:   ema_trend = "bull"
            elif e20 < e50 < e200: ema_trend = "bear"
            else:                  ema_trend = "sideways"
        else:
            ema_trend = "sideways"

        if ema_trend != _cur_trend:
            _cur_trend = ema_trend; _trend_since_i = i

        # SuperTrend(10, 3.0)
        st = calculate_supertrend(h, l, c, period=10, factor=3.0)
        st_dir = st["direction"] if st else None

        hour = (candles[i]["ts"] % 86400) // 3600
        sigs.append({
            "idx": i, "score": sig["score"], "direction": sig["direction"],
            "price": c[-1], "atr": atr, "hour": hour,
            "ema_trend": ema_trend, "st_dir": st_dir,
            "ts": candles[i]["ts"],
        })
        if len(sigs) % 100 == 0: print(".", end="", flush=True)
    print(f" {len(sigs)} signaux ({errors} erreurs)")
    return sigs


def run(candles, sigs, thresh=70,
        ema_buy=False, ema_sell=False,
        st_buy=False,  st_sell=False,
        block_us=True):
    trades = []; end_idx = 0; prev = 0
    for s in sigs:
        if s["idx"] < end_idx:
            prev = s["score"]; continue
        if not (prev < thresh <= s["score"]):
            prev = s["score"]; continue
        prev = s["score"]

        d = s["direction"]; h = s.get("hour", 0)
        if block_us and 16 <= h <= 18:
            continue

        if ema_buy  and d == "BUY"  and s.get("ema_trend") != "bull": continue
        if ema_sell and d == "SELL" and s.get("ema_trend") != "bear": continue
        if st_buy   and d == "BUY"  and s.get("st_dir")   != "UP":   continue
        if st_sell  and d == "SELL" and s.get("st_dir")   != "DOWN":  continue

        pnl, rsn, bars = sim_E(candles, s["idx"], d, s["atr"])
        if rsn == "skip": continue
        trades.append({**s, "pnl_pct": pnl*100, "pnl_eur": pnl*TRADE_SIZE,
                       "reason": rsn, "bars": bars})
        end_idx = s["idx"] + bars + 4
    return trades


def row(label, trades, best_sh):
    s = stats(trades)
    if not s:
        print(f"  {label:<42} |  <3   |   -    |    -    |    -       |   -")
        return best_sh
    flag = " ◄ BEST" if s["sh"] > best_sh and s["n"] >= 5 else ""
    print(f"  {label:<42} | {s['n']:5d} | {s['wr']:5.1f}% | {s['sh']:+6.2f} | {s['net_eur']:+9.0f} EUR | {s['sl_pct']:4.0f}%{flag}")
    if s["sh"] > best_sh and s["n"] >= 5:
        return s["sh"]
    return best_sh


def detail_direction(label, trades):
    buys  = [t for t in trades if t["direction"] == "BUY"]
    sells = [t for t in trades if t["direction"] == "SELL"]
    print(f"\n  ── {label} ──")
    print(f"  {'':8} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'Net EUR':>10} | {'SL%':>5}")
    print("  " + "─" * 52)
    for lbl, g in [("TOUS", trades), ("BUY", buys), ("SELL", sells)]:
        s = stats(g)
        if s:
            print(f"  {lbl:<8} | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% | {s['net_eur']:+9.0f} EUR | {s['sl_pct']:4.0f}%")
        else:
            print(f"  {lbl:<8} |  <3   |   -    |    -     |    -       |   -")


def signal_quality(candles, sigs):
    """Qualité brute des signaux par direction, sans aucun filtre."""
    print(f"\n{'─' * 72}")
    print("  QUALITÉ BRUTE DES SIGNAUX (aucun filtre, y compris heures)")
    print(f"{'─' * 72}")
    all_t = run(candles, sigs, ema_buy=False, ema_sell=False,
                st_buy=False, st_sell=False, block_us=False)
    buys  = [t for t in all_t if t["direction"] == "BUY"]
    sells = [t for t in all_t if t["direction"] == "SELL"]

    print(f"\n  Sans aucun filtre :")
    for lbl, g in [("TOUS", all_t), ("BUY", buys), ("SELL", sells)]:
        s = stats(g)
        if s:
            print(f"    {lbl:<6}: {s['n']:3d} trades | {s['wr']:5.1f}% WR | {s['net_eur']:+7.0f} EUR "
                  f"| Sharpe {s['sh']:+.2f} | MaxDD -{s['mdd']*100:.1f}%")

    # Qualité par heure pour chaque direction
    print(f"\n  Win rate BUY par heure :")
    by_h_buy = defaultdict(list)
    for t in buys: by_h_buy[t.get("hour", 0)].append(t["pnl_pct"])
    for h in sorted(by_h_buy.keys()):
        g = by_h_buy[h]; wr = sum(1 for p in g if p > 0) / len(g) * 100
        bar = ("█" if wr >= 50 else "░") * min(int(wr/10), 10)
        print(f"    {h:02d}h : {len(g):3d}t | {wr:5.1f}% WR  {bar}")

    print(f"\n  Win rate SELL par heure :")
    by_h_sell = defaultdict(list)
    for t in sells: by_h_sell[t.get("hour", 0)].append(t["pnl_pct"])
    for h in sorted(by_h_sell.keys()):
        g = by_h_sell[h]; wr = sum(1 for p in g if p > 0) / len(g) * 100
        bar = ("█" if wr >= 50 else "░") * min(int(wr/10), 10)
        print(f"    {h:02d}h : {len(g):3d}t | {wr:5.1f}% WR  {bar}")


def matrice_filtres(candles, sigs):
    print(f"\n{'─' * 80}")
    print("  MATRICE : EMA vs SuperTrend vs Combo (filtre US open actif dans tous les cas)")
    print(f"{'─' * 80}")
    print(f"\n  {'Config':<42} | {'N':>5} | {'Win%':>6} | {'Sharpe':>7} | {'Net EUR':>10} | {'SL%':>5}")
    print("  " + "─" * 82)

    best = -999
    configs = [
        # label,                              ema_b, ema_s, st_b, st_s
        ("Aucun filtre direction",             False, False, False, False),
        ("─── BUY filtré ─────────────────",  None,  None,  None,  None),
        ("EMA BUY-only (EMA20>50>200)",        True,  False, False, False),
        ("ST  BUY-only (ST=UP)",               False, False, True,  False),
        ("EMA+ST BUY-only (les deux)",         True,  False, True,  False),
        ("─── SELL filtré ────────────────",   None,  None,  None,  None),
        ("EMA SELL-only (EMA20<50<200)",        False, True,  False, False),
        ("ST  SELL-only (ST=DOWN)",             False, False, False, True),
        ("EMA+ST SELL-only",                    False, True,  False, True),
        ("─── BUY+SELL filtrés ───────────",   None,  None,  None,  None),
        ("EMA BUY+SELL alignés",                True,  True,  False, False),
        ("ST  BUY+SELL alignés",                False, False, True,  True),
        ("EMA+ST BUY+SELL alignés",             True,  True,  True,  True),
    ]

    for label, eb, es, sb, ss in configs:
        if eb is None:
            print(f"  {label}")
            continue
        t = run(candles, sigs, ema_buy=eb, ema_sell=es, st_buy=sb, st_sell=ss)
        best = row(label, t, best)
    return best


def analyse_desaccord(candles, sigs):
    """Que se passe-t-il quand EMA et SuperTrend sont en désaccord ?"""
    print(f"\n{'─' * 72}")
    print("  DÉSACCORD EMA vs SuperTrend : que vaut chaque signal ?")
    print(f"{'─' * 72}")

    groups = {
        "EMA bull + ST UP   (accord haussier)":  lambda s: s["ema_trend"]=="bull" and s["st_dir"]=="UP",
        "EMA bull + ST DOWN (désaccord)":         lambda s: s["ema_trend"]=="bull" and s["st_dir"]=="DOWN",
        "EMA bear + ST DOWN (accord baissier)":   lambda s: s["ema_trend"]=="bear" and s["st_dir"]=="DOWN",
        "EMA bear + ST UP   (désaccord)":         lambda s: s["ema_trend"]=="bear" and s["st_dir"]=="UP",
        "EMA sideways + ST UP":                   lambda s: s["ema_trend"]=="sideways" and s["st_dir"]=="UP",
        "EMA sideways + ST DOWN":                 lambda s: s["ema_trend"]=="sideways" and s["st_dir"]=="DOWN",
    }

    print(f"\n  {'Contexte':<40} | {'N':>5} | {'Win%':>6} | {'Net EUR':>10} | {'SL%':>5}")
    print("  " + "─" * 70)
    for label, filt in groups.items():
        filtered = [s for s in sigs if filt(s) and not (16 <= s.get("hour",0) <= 18)]
        trades = []
        end_idx = 0; prev = 0
        for s in filtered:
            if s["idx"] < end_idx: prev = s["score"]; continue
            if not (prev < 70 <= s["score"]): prev = s["score"]; continue
            prev = s["score"]
            pnl, rsn, bars = sim_E(candles, s["idx"], s["direction"], s["atr"])
            if rsn == "skip": continue
            trades.append({**s, "pnl_pct": pnl*100, "pnl_eur": pnl*TRADE_SIZE,
                           "reason": rsn, "bars": bars})
            end_idx = s["idx"] + bars + 4
        s_stat = stats(trades)
        if s_stat:
            print(f"  {label:<40} | {s_stat['n']:5d} | {s_stat['wr']:5.1f}% | {s_stat['net_eur']:+9.0f} EUR | {s_stat['sl_pct']:4.0f}%")
        else:
            print(f"  {label:<40} |  <3   |   -    |    -       |   -")


def main():
    print("\n" + "=" * 80)
    print("  EMA vs SuperTrend — Quel filtre retenir ?")
    print("  Données réelles Binance, Sep 2025 → Mar 2026")
    print("=" * 80)

    candles = load_real_candles()
    sigs = precompute(candles)

    signal_quality(candles, sigs)
    matrice_filtres(candles, sigs)
    analyse_desaccord(candles, sigs)

    # Résumé
    print(f"\n{'=' * 80}")
    print("  VERDICT")
    print(f"{'=' * 80}")
    best = run(candles, sigs, ema_buy=False, ema_sell=False, st_buy=False, st_sell=False)
    ema  = run(candles, sigs, ema_buy=True,  ema_sell=False, st_buy=False, st_sell=False)
    st   = run(candles, sigs, ema_buy=False, ema_sell=False, st_buy=True,  st_sell=False)
    both = run(candles, sigs, ema_buy=True,  ema_sell=False, st_buy=True,  st_sell=False)
    for lbl, t in [("Baseline (aucun filtre)", best), ("EMA seul", ema),
                   ("SuperTrend seul", st), ("EMA + SuperTrend", both)]:
        s = stats(t)
        if s:
            print(f"  {lbl:<28}: {s['n']:3d}t | {s['wr']:5.1f}% WR | {s['sh']:+.2f} Sharpe | {s['net_eur']:+.0f} EUR")
    print()


if __name__ == "__main__":
    main()
