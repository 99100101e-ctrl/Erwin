"""
Backtest v3 — Focus ADX1h > 25 + SELL only + CVD divergence
=============================================================
Suite de backtest_v2.py — approfondit les 3 pistes les plus prometteuses :

  1. ADX1h > 25  : meilleur Net EUR (+656€) — explorer toutes les combos
  2. SELL only   : meilleur Sharpe (+1.52) — pourquoi ? quels filtres aident ?
  3. CVD divergence : WR 71.4% — trop peu de trades, besoin de plus de combos

Nouveaux tests :
  • ADX > 25 seul vs ADX > 22 / 28 / 30 (granularité)
  • ADX > 25 + EMA1h / EMA4h / macro / combos
  • ADX > 25 + SELL only × macro / CVD / EMA
  • ADX > 25 + SL multiplier (1.5 / 1.8 / 2.2)
  • ADX > 25 + score threshold (70 / 80)
  • SELL only × filtres fins
  • CVD divergence × toutes combos disponibles
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from bt_common import load_real_candles
from backtest_2ans import (
    section, row, HDR, SEP,
    yearly_breakdown, exit_reasons,
)
from backtest_v2 import (
    precompute_full,
    enrich_signals,
    run_v2,
)


def main():
    print("\n" + "=" * 80)
    print("  BACKTEST v3 — Focus ADX>25 / SELL only / CVD divergence")
    print("  Base : 2 ans BTC réel Binance — score≥70, SL×1.8, cooldown 2h")
    print("=" * 80)

    candles = load_real_candles()
    n_years = (candles[-1]["ts"] - candles[0]["ts"]) / (365.25 * 86400)
    print(f"  Durée : {n_years:.1f} an(s)\n")

    sigs_base = precompute_full(candles)
    sigs      = enrich_signals(candles, sigs_base)
    mk        = {"wr": 0.0, "sh": -999.0}

    # ─────────────────────────────────────────────────────
    # RÉFÉRENCE
    # ─────────────────────────────────────────────────────
    section("RÉFÉRENCE — meilleurs résultats v2")
    row("F5 baseline",               run_v2(candles, sigs), mk)
    row("ADX1h > 25 (best net v2)",  run_v2(candles, sigs, adx1h_min=25), mk)
    row("SELL baseline (best sh v2)",
        [x for x in run_v2(candles, sigs, direction_only="SELL") if True], mk)
    row("Macro aligné + EMA1h",      run_v2(candles, sigs, macro_filter="aligned", ema1_filter=True), mk)

    # ─────────────────────────────────────────────────────
    # 15. ADX1h GRANULARITÉ (22 / 25 / 28 / 30)
    # ─────────────────────────────────────────────────────
    section("15 — ADX1h GRANULARITÉ (score≥70, SL×1.8)")
    for adx_min in [20, 22, 25, 28, 30]:
        row(f"ADX1h > {adx_min}",
            run_v2(candles, sigs, adx1h_min=adx_min), mk)

    # ─────────────────────────────────────────────────────
    # 16. ADX > 25 × FILTRES DIRECTIONNELS
    # ─────────────────────────────────────────────────────
    section("16 — ADX1h > 25 × filtres directionnels (score≥70, SL×1.8)")
    row("ADX > 25 seul",
        run_v2(candles, sigs, adx1h_min=25), mk)
    row("ADX > 25 + EMA1h",
        run_v2(candles, sigs, adx1h_min=25, ema1_filter=True), mk)
    row("ADX > 25 + EMA4h",
        run_v2(candles, sigs, adx1h_min=25, ema4_filter=True), mk)
    row("ADX > 25 + EMA1h + EMA4h",
        run_v2(candles, sigs, adx1h_min=25, ema1_filter=True, ema4_filter=True), mk)
    row("ADX > 25 + macro aligné",
        run_v2(candles, sigs, adx1h_min=25, macro_filter="aligned"), mk)
    row("ADX > 25 + macro aligné + EMA1h",
        run_v2(candles, sigs, adx1h_min=25, macro_filter="aligned", ema1_filter=True), mk)
    row("ADX > 25 + macro aligné + EMA4h",
        run_v2(candles, sigs, adx1h_min=25, macro_filter="aligned", ema4_filter=True), mk)
    row("ADX > 25 + 3 TF (macro+4h+1h)",
        run_v2(candles, sigs, adx1h_min=25, macro_filter="aligned", ema4_filter=True, ema1_filter=True), mk)
    row("ADX > 25 + CVD trend",
        run_v2(candles, sigs, adx1h_min=25, cvd_trend_filter=True), mk)
    row("ADX > 25 + CVD div",
        run_v2(candles, sigs, adx1h_min=25, cvd_div_filter=True), mk)
    row("ADX > 25 + RSI4h",
        run_v2(candles, sigs, adx1h_min=25, rsi4_filter=True), mk)

    # ─────────────────────────────────────────────────────
    # 17. ADX > 25 — SELL ONLY × tous filtres
    # ─────────────────────────────────────────────────────
    section("17 — ADX1h > 25 — SELL only × filtres (score≥70, SL×1.8)")
    row("SELL + ADX > 25",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=25), mk)
    row("SELL + ADX > 25 + EMA1h",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=25, ema1_filter=True), mk)
    row("SELL + ADX > 25 + EMA4h",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=25, ema4_filter=True), mk)
    row("SELL + ADX > 25 + macro BEAR",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=25, macro_filter="bear"), mk)
    row("SELL + ADX > 25 + macro BEAR + EMA1h",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=25, macro_filter="bear", ema1_filter=True), mk)
    row("SELL + ADX > 25 + CVD trend down",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=25, cvd_trend_filter=True), mk)
    row("SELL + ADX > 25 + CVD div",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=25, cvd_div_filter=True), mk)
    row("SELL + ADX > 25 + macro + CVD",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=25, macro_filter="bear", cvd_trend_filter=True), mk)
    row("SELL + ADX > 25 + macro + CVD + EMA1h",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=25, macro_filter="bear", cvd_trend_filter=True, ema1_filter=True), mk)
    row("SELL + ADX > 25 + 3TF",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=25, macro_filter="bear", ema4_filter=True, ema1_filter=True), mk)
    row("SELL + ADX > 25 + RSI4h",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=25, rsi4_filter=True), mk)

    # ─────────────────────────────────────────────────────
    # 18. ADX > 25 × SL MULTIPLIER
    # ─────────────────────────────────────────────────────
    section("18 — ADX1h > 25 × SL multiplier ATR")
    for sl in [1.5, 1.8, 2.2]:
        row(f"ADX > 25 + SL ×{sl}",
            run_v2(candles, sigs, adx1h_min=25, sl_mult=sl), mk)
    for sl in [1.5, 1.8, 2.2]:
        row(f"SELL + ADX > 25 + SL ×{sl}",
            run_v2(candles, sigs, direction_only="SELL", adx1h_min=25, sl_mult=sl), mk)

    # ─────────────────────────────────────────────────────
    # 19. ADX > 25 × SCORE THRESHOLD
    # ─────────────────────────────────────────────────────
    section("19 — ADX1h > 25 × score threshold")
    for thresh in [60, 70, 80]:
        row(f"ADX > 25 + score ≥ {thresh}",
            run_v2(candles, sigs, adx1h_min=25, thresh=thresh), mk)
    for thresh in [60, 70, 80]:
        row(f"SELL + ADX > 25 + score ≥ {thresh}",
            run_v2(candles, sigs, direction_only="SELL", adx1h_min=25, thresh=thresh), mk)

    # ─────────────────────────────────────────────────────
    # 20. SELL only — approfondissement
    # ─────────────────────────────────────────────────────
    section("20 — SELL only — approfondissement (score≥70, SL×1.8)")
    row("SELL baseline",
        run_v2(candles, sigs, direction_only="SELL"), mk)
    row("SELL + EMA1h",
        run_v2(candles, sigs, direction_only="SELL", ema1_filter=True), mk)
    row("SELL + EMA4h",
        run_v2(candles, sigs, direction_only="SELL", ema4_filter=True), mk)
    row("SELL + EMA1h + EMA4h",
        run_v2(candles, sigs, direction_only="SELL", ema1_filter=True, ema4_filter=True), mk)
    row("SELL + RSI4h",
        run_v2(candles, sigs, direction_only="SELL", rsi4_filter=True), mk)
    row("SELL + macro BEAR",
        run_v2(candles, sigs, direction_only="SELL", macro_filter="bear"), mk)
    row("SELL + macro BEAR + EMA1h",
        run_v2(candles, sigs, direction_only="SELL", macro_filter="bear", ema1_filter=True), mk)
    row("SELL + ADX > 20",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=20), mk)
    row("SELL + ADX > 25",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=25), mk)
    row("SELL + ADX > 25 + EMA1h",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=25, ema1_filter=True), mk)
    row("SELL + score ≥ 80",
        run_v2(candles, sigs, direction_only="SELL", thresh=80), mk)
    row("SELL + score ≥ 80 + ADX > 20",
        run_v2(candles, sigs, direction_only="SELL", thresh=80, adx1h_min=20), mk)
    row("SELL + SL ×1.5",
        run_v2(candles, sigs, direction_only="SELL", sl_mult=1.5), mk)
    row("SELL + SL ×2.2",
        run_v2(candles, sigs, direction_only="SELL", sl_mult=2.2), mk)
    row("SELL + SL ×2.2 + ADX > 25",
        run_v2(candles, sigs, direction_only="SELL", sl_mult=2.2, adx1h_min=25), mk)

    # ─────────────────────────────────────────────────────
    # 21. CVD DIVERGENCE — approfondissement
    # ─────────────────────────────────────────────────────
    section("21 — CVD DIVERGENCE — approfondissement (score≥70, SL×1.8)")
    row("SELL + CVD div (baseline)",
        run_v2(candles, sigs, direction_only="SELL", cvd_div_filter=True), mk)
    row("SELL + CVD div + EMA1h",
        run_v2(candles, sigs, direction_only="SELL", cvd_div_filter=True, ema1_filter=True), mk)
    row("SELL + CVD div + ADX > 20",
        run_v2(candles, sigs, direction_only="SELL", cvd_div_filter=True, adx1h_min=20), mk)
    row("SELL + CVD div + ADX > 25",
        run_v2(candles, sigs, direction_only="SELL", cvd_div_filter=True, adx1h_min=25), mk)
    row("SELL + CVD div + macro BEAR",
        run_v2(candles, sigs, direction_only="SELL", cvd_div_filter=True, macro_filter="bear"), mk)
    row("SELL + CVD div + macro + EMA1h",
        run_v2(candles, sigs, direction_only="SELL", cvd_div_filter=True, macro_filter="bear", ema1_filter=True), mk)
    row("SELL + CVD div + RSI4h",
        run_v2(candles, sigs, direction_only="SELL", cvd_div_filter=True, rsi4_filter=True), mk)
    row("SELL + CVD div + score ≥ 80",
        run_v2(candles, sigs, direction_only="SELL", cvd_div_filter=True, thresh=80), mk)
    row("SELL + CVD div + SL ×1.5",
        run_v2(candles, sigs, direction_only="SELL", cvd_div_filter=True, sl_mult=1.5), mk)
    row("SELL + CVD div + SL ×2.2",
        run_v2(candles, sigs, direction_only="SELL", cvd_div_filter=True, sl_mult=2.2), mk)
    # BUY avec CVD divergence haussière
    row("BUY + CVD div (bullish)",
        run_v2(candles, sigs, direction_only="BUY", cvd_div_filter=True), mk)
    row("BUY + CVD div + macro BULL",
        run_v2(candles, sigs, direction_only="BUY", cvd_div_filter=True, macro_filter="bull"), mk)

    # ─────────────────────────────────────────────────────
    # 22. MEILLEURES COMBOS v3
    # ─────────────────────────────────────────────────────
    section("22 — MEILLEURES COMBOS v3 (score≥70, cooldown 2h)")
    top = [
        ("ADX>25",                                  dict(adx1h_min=25)),
        ("ADX>25 + EMA1h",                          dict(adx1h_min=25, ema1_filter=True)),
        ("ADX>25 + macro aligné + EMA1h",           dict(adx1h_min=25, macro_filter="aligned", ema1_filter=True)),
        ("ADX>25 + 3TF",                            dict(adx1h_min=25, macro_filter="aligned", ema4_filter=True, ema1_filter=True)),
        ("SELL + ADX>25",                           dict(direction_only="SELL", adx1h_min=25)),
        ("SELL + ADX>25 + EMA1h",                   dict(direction_only="SELL", adx1h_min=25, ema1_filter=True)),
        ("SELL + ADX>25 + macro BEAR",              dict(direction_only="SELL", adx1h_min=25, macro_filter="bear")),
        ("SELL + ADX>25 + macro BEAR + EMA1h",      dict(direction_only="SELL", adx1h_min=25, macro_filter="bear", ema1_filter=True)),
        ("SELL + ADX>25 + CVD div",                 dict(direction_only="SELL", adx1h_min=25, cvd_div_filter=True)),
        ("SELL + ADX>25 + SL×2.2",                  dict(direction_only="SELL", adx1h_min=25, sl_mult=2.2)),
        ("SELL baseline",                           dict(direction_only="SELL")),
        ("SELL + macro BEAR + EMA1h",               dict(direction_only="SELL", macro_filter="bear", ema1_filter=True)),
        ("SELL + CVD div",                          dict(direction_only="SELL", cvd_div_filter=True)),
        ("SELL + CVD div + ADX>25",                 dict(direction_only="SELL", cvd_div_filter=True, adx1h_min=25)),
        ("Macro aligné + EMA1h",                    dict(macro_filter="aligned", ema1_filter=True)),
    ]
    for label, kwargs in top:
        row(f"{label}", run_v2(candles, sigs, **kwargs), mk)

    # ─────────────────────────────────────────────────────
    # 23. BREAKDOWN ANNUEL — top configs v3
    # ─────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  ▶ 23 — BREAKDOWN ANNUEL (top configs v3)")
    print(SEP)
    annual = [
        ("F5 baseline",                    dict()),
        ("ADX>25",                         dict(adx1h_min=25)),
        ("ADX>25 + EMA1h",                 dict(adx1h_min=25, ema1_filter=True)),
        ("ADX>25 + macro + EMA1h",         dict(adx1h_min=25, macro_filter="aligned", ema1_filter=True)),
        ("SELL baseline",                  dict(direction_only="SELL")),
        ("SELL + ADX>25",                  dict(direction_only="SELL", adx1h_min=25)),
        ("SELL + ADX>25 + macro BEAR",     dict(direction_only="SELL", adx1h_min=25, macro_filter="bear")),
        ("SELL + CVD div",                 dict(direction_only="SELL", cvd_div_filter=True)),
    ]
    for label, kwargs in annual:
        t = run_v2(candles, sigs, **kwargs)
        yearly_breakdown(candles, t, label)
    print()
    t_top1 = run_v2(candles, sigs, adx1h_min=25, ema1_filter=True)
    t_top2 = run_v2(candles, sigs, direction_only="SELL", adx1h_min=25, macro_filter="bear", ema1_filter=True)
    exit_reasons(t_top1, "ADX>25+EMA1h")
    exit_reasons(t_top2, "SELL+ADX>25+macro+EMA1h")

    # ─────────────────────────────────────────────────────
    # RÉSUMÉ
    # ─────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print(f"  Meilleur Win Rate : {mk['wr']:.1f}%")
    print(f"  Meilleur Sharpe   : {mk['sh']:+.2f}")
    print(f"  (◄WR / ◄SH dans les tableaux)")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
