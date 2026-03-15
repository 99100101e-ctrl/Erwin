"""
Backtest BUY vs SELL — BTC Trading Advisor
Analyse separee des signaux haussiers et baissiers.
Questions cles :
  - Le moteur detecte-t-il mieux les hausses ou les baisses ?
  - Faut-il filtrer une direction en certaines conditions ?
  - Le score est-il predictif differemment selon la direction ?
"""
from bt_common import (generate_btc_1an, precompute, run_backtest,
                        stats, print_stats_row, TRADE_SIZE)
import numpy as np
from collections import defaultdict


# ─────────────────────────────────────────────────────────────────────────────
# Analyse BUY vs SELL par seuil
# ─────────────────────────────────────────────────────────────────────────────

def analyse_par_seuil(candles, sigs):
    print(f"\n{'─' * 78}")
    print("  PARTIE 1 — BUY vs SELL par seuil d'entree")
    print(f"{'─' * 78}")
    col = f"{'Groupe':<22} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'MaxDD':>7} | {'Sharpe':>7} | {'Net EUR':>10} | {'SL%':>5}"
    for thresh in [70, 80]:
        trades = run_backtest(candles, sigs, thresh)
        if not trades:
            continue
        buys  = [t for t in trades if t["direction"] == "BUY"]
        sells = [t for t in trades if t["direction"] == "SELL"]
        print(f"\n  Seuil >= {thresh} — {len(trades)} trades total")
        print(f"  {col}")
        print("  " + "─" * 78)
        print_stats_row(f"  TOUS",              stats(trades))
        print_stats_row(f"  BUY uniquement",    stats(buys))
        print_stats_row(f"  SELL uniquement",   stats(sells))


# ─────────────────────────────────────────────────────────────────────────────
# Distribution des outcomes BUY vs SELL
# ─────────────────────────────────────────────────────────────────────────────

def analyse_outcomes(trades):
    print(f"\n{'─' * 78}")
    print("  PARTIE 2 — Distribution des resultats par direction (seuil >= 70)")
    print(f"{'─' * 78}")
    for direction in ["BUY", "SELL"]:
        group = [t for t in trades if t["direction"] == direction]
        if len(group) < 3:
            continue
        reasons = defaultdict(int)
        for t in group:
            reasons[t["reason"]] += 1
        total = len(group)
        s = stats(group)
        print(f"\n  {direction} ({total} trades) :")
        print(f"    Win rate     : {s['wr']:.1f}%")
        print(f"    Gain moyen   : {s['avg_win']:+.2f}%  |  Perte moyenne : {s['avg_loss']:+.2f}%")
        print(f"    Serie pertes : {s['max_streak']} consecutives max")
        print(f"    Duree moy.   : {s['avg_bars']:.0f}h")
        print(f"    Resultats    :", end="")
        for reason, cnt in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"  {reason}={cnt} ({cnt/total*100:.0f}%)", end="")
        print()


# ─────────────────────────────────────────────────────────────────────────────
# Score vs Win Rate par direction
# ─────────────────────────────────────────────────────────────────────────────

def analyse_score_direction(trades):
    print(f"\n{'─' * 78}")
    print("  PARTIE 3 — Score signal vs Win Rate reel par direction")
    print(f"{'─' * 78}")
    bands = [(60, 74), (75, 84), (85, 100)]
    for direction in ["BUY", "SELL"]:
        print(f"\n  {direction} :")
        print(f"  {'Score':^12} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'Net EUR':>10}")
        print("  " + "─" * 50)
        for lo, hi in bands:
            group = [t for t in trades if t["direction"] == direction and lo <= t["score"] <= hi]
            if not group:
                print(f"  {lo:3d}-{hi:3d}      |   0   |   -    |    -     |    -")
                continue
            s = stats(group)
            if s:
                print(f"  {lo:3d}-{hi:3d}      | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% | {s['net_eur']:+9.0f} EUR")


# ─────────────────────────────────────────────────────────────────────────────
# Courbe d'equite BUY vs SELL dans le temps
# ─────────────────────────────────────────────────────────────────────────────

