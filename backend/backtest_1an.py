"""
Backtest 6 MOIS — BTC Trading Advisor — Strategie E
Données RÉELLES : backend/data/btc_1h_real.json (6 derniers mois Binance)

- 2000 EUR par trade
- Seuils 60 / 70 / 80 / 90
- Analyse BUY vs SELL, tendances EMA, heures, score vs win rate
"""
import numpy as np
from collections import defaultdict
from datetime import datetime, timezone
from bt_common import (load_real_candles, precompute, sim_E,
                        stats, TRADE_SIZE)


def bt_threshold(candles, sigs, thresh):
    trades = []; end_idx = 0; prev = 0
    for s in sigs:
        if s["idx"] < end_idx:
            prev = s["score"]; continue
        crossed = (prev < thresh <= s["score"]); prev = s["score"]
        if not crossed:
            continue
        pnl, rsn, bars = sim_E(candles, s["idx"], s["direction"], s["atr"])
        if rsn == "skip":
            continue
        trades.append({**s, "pnl_pct": pnl * 100, "pnl_eur": pnl * TRADE_SIZE, "reason": rsn, "bars": bars})
        end_idx = s["idx"] + bars + 4
    return trades


def analyse_direction(trades):
    buys = [t for t in trades if t["direction"] == "BUY"]
    sells = [t for t in trades if t["direction"] == "SELL"]
    print(f"\n{'─' * 70}")
    print("  ANALYSE : BUY vs SELL")
    print(f"{'─' * 70}")
    print(f"{'Direction':<10} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'Net EUR':>10}")
    print("─" * 50)
    for label, group in [("BUY", buys), ("SELL", sells)]:
        if not group:
            print(f"  {label:<8} |   0   |   -    |    -     |    -")
            continue
        s = stats(group)
        if s:
            print(f"  {label:<8} | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% | {s['net_eur']:+9.0f} EUR")


def analyse_tendance(trades):
    print(f"\n{'─' * 70}")
    print("  ANALYSE : Performance par tendance EMA (bull/bear/sideways)")
    print(f"{'─' * 70}")
    print(f"{'Tendance':<12} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'Net EUR':>10}")
    print("─" * 55)
    for trend in ["bull", "sideways", "bear"]:
        group = [t for t in trades if t.get("trend") == trend]
        if not group:
            print(f"  {trend:<10} |   0   |   -    |    -     |    -")
            continue
        s = stats(group)
        if s:
            flag = " <- attention" if s["wr"] < 40 else (" <- optimal" if s["wr"] > 60 else "")
            print(f"  {trend:<10} | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% | {s['net_eur']:+9.0f} EUR{flag}")


def analyse_score_quality(trades):
    print(f"\n{'─' * 70}")
    print("  ANALYSE : Score du signal vs taux de reussite reel")
    print(f"{'─' * 70}")
    bands = [(60, 69), (70, 79), (80, 89), (90, 100)]
    print(f"  {'Score':^10} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'Net EUR':>10}")
    print("  " + "─" * 52)
    for lo, hi in bands:
        group = [t for t in trades if lo <= t["score"] <= hi]
        if not group:
            print(f"  {lo:3d}-{hi:3d}    |   0   |   -    |    -     |    -")
            continue
        s = stats(group)
        if s:
            print(f"  {lo:3d}-{hi:3d}    | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% | {s['net_eur']:+9.0f} EUR")


def analyse_hours(trades):
    print(f"\n{'─' * 70}")
    print("  ANALYSE : Performance par heure UTC (top 6 et flop 6)")
    print(f"{'─' * 70}")
    by_hour = defaultdict(list)
    for t in trades:
        by_hour[t.get("hour", 0)].append(t)
    hour_stats = {}
    for h, group in by_hour.items():
        if len(group) >= 3:
            s = stats(group)
            if s:
                hour_stats[h] = s
    if not hour_stats:
        print("  Pas assez de donnees par heure.")
        return
    sorted_hours = sorted(hour_stats.items(), key=lambda x: x[1]["net_eur"], reverse=True)
    print(f"\n  Meilleures heures :")
    print(f"  {'Heure':>6} | {'N':>4} | {'Win%':>6} | {'Net EUR':>10}")
    print("  " + "─" * 35)
    for h, s in sorted_hours[:6]:
        print(f"  {h:02d}h UTC | {s['n']:4d} | {s['wr']:5.1f}% | {s['net_eur']:+9.0f} EUR")
    print(f"\n  Pires heures :")
    for h, s in sorted_hours[-6:]:
        print(f"  {h:02d}h UTC | {s['n']:4d} | {s['wr']:5.1f}% | {s['net_eur']:+9.0f} EUR")


