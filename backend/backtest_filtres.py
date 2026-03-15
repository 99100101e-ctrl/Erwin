"""
Backtest comparatif des filtres — BTC Trading Advisor
Compare 5 strategies pour valider les filtres avant deploiement.

Filtres testes :
  F0 : Baseline         — seuil 70, aucun filtre
  F1 : Trend filter     — BUY en bull, SELL en bear (EMA20>50>200 / EMA20<50<200)
  F2 : Regime etabli    — attendre 48h apres changement de tendance
  F3 : F1 + F2          — les deux filtres combines (config deployee)
  F4 : F1 seuil 80      — filtre tendance + seuil plus strict

Explique aussi en clair ce que signifie "debut de regime" et montre l'impact.
"""
from bt_common import (generate_btc_1an, precompute, run_backtest,
                        stats, print_stats_row, TRADE_SIZE)
import numpy as np
from collections import defaultdict


# ─────────────────────────────────────────────────────────────────────────────
# Strategies a comparer
# ─────────────────────────────────────────────────────────────────────────────

STRATEGIES = [
    ("F0 — Baseline (seuil 70)",             dict(thresh=70, trend_filter=False, min_trend_age=0)),
    ("F1 — Trend filter seul",               dict(thresh=70, trend_filter=True,  min_trend_age=0)),
    ("F2 — Regime etabli seul (>=48h)",      dict(thresh=70, trend_filter=False, min_trend_age=48)),
    ("F3 — F1+F2 (config deployee)",         dict(thresh=70, trend_filter=True,  min_trend_age=48)),
    ("F4 — F1+F2 seuil 80",                  dict(thresh=80, trend_filter=True,  min_trend_age=48)),
    ("F5 — BUY-only filter (SELL libre)",    dict(thresh=70, trend_filter=False, min_trend_age=0,
                                                  buy_trend_only=True)),
]


# ─────────────────────────────────────────────────────────────────────────────
# Partie 1 — Tableau comparatif global
# ─────────────────────────────────────────────────────────────────────────────

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
            # Filtrer uniquement les BUY hors-bull, garder tous les SELL
            trades = [t for t in trades_all
                      if not (t["direction"] == "BUY" and t.get("trend") != "bull")]
        else:
            trades = trades_all
        s = stats(trades)
        results[label] = (trades, s)  # type: ignore
        if s:
            print(f"  {label:<34} | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% "
                  f"| -{s['mdd']*100:4.1f}% | {s['sh']:+6.2f} | {s['net_eur']:+9.0f} EUR | {s['sl_pct']:4.0f}%")
        else:
            print(f"  {label:<34} |  <3   |   -    |    -     |    -    |    -    |    -       |   -")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Partie 2 — Explication "debut de regime" avec exemples chiffres
# ─────────────────────────────────────────────────────────────────────────────

def expliquer_debut_regime(candles, sigs):
    print(f"\n{'─' * 78}")
    print("  PARTIE 2 — Qu'est-ce que 'debut de regime' ? (impact chiffre)")
    print(f"{'─' * 78}")
    print("""
  DEFINITION :
  Un "regime" = periode ou les 3 EMAs sont alignees dans la meme direction :
    Bull     : EMA20 > EMA50 > EMA200  (marche clairement haussier)
    Bear     : EMA20 < EMA50 < EMA200  (marche clairement baissier)
    Sideways : autrement               (EMAs entrelacees, direction floue)

  Un "debut de regime" = les 48 premieres heures apres un changement d'alignement.
  Exemple : EMA20 vient de croiser EMA50 vers le haut → nouveau bull, mais
  le signal est souvent trop precipite, le prix revient souvent tester les EMAs.

  POURQUOI 48h ? Le backtest montre :""")

    for cutoff in [0, 12, 24, 48, 72, 96]:
        trades = run_backtest(candles, sigs, thresh=70, trend_filter=True,
                              min_trend_age=cutoff)
        s = stats(trades)
        if s:
            print(f"    min_trend_age >= {cutoff:3d}h : {s['n']:4d} trades "
                  f"| {s['wr']:5.1f}% WR | {s['net_eur']:+8.0f} EUR net")

    # Stats sur les trades early vs etablis (avec filtre tendance)
    all_trend = run_backtest(candles, sigs, thresh=70, trend_filter=True, min_trend_age=0)
    early  = [t for t in all_trend if t.get("trend_age_h", 9999) < 48]
    mature = [t for t in all_trend if t.get("trend_age_h", 0)   >= 48]
    se = stats(early); sm = stats(mature)

    print(f"""
  RESULTAT DIRECT :
    Trades en debut de regime (<48h) : {len(early):3d} trades | """, end="")
    if se:
        print(f"{se['wr']:4.1f}% WR | {se['net_eur']:+6.0f} EUR | Sharpe {se['sh']:+.2f}")
    else:
        print("insuffisant")
    print(f"    Trades en regime etabli (>=48h): {len(mature):3d} trades | ", end="")
    if sm:
        print(f"{sm['wr']:4.1f}% WR | {sm['net_eur']:+6.0f} EUR | Sharpe {sm['sh']:+.2f}")
    else:
        print("insuffisant")


