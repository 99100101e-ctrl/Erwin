"""
BTCtest_adx20.py — Backtest du bot v8 (ADX >= 20)
==================================================
Reproduction EXACTE du signal_engine.py mis à jour :
  - Score >= 70
  - EMA100 daily aligné
  - ADX 1h >= 20  (↓ vs 25 du bot précédent)
  - Heures FR : 8h-21h UTC, hors US open (16h-18h)
  - Cooldown 2h
  - SL×2.0 | TP1=1.0xR | TP2=2.5xR | TP3=5.0xR

Usage :
    python fetch_btc_data.py          # telecharge 2 ans de donnees
    python backend/BTCtest_adx20.py   # lance le backtest
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
            adx1h_min=20,
            macro_field="ema100_trend",
            macro_mode="aligned",
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

        # 1. EMA100 daily aligné
        if macro_mode == "aligned":
            if mt == "bull"    and d != "BUY":  continue
            if mt == "bear"    and d != "SELL": continue
            if mt == "neutral":                 continue

        # 2. ADX 1h >= 20
        if adx1h_min > 0 and s.get("adx1h", 0) < adx1h_min:
            continue

        # 3. Heures FR
        if fr_hours_filter:
            dt = datetime.fromtimestamp(s["ts"], tz=timezone.utc)
            if dt.hour not in FR_HOURS:
                continue

        # 4. Cooldown 2h
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
    print(f"  {'Mois':<10} | {'N':>4} | {'WR':>6} | {'Net EUR':>9} | Barre")
    print(f"  {'-'*10}-+-{'-'*4}-+-{'-'*6}-+-{'-'*9}-+-{'-'*25}")
    monthly = defaultdict(list)
    for t in trades:
        dt = datetime.fromtimestamp(candles[t["idx"]]["ts"], tz=timezone.utc)
        monthly[(dt.year, dt.month)].append(t["pnl_eur"])
    for (yr, mo), pnls in sorted(monthly.items()):
        wr  = sum(1 for p in pnls if p > 0) / len(pnls) * 100
        net = sum(pnls)
        bar = "+" * int(abs(net) / 30) if net >= 0 else "-" * int(abs(net) / 30)
        print(f"  {yr}-{mo:02d}     | {len(pnls):>4} | {wr:>5.0f}% | {net:>+8.0f}€ | {bar}")


def main():
    print("\n" + "=" * 80)
    print("  BTCtest_adx20 — Backtest bot v8 (ADX >= 20)")
    print("  Config : EMA100d + ADX>=20 + HeuresFR + SL×2.0 + Cooldown 2h")
    print("=" * 80)

    candles = load_real_candles()
    n_years = (candles[-1]["ts"] - candles[0]["ts"]) / (365.25 * 86400)
    print(f"  Durée : {n_years:.1f} an(s)\n")

    if n_years < 1.5:
        print("  ATTENTION : moins de 1.5 an de données.")
        print("  Lance fetch_btc_data.py pour obtenir 2 ans.\n")

    sigs_base = precompute_full(candles)
    sigs_v2   = enrich_signals(candles, sigs_base)
    sigs      = enrich_v6(candles, sigs_v2)

    mk = {"wr": 0.0, "sh": -999.0}

    bot   = run_bot(candles, sigs)
    s     = stats(bot)
    label = "Bot v8 — EMA100d + ADX>=20 + HeuresFR + Cooldown 2h + SL×2.0"

    # ── Comparatif v7 (ADX>25) vs v8 (ADX>=20) ──────────────────────────────
    from BTCtest1603 import run_bot as run_v7
    bot_v7 = run_v7(candles, sigs, adx1h_min=25)

    section("COMPARATIF v7 (ADX>25) vs v8 (ADX>=20)")
    print(HDR)
    row("v7 — Bot précédent  (ADX >= 25)", bot_v7, mk)
    row("v8 — Bot ADX20      (ADX >= 20) ★", bot,    mk)

    # ── Détail BUY / SELL ────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  DÉTAIL v8 — BUY vs SELL")
    print(SEP)
    buys  = [t for t in bot if t["direction"] == "BUY"]
    sells = [t for t in bot if t["direction"] == "SELL"]
    print(HDR)
    row("  BUY  (EMA100d BULL)", buys,  mk)
    row("  SELL (EMA100d BEAR)", sells, mk)

    # ── Breakdown annuel ─────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  BREAKDOWN ANNUEL — v8")
    print(SEP)
    yearly_breakdown(candles, bot, label)

    # ── Sorties + P&L mensuel ─────────────────────────────────────────────────
    if s:
        print(f"\n{SEP}")
        exit_reasons(bot, label)
        print_monthly(candles, bot, label)

    # ── Résumé final ──────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("  RÉSULTAT BOT v8 (ADX >= 20)")
    if s:
        print(f"     N trades  : {s['n']}")
        print(f"     Win Rate  : {s['wr']:.1f}%")
        print(f"     Sharpe    : {s['sh']:+.2f}")
        print(f"     MDD       : -{s['mdd']*100:.1f}%")
        print(f"     Net total : {s['net_eur']:+.0f} EUR")
        print(f"     Avg/trade : {s['avg_eur']:+.0f} EUR")
        print(f"     Avg win   : {s['avg_win']:+.2f}%   Avg loss : {s['avg_loss']:+.2f}%")
    else:
        print("  Pas assez de trades (< 3)")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
