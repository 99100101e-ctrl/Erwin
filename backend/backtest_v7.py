"""
Backtest v7 — Validation finale EMA100 + ADX>25 + SL×2.0
==========================================================
Objectif : confirmer que la config candidate est robuste
avant implémentation live.

Tests :
  1. Breakdown annuel complet (2024 / 2025 / 2026) sur toutes les variantes EMA100
  2. SL granulaire EMA100 : ×1.5 / ×1.8 / ×2.0 / ×2.2 / ×2.5
  3. Comparaison EMA200 vs EMA100 vs EMA50 sur SL×2.0
  4. EMA100 + SL×2.0 × filtres supplémentaires (ADX seuils, EMA1h, CVD)
  5. BUY seul vs SELL seul vs aligné sur EMA100
  6. Stress test : que se passe-t-il si on enlève ADX ?
  7. Tableau de validation finale — top 10 définitifs
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from bt_common import load_real_candles
from backtest_2ans import (
    section, row, HDR, SEP,
    yearly_breakdown, exit_reasons, stats,
)
from backtest_v2 import precompute_full, enrich_signals
from backtest_v6 import enrich_v6, run_v6
from collections import defaultdict
from datetime import datetime, timezone


def main():
    print("\n" + "=" * 80)
    print("  BACKTEST v7 — Validation finale : EMA100 + ADX>25 + SL×2.0")
    print("  Avant implémentation live")
    print("=" * 80)

    candles   = load_real_candles()
    n_years   = (candles[-1]["ts"] - candles[0]["ts"]) / (365.25 * 86400)
    print(f"  Durée : {n_years:.1f} an(s)\n")

    sigs_base = precompute_full(candles)
    sigs_v2   = enrich_signals(candles, sigs_base)
    sigs      = enrich_v6(candles, sigs_v2)
    mk        = {"wr": 0.0, "sh": -999.0}

    # ─────────────────────────────────────────────────────────────
    # 1. SL GRANULAIRE — EMA100 + ADX>25
    # ─────────────────────────────────────────────────────────────
    section("1 — SL granulaire EMA100 + ADX>25 (×1.0 → ×2.5)")
    for sl in [1.0, 1.2, 1.5, 1.8, 2.0, 2.2, 2.5]:
        row(f"EMA100 aligné + ADX>25 + SL×{sl}",
            run_v6(candles, sigs, adx1h_min=25, sl_mult=sl,
                   macro_field="ema100_trend", macro_mode="aligned"), mk)

    # ─────────────────────────────────────────────────────────────
    # 2. EMA200 vs EMA100 vs EMA50 — SL×2.0 (comparaison directe)
    # ─────────────────────────────────────────────────────────────
    section("2 — EMA200 vs EMA100 vs EMA50 + ADX>25 + SL×2.0")
    row("EMA200 + ADX>25 + SL×2.0",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0,
               macro_field="ema200_trend", macro_mode="aligned"), mk)
    row("EMA100 + ADX>25 + SL×2.0  ← candidate",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0,
               macro_field="ema100_trend", macro_mode="aligned"), mk)
    row("EMA50  + ADX>25 + SL×2.0",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0,
               macro_field="ema50_trend",  macro_mode="aligned"), mk)
    row("No macro + ADX>25 + SL×2.0",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0), mk)

    # ─────────────────────────────────────────────────────────────
    # 3. EMA100 + SL×2.0 × filtres supplémentaires
    # ─────────────────────────────────────────────────────────────
    section("3 — EMA100 + SL×2.0 × filtres supplémentaires")
    row("EMA100 + ADX>25 + SL×2.0  (base)",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0,
               macro_field="ema100_trend", macro_mode="aligned"), mk)
    row("EMA100 + ADX>22 + SL×2.0",
        run_v6(candles, sigs, adx1h_min=22, sl_mult=2.0,
               macro_field="ema100_trend", macro_mode="aligned"), mk)
    row("EMA100 + ADX>20 + SL×2.0",
        run_v6(candles, sigs, adx1h_min=20, sl_mult=2.0,
               macro_field="ema100_trend", macro_mode="aligned"), mk)
    row("EMA100 + ADX>28 + SL×2.0",
        run_v6(candles, sigs, adx1h_min=28, sl_mult=2.0,
               macro_field="ema100_trend", macro_mode="aligned"), mk)
    row("EMA100 + ADX>30 + SL×2.0",
        run_v6(candles, sigs, adx1h_min=30, sl_mult=2.0,
               macro_field="ema100_trend", macro_mode="aligned"), mk)
    row("EMA100 + ADX>25 + EMA1h + SL×2.0",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0, ema1_filter=True,
               macro_field="ema100_trend", macro_mode="aligned"), mk)
    row("EMA100 + ADX>25 + CVD trend + SL×2.0",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0, cvd_trend_filter=True,
               macro_field="ema100_trend", macro_mode="aligned"), mk)
    row("EMA100 + ADX>25 + RSI4h + SL×2.0",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0, rsi4_filter=True,
               macro_field="ema100_trend", macro_mode="aligned"), mk)
    row("EMA100 + ADX>25 + SL×2.0 + score≥80",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0, thresh=80,
               macro_field="ema100_trend", macro_mode="aligned"), mk)

    # ─────────────────────────────────────────────────────────────
    # 4. BUY ONLY vs SELL ONLY vs ALIGNÉ — EMA100 + SL×2.0
    # ─────────────────────────────────────────────────────────────
    section("4 — BUY only vs SELL only vs aligné (EMA100 + ADX>25 + SL×2.0)")
    row("Aligné (BUY en BULL + SELL en BEAR)",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0,
               macro_field="ema100_trend", macro_mode="aligned"), mk)
    row("BUY only en macro BULL",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0,
               macro_field="ema100_trend", macro_mode="bull"), mk)
    row("SELL only en macro BEAR",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0,
               macro_field="ema100_trend", macro_mode="bear"), mk)
    row("BUY only + SL×1.5",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5,
               macro_field="ema100_trend", macro_mode="bull"), mk)
    row("SELL baseline (ref)",
        run_v6(candles, sigs, direction_only="SELL"), mk)

    # ─────────────────────────────────────────────────────────────
    # 5. STRESS TEST — que se passe-t-il sans ADX ?
    # ─────────────────────────────────────────────────────────────
    section("5 — Stress test : rôle de l'ADX>25")
    row("EMA100 + no ADX + SL×2.0",
        run_v6(candles, sigs, sl_mult=2.0,
               macro_field="ema100_trend", macro_mode="aligned"), mk)
    row("EMA100 + ADX>20 + SL×2.0",
        run_v6(candles, sigs, adx1h_min=20, sl_mult=2.0,
               macro_field="ema100_trend", macro_mode="aligned"), mk)
    row("EMA100 + ADX>25 + SL×2.0",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0,
               macro_field="ema100_trend", macro_mode="aligned"), mk)
    row("EMA100 + ADX>30 + SL×2.0",
        run_v6(candles, sigs, adx1h_min=30, sl_mult=2.0,
               macro_field="ema100_trend", macro_mode="aligned"), mk)
    row("No macro + no ADX + SL×2.0 (F5)",
        run_v6(candles, sigs, sl_mult=2.0), mk)

    # ─────────────────────────────────────────────────────────────
    # 6. BREAKDOWN ANNUEL COMPLET — toutes les variantes clés
    # ─────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  ▶ 6 — BREAKDOWN ANNUEL COMPLET")
    print(SEP)

    configs = [
        # Candidate principale
        ("★ EMA100 + ADX>25 + SL×2.0",
         dict(adx1h_min=25, sl_mult=2.0, macro_field="ema100_trend", macro_mode="aligned")),
        # Variantes SL
        ("  EMA100 + ADX>25 + SL×1.5",
         dict(adx1h_min=25, sl_mult=1.5, macro_field="ema100_trend", macro_mode="aligned")),
        ("  EMA100 + ADX>25 + SL×1.8",
         dict(adx1h_min=25, sl_mult=1.8, macro_field="ema100_trend", macro_mode="aligned")),
        ("  EMA100 + ADX>25 + SL×2.2",
         dict(adx1h_min=25, sl_mult=2.2, macro_field="ema100_trend", macro_mode="aligned")),
        # Comparaison EMA
        ("  EMA200 + ADX>25 + SL×2.0",
         dict(adx1h_min=25, sl_mult=2.0, macro_field="ema200_trend", macro_mode="aligned")),
        ("  EMA50  + ADX>25 + SL×2.0",
         dict(adx1h_min=25, sl_mult=2.0, macro_field="ema50_trend",  macro_mode="aligned")),
        # BUY only
        ("  BUY + EMA100 BULL + ADX>25 + SL×2.0",
         dict(adx1h_min=25, sl_mult=2.0, macro_field="ema100_trend", macro_mode="bull")),
        ("  BUY + EMA100 BULL + ADX>25 + SL×1.5",
         dict(adx1h_min=25, sl_mult=1.5, macro_field="ema100_trend", macro_mode="bull")),
        # Références solides
        ("  SELL baseline",
         dict(direction_only="SELL")),
        ("  F5 baseline",
         dict()),
    ]

    for label, kwargs in configs:
        t = run_v6(candles, sigs, **kwargs)
        yearly_breakdown(candles, t, label)

    # Exit reasons candidat principal
    print()
    t_final = run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0,
                     macro_field="ema100_trend", macro_mode="aligned")
    t_buy   = run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0,
                     macro_field="ema100_trend", macro_mode="bull")
    t_sell  = run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0,
                     macro_field="ema100_trend", macro_mode="bear")
    exit_reasons(t_final, "EMA100+ADX>25+SL×2.0 (aligné)")
    exit_reasons(t_buy,   "EMA100+ADX>25+SL×2.0 (BUY only)")
    exit_reasons(t_sell,  "EMA100+ADX>25+SL×2.0 (SELL only)")

    # ─────────────────────────────────────────────────────────────
    # 7. TABLEAU DE VALIDATION FINALE — TOP 10
    # ─────────────────────────────────────────────────────────────
    section("7 — TABLEAU DE VALIDATION FINALE — TOP 10 definitifs")
    final = [
        ("★★★ EMA100 + ADX>25 + SL×2.0",
         dict(adx1h_min=25, sl_mult=2.0, macro_field="ema100_trend", macro_mode="aligned")),
        ("★★  EMA100 + ADX>25 + SL×1.5",
         dict(adx1h_min=25, sl_mult=1.5, macro_field="ema100_trend", macro_mode="aligned")),
        ("★★  EMA100 + ADX>22 + SL×2.0",
         dict(adx1h_min=22, sl_mult=2.0, macro_field="ema100_trend", macro_mode="aligned")),
        ("★   EMA200 + ADX>25 + SL×2.0",
         dict(adx1h_min=25, sl_mult=2.0, macro_field="ema200_trend", macro_mode="aligned")),
        ("★   EMA200 + ADX>25 + SL×1.5",
         dict(adx1h_min=25, sl_mult=1.5, macro_field="ema200_trend", macro_mode="aligned")),
        ("★   EMA50  + ADX>25 + SL×2.0",
         dict(adx1h_min=25, sl_mult=2.0, macro_field="ema50_trend",  macro_mode="aligned")),
        ("    BUY + EMA100 BULL + ADX>25 + SL×2.0",
         dict(adx1h_min=25, sl_mult=2.0, macro_field="ema100_trend", macro_mode="bull")),
        ("    BUY + EMA100 BULL + ADX>25 + SL×1.5",
         dict(adx1h_min=25, sl_mult=1.5, macro_field="ema100_trend", macro_mode="bull")),
        ("    SELL baseline",
         dict(direction_only="SELL")),
        ("    F5 baseline",
         dict()),
    ]
    for label, kwargs in final:
        row(label, run_v6(candles, sigs, **kwargs), mk)

    # ─────────────────────────────────────────────────────────────
    # RÉSUMÉ
    # ─────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print(f"  Meilleur Win Rate : {mk['wr']:.1f}%")
    print(f"  Meilleur Sharpe   : {mk['sh']:+.2f}")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