def analyse_monthly(candles, trades):
    print(f"\n{'─' * 70}")
    print(f"  ANALYSE : P&L mensuel ({TRADE_SIZE} EUR/trade)")
    print(f"{'─' * 70}")
    by_month = defaultdict(list)
    for t in trades:
        dt = datetime.fromtimestamp(candles[t["idx"]]["ts"], tz=timezone.utc)
        mk = (dt.year, dt.month)
        by_month[mk].append(t)

    print(f"\n  {'Mois':>8} | {'N':>4} | {'Win%':>6} | {'Net EUR':>10} | Barre")
    print("  " + "─" * 55)
    cumul = 0
    for mk in sorted(by_month.keys()):
        group = by_month[mk]
        net = sum(t["pnl_eur"] for t in group)
        cumul += net
        wr = sum(1 for t in group if t["pnl_pct"] > 0) / len(group) * 100
        bar = ("█" if net > 0 else "░") * min(int(abs(net) / 20), 30)
        label = datetime(mk[0], mk[1], 1).strftime("%b %Y")
        print(f"  {label:>8} | {len(group):4d} | {wr:5.1f}% | {net:+9.0f} EUR | {bar}")
    print(f"  {'─' * 40}")
    print(f"  {'TOTAL':>8} | {len(trades):4d} |       | {cumul:+9.0f} EUR |")


def run():
    print("\n" + "=" * 70)
    print("  BACKTEST 6 MOIS — BTC Trading Advisor — DONNÉES RÉELLES BINANCE")
    print(f"  Capital par trade : {TRADE_SIZE} EUR — Strategie E (TP1=1.0xR + Breakeven)")
    print("=" * 70 + "\n")

    candles = load_real_candles()

    print("\n  Precompute des signaux...")
    sigs = precompute(candles, warmup=200, step=4)

    if not sigs:
        print("\n  ERREUR: aucun signal genere. Verifiez le signal_engine.")
        return

    # ── Tableau principal : seuils ────────────────────────────────────────────
    print(f"\n{'─' * 70}")
    print("  RESULTATS — Strategie E par seuil d'entree")
    print(f"{'─' * 70}\n")
    print(f"  {'Seuil':>7} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'MaxDD':>7} | {'Sharpe':>7} | {'Net EUR':>11} | {'SL%':>5}")
    print("  " + "─" * 72)

    thresholds = [60, 70, 80, 90]
    all_trades = {}
    best_thresh = 70
    best_score = -999

    for t in thresholds:
        trades = bt_threshold(candles, sigs, t)
        all_trades[t] = trades
        s = stats(trades)
        if not s:
            print(f"  >= {t:3d}  |  <3   |   -    |    -     |    -    |    -    |    -        |   -")
            continue
        sc = s["sh"] * (1 if s["wr"] > 45 else .5) / max(s["mdd"], .05)
        flag = "  <- OPTIMAL" if sc > best_score and s["n"] >= 5 else ""
        if sc > best_score and s["n"] >= 5:
            best_score = sc; best_thresh = t
        print(f"  >= {t:3d}  | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% | -{s['mdd'] * 100:4.1f}% | {s['sh']:+6.2f} | {s['net_eur']:+10.0f} EUR | {s['sl_pct']:4.0f}%{flag}")

    print(f"\n  SL = 1.8xATR | TP1 = 1.0xR (+BE) | TP2 = 2.5xR | TP3 = 5.0xR | max 72h/trade")

    # ── Detail du seuil optimal ───────────────────────────────────────────────
    best_trades = all_trades.get(best_thresh, [])
    s = stats(best_trades)
    if s:
        print(f"\n{'═' * 70}")
        print(f"  DETAIL — Seuil >= {best_thresh} (meilleur compromis)")
        print(f"{'═' * 70}")
        print(f"  Nb trades           : {s['n']}")
        print(f"  Win rate            : {s['wr']:.1f}%")
        print(f"  P&L moyen / trade   : {s['avg']:+.2f}%  ({s['avg_eur']:+.0f} EUR)")
        print(f"  P&L median / trade  : {s['med']:+.2f}%")
        print(f"  Meilleur trade      : {s['best_eur']:+.0f} EUR")
        print(f"  Pire trade          : {s['worst_eur']:+.0f} EUR")
        print(f"  Max Drawdown        : -{s['mdd'] * 100:.1f}%")
        print(f"  Sharpe              : {s['sh']:+.2f}")
        print(f"  Duree moy. trade    : {s['avg_bars']:.0f}h")
        print(f"  Stop loss touches   : {s['sl_pct']:.0f}%")
        print(f"  Breakeven touches   : {s['be_pct']:.0f}%")
        print(f"  TP3 complet         : {s['tp3_pct']:.0f}%")
        print(f"  Net P&L total       : {s['net_eur']:+.0f} EUR  (sur {TRADE_SIZE} EUR/trade)")

    if best_trades:
        analyse_direction(best_trades)
        analyse_tendance(best_trades)
        analyse_score_quality(best_trades)
        analyse_hours(best_trades)
        analyse_monthly(candles, best_trades)

    print(f"\n{'=' * 70}")
    print(f"  RESUME — Seuil recommande : >= {best_thresh}")
    print(f"  Capital requis suggere    : {TRADE_SIZE} EUR x 3 trades simultanes max = {TRADE_SIZE * 3} EUR")
    print(f"  Strategie                 : E (TP1=1.0xR + Breakeven immediat)")
    print(f"  Données                   : RÉELLES — Binance BTCUSDT 1h")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    run()
