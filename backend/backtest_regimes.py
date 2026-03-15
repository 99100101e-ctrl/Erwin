"""
Backtest Regimes de Marche — BTC Trading Advisor
Données RÉELLES : backend/data/btc_1h_real.json (6 derniers mois Binance)

Regime = tendance EMA calculée en temps réel (bull/bear/sideways)
  Bull     : EMA20 > EMA50 > EMA200
  Bear     : EMA20 < EMA50 < EMA200
  Sideways : autrement
"""
from bt_common import (load_real_candles, precompute, run_backtest,
                        stats, print_stats_row, TRADE_SIZE)
import numpy as np
from collections import defaultdict
from datetime import datetime, timezone


REGIMES = ["bull", "sideways", "bear"]
REGIME_LABELS = {"bull": "Bull  (EMA hausse)", "sideways": "Sideways (EMA neutre)", "bear": "Bear  (EMA baisse)"}


def repartition_regimes(sigs):
    counts = defaultdict(int)
    for s in sigs:
        counts[s.get("trend", "unknown")] += 1
    total = len(sigs)
    print(f"\n{'─' * 70}")
    print("  Repartition des signaux bruts par regime EMA")
    print(f"{'─' * 70}")
    for r in REGIMES:
        n = counts[r]; pct = n / total * 100 if total else 0
        bar = "█" * int(pct / 2)
        print(f"  {REGIME_LABELS[r]:<24} : {n:5d} signaux ({pct:4.1f}%) {bar}")


def analyse_par_regime(candles, sigs):
    print(f"\n{'─' * 78}")
    print("  PARTIE 1 — Performance globale par regime EMA (seuil >= 70)")
    print(f"{'─' * 78}")
    trades = run_backtest(candles, sigs, thresh=70)
    if not trades:
        print("  Aucun trade."); return trades

    col = f"  {'Regime':<24} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'MaxDD':>7} | {'Sharpe':>7} | {'Net EUR':>10} | {'SL%':>5}"
    print(f"\n{col}")
    print("  " + "─" * 80)
    print_stats_row("TOTAL", stats(trades))
    for r in REGIMES:
        # Utiliser "trend" (calculé depuis EMA) au lieu de "regime" (synthétique)
        group = [t for t in trades if t.get("trend") == r]
        print_stats_row(REGIME_LABELS[r], stats(group))
    return trades


def analyse_direction_par_regime(trades):
    print(f"\n{'─' * 78}")
    print("  PARTIE 2 — BUY vs SELL dans chaque regime EMA")
    print(f"{'─' * 78}")
    for r in REGIMES:
        regime_trades = [t for t in trades if t.get("trend") == r]
        if len(regime_trades) < 3:
            continue
        buys  = [t for t in regime_trades if t["direction"] == "BUY"]
        sells = [t for t in regime_trades if t["direction"] == "SELL"]
        sb = stats(buys); ss = stats(sells)
        print(f"\n  {REGIME_LABELS[r].upper()} ({len(regime_trades)} trades) :")
        print(f"  {'Direction':<12} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'Net EUR':>10} | {'SL%':>5}")
        print("  " + "─" * 55)
        for label, s in [("BUY", sb), ("SELL", ss)]:
            if s:
                print(f"  {label:<12} | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% | {s['net_eur']:+9.0f} EUR | {s['sl_pct']:4.0f}%")
            else:
                print(f"  {label:<12} |   0   |   -    |    -     |    -       |   -")


def analyse_strategies_filtrees(candles, sigs):
    print(f"\n{'─' * 78}")
    print("  PARTIE 3 — Comparaison : tout trader vs filtrer par regime EMA")
    print(f"{'─' * 78}")
    trades_all = run_backtest(candles, sigs, thresh=70)

    trades_filtre = [t for t in trades_all
                     if (t["direction"] == "BUY"  and t.get("trend") in ("bull", "sideways"))
                     or (t["direction"] == "SELL" and t.get("trend") in ("bear", "sideways"))]

    trades_sideways = [t for t in trades_all if t.get("trend") == "sideways"]

    trades_no_counter = [t for t in trades_all
                         if not (t["direction"] == "BUY"  and t.get("trend") == "bear")
                         and not (t["direction"] == "SELL" and t.get("trend") == "bull")]

    print(f"\n  {'Strategie':<30} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'Net EUR':>10} | {'SL%':>5}")
    print("  " + "─" * 72)
    for label, group in [
        ("Tout trader (baseline)",        trades_all),
        ("Filtre Bull/Bear EMA strict",   trades_filtre),
        ("Pas de trades contre-tendance", trades_no_counter),
        ("Sideways uniquement",           trades_sideways),
    ]:
        s = stats(group)
        if s:
            print(f"  {label:<30} | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% | {s['net_eur']:+9.0f} EUR | {s['sl_pct']:4.0f}%")
        else:
            print(f"  {label:<30} |  <3   |   -    |    -     |    -       |   -")