# ─────────────────────────────────────────────────────────────────────────────
# Partie 3 — Detail F3 (config deployee) : BUY vs SELL par regime EMA
# ─────────────────────────────────────────────────────────────────────────────

def detail_config_deployee(candles, sigs):
    print(f"\n{'─' * 78}")
    print("  PARTIE 3 — Detail F3 (config deployee) : BUY/SELL par regime EMA")
    print(f"{'─' * 78}")
    trades = run_backtest(candles, sigs, thresh=70, trend_filter=True, min_trend_age=48)
    if not trades:
        print("  Aucun trade avec F3."); return

    buys  = [t for t in trades if t["direction"] == "BUY"]
    sells = [t for t in trades if t["direction"] == "SELL"]

    print(f"\n  {'Direction':<12} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'Net EUR':>10} | {'SL%':>5} | {'MaxDD':>7}")
    print("  " + "─" * 68)
    for label, group in [("TOUS", trades), ("BUY (en bull)", buys), ("SELL (en bear)", sells)]:
        s = stats(group)
        if s:
            print(f"  {label:<12} | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% "
                  f"| {s['net_eur']:+9.0f} EUR | {s['sl_pct']:4.0f}% | -{s['mdd']*100:4.1f}%")
        else:
            print(f"  {label:<12} |  <3   |   -    |    -     |    -       |   -   |    -")

    # Tendance EMA dans les signaux disponibles
    trend_counts = defaultdict(int)
    for s in sigs:
        trend_counts[s.get("trend", "?")] += 1
    print(f"\n  Repartition des signaux bruts par tendance EMA :")
    for t, n in sorted(trend_counts.items(), key=lambda x: -x[1]):
        print(f"    {t:<10} : {n:4d} signaux ({n/len(sigs)*100:.1f}%)")


# ─────────────────────────────────────────────────────────────────────────────
# Partie 4 — Courbe d'equite F0 vs F3 (baseline vs config deployee)
# ─────────────────────────────────────────────────────────────────────────────

def courbe_equite(candles, results):
    print(f"\n{'─' * 78}")
    print("  PARTIE 4 — P&L mensuel : F0 (baseline) vs F3 (config deployee)")
    print(f"{'─' * 78}")
    months = ["Jan", "Fev", "Mar", "Avr", "Mai", "Jun",
              "Jul", "Aou", "Sep", "Oct", "Nov", "Dec"]

    trades_f0 = results["F0 — Baseline (seuil 70)"][0]
    trades_f3 = results["F3 — F1+F2 (config deployee)"][0]

    by_m_f0 = defaultdict(float)
    by_m_f3 = defaultdict(float)
    for t in trades_f0:
        m = (candles[t["idx"]]["ts"] - 1704067200) // (30 * 24 * 3600)
        by_m_f0[m] += t["pnl_eur"]
    for t in trades_f3:
        m = (candles[t["idx"]]["ts"] - 1704067200) // (30 * 24 * 3600)
        by_m_f3[m] += t["pnl_eur"]

    all_months = sorted(set(list(by_m_f0.keys()) + list(by_m_f3.keys())))
    print(f"\n  {'Mois':>5} | {'F0 (aucun filtre)':>18} | {'F3 (filtres actifs)':>19} | {'Diff':>8}")
    print("  " + "─" * 62)
    cumul_f0 = cumul_f3 = 0
    for m in all_months:
        f0 = by_m_f0.get(m, 0); f3 = by_m_f3.get(m, 0)
        cumul_f0 += f0; cumul_f3 += f3
        label = months[m % 12] if m < 12 else f"M{m+1}"
        diff = f3 - f0
        print(f"  {label:>5} | {f0:+17.0f}€ | {f3:+18.0f}€ | {diff:+7.0f}€")
    print("  " + "─" * 62)
    print(f"  {'TOTAL':>5} | {cumul_f0:+17.0f}€ | {cumul_f3:+18.0f}€ | {cumul_f3-cumul_f0:+7.0f}€")
    print(f"  {'cumul':>5} | {cumul_f0:+17.0f}€ | {cumul_f3:+18.0f}€ |")


