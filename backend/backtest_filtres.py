"""
Backtest comparatif des filtres — BTC Trading Advisor
Données RÉELLES : backend/data/btc_1h_real.json (6 derniers mois Binance)

Filtres testes :
  F0 : Baseline         — seuil 70, aucun filtre
  F1 : Trend filter     — BUY en bull, SELL en bear (EMA20>50>200 / EMA20<50<200)
  F2 : Regime etabli    — attendre 48h apres changement de tendance
  F3 : F1 + F2          — les deux filtres combines (config deployee)
  F4 : F1 seuil 80      — filtre tendance + seuil plus strict
  F5 : BUY-only filter  — BUY uniquement en bull, SELL libre
"""
from bt_common import (load_real_candles, precompute, run_backtest,
                        stats, print_stats_row, TRADE_SIZE)
import numpy as np
from collections import defaultdict
from datetime import datetime, timezone


STRATEGIES = [
    ("F0 — Baseline (seuil 70)",             dict(thresh=70, trend_filter=False, min_trend_age=0)),
    ("F1 — Trend filter seul",               dict(thresh=70, trend_filter=True,  min_trend_age=0)),
    ("F2 — Regime etabli seul (>=48h)",      dict(thresh=70, trend_filter=False, min_trend_age=48)),
    ("F3 — F1+F2 (config deployee)",         dict(thresh=70, trend_filter=True,  min_trend_age=48)),
    ("F4 — F1+F2 seuil 80",                  dict(thresh=80, trend_filter=True,  min_trend_age=48)),
    ("F5 — BUY-only filter (SELL libre)",    dict(thresh=70, trend_filter=False, min_trend_age=0,
                                                  buy_trend_only=True)),
]


def tableau_comparatif(candles, sigs):
    print(f"\n{'─' * 90}")
    print("  TABLEAU COMPARATIF — toutes strategies")
    print(f"{'─' * 90}")
    header = (f"  {'Strategie':<34} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} "
              f"| {'MaxDD':>7} | {'Sharpe':>7} | {'Net EUR':>10} | {'SL%':>5}")
    print(f"\n{header}")
    print("  " + "─" * 88)

    results = {}
    for label, params in STRATEGIES:
        p = {k: v for k, v in params.items() if k != "buy_trend_only"}
        buy_only = params.get("buy_trend_only", False)
        trades_all = run_backtest(candles, sigs, **p)
        if buy_only:
            trades = [t for t in trades_all
                      if not (t["direction"] == "BUY" and t.get("trend") != "bull")]
        else:
            trades = trades_all
        s = stats(trades)
        results[label] = (trades, s)
        if s:
            print(f"  {label:<34} | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% "
                  f"| -{s['mdd']*100:4.1f}% | {s['sh']:+6.2f} | {s['net_eur']:+9.0f} EUR | {s['sl_pct']:4.0f}%")
        else:
            print(f"  {label:<34} |  <3   |   -    |    -     |    -    |    -    |    -       |   -")
    return results


def expliquer_debut_regime(candles, sigs):
    print(f"\n{'─' * 78}")
    print("  PARTIE 2 — Impact du filtre 'debut de regime'")
    print(f"{'─' * 78}")
    for cutoff in [0, 12, 24, 48, 72, 96]:
        trades = run_backtest(candles, sigs, thresh=70, trend_filter=True, min_trend_age=cutoff)
        s = stats(trades)
        if s:
            print(f"    min_trend_age >= {cutoff:3d}h : {s['n']:4d} trades "
                  f"| {s['wr']:5.1f}% WR | {s['net_eur']:+8.0f} EUR net")

    all_trend = run_backtest(candles, sigs, thresh=70, trend_filter=True, min_trend_age=0)
    early  = [t for t in all_trend if t.get("trend_age_h", 9999) < 48]
    mature = [t for t in all_trend if t.get("trend_age_h", 0)   >= 48]
    se = stats(early); sm = stats(mature)

    print(f"\n  Trades en debut de regime (<48h) : {len(early):3d} | ", end="")
    if se:
        print(f"{se['wr']:4.1f}% WR | {se['net_eur']:+6.0f} EUR | Sharpe {se['sh']:+.2f}")
    else:
        print("insuffisant")
    print(f"  Trades en regime etabli (>=48h) : {len(mature):3d} | ", end="")
    if sm:
        print(f"{sm['wr']:4.1f}% WR | {sm['net_eur']:+6.0f} EUR | Sharpe {sm['sh']:+.2f}")
    else:
        print("insuffisant")


