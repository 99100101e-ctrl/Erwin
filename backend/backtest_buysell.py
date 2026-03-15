"""
Backtest BUY vs SELL — BTC Trading Advisor
Données RÉELLES : backend/data/btc_1h_real.json (6 derniers mois Binance)
"""
from bt_common import (load_real_candles, precompute, run_backtest,
                        stats, print_stats_row, TRADE_SIZE)
import numpy as np
from collections import defaultdict
from datetime import datetime, timezone


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
        print_stats_row("  TOUS",            stats(trades))
        print_stats_row("  BUY uniquement",  stats(buys))
        print_stats_row("  SELL uniquement", stats(sells))


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


def analyse_equite_mensuelle(candles, trades):
    print(f"\n{'─' * 78}")
    print("  PARTIE 4 — P&L mensuel BUY vs SELL (2000 EUR/trade)")
    print(f"{'─' * 78}")
    by_month = defaultdict(lambda: {"BUY": [], "SELL": []})
    for t in trades:
        dt = datetime.fromtimestamp(candles[t["idx"]]["ts"], tz=timezone.utc)
        mk = (dt.year, dt.month)
        by_month[mk][t["direction"]].append(t["pnl_eur"])

    print(f"\n  {'Mois':>8} | {'BUY EUR':>10} | {'SELL EUR':>10} | {'TOTAL EUR':>11} | Bar")
    print("  " + "─" * 65)
    cumul = 0
    for mk in sorted(by_month.keys()):
        d = by_month[mk]
        buy_net  = sum(d["BUY"])  if d["BUY"]  else 0
        sell_net = sum(d["SELL"]) if d["SELL"] else 0
        total    = buy_net + sell_net
        cumul   += total
        label = datetime(mk[0], mk[1], 1).strftime("%b %Y")
        bar = ("█" if total > 0 else "░") * min(int(abs(total) / 25), 25)
        print(f"  {label:>8} | {buy_net:+10.0f} | {sell_net:+10.0f} | {total:+11.0f} | {bar}")
    print(f"  {'─' * 55}")
    print(f"  {'TOTAL':>8} | {sum(t['pnl_eur'] for t in trades if t['direction']=='BUY'):+10.0f}"
          f" | {sum(t['pnl_eur'] for t in trades if t['direction']=='SELL'):+10.0f}"
          f" | {cumul:+11.0f} |")


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
            print("     Envisager un filtre : BUY uniquement en tendance Bullish (EMA20>EMA50>EMA200).")
        elif sb["net_eur"] > ss["net_eur"] * 1.3:
            print("  -> Les signaux BUY sont nettement plus profitables sur cette periode.")
            print("     Envisager un filtre : SELL uniquement en tendance Bearish (EMA20<EMA50<EMA200).")
        else:
            print("  -> BUY et SELL sont equilibres. La strategie est bidirectionnelle saine.")
        print(f"\n  BUY  : {sb['n']} trades | {sb['wr']:.1f}% win | {sb['net_eur']:+.0f} EUR net")
        print(f"  SELL : {ss['n']} trades | {ss['wr']:.1f}% win | {ss['net_eur']:+.0f} EUR net")
    print(f"{'=' * 78}\n")


def run():
    print("\n" + "=" * 78)
    print("  BACKTEST BUY vs SELL — BTC Trading Advisor — DONNÉES RÉELLES BINANCE")
    print("=" * 78)

    candles = load_real_candles()
    print("\n  Precompute signaux...")
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
