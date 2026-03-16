"""
BTCtest1603.py — Backtest bot live actuel (16 mars 2026)
=========================================================
Filtres exacts du bot (signal_engine.py) :
  - Score >= 70
  - EMA100 daily aligne (BUY si bull, SELL si bear)
  - ADX 1h > 25
  - Heures FR : 8h-21h UTC, hors US open (16h-18h)
  - SL x 2.0 | TP1=1.0xR | TP2=2.5xR | TP3=5.0xR
  - Cooldown 2h
  RSI 4h : retire du bot live (reduisait 54 -> 8 trades sur 2 ans)

Usage :
    python fetch_btc_data.py          # telecharge 2 ans de donnees
    python backend/BTCtest1603.py     # lance le backtest
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

# Heures actives : 8h-21h UTC inclus, hors US open (16h, 17h, 18h)
FR_HOURS = set(range(8, 22)) - {16, 17, 18}


def run_bot(candles, sigs,
            thresh=70, sl_mult=2.0, cooldown_h=2,
            adx1h_min=25,
            macro_field="ema100_trend",
            macro_mode="aligned",
            rsi4_filter=False,
            fr_hours_filter=True):
    """
    Simule les filtres du bot live (signal_engine.py) :
      1. EMA100 daily aligne
      2. ADX 1h > 25
      3. Heures FR (8h-21h UTC, hors 16h-18h)
      4. Cooldown 2h par direction
      5. RSI 4h (optionnel, desactive par defaut)
    """
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

        # 1. EMA100 daily
        if macro_mode == "aligned":
            if mt == "bull"    and d != "BUY":  continue
            if mt == "bear"    and d != "SELL": continue
            if mt == "neutral":                 continue

        # 2. ADX 1h > 25
        if adx1h_min > 0 and s.get("adx1h", 0) < adx1h_min:
            continue

        # 3. Heures FR
        if fr_hours_filter:
            dt = datetime.fromtimestamp(s["ts"], tz=timezone.utc)
            if dt.hour not in FR_HOURS:
                continue

        # 4. RSI 4h (optionnel)
        if rsi4_filter and s.get("rsi4") is not None:
            if d == "BUY"  and s["rsi4"] >= 50: continue
            if d == "SELL" and s["rsi4"] <= 50: continue

        # 5. Cooldown 2h
        if cooldown_h > 0 and (s["ts"] - last_ts[d]) < cooldown_h * 3600:
            continue

        # Simulation
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
    print("  BTCtest1603 — Backtest bot live actuel (16 mars 2026)")
    print("  Config : EMA100d + ADX>25 + HeuresFR + SL×2.0 + Cooldown 2h")
    print("=" * 80)

    candles = load_real_candles()
    n_years = (candles[-1]["ts"] - candles[0]["ts"]) / (365.25 * 86400)
    print(f"  Duree : {n_years:.1f} an(s)\n")

    if n_years < 1.5:
        print("  ATTENTION : moins de 1.5 an de donnees.")
        print("  Lance fetch_btc_data.py pour obtenir 2 ans.\n")

    sigs_base = precompute_full(candles)
    sigs_v2   = enrich_signals(candles, sigs_base)
    sigs      = enrich_v6(candles, sigs_v2)

    mk = {"wr": 0.0, "sh": -999.0}

    BASE = dict(
        thresh          = 70,
        adx1h_min       = 25,
        sl_mult         = 2.0,
        cooldown_h      = 2,
        macro_field     = "ema100_trend",
        macro_mode      = "aligned",
        rsi4_filter     = False,
        fr_hours_filter = True,
    )

    # ── Tableau comparatif ───────────────────────────────────────────────────
    section("IMPACT DE CHAQUE FILTRE")
    print(HDR)

    configs = [
        ("EMA100d + ADX>25 (base, 24h/24)",          dict(fr_hours_filter=False, rsi4_filter=False)),
        ("+ Heures FR  <-- BOT ACTUEL",               dict(fr_hours_filter=True,  rsi4_filter=False)),
        ("+ Heures FR + RSI 4h (comparaison)",        dict(fr_hours_filter=True,  rsi4_filter=True)),
    ]

    results = {}
    for label, extra in configs:
        t = run_bot(candles, sigs, **{**BASE, **extra})
        row(label, t, mk)
        results[label] = t

    # ── Detail bot actuel ────────────────────────────────────────────────────
    bot_label = "+ Heures FR  <-- BOT ACTUEL"
    bot = results[bot_label]
    s   = stats(bot)

    print(f"\n{SEP}")
    print("  DETAIL BOT ACTUEL — BUY vs SELL")
    print(SEP)
    if s:
        buys  = [t for t in bot if t["direction"] == "BUY"]
        sells = [t for t in bot if t["direction"] == "SELL"]
        print(HDR)
        row("  BUY  (EMA100d BULL)", buys,  mk)
        row("  SELL (EMA100d BEAR)", sells, mk)

    # ── Breakdown annuel ─────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  BREAKDOWN ANNUEL")
    print(SEP)
    for label, _ in configs:
        yearly_breakdown(candles, results[label], label)

    # ── Raisons de sortie + P&L mensuel ─────────────────────────────────────
    if s:
        print(f"\n{SEP}")
        exit_reasons(bot, bot_label)
        print_monthly(candles, bot, bot_label)

    # ── Resume final ─────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("  RESULTAT BOT ACTUEL")
    if s:
        print(f"     N trades  : {s['n']}")
        print(f"     Win Rate  : {s['wr']:.1f}%")
        print(f"     Sharpe    : {s['sh']:+.2f}")
        print(f"     MDD       : -{s['mdd']*100:.1f}%")
        print(f"     Net total : {s['net_eur']:+.0f} EUR")
        print(f"     Avg/trade : {s['avg_eur']:+.0f} EUR")
    else:
        print("  Pas assez de trades (< 3)")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
