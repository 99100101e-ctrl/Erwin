"""
Recherche de la stratégie avec le meilleur Win Rate.
Asymétrique : règles différentes pour BUY et SELL.
"""
import numpy as np
from bt_common import load_real_candles, stats, sim_E, TRADE_SIZE
from indicators import calculate_all_indicators, calculate_supertrend
from signal_engine import SignalEngine


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

        emas = ind.get("emas_1h") or {}
        e20, e50, e200 = emas.get("ema20"), emas.get("ema50"), emas.get("ema200")
        if e20 and e50 and e200:
            if   e20 > e50 > e200: ema_trend = "bull"
            elif e20 < e50 < e200: ema_trend = "bear"
            else:                  ema_trend = "sideways"
        else:
            ema_trend = "sideways"

        st = calculate_supertrend(h, l, c, period=10, factor=3.0)
        st_dir = st["direction"] if st else None

        hour = (candles[i]["ts"] % 86400) // 3600
        sigs.append({
            "idx": i, "score": sig["score"], "direction": sig["direction"],
            "price": c[-1], "atr": atr, "hour": hour,
            "ema_trend": ema_trend, "st_dir": st_dir,
        })
        if len(sigs) % 100 == 0: print(".", end="", flush=True)
    print(f" {len(sigs)} signaux")
    return sigs


def run_custom(candles, sigs, thresh=70,
               buy_hours=None, sell_hours=None,
               buy_ema=None, buy_st=None,
               sell_ema=None, sell_st=None):
    """
    Stratégie asymétrique : conditions différentes BUY vs SELL.
    buy_hours / sell_hours : set d'heures autorisées (None = toutes sauf 16-18)
    buy_ema / sell_ema : "bull" / "bear" / "sideways" / None (= pas de filtre)
    buy_st  / sell_st  : "UP" / "DOWN" / None
    """
    blocked = {16, 17, 18}
    if buy_hours  is None: buy_hours  = set(range(24)) - blocked
    if sell_hours is None: sell_hours = set(range(24)) - blocked

    trades = []; end_idx = 0; prev = 0
    for s in sigs:
        if s["idx"] < end_idx: prev = s["score"]; continue
        if not (prev < thresh <= s["score"]): prev = s["score"]; continue
        prev = s["score"]

        d = s["direction"]; h = s.get("hour", 0)
        if d == "BUY":
            if h not in buy_hours: continue
            if buy_ema is not None and s.get("ema_trend") != buy_ema: continue
            if buy_st  is not None and s.get("st_dir")   != buy_st:  continue
        else:  # SELL
            if h not in sell_hours: continue
            if sell_ema is not None and s.get("ema_trend") != sell_ema: continue
            if sell_st  is not None and s.get("st_dir")   != sell_st:  continue

        pnl, rsn, bars = sim_E(candles, s["idx"], d, s["atr"])
        if rsn == "skip": continue
        trades.append({**s, "pnl_pct": pnl*100, "pnl_eur": pnl*TRADE_SIZE,
                       "reason": rsn, "bars": bars})
        end_idx = s["idx"] + bars + 4
    return trades


def row(label, trades, best_wr, best_sh):
    s = stats(trades)
    if not s or s["n"] < 5:
        print(f"  {label:<52} |  <5   |   -    |    -    |    -")
        return best_wr, best_sh
    flags = []
    if s["wr"] > best_wr:   flags.append("WR↑"); best_wr = s["wr"]
    if s["sh"] > best_sh:   flags.append("SH↑"); best_sh = s["sh"]
    tag = " ◄ " + " ".join(flags) if flags else ""
    print(f"  {label:<52} | {s['n']:5d} | {s['wr']:5.1f}% | {s['sh']:+6.2f} | {s['net_eur']:+8.0f}€{tag}")
    return best_wr, best_sh


