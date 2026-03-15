"""
Backtest Regimes de Marche — BTC Trading Advisor
Analyse : Bull vs Sideways vs Bear
Questions cles :
  - Dans quel regime la strategie performe le mieux ?
  - Faut-il couper les signaux en marche baissier ?
  - Est-il preferable de ne trader que BUY en Bull et SELL en Bear ?
"""
from bt_common import (generate_btc_1an, precompute, run_backtest,
                        stats, print_stats_row, TRADE_SIZE)
import numpy as np
from collections import defaultdict


REGIMES = ["bull", "sideways", "bear"]
REGIME_LABELS = {"bull": "Bull  (hausse)", "sideways": "Sideways (lateral)", "bear": "Bear  (baisse)"}


# ─────────────────────────────────────────────────────────────────────────────
# Repartition du temps par regime
# ─────────────────────────────────────────────────────────────────────────────

def repartition_regimes(candles):
    counts = defaultdict(int)
    for c in candles:
        counts[c.get("regime", "unknown")] += 1
    total = len(candles)
    print(f"\n{'─' * 70}")
    print("  Repartition du temps par regime (annee complete)")
    print(f"{'─' * 70}")
    for r in REGIMES:
        n = counts[r]; pct = n / total * 100
        bar = "█" * int(pct / 2)
        print(f"  {REGIME_LABELS[r]:<22} : {n:5d}h ({pct:4.1f}%) {bar}")


# ─────────────────────────────────────────────────────────────────────────────
# Performance par regime
# ─────────────────────────────────────────────────────────────────────────────

def analyse_par_regime(candles, sigs):
    print(f"\n{'─' * 78}")
    print("  PARTIE 1 — Performance globale par regime (seuil >= 70)")
    print(f"{'─' * 78}")
    trades = run_backtest(candles, sigs, thresh=70)
    if not trades:
        print("  Aucun trade."); return trades

    col = f"  {'Regime':<22} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'MaxDD':>7} | {'Sharpe':>7} | {'Net EUR':>10} | {'SL%':>5}"
    print(f"\n{col}")
    print("  " + "─" * 78)
    print_stats_row("TOTAL", stats(trades))
    for r in REGIMES:
        group = [t for t in trades if t.get("regime") == r]
        print_stats_row(REGIME_LABELS[r], stats(group))
    return trades


# ─────────────────────────────────────────────────────────────────────────────
# BUY et SELL par regime
# ─────────────────────────────────────────────────────────────────────────────

def analyse_direction_par_regime(trades):
    print(f"\n{'─' * 78}")
    print("  PARTIE 2 — BUY vs SELL dans chaque regime")
    print(f"{'─' * 78}")
    for r in REGIMES:
        regime_trades = [t for t in trades if t.get("regime") == r]
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


# ─────────────────────────────────────────────────────────────────────────────
# Strategies filtrees selon le regime
# ─────────────────────────────────────────────────────────────────────────────

def analyse_strategies_filtrees(candles, sigs):
    print(f"\n{'─' * 78}")
    print("  PARTIE 3 — Comparaison : tout trader vs filtrer par regime")
    print(f"{'─' * 78}")
    trades_all   = run_backtest(candles, sigs, thresh=70)

    # Strategie : BUY seulement en Bull/Sideways, SELL seulement en Bear/Sideways
    trades_filtre = [t for t in trades_all
                     if (t["direction"] == "BUY"  and t.get("regime") in ("bull", "sideways"))
                     or (t["direction"] == "SELL" and t.get("regime") in ("bear", "sideways"))]

    # Strategie : uniquement Sideways (zone de range, scalp)
    trades_sideways = [t for t in trades_all if t.get("regime") == "sideways"]

    # Strategie : exclure Bear pour BUY
    trades_no_counter = [t for t in trades_all
                         if not (t["direction"] == "BUY" and t.get("regime") == "bear")
                         and not (t["direction"] == "SELL" and t.get("regime") == "bull")]

    print(f"\n  {'Strategie':<30} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'Net EUR':>10} | {'SL%':>5}")
    print("  " + "─" * 72)
    for label, group in [
        ("Tout trader (baseline)",         trades_all),
        ("Filtre Bull/Bear strict",         trades_filtre),
        ("Pas de trades contre-tendance",  trades_no_counter),
        ("Sideways uniquement",            trades_sideways),
    ]:
        s = stats(group)
        if s:
            print(f"  {label:<30} | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% | {s['net_eur']:+9.0f} EUR | {s['sl_pct']:4.0f}%")
        else:
            print(f"  {label:<30} |  <3   |   -    |    -     |    -       |   -")


# ─────────────────────────────────────────────────────────────────────────────
# Transitions de regime (entrer en fin de Bear = meilleur timing ?)
# ─────────────────────────────────────────────────────────────────────────────

