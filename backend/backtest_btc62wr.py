"""
Backtest BTC62WR — Comparaison configurations
==============================================
Teste toutes les combinaisons de filtres pour trouver
la config optimale à implémenter dans le bot live.

Base commune :
  - Score ≥ 70
  - EMA100 daily aligné
  - ADX 1h > 25
  - SL × 2.0 | TP1=1.0xR | TP2=2.5xR | TP3=5.0xR
  - Cooldown 2h

Filtres additionnels testés :
  - RSI 4h (BUY si RSI4h < 50, SELL si RSI4h > 50)
  - Heures FR (8h-21h UTC, hors 16h-18h)
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from bt_common import load_real_candles, TRADE_SIZE
from backtest_2ans import (
    precompute_full, section, row, HDR, SEP,
    yearly_breakdown, exit_reasons, stats,
)
from backtest_v2 import enrich_signals
from backtest_v6 import enrich_v6, run_v6
from datetime import datetime, timezone
from collections import defaultdict

FR_HOURS = set(range(8, 22)) - {16, 17, 18}   # 8h-21h UTC hors US open


def run_btc62wr(candles, sigs, rsi4=False, fr_hours=False, **kwargs):
    """run_v6 avec filtre heures FR optionnel."""
    if not fr_hours:
        return run_v6(candles, sigs, rsi4_filter=rsi4, **kwargs)

    # Filtre heures FR en post-processing sur run_v6
    base = run_v6(candles, sigs, rsi4_filter=rsi4, **kwargs)
    return [t for t in base if t.get("hour", 0) in FR_HOURS]


def print_monthly(candles, trades, label):
    if not trades:
        return
    print(f"\n  P&L mensuel — {label}")
    monthly = defaultdict(list)
    for t in trades:
        dt = datetime.fromtimestamp(candles[t["idx"]]["ts"], tz=timezone.utc)
        monthly[(dt.year, dt.month)].append(t["pnl_eur"])
    for (yr, mo), pnls in sorted(monthly.items()):
        wr  = sum(1 for p in pnls if p > 0) / len(pnls) * 100
        net = sum(pnls)
        bar = "█" * int(abs(net) / 30)
        sign = "+" if net >= 0 else ""
        print(f"  {yr}-{mo:02d} | N={len(pnls):2d} | WR {wr:4.0f}% | {sign}{net:+6.0f}€ | {bar}")


def main():
    print("\n" + "=" * 80)
    print("  BACKTEST BTC62WR — Recherche config optimale")
    print("  Base : EMA100 daily + ADX>25 + SL×2.0 + cooldown 2h")
    print("=" * 80)

    candles = load_real_candles()
    n_years = (candles[-1]["ts"] - candles[0]["ts"]) / (365.25 * 86400)
    print(f"  Durée : {n_years:.1f} an(s)\n")

    if n_years < 1.5:
        print("  ⚠️  ATTENTION : moins de 1.5 an de données.")
        print("     Lance fetch_btc_data.py sur Windows pour obtenir 2 ans.\n")

    sigs_base = precompute_full(candles)
    sigs_v2   = enrich_signals(candles, sigs_base)
    sigs      = enrich_v6(candles, sigs_v2)

    BASE = dict(
        thresh      = 70,
        adx1h_min   = 25,
        sl_mult     = 2.0,
        cooldown_h  = 2,
        macro_field = "ema100_trend",
        macro_mode  = "aligned",
    )

    mk = {"wr": 0.0, "sh": -999.0}

    # ── Tableau comparatif ──────────────────────────────────────────────────
    section("COMPARAISON DES CONFIGS — EMA100 + ADX>25 + SL×2.0")
    print(HDR)

    configs = [
        ("Sans filtre extra (live actuel)",        dict(rsi4=False, fr_hours=False)),
        ("+ RSI 4h",                               dict(rsi4=True,  fr_hours=False)),
        ("+ Heures FR (8h-21h)",                   dict(rsi4=False, fr_hours=True)),
        ("+ RSI 4h + Heures FR  ← config origine", dict(rsi4=True,  fr_hours=True)),
    ]

    results = {}
    for label, extra in configs:
        t = run_btc62wr(candles, sigs, **extra, **BASE)
        row(label, t, mk)
        results[label] = t

    # ── Breakdown annuel pour chaque config ─────────────────────────────────
    print(f"\n{SEP}")
    print("  ▶ BREAKDOWN ANNUEL PAR CONFIG")
    print(SEP)
    for label, extra in configs:
        yearly_breakdown(candles, results[label], label)

    # ── Détail de la meilleure config ───────────────────────────────────────
    best_label = max(results, key=lambda k: (stats(results[k]) or {}).get("sh", -999))
    best = results[best_label]
    s = stats(best)

    print(f"\n{SEP}")
    print(f"  ▶ DÉTAIL — {best_label}")
    print(SEP)

    if s:
        buys  = [t for t in best if t["direction"] == "BUY"]
        sells = [t for t in best if t["direction"] == "SELL"]
        print(HDR)
        row("  BUY  (macro BULL)", buys,  mk)
        row("  SELL (macro BEAR)", sells, mk)
        print()
        exit_reasons(best, best_label)
        print_monthly(candles, best, best_label)

    # ── Résumé final ────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print(f"  ★ MEILLEURE CONFIG : {best_label}")
    if s:
        print(f"     N trades  : {s['n']}")
        print(f"     Win Rate  : {s['wr']:.1f}%")
        print(f"     Sharpe    : {s['sh']:+.2f}")
        print(f"     MDD       : -{s['mdd']*100:.1f}%")
        print(f"     Net total : {s['net_eur']:+.0f}€")
        print(f"     Avg/trade : {s['avg_eur']:+.0f}€")
    else:
        print("  ⚠️  Pas assez de trades")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
