"""
Backtest v4 — Approfondissement des 5 pistes issues de v3
==========================================================
Pistes :
  A) ADX>25 + macro aligné  → Sharpe +1.94 (best v3) — N=76, explorer combos
  B) ADX>25 + CVD trend     → Sharpe +1.68 — N=60, très prometteur
  C) SELL + RSI4h           → Avg +0.73% record — N=20, augmenter N
  D) ADX>25 + EMA1h         → config la plus consistante ann. — tester SL×2.2
  E) Triples combos         → macro + CVD trend + ADX>25

Nouveaux tests v4 :
  • Piste A : macro aligné × SL / CVD trend / RSI4h / SELL / ADX seuils
  • Piste B : CVD trend × macro / EMA / RSI4h / SL / SELL / ADX seuils
  • Piste C : SELL+RSI4h × ADX / macro / EMA / SL / score — chercher combos N>30
  • Piste D : ADX>25+EMA1h × SL×2.2 vs ×1.8 vs ×1.5 / SELL / macro
  • Piste E : triples filtres — 15+ combos 3-facteurs
  • Cooldown : 1h / 2h / 3h — impact sur qualité
  • Breakdown annuel des meilleures configs v4
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
    print("  BACKTEST v4 — ADX+macro / CVD trend / SELL+RSI4h / triples combos")
    print("  Base : 2 ans BTC réel Binance — score≥70, SL×1.8, cooldown 2h (défaut)")
    print("=" * 80)

    candles = load_real_candles()
    n_years = (candles[-1]["ts"] - candles[0]["ts"]) / (365.25 * 86400)
    print(f"  Durée : {n_years:.1f} an(s)\n")

    sigs_base = precompute_full(candles)
    sigs      = enrich_signals(candles, sigs_base)
    mk        = {"wr": 0.0, "sh": -999.0}

    # ─────────────────────────────────────────────────────────────────
    # RÉFÉRENCE
    # ─────────────────────────────────────────────────────────────────
    section("RÉFÉRENCE — top v3")
    row("F5 baseline",                    run_v2(candles, sigs), mk)
    row("ADX>25 + macro aligné (best v3 Sharpe)", run_v2(candles, sigs, adx1h_min=25, macro_filter="aligned"), mk)
    row("ADX>25 + CVD trend (v3 #2)",     run_v2(candles, sigs, adx1h_min=25, cvd_trend_filter=True), mk)
    row("ADX>25 + EMA1h (v3 consistent)", run_v2(candles, sigs, adx1h_min=25, ema1_filter=True), mk)
    row("SELL baseline",                  run_v2(candles, sigs, direction_only="SELL"), mk)
    row("SELL + RSI4h (v3 best Avg)",     run_v2(candles, sigs, direction_only="SELL", rsi4_filter=True), mk)

    # ─────────────────────────────────────────────────────────────────
    # A — ADX>25 + macro aligné — exploration complète
    # ─────────────────────────────────────────────────────────────────
    section("A — ADX>25 + macro aligné × filtres supplémentaires")
    row("ADX>25 + macro seul",
        run_v2(candles, sigs, adx1h_min=25, macro_filter="aligned"), mk)
    row("ADX>25 + macro + CVD trend",
        run_v2(candles, sigs, adx1h_min=25, macro_filter="aligned", cvd_trend_filter=True), mk)
    row("ADX>25 + macro + CVD div",
        run_v2(candles, sigs, adx1h_min=25, macro_filter="aligned", cvd_div_filter=True), mk)
    row("ADX>25 + macro + RSI4h",
        run_v2(candles, sigs, adx1h_min=25, macro_filter="aligned", rsi4_filter=True), mk)
    row("ADX>25 + macro + EMA1h",
        run_v2(candles, sigs, adx1h_min=25, macro_filter="aligned", ema1_filter=True), mk)
    row("ADX>25 + macro + EMA4h",
        run_v2(candles, sigs, adx1h_min=25, macro_filter="aligned", ema4_filter=True), mk)
    row("ADX>25 + macro + absorption",
        run_v2(candles, sigs, adx1h_min=25, macro_filter="aligned", absorption_filter=True), mk)
    row("ADX>25 + macro + SL×1.5",
        run_v2(candles, sigs, adx1h_min=25, macro_filter="aligned", sl_mult=1.5), mk)
    row("ADX>25 + macro + SL×2.2",
        run_v2(candles, sigs, adx1h_min=25, macro_filter="aligned", sl_mult=2.2), mk)
    row("ADX>22 + macro",
        run_v2(candles, sigs, adx1h_min=22, macro_filter="aligned"), mk)
    row("ADX>20 + macro",
        run_v2(candles, sigs, adx1h_min=20, macro_filter="aligned"), mk)
    # SELL only
    row("SELL + ADX>25 + macro BEAR",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=25, macro_filter="bear"), mk)
    row("SELL + ADX>22 + macro BEAR",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=22, macro_filter="bear"), mk)
    row("SELL + ADX>20 + macro BEAR",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=20, macro_filter="bear"), mk)
    row("BUY  + ADX>25 + macro BULL",
        run_v2(candles, sigs, direction_only="BUY",  adx1h_min=25, macro_filter="bull"), mk)

    # ─────────────────────────────────────────────────────────────────
    # B — ADX>25 + CVD trend — exploration complète
    # ─────────────────────────────────────────────────────────────────
    section("B — ADX>25 + CVD trend × filtres supplémentaires")
    row("ADX>25 + CVD trend seul",
        run_v2(candles, sigs, adx1h_min=25, cvd_trend_filter=True), mk)
    row("ADX>25 + CVD trend + macro",
        run_v2(candles, sigs, adx1h_min=25, cvd_trend_filter=True, macro_filter="aligned"), mk)
    row("ADX>25 + CVD trend + EMA1h",
        run_v2(candles, sigs, adx1h_min=25, cvd_trend_filter=True, ema1_filter=True), mk)
    row("ADX>25 + CVD trend + EMA4h",
        run_v2(candles, sigs, adx1h_min=25, cvd_trend_filter=True, ema4_filter=True), mk)
    row("ADX>25 + CVD trend + RSI4h",
        run_v2(candles, sigs, adx1h_min=25, cvd_trend_filter=True, rsi4_filter=True), mk)
    row("ADX>25 + CVD trend + SL×1.5",
        run_v2(candles, sigs, adx1h_min=25, cvd_trend_filter=True, sl_mult=1.5), mk)
    row("ADX>25 + CVD trend + SL×2.2",
        run_v2(candles, sigs, adx1h_min=25, cvd_trend_filter=True, sl_mult=2.2), mk)
    row("ADX>22 + CVD trend",
        run_v2(candles, sigs, adx1h_min=22, cvd_trend_filter=True), mk)
    row("ADX>20 + CVD trend",
        run_v2(candles, sigs, adx1h_min=20, cvd_trend_filter=True), mk)
    # SELL
    row("SELL + ADX>25 + CVD trend",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=25, cvd_trend_filter=True), mk)
    row("SELL + ADX>22 + CVD trend",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=22, cvd_trend_filter=True), mk)
    row("SELL + ADX>20 + CVD trend",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=20, cvd_trend_filter=True), mk)
    row("SELL + CVD trend seul",
        run_v2(candles, sigs, direction_only="SELL", cvd_trend_filter=True), mk)
    row("SELL + CVD trend + macro BEAR",
        run_v2(candles, sigs, direction_only="SELL", cvd_trend_filter=True, macro_filter="bear"), mk)
    row("SELL + CVD trend + EMA1h",
        run_v2(candles, sigs, direction_only="SELL", cvd_trend_filter=True, ema1_filter=True), mk)
    row("SELL + CVD trend + RSI4h",
        run_v2(candles, sigs, direction_only="SELL", cvd_trend_filter=True, rsi4_filter=True), mk)
    row("SELL + CVD trend + SL×2.2",
        run_v2(candles, sigs, direction_only="SELL", cvd_trend_filter=True, sl_mult=2.2), mk)
    row("BUY + CVD trend seul",
        run_v2(candles, sigs, direction_only="BUY", cvd_trend_filter=True), mk)
    row("BUY + CVD trend + macro BULL",
        run_v2(candles, sigs, direction_only="BUY", cvd_trend_filter=True, macro_filter="bull"), mk)

    # ─────────────────────────────────────────────────────────────────
    # C — SELL + RSI4h — augmenter N / explorer combos
    # ─────────────────────────────────────────────────────────────────
    section("C — SELL + RSI4h × filtres (chercher combos N>30)")
    row("SELL + RSI4h seul",
        run_v2(candles, sigs, direction_only="SELL", rsi4_filter=True), mk)
    row("SELL + RSI4h + EMA1h",
        run_v2(candles, sigs, direction_only="SELL", rsi4_filter=True, ema1_filter=True), mk)
    row("SELL + RSI4h + EMA4h",
        run_v2(candles, sigs, direction_only="SELL", rsi4_filter=True, ema4_filter=True), mk)
    row("SELL + RSI4h + macro BEAR",
        run_v2(candles, sigs, direction_only="SELL", rsi4_filter=True, macro_filter="bear"), mk)
    row("SELL + RSI4h + ADX>20",
        run_v2(candles, sigs, direction_only="SELL", rsi4_filter=True, adx1h_min=20), mk)
    row("SELL + RSI4h + ADX>22",
        run_v2(candles, sigs, direction_only="SELL", rsi4_filter=True, adx1h_min=22), mk)
    row("SELL + RSI4h + ADX>25",
        run_v2(candles, sigs, direction_only="SELL", rsi4_filter=True, adx1h_min=25), mk)
    row("SELL + RSI4h + CVD trend",
        run_v2(candles, sigs, direction_only="SELL", rsi4_filter=True, cvd_trend_filter=True), mk)
    row("SELL + RSI4h + CVD div",
        run_v2(candles, sigs, direction_only="SELL", rsi4_filter=True, cvd_div_filter=True), mk)
    row("SELL + RSI4h + SL×1.5",
        run_v2(candles, sigs, direction_only="SELL", rsi4_filter=True, sl_mult=1.5), mk)
    row("SELL + RSI4h + SL×2.2",
        run_v2(candles, sigs, direction_only="SELL", rsi4_filter=True, sl_mult=2.2), mk)
    row("SELL + RSI4h + score ≥ 80",
        run_v2(candles, sigs, direction_only="SELL", rsi4_filter=True, thresh=80), mk)
    row("SELL + RSI4h + cooldown 1h",
        run_v2(candles, sigs, direction_only="SELL", rsi4_filter=True, cooldown_h=1), mk)
    row("SELL + RSI4h + cooldown 3h",
        run_v2(candles, sigs, direction_only="SELL", rsi4_filter=True, cooldown_h=3), mk)
    # BUY + RSI4h
    row("BUY + RSI4h seul",
        run_v2(candles, sigs, direction_only="BUY", rsi4_filter=True), mk)
    row("BUY + RSI4h + macro BULL",
        run_v2(candles, sigs, direction_only="BUY", rsi4_filter=True, macro_filter="bull"), mk)
    row("BUY + RSI4h + ADX>20",
        run_v2(candles, sigs, direction_only="BUY", rsi4_filter=True, adx1h_min=20), mk)

    # ─────────────────────────────────────────────────────────────────
    # D — ADX>25 + EMA1h — config la plus consistante, tester SL×2.2
    # ─────────────────────────────────────────────────────────────────
    section("D — ADX>25 + EMA1h × SL / macro / SELL")
    row("ADX>25 + EMA1h + SL×1.5",
        run_v2(candles, sigs, adx1h_min=25, ema1_filter=True, sl_mult=1.5), mk)
    row("ADX>25 + EMA1h + SL×1.8",
        run_v2(candles, sigs, adx1h_min=25, ema1_filter=True, sl_mult=1.8), mk)
    row("ADX>25 + EMA1h + SL×2.2",
        run_v2(candles, sigs, adx1h_min=25, ema1_filter=True, sl_mult=2.2), mk)
    row("ADX>25 + EMA1h + macro + SL×1.8",
        run_v2(candles, sigs, adx1h_min=25, ema1_filter=True, macro_filter="aligned", sl_mult=1.8), mk)
    row("ADX>25 + EMA1h + macro + SL×2.2",
        run_v2(candles, sigs, adx1h_min=25, ema1_filter=True, macro_filter="aligned", sl_mult=2.2), mk)
    row("ADX>25 + EMA1h + CVD trend",
        run_v2(candles, sigs, adx1h_min=25, ema1_filter=True, cvd_trend_filter=True), mk)
    row("ADX>25 + EMA1h + RSI4h",
        run_v2(candles, sigs, adx1h_min=25, ema1_filter=True, rsi4_filter=True), mk)
    row("ADX>25 + EMA1h + cooldown 1h",
        run_v2(candles, sigs, adx1h_min=25, ema1_filter=True, cooldown_h=1), mk)
    row("ADX>25 + EMA1h + cooldown 3h",
        run_v2(candles, sigs, adx1h_min=25, ema1_filter=True, cooldown_h=3), mk)
    row("SELL + ADX>25 + EMA1h + SL×2.2",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=25, ema1_filter=True, sl_mult=2.2), mk)
    row("BUY + ADX>25 + EMA1h",
        run_v2(candles, sigs, direction_only="BUY", adx1h_min=25, ema1_filter=True), mk)
    row("BUY + ADX>25 + EMA1h + macro BULL",
        run_v2(candles, sigs, direction_only="BUY", adx1h_min=25, ema1_filter=True, macro_filter="bull"), mk)

    # ─────────────────────────────────────────────────────────────────
    # E — TRIPLES COMBOS — macro + CVD trend + ADX>25
    # ─────────────────────────────────────────────────────────────────
    section("E — TRIPLES COMBOS — 3 filtres simultanés")
    row("ADX>25 + macro + CVD trend",
        run_v2(candles, sigs, adx1h_min=25, macro_filter="aligned", cvd_trend_filter=True), mk)
    row("ADX>25 + macro + CVD trend + EMA1h",
        run_v2(candles, sigs, adx1h_min=25, macro_filter="aligned", cvd_trend_filter=True, ema1_filter=True), mk)
    row("ADX>25 + macro + CVD trend + SL×2.2",
        run_v2(candles, sigs, adx1h_min=25, macro_filter="aligned", cvd_trend_filter=True, sl_mult=2.2), mk)
    row("ADX>25 + macro + RSI4h",
        run_v2(candles, sigs, adx1h_min=25, macro_filter="aligned", rsi4_filter=True), mk)
    row("ADX>25 + macro + RSI4h + EMA1h",
        run_v2(candles, sigs, adx1h_min=25, macro_filter="aligned", rsi4_filter=True, ema1_filter=True), mk)
    row("ADX>25 + CVD trend + RSI4h",
        run_v2(candles, sigs, adx1h_min=25, cvd_trend_filter=True, rsi4_filter=True), mk)
    row("ADX>25 + CVD trend + EMA1h + macro",
        run_v2(candles, sigs, adx1h_min=25, cvd_trend_filter=True, ema1_filter=True, macro_filter="aligned"), mk)
    row("ADX>22 + macro + CVD trend",
        run_v2(candles, sigs, adx1h_min=22, macro_filter="aligned", cvd_trend_filter=True), mk)
    row("SELL + ADX>25 + macro + CVD trend",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=25, macro_filter="bear", cvd_trend_filter=True), mk)
    row("SELL + ADX>25 + macro + RSI4h",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=25, macro_filter="bear", rsi4_filter=True), mk)
    row("SELL + ADX>25 + CVD trend + RSI4h",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=25, cvd_trend_filter=True, rsi4_filter=True), mk)
    row("SELL + ADX>25 + CVD trend + EMA1h",
        run_v2(candles, sigs, direction_only="SELL", adx1h_min=25, cvd_trend_filter=True, ema1_filter=True), mk)
    row("SELL + macro + CVD trend + EMA1h",
        run_v2(candles, sigs, direction_only="SELL", macro_filter="bear", cvd_trend_filter=True, ema1_filter=True), mk)
    row("SELL + RSI4h + macro + CVD trend",
        run_v2(candles, sigs, direction_only="SELL", rsi4_filter=True, macro_filter="bear", cvd_trend_filter=True), mk)
    row("BUY + ADX>25 + macro + CVD trend",
        run_v2(candles, sigs, direction_only="BUY", adx1h_min=25, macro_filter="bull", cvd_trend_filter=True), mk)

    # ─────────────────────────────────────────────────────────────────
    # F — COOLDOWN IMPACT
    # ─────────────────────────────────────────────────────────────────
    section("F — COOLDOWN × meilleures configs (1h / 2h / 3h)")
    for cd in [1, 2, 3]:
        row(f"F5 baseline cooldown {cd}h",
            run_v2(candles, sigs, cooldown_h=cd), mk)
    for cd in [1, 2, 3]:
        row(f"ADX>25 + macro cooldown {cd}h",
            run_v2(candles, sigs, adx1h_min=25, macro_filter="aligned", cooldown_h=cd), mk)
    for cd in [1, 2, 3]:
        row(f"SELL baseline cooldown {cd}h",
            run_v2(candles, sigs, direction_only="SELL", cooldown_h=cd), mk)
    for cd in [1, 2, 3]:
        row(f"ADX>25 + CVD trend cooldown {cd}h",
            run_v2(candles, sigs, adx1h_min=25, cvd_trend_filter=True, cooldown_h=cd), mk)

    # ─────────────────────────────────────────────────────────────────
    # G — TOP 20 CONFIGS v4 — récap
    # ─────────────────────────────────────────────────────────────────
    section("G — TOP CONFIGS v4 (récap général)")
    top = [
        ("ADX>25 + macro aligné",                       dict(adx1h_min=25, macro_filter="aligned")),
        ("ADX>25 + macro + CVD trend",                  dict(adx1h_min=25, macro_filter="aligned", cvd_trend_filter=True)),
        ("ADX>25 + macro + SL×2.2",                     dict(adx1h_min=25, macro_filter="aligned", sl_mult=2.2)),
        ("ADX>25 + macro + RSI4h",                      dict(adx1h_min=25, macro_filter="aligned", rsi4_filter=True)),
        ("ADX>25 + CVD trend",                          dict(adx1h_min=25, cvd_trend_filter=True)),
        ("ADX>25 + CVD trend + macro",                  dict(adx1h_min=25, cvd_trend_filter=True, macro_filter="aligned")),
        ("ADX>25 + CVD trend + SL×2.2",                 dict(adx1h_min=25, cvd_trend_filter=True, sl_mult=2.2)),
        ("ADX>25 + EMA1h",                              dict(adx1h_min=25, ema1_filter=True)),
        ("ADX>25 + EMA1h + SL×2.2",                     dict(adx1h_min=25, ema1_filter=True, sl_mult=2.2)),
        ("SELL + RSI4h",                                dict(direction_only="SELL", rsi4_filter=True)),
        ("SELL + RSI4h + SL×2.2",                       dict(direction_only="SELL", rsi4_filter=True, sl_mult=2.2)),
        ("SELL + RSI4h + ADX>20",                       dict(direction_only="SELL", rsi4_filter=True, adx1h_min=20)),
        ("SELL + RSI4h + CVD trend",                    dict(direction_only="SELL", rsi4_filter=True, cvd_trend_filter=True)),
        ("SELL baseline",                               dict(direction_only="SELL")),
        ("SELL + ADX>25 + CVD trend",                   dict(direction_only="SELL", adx1h_min=25, cvd_trend_filter=True)),
        ("SELL + CVD trend",                            dict(direction_only="SELL", cvd_trend_filter=True)),
        ("SELL + ADX>25 + macro + CVD trend",           dict(direction_only="SELL", adx1h_min=25, macro_filter="bear", cvd_trend_filter=True)),
        ("SELL + macro + CVD trend + EMA1h",            dict(direction_only="SELL", macro_filter="bear", cvd_trend_filter=True, ema1_filter=True)),
        ("ADX>22 + macro + CVD trend",                  dict(adx1h_min=22, macro_filter="aligned", cvd_trend_filter=True)),
        ("ADX>25 + macro + CVD trend + SL×2.2",         dict(adx1h_min=25, macro_filter="aligned", cvd_trend_filter=True, sl_mult=2.2)),
    ]
    for label, kwargs in top:
        row(label, run_v2(candles, sigs, **kwargs), mk)

    # ─────────────────────────────────────────────────────────────────
    # H — BREAKDOWN ANNUEL — top configs v4
    # ─────────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  ▶ H — BREAKDOWN ANNUEL (top configs v4)")
    print(SEP)
    annual = [
        ("F5 baseline",                         dict()),
        ("ADX>25 + macro",                      dict(adx1h_min=25, macro_filter="aligned")),
        ("ADX>25 + macro + CVD trend",          dict(adx1h_min=25, macro_filter="aligned", cvd_trend_filter=True)),
        ("ADX>25 + CVD trend",                  dict(adx1h_min=25, cvd_trend_filter=True)),
        ("ADX>25 + EMA1h + SL×2.2",             dict(adx1h_min=25, ema1_filter=True, sl_mult=2.2)),
        ("SELL + RSI4h",                        dict(direction_only="SELL", rsi4_filter=True)),
        ("SELL baseline",                       dict(direction_only="SELL")),
        ("SELL + CVD trend",                    dict(direction_only="SELL", cvd_trend_filter=True)),
        ("SELL + ADX>25 + macro + CVD trend",   dict(direction_only="SELL", adx1h_min=25, macro_filter="bear", cvd_trend_filter=True)),
    ]
    for label, kwargs in annual:
        t = run_v2(candles, sigs, **kwargs)
        yearly_breakdown(candles, t, label)

    # Exit reasons pour les tops
    print()
    t1 = run_v2(candles, sigs, adx1h_min=25, macro_filter="aligned", cvd_trend_filter=True)
    t2 = run_v2(candles, sigs, direction_only="SELL", rsi4_filter=True)
    t3 = run_v2(candles, sigs, adx1h_min=25, cvd_trend_filter=True)
    exit_reasons(t1, "ADX>25+macro+CVD_trend")
    exit_reasons(t2, "SELL+RSI4h")
    exit_reasons(t3, "ADX>25+CVD_trend")

    # ─────────────────────────────────────────────────────────────────
    # RÉSUMÉ
    # ─────────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print(f"  Meilleur Win Rate : {mk['wr']:.1f}%")
    print(f"  Meilleur Sharpe   : {mk['sh']:+.2f}")
    print(f"  (◄WR / ◄SH dans les tableaux)")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