def analyse_mensuel_regime(candles, trades):
    print(f"\n{'─' * 78}")
    print("  PARTIE 4 — P&L mensuel par regime EMA (2000 EUR/trade)")
    print(f"{'─' * 78}")
    by_month = defaultdict(lambda: {r: [] for r in REGIMES})
    for t in trades:
        dt = datetime.fromtimestamp(candles[t["idx"]]["ts"], tz=timezone.utc)
        mk = (dt.year, dt.month)
        by_month[mk][t.get("trend", "bull")].append(t["pnl_eur"])

    print(f"\n  {'Mois':>8} | {'Bull EUR':>10} | {'Sideways':>10} | {'Bear EUR':>10} | {'TOTAL':>9} | Bar")
    print("  " + "─" * 72)
    cumul = 0
    for mk in sorted(by_month.keys()):
        d = by_month[mk]
        bull_n = sum(d["bull"]); side_n = sum(d["sideways"]); bear_n = sum(d["bear"])
        total = bull_n + side_n + bear_n; cumul += total
        label = datetime(mk[0], mk[1], 1).strftime("%b %Y")
        bar = ("█" if total > 0 else "░") * min(int(abs(total) / 20), 28)
        print(f"  {label:>8} | {bull_n:+10.0f} | {side_n:+10.0f} | {bear_n:+10.0f} | {total:+9.0f} | {bar}")
    print(f"  {'─' * 65}")
    print(f"  {'TOTAL':>8} | {sum(t['pnl_eur'] for t in trades if t.get('trend')=='bull'):+10.0f}"
          f" | {sum(t['pnl_eur'] for t in trades if t.get('trend')=='sideways'):+10.0f}"
          f" | {sum(t['pnl_eur'] for t in trades if t.get('trend')=='bear'):+10.0f}"
          f" | {sum(t['pnl_eur'] for t in trades):+9.0f} |")


def recommandation(trades):
    print(f"\n{'=' * 78}")
    print("  RECOMMANDATION — Regimes")
    print(f"{'=' * 78}")
    for r in REGIMES:
        group = [t for t in trades if t.get("trend") == r]
        s = stats(group)
        if not s: continue
        if s["wr"] < 40:
            verdict = "EVITER — Win rate trop faible"
        elif s["net_eur"] < 0:
            verdict = "PRUDENCE — P&L negatif sur la periode"
        elif s["wr"] > 55 and s["net_eur"] > 0:
            verdict = "OPTIMAL — Continuer a trader"
        else:
            verdict = "ACCEPTABLE — Surveiller"
        print(f"  {REGIME_LABELS[r]:<24} : {verdict}  ({s['wr']:.1f}% WR, {s['net_eur']:+.0f} EUR)")
    print(f"{'=' * 78}\n")


def run():
    print("\n" + "=" * 78)
    print("  BACKTEST REGIMES — BTC Trading Advisor — DONNÉES RÉELLES BINANCE")
    print("  Regime EMA = Bull/Sideways/Bear selon alignement EMA20/50/200")
    print("=" * 78)

    candles = load_real_candles()
    print("\n  Precompute signaux...")
    sigs = precompute(candles)
    if not sigs:
        print("  Aucun signal. Abandon."); return

    repartition_regimes(sigs)
    trades = analyse_par_regime(candles, sigs)
    if trades:
        analyse_direction_par_regime(trades)
        analyse_strategies_filtrees(candles, sigs)
        analyse_mensuel_regime(candles, trades)
        recommandation(trades)


if __name__ == "__main__":
    run()