def main():
    print("\n" + "=" * 80)
    print("  Recherche meilleur Win Rate — stratégies asymétriques BUY/SELL")
    print("=" * 80)
    candles = load_real_candles()
    sigs    = precompute(candles)

    # HEURES BONNES pour BUY (sans 16-18h)
    GOOD_BUY_H = {0, 4, 12, 20}   # 100%, 50%, 100%, 50% WR

    print(f"\n  {'Config':<52} | {'N':>5} | {'Win%':>6} | {'Sharpe':>7} | {'Net':>9}")
    print("  " + "─" * 82)

    best_wr = 0; best_sh = -999

    # ── Références ──────────────────────────────────────────────────
    print("  ── Références ──")
    t = run_custom(candles, sigs)
    best_wr, best_sh = row("Baseline (16-18h bloqué)", t, best_wr, best_sh)

    t = run_custom(candles, sigs, sell_ema="bear")
    best_wr, best_sh = row("SELL filtré EMA=bear", t, best_wr, best_sh)

    # ── Threshold plus haut ─────────────────────────────────────────
    print("  ── Score threshold ──")
    for thr in [72, 75, 78, 80, 85]:
        t = run_custom(candles, sigs, thresh=thr)
        best_wr, best_sh = row(f"Threshold={thr} (aucun filtre direction)", t, best_wr, best_sh)

    # ── BUY : filtre heures seulement ───────────────────────────────
    print("  ── BUY heures sélectives ──")
    t = run_custom(candles, sigs, buy_hours=GOOD_BUY_H)
    best_wr, best_sh = row("BUY heures {0,4,12,20h} + SELL libre", t, best_wr, best_sh)

    t = run_custom(candles, sigs, buy_hours={0, 12})
    best_wr, best_sh = row("BUY heures {0h,12h} seulement + SELL libre", t, best_wr, best_sh)

    # ── BUY : EMA sideways + ST UP (75% WR du tableau désaccord) ───
    print("  ── BUY : EMA sideways + ST UP (contexte 75% WR) ──")
    t = run_custom(candles, sigs, buy_ema="sideways", buy_st="UP")
    best_wr, best_sh = row("BUY ema=sideways+st=UP + SELL libre", t, best_wr, best_sh)

    t = run_custom(candles, sigs, buy_ema="sideways", buy_st="UP", sell_ema="bear")
    best_wr, best_sh = row("BUY ema=sideways+st=UP + SELL ema=bear", t, best_wr, best_sh)

    t = run_custom(candles, sigs, buy_ema="sideways", buy_st="UP", sell_st="DOWN")
    best_wr, best_sh = row("BUY ema=sideways+st=UP + SELL st=DOWN", t, best_wr, best_sh)

    # ── Combos asymétriques ─────────────────────────────────────────
    print("  ── Combos asymétriques ──")
    t = run_custom(candles, sigs, buy_ema="sideways", buy_st="UP",
                   buy_hours=GOOD_BUY_H, sell_ema="bear")
    best_wr, best_sh = row("BUY sideways+UP+heures + SELL bear", t, best_wr, best_sh)

    t = run_custom(candles, sigs, buy_ema="sideways",
                   buy_hours=GOOD_BUY_H, sell_ema="bear")
    best_wr, best_sh = row("BUY sideways+heures + SELL bear", t, best_wr, best_sh)

    # SELL only (supprimer les BUY)
    print("  ── SELL only ──")
    t = run_custom(candles, sigs,
                   buy_hours=set(),          # bloque tous les BUY
                   sell_ema=None, sell_st=None)
    best_wr, best_sh = row("SELL only (aucun BUY)", t, best_wr, best_sh)

    t = run_custom(candles, sigs, buy_hours=set(), sell_ema="bear")
    best_wr, best_sh = row("SELL only + EMA=bear", t, best_wr, best_sh)

    t = run_custom(candles, sigs, buy_hours=set(), sell_st="DOWN")
    best_wr, best_sh = row("SELL only + ST=DOWN", t, best_wr, best_sh)

    t = run_custom(candles, sigs, buy_hours=set(), sell_ema="bear", sell_st="DOWN")
    best_wr, best_sh = row("SELL only + EMA=bear + ST=DOWN", t, best_wr, best_sh)

    # SELL only + threshold plus haut
    print("  ── SELL only + threshold ──")
    for thr in [72, 75, 78, 80]:
        t = run_custom(candles, sigs, thresh=thr, buy_hours=set())
        best_wr, best_sh = row(f"SELL only threshold={thr}", t, best_wr, best_sh)

    # Résumé
    print(f"\n{'=' * 80}")
    print(f"  Meilleur Win Rate atteint : {best_wr:.1f}%")
    print(f"  Meilleur Sharpe atteint   : {best_sh:+.2f}")
    print(f"{'=' * 80}")


if __name__ == "__main__":
    main()