# ─────────────────────────────────────────────────────────────────────────────
# Partie 5 — Recommandation finale : quelle config deployer ?
# ─────────────────────────────────────────────────────────────────────────────

def recommandation(results):
    print(f"\n{'=' * 78}")
    print("  RECOMMANDATION — Analyse des resultats")
    print(f"{'=' * 78}")

    # Trouver la meilleure config
    best_label = None; best_net = float("-inf"); best_s = None
    for label, (trades, s) in results.items():
        if s and s["net_eur"] > best_net:
            best_net = s["net_eur"]; best_label = label; best_s = s

    if best_label:
        print(f"\n  Meilleure config (donnees synthetiques) : {best_label}")
        print(f"  -> {best_s['n']} trades | {best_s['wr']:.1f}% WR | "
              f"Sharpe {best_s['sh']:+.2f} | {best_s['net_eur']:+.0f} EUR net | MaxDD -{best_s['mdd']*100:.1f}%")

    # Analyser F0 vs F1 vs F5
    s_f0 = results.get("F0 — Baseline (seuil 70)", ([], None))[1]
    s_f1 = results.get("F1 — Trend filter seul", ([], None))[1]
    s_f5 = results.get("F5 — BUY-only filter (SELL libre)", ([], None))[1]

    print("""
  ANALYSE :
    Le filtre de tendance strict (F1/F3) reduit le nombre de trades.
    Sur donnees synthetiques, les SELL contre-tendance sont profitables —
    ce qui peut differer du vrai marche BTC (moins de mean-reversion).

    Sur donnees reelles, la tendance EMA20>50>200 tend a mieux filtrer
    les faux signaux. Le choix dependend de ton style de trading :

    -> Si tu veux MOINS de trades, plus selectifs, GARDE F3 (trend + regime etabli)
    -> Si tu veux plus de trades avec filtre doux, utilise F5 (BUY filtre, SELL libre)
    -> Si tu veux tester sur donnees reelles avant de decider, garde F0 en observation

  REGLES DEPLOYEES DANS signal_engine.py (actif des maintenant) :
    [1] Score minimum : 70/100 (seuil monte de 60 a 70)
    [2] BUY bloque si EMA20 < EMA50 OU EMA50 < EMA200 (trend != 'bull')
    [3] SELL bloque si EMA20 > EMA50 OU EMA50 > EMA200 (trend != 'bear')
    [4] Tout signal bloque si regime < 48h apres changement de tendance

  AFFICHAGE DANS L'UI (signal visible meme si supprime) :
    Trend filter : "Trend filter: BUY bloque (sideways) — attend EMA20>EMA50>EMA200"
    Regime debut : "Debut de regime bull (12h/48h) — attendre 36h"
""")
    print(f"{'=' * 78}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def run():
    print("\n" + "=" * 78)
    print("  BACKTEST FILTRES — BTC Trading Advisor — 1 an — 2000 EUR/trade")
    print("  Validation des filtres avant deploiement sur le vrai logiciel")
    print("=" * 78)

    candles = generate_btc_1an()
    p0 = candles[200]["close"]; p1 = candles[-1]["close"]
    print(f"\n  BTC simule : ${p0:,.0f} -> ${p1:,.0f}  ({(p1/p0-1)*100:+.1f}%)\n")

    print("  Precompute signaux (score >= 70)...")
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