def analyse_transitions(candles, trades):
    print(f"\n{'─' * 78}")
    print("  PARTIE 4 — Trades en debut vs fin de regime")
    print(f"{'─' * 78}")

    # Detecter les changements de regime
    transitions = {}
    prev_r = candles[0].get("regime", "bull")
    for i, c in enumerate(candles):
        r = c.get("regime", "bull")
        if r != prev_r:
            transitions[i] = (prev_r, r)
        prev_r = r

    # Categoriser chaque trade : debut (<48h apres transition) ou milieu
    early = []; mid = []
    for t in trades:
        idx = t["idx"]
        is_early = any(abs(idx - tr_idx) < 48 for tr_idx in transitions.keys())
        (early if is_early else mid).append(t)

    print(f"\n  {'Moment':<28} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'Net EUR':>10}")
    print("  " + "─" * 62)
    for label, group in [
        ("Debut regime (<48h apres transition)", early),
        ("Milieu de regime (etabli)",            mid),
    ]:
        s = stats(group)
        if s:
            print(f"  {label:<38} | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% | {s['net_eur']:+9.0f} EUR")
        else:
            print(f"  {label:<38} |  <3   |   -    |    -     |    -")


# ─────────────────────────────────────────────────────────────────────────────
# P&L mensuel par regime
# ─────────────────────────────────────────────────────────────────────────────

def analyse_mensuel_regime(candles, trades):
    print(f"\n{'─' * 78}")
    print("  PARTIE 5 — P&L mensuel par regime (2000 EUR/trade)")
    print(f"{'─' * 78}")
    months = ["Jan", "Fev", "Mar", "Avr", "Mai", "Jun",
              "Jul", "Aou", "Sep", "Oct", "Nov", "Dec"]
    by_month = defaultdict(lambda: {r: [] for r in REGIMES})
    for t in trades:
        m = (candles[t["idx"]]["ts"] - 1704067200) // (30 * 24 * 3600)
        by_month[m][t.get("regime", "bull")].append(t["pnl_eur"])

    print(f"\n  {'Mois':>5} | {'Bull EUR':>10} | {'Sideways':>10} | {'Bear EUR':>10} | {'TOTAL':>9} | Bar")
    print("  " + "─" * 72)
    cumul = 0
    for m in sorted(by_month.keys()):
        d = by_month[m]
        bull_n = sum(d["bull"]); side_n = sum(d["sideways"]); bear_n = sum(d["bear"])
        total = bull_n + side_n + bear_n; cumul += total
        label = months[m % 12] if m < 12 else f"M{m+1}"
        bar = ("█" if total > 0 else "░") * min(int(abs(total) / 20), 28)
        print(f"  {label:>5} | {bull_n:+10.0f} | {side_n:+10.0f} | {bear_n:+10.0f} | {total:+9.0f} | {bar}")
    print(f"  {'─' * 65}")
    print(f"  {'TOTAL':>5} | {sum(t['pnl_eur'] for t in trades if t.get('regime')=='bull'):+10.0f}"
          f" | {sum(t['pnl_eur'] for t in trades if t.get('regime')=='sideways'):+10.0f}"
          f" | {sum(t['pnl_eur'] for t in trades if t.get('regime')=='bear'):+10.0f}"
          f" | {sum(t['pnl_eur'] for t in trades):+9.0f} |")


# ─────────────────────────────────────────────────────────────────────────────
# Recommandation
# ─────────────────────────────────────────────────────────────────────────────

def recommandation(trades):
    print(f"\n{'=' * 78}")
    print("  RECOMMANDATION — Regimes")
    print(f"{'=' * 78}")
    for r in REGIMES:
        group = [t for t in trades if t.get("regime") == r]
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
        print(f"  {REGIME_LABELS[r]:<22} : {verdict}  ({s['wr']:.1f}% WR, {s['net_eur']:+.0f} EUR)")
    print(f"{'=' * 78}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def run():
    print("\n" + "=" * 78)
    print("  BACKTEST REGIMES MARCHE — BTC Trading Advisor — 1 an — 2000 EUR/trade")
    print("  Analyse : Bull vs Sideways vs Bear")
    print("=" * 78)

    candles = generate_btc_1an()
    p0 = candles[200]["close"]; p1 = candles[-1]["close"]
    print(f"\n  BTC simule : ${p0:,.0f} -> ${p1:,.0f}  ({(p1/p0-1)*100:+.1f}%)")

    repartition_regimes(candles)

    print("\n  Precompute signaux...")
    sigs = precompute(candles)
    if not sigs:
        print("  Aucun signal. Abandon."); return

    trades = analyse_par_regime(candles, sigs)
    if trades:
        analyse_direction_par_regime(trades)
        analyse_strategies_filtrees(candles, sigs)
        analyse_transitions(candles, trades)
        analyse_mensuel_regime(candles, trades)
        recommandation(trades)


if __name__ == "__main__":
    run()