def detail_config_deployee(candles, sigs):
    print(f"\n{'─' * 78}")
    print("  PARTIE 3 — Detail F3 (config deployee) : BUY/SELL par tendance EMA")
    print(f"{'─' * 78}")
    trades = run_backtest(candles, sigs, thresh=70, trend_filter=True, min_trend_age=48)
    if not trades:
        print("  Aucun trade avec F3."); return

    buys  = [t for t in trades if t["direction"] == "BUY"]
    sells = [t for t in trades if t["direction"] == "SELL"]

    print(f"\n  {'Direction':<14} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'Net EUR':>10} | {'SL%':>5}")
    print("  " + "─" * 60)
    for label, group in [("TOUS", trades), ("BUY (en bull)", buys), ("SELL (en bear)", sells)]:
        s = stats(group)
        if s:
            print(f"  {label:<14} | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% "
                  f"| {s['net_eur']:+9.0f} EUR | {s['sl_pct']:4.0f}%")

    trend_counts = defaultdict(int)
    for s in sigs:
        trend_counts[s.get("trend", "?")] += 1
    print(f"\n  Repartition des signaux par tendance EMA :")
    for t, n in sorted(trend_counts.items(), key=lambda x: -x[1]):
        print(f"    {t:<10} : {n:4d} signaux ({n/len(sigs)*100:.1f}%)")


def courbe_equite(candles, results):
    print(f"\n{'─' * 78}")
    print("  PARTIE 4 — P&L mensuel : F0 (baseline) vs F3 (config deployee)")
    print(f"{'─' * 78}")

    trades_f0 = results["F0 — Baseline (seuil 70)"][0]
    trades_f3 = results["F3 — F1+F2 (config deployee)"][0]

    by_m_f0 = defaultdict(float)
    by_m_f3 = defaultdict(float)
    for t in trades_f0:
        dt = datetime.fromtimestamp(candles[t["idx"]]["ts"], tz=timezone.utc)
        mk = (dt.year, dt.month)
        by_m_f0[mk] += t["pnl_eur"]
    for t in trades_f3:
        dt = datetime.fromtimestamp(candles[t["idx"]]["ts"], tz=timezone.utc)
        mk = (dt.year, dt.month)
        by_m_f3[mk] += t["pnl_eur"]

    all_months = sorted(set(list(by_m_f0.keys()) + list(by_m_f3.keys())))
    print(f"\n  {'Mois':>8} | {'F0 (aucun filtre)':>18} | {'F3 (filtres)':>14} | {'Diff':>8}")
    print("  " + "─" * 56)
    cumul_f0 = cumul_f3 = 0
    for mk in all_months:
        f0 = by_m_f0.get(mk, 0); f3 = by_m_f3.get(mk, 0)
        cumul_f0 += f0; cumul_f3 += f3
        label = datetime(mk[0], mk[1], 1).strftime("%b %Y")
        print(f"  {label:>8} | {f0:+17.0f}€ | {f3:+13.0f}€ | {f3-f0:+7.0f}€")
    print("  " + "─" * 56)
    print(f"  {'TOTAL':>8} | {cumul_f0:+17.0f}€ | {cumul_f3:+13.0f}€ | {cumul_f3-cumul_f0:+7.0f}€")


def recommandation(results):
    print(f"\n{'=' * 78}")
    print("  RECOMMANDATION")
    print(f"{'=' * 78}")

    best_label = None; best_sh = float("-inf"); best_s = None
    for label, (trades, s) in results.items():
        if s and s["sh"] > best_sh and s["n"] >= 5:
            best_sh = s["sh"]; best_label = label; best_s = s

    if best_label:
        print(f"\n  Meilleure config (donnees reelles) : {best_label}")
        print(f"  -> {best_s['n']} trades | {best_s['wr']:.1f}% WR | "
              f"Sharpe {best_s['sh']:+.2f} | {best_s['net_eur']:+.0f} EUR net | MaxDD -{best_s['mdd']*100:.1f}%")
    print(f"{'=' * 78}\n")


def run():
    print("\n" + "=" * 78)
    print("  BACKTEST FILTRES — BTC Trading Advisor — DONNÉES RÉELLES BINANCE")
    print("  Validation des filtres sur vrais prix BTC/USDT")
    print("=" * 78)

    candles = load_real_candles()

    print("\n  Precompute signaux (score >= 60)...")
    sigs = precompute(candles, verbose=True)
    if not sigs:
        print("  Aucun signal. Abandon."); return

    print(f"\n  Tendance EMA des signaux : "
          f"bull={sum(1 for s in sigs if s.get('trend')=='bull')} "
          f"bear={sum(1 for s in sigs if s.get('trend')=='bear')} "
          f"sideways={sum(1 for s in sigs if s.get('trend')=='sideways')}")

    results = tableau_comparatif(candles, sigs)
    expliquer_debut_regime(candles, sigs)
    detail_config_deployee(candles, sigs)
    courbe_equite(candles, results)
    recommandation(results)


if __name__ == "__main__":
    run()
