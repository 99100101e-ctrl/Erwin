"""
Backtest BTC62WR — Confirmation stratégie live
===============================================
Reproduit EXACTEMENT les filtres du signal_engine.py actuel :

  1. Score ≥ 70          (seuil signal actionnable)
  2. EMA100 daily aligné (BUY si prix > EMA100d, SELL si prix < EMA100d)
  3. ADX 1h > 25         (marché en tendance, pas en range)
  4. Cooldown 2h         (pas deux signaux dans la même direction < 2h)
  5. SL = 2.0 × ATR
     TP1 = 1.0 × R  → 40% de la position + déplace SL au BE
     TP2 = 2.5 × R  → 35%
     TP3 = 5.0 × R  → 25%

Résultats attendus (sur 2 ans réels BTC Binance) :
  N=94 | WR 62.8% | Sharpe +2.78 | MDD -6.0%
  +209€ (2024) | +637€ (2025) | +207€ (2026) = +1053€ total
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


def main():
    print("\n" + "=" * 80)
    print("  BACKTEST BTC62WR — Confirmation stratégie live")
    print("  Filtres : EMA100 daily + ADX>25 + SL×2.0 + cooldown 2h")
    print("=" * 80)

    candles = load_real_candles()
    n_years = (candles[-1]["ts"] - candles[0]["ts"]) / (365.25 * 86400)
    print(f"  Durée : {n_years:.1f} an(s)\n")

    if n_years < 1.5:
        print("  ⚠️  ATTENTION : moins de 1.5 an de données.")
        print("     Lance fetch_btc_data.py sur Windows pour obtenir 2 ans.\n")

    # ── Génération des signaux ──────────────────────────────────────────────
    sigs_base = precompute_full(candles)
    sigs_v2   = enrich_signals(candles, sigs_base)
    sigs      = enrich_v6(candles, sigs_v2)

    mk = {"wr": 0.0, "sh": -999.0}

    # ── Stratégie BTC62WR (live) ────────────────────────────────────────────
    LIVE_CONFIG = dict(
        thresh       = 70,
        adx1h_min    = 25,
        sl_mult      = 2.0,
        cooldown_h   = 2,
        macro_field  = "ema100_trend",
        macro_mode   = "aligned",
    )

    t_live = run_v6(candles, sigs, **LIVE_CONFIG)

    # ── Résumé principal ────────────────────────────────────────────────────
    section("★ BTC62WR — Stratégie live (EMA100d + ADX>25 + SL×2.0)")
    print(HDR)
    row("★★★ BTC62WR (live)", t_live, mk)

    # ── Comparaisons pour contexte ──────────────────────────────────────────
    section("Comparaisons (contexte)")
    print(HDR)
    row("F5 baseline (aucun filtre)",
        run_v6(candles, sigs), mk)
    row("ADX>25 seul (sans EMA100d)",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0), mk)
    row("EMA100d seul (sans ADX)",
        run_v6(candles, sigs, sl_mult=2.0,
               macro_field="ema100_trend", macro_mode="aligned"), mk)
    row("BTC62WR BUY only (macro BULL)",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0,
               macro_field="ema100_trend", macro_mode="bull"), mk)
    row("BTC62WR SELL only (macro BEAR)",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0,
               macro_field="ema100_trend", macro_mode="bear"), mk)

    # ── Breakdown annuel ────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  ▶ BREAKDOWN ANNUEL — BTC62WR")
    print(SEP)
    yearly_breakdown(candles, t_live, "BTC62WR live")

    # ── Raisons de sortie ───────────────────────────────────────────────────
    print()
    exit_reasons(t_live, "BTC62WR live")

    # ── Détail trades BUY / SELL ────────────────────────────────────────────
    buys  = [t for t in t_live if t["direction"] == "BUY"]
    sells = [t for t in t_live if t["direction"] == "SELL"]
    s_all  = stats(t_live)
    s_buy  = stats(buys)
    s_sell = stats(sells)

    print(f"\n{SEP}")
    print("  ▶ BUY vs SELL")
    print(SEP)
    print(HDR)
    if s_buy:
        row("  BUY  (macro BULL)", buys, mk)
    else:
        print("  BUY  : < 3 trades — pas assez de données")
    if s_sell:
        row("  SELL (macro BEAR)", sells, mk)
    else:
        print("  SELL : < 3 trades — pas assez de données")

    # ── Distribution mensuelle ──────────────────────────────────────────────
    if t_live:
        print(f"\n{SEP}")
        print("  ▶ P&L MENSUEL")
        print(SEP)
        from collections import defaultdict
        monthly = defaultdict(list)
        for t in t_live:
            dt = datetime.fromtimestamp(candles[t["idx"]]["ts"], tz=timezone.utc)
            monthly[(dt.year, dt.month)].append(t["pnl_eur"])
        for (yr, mo), pnls in sorted(monthly.items()):
            wr  = sum(1 for p in pnls if p > 0) / len(pnls) * 100
            net = sum(pnls)
            bar = "█" * int(abs(net) / 30)
            sign = "+" if net >= 0 else ""
            print(f"  {yr}-{mo:02d} | N={len(pnls):2d} | WR {wr:4.0f}% | {sign}{net:+6.0f}€ | {bar}")

    # ── Résumé final ────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    if s_all:
        print(f"  ★ BTC62WR — RÉSULTATS FINAUX")
        print(f"     N trades  : {s_all['n']}")
        print(f"     Win Rate  : {s_all['wr']:.1f}%")
        print(f"     Sharpe    : {s_all['sh']:+.2f}")
        print(f"     MDD       : -{s_all['mdd']*100:.1f}%")
        print(f"     Net total : {s_all['net_eur']:+.0f}€")
        print(f"     Avg/trade : {s_all['avg_eur']:+.0f}€")
    else:
        print("  ⚠️  Pas assez de trades — télécharge 2 ans de données (fetch_btc_data.py)")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