def analyse_equite_mensuelle(candles, trades):
    print(f"\n{'─' * 78}")
    print("  PARTIE 4 — P&L mensuel BUY vs SELL (2000 EUR/trade)")
    print(f"{'─' * 78}")
    months = ["Jan", "Fev", "Mar", "Avr", "Mai", "Jun",
              "Jul", "Aou", "Sep", "Oct", "Nov", "Dec"]
    by_month = defaultdict(lambda: {"BUY": [], "SELL": []})
    for t in trades:
        m = (candles[t["idx"]]["ts"] - 1704067200) // (30 * 24 * 3600)
        by_month[m][t["direction"]].append(t["pnl_eur"])

    print(f"\n  {'Mois':>5} | {'BUY EUR':>10} | {'SELL EUR':>10} | {'TOTAL EUR':>11} | Bar")
    print("  " + "─" * 65)
    cumul = 0
    for m in sorted(by_month.keys()):
        d = by_month[m]
        buy_net  = sum(d["BUY"])  if d["BUY"]  else 0
        sell_net = sum(d["SELL"]) if d["SELL"] else 0
        total    = buy_net + sell_net
        cumul   += total
        label = months[m % 12] if m < 12 else f"M{m+1}"
        bar = ("█" if total > 0 else "░") * min(int(abs(total) / 25), 25)
        print(f"  {label:>5} | {buy_net:+10.0f} | {sell_net:+10.0f} | {total:+11.0f} | {bar}")
    print(f"  {'─' * 55}")
    print(f"  {'TOTAL':>5} | {sum(t['pnl_eur'] for t in trades if t['direction']=='BUY'):+10.0f}"
          f" | {sum(t['pnl_eur'] for t in trades if t['direction']=='SELL'):+10.0f}"
          f" | {cumul:+11.0f} |")


# ─────────────────────────────────────────────────────────────────────────────
# Recommandation
# ─────────────────────────────────────────────────────────────────────────────

def recommandation(trades):
    buys  = [t for t in trades if t["direction"] == "BUY"]
    sells = [t for t in trades if t["direction"] == "SELL"]
    sb = stats(buys); ss = stats(sells)
    print(f"\n{'=' * 78}")
    print("  RECOMMANDATION")
    print(f"{'=' * 78}")
    if sb and ss:
        if ss["net_eur"] > sb["net_eur"] * 1.3:
            print("  -> Les signaux SELL sont nettement plus profitables sur cette periode.")
            print("     Envisager un filtre : ne prendre les BUY qu'en tendance Bullish confirmee (EMA20>EMA50>EMA200).")
        elif sb["net_eur"] > ss["net_eur"] * 1.3:
            print("  -> Les signaux BUY sont nettement plus profitables sur cette periode.")
            print("     Envisager un filtre : ne prendre les SELL qu'en tendance Bearish confirmee (EMA20<EMA50<EMA200).")
        else:
            print("  -> BUY et SELL sont equilibres. La strategie est bidirectionnelle saine.")
        print(f"\n  BUY  : {sb['n']} trades | {sb['wr']:.1f}% win | {sb['net_eur']:+.0f} EUR net")
        print(f"  SELL : {ss['n']} trades | {ss['wr']:.1f}% win | {ss['net_eur']:+.0f} EUR net")
    print(f"{'=' * 78}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def run():
    print("\n" + "=" * 78)
    print("  BACKTEST BUY vs SELL — BTC Trading Advisor — 1 an — 2000 EUR/trade")
    print("=" * 78)

    candles = generate_btc_1an()
    p0 = candles[200]["close"]; p1 = candles[-1]["close"]
    print(f"\n  BTC simule : ${p0:,.0f} -> ${p1:,.0f}  ({(p1/p0-1)*100:+.1f}%)\n")

    print("  Precompute signaux...")
    sigs = precompute(candles)
    if not sigs:
        print("  Aucun signal. Abandon."); return

    trades_70 = run_backtest(candles, sigs, thresh=70)

    analyse_par_seuil(candles, sigs)
    analyse_outcomes(trades_70)
    analyse_score_direction(trades_70)
    analyse_equite_mensuelle(candles, trades_70)
    recommandation(trades_70)


if __name__ == "__main__":
    run()
