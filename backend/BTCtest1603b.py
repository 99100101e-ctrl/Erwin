"""
BTCtest1603b.py — Test toutes combinaisons de filtres
======================================================
Variables testees :
  - HeuresFR    : on / off
  - Score seuil : 70 / 60
  - ADX min     : 25 / 20
  - Cooldown    : 2h / 1h

= 16 combinaisons

Usage :
    python backend/BTCtest1603b.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from bt_common import load_real_candles, TRADE_SIZE
from backtest_2ans import (
    precompute_full, section, row, HDR, SEP,
    yearly_breakdown, exit_reasons, stats,
    _sim_custom_sl,
)
from backtest_v2 import enrich_signals
from backtest_v6 import enrich_v6
from datetime import datetime, timezone
from collections import defaultdict

FR_HOURS = set(range(8, 22)) - {16, 17, 18}


def run_bot(candles, sigs,
            thresh=70, sl_mult=2.0, cooldown_h=2,
            adx1h_min=25,
            macro_field="ema100_trend",
            macro_mode="aligned",
            rsi4_filter=False,
            fr_hours_filter=True):
    trades = []
    end_idx = 0
    prev = 0
    last_ts = {"BUY": 0, "SELL": 0}

    for s in sigs:
        if s["idx"] < end_idx:
            prev = s["score"]
            continue
        if not (prev < thresh <= s["score"]):
            prev = s["score"]
            continue
        prev = s["score"]

        d  = s["direction"]
        mt = s.get(macro_field, "neutral")

        if macro_mode == "aligned":
            if mt == "bull"    and d != "BUY":  continue
            if mt == "bear"    and d != "SELL": continue
            if mt == "neutral":                 continue

        if adx1h_min > 0 and s.get("adx1h", 0) < adx1h_min:
            continue

        if fr_hours_filter:
            dt = datetime.fromtimestamp(s["ts"], tz=timezone.utc)
            if dt.hour not in FR_HOURS:
                continue

        if rsi4_filter and s.get("rsi4") is not None:
            if d == "BUY"  and s["rsi4"] >= 50: continue
            if d == "SELL" and s["rsi4"] <= 50: continue

        if cooldown_h > 0 and (s["ts"] - last_ts[d]) < cooldown_h * 3600:
            continue

        pnl, rsn, bars = _sim_custom_sl(candles, s["idx"], d, s["atr"], sl_mult)
        if rsn == "skip":
            continue

        last_ts[d] = s["ts"]
        trades.append({
            **s,
            "pnl_pct": pnl * 100,
            "pnl_eur": pnl * TRADE_SIZE,
            "reason":  rsn,
            "bars":    bars,
        })
        end_idx = s["idx"] + bars + 4

    return trades


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
        bar = "+" * int(abs(net) / 30) if net >= 0 else "-" * int(abs(net) / 30)
        print(f"  {yr}-{mo:02d} | N={len(pnls):2d} | WR {wr:4.0f}% | {net:+6.0f}EUR | {bar}")


def main():
    print("\n" + "=" * 80)
    print("  BTCtest1603b — Test toutes combinaisons de filtres")
    print("  EMA100d + ADX(20/25) + HeuresFR(on/off) + Score(60/70) + Cooldown(1h/2h)")
    print("=" * 80)

    candles = load_real_candles()
    n_years = (candles[-1]["ts"] - candles[0]["ts"]) / (365.25 * 86400)
    print(f"  Duree : {n_years:.1f} an(s)\n")

    sigs_base = precompute_full(candles)
    sigs_v2   = enrich_signals(candles, sigs_base)
    sigs      = enrich_v6(candles, sigs_v2)

    mk = {"wr": 0.0, "sh": -999.0}

    # ── 16 combinaisons ─────────────────────────────────────────────────────
    configs = []
    for thresh in [70, 60]:
        for adx in [25, 20]:
            for fr in [True, False]:
                for cd in [2, 1]:
                    label = (
                        f"Score>={thresh} | ADX>{adx} | "
                        f"HeuresFR={'oui' if fr else 'non'} | "
                        f"Cooldown={cd}h"
                    )
                    params = dict(
                        thresh          = thresh,
                        adx1h_min       = adx,
                        fr_hours_filter = fr,
                        cooldown_h      = cd,
                        sl_mult         = 2.0,
                        macro_field     = "ema100_trend",
                        macro_mode      = "aligned",
                        rsi4_filter     = False,
                    )
                    configs.append((label, params))

    section("TOUTES COMBINAISONS — classement par Sharpe")
    print(HDR)

    results = []
    for label, params in configs:
        t = run_bot(candles, sigs, **params)
        row(label, t, mk)
        s = stats(t)
        results.append((label, t, s, params))

    # ── Top 5 par Sharpe ─────────────────────────────────────────────────────
    ranked = [(l, t, s, p) for l, t, s, p in results if s is not None]
    ranked.sort(key=lambda x: x[2]["sh"], reverse=True)

    print(f"\n{SEP}")
    print("  TOP 5 — meilleur Sharpe")
    print(SEP)
    print(HDR)
    for label, t, s, _ in ranked[:5]:
        row(f"  {label}", t, mk)

    print(f"\n{SEP}")
    print("  TOP 5 — meilleur Net EUR")
    print(SEP)
    ranked_net = sorted(ranked, key=lambda x: x[2]["net_eur"], reverse=True)
    print(HDR)
    for label, t, s, _ in ranked_net[:5]:
        row(f"  {label}", t, mk)

    print(f"\n{SEP}")
    print("  TOP 5 — meilleur Win Rate")
    print(SEP)
    ranked_wr = sorted(ranked, key=lambda x: x[2]["wr"], reverse=True)
    print(HDR)
    for label, t, s, _ in ranked_wr[:5]:
        row(f"  {label}", t, mk)

    # ── Meilleure config : detail complet ────────────────────────────────────
    if ranked:
        best_label, best_trades, best_stats, best_params = ranked[0]
        print(f"\n{SEP}")
        print(f"  MEILLEURE CONFIG (Sharpe) : {best_label}")
        print(SEP)
        if best_stats:
            print(f"     N trades  : {best_stats['n']}")
            print(f"     Win Rate  : {best_stats['wr']:.1f}%")
            print(f"     Sharpe    : {best_stats['sh']:+.2f}")
            print(f"     MDD       : -{best_stats['mdd']*100:.1f}%")
            print(f"     Net total : {best_stats['net_eur']:+.0f} EUR")
            print(f"     Avg/trade : {best_stats['avg_eur']:+.0f} EUR")

        print(f"\n{SEP}")
        print("  BREAKDOWN ANNUEL — meilleure config")
        print(SEP)
        yearly_breakdown(candles, best_trades, best_label)

        print(f"\n{SEP}")
        exit_reasons(best_trades, best_label)
        print_monthly(candles, best_trades, best_label)

    # ── Config bot actuel pour reference ─────────────────────────────────────
    bot_label = "Score>=70 | ADX>25 | HeuresFR=oui | Cooldown=2h"
    bot_entry = next((x for x in results if x[0] == bot_label), None)
    if bot_entry:
        _, bot_trades, bot_stats, _ = bot_entry
        print(f"\n{SEP}")
        print(f"  BOT ACTUEL (reference) : {bot_label}")
        print(SEP)
        if bot_stats:
            print(f"     N trades  : {bot_stats['n']}")
            print(f"     Win Rate  : {bot_stats['wr']:.1f}%")
            print(f"     Sharpe    : {bot_stats['sh']:+.2f}")
            print(f"     MDD       : -{bot_stats['mdd']*100:.1f}%")
            print(f"     Net total : {bot_stats['net_eur']:+.0f} EUR")
            print(f"     Avg/trade : {bot_stats['avg_eur']:+.0f} EUR")

    print(f"\n{'=' * 80}\n")


if __name__ == "__main__":
    main()
