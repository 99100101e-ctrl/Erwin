"""
Backtest BTC62WR — Confirmation bot live (état restauré v7)
============================================================
Config exacte du bot actuel :
  - Score ≥ 70
  - EMA100 daily aligné (BUY si bull, SELL si bear)
  - ADX 1h > 25
  - Heures FR : 8h-21h UTC, hors US open (16h-18h)
  - RSI 4h : BUY si RSI4h < 50, SELL si RSI4h > 50
  - SL × 2.0 | TP1=1.0xR | TP2=2.5xR | TP3=5.0xR
  - Cooldown 2h
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


def run_bot_actuel(candles, sigs,
                   thresh=70, sl_mult=2.0, cooldown_h=2,
                   adx1h_min=25,
                   macro_field="ema100_trend",
                   macro_mode="aligned",
                   rsi4_filter=True,
                   fr_hours_filter=True):
    """
    Reproduit exactement les filtres de suppression du bot live (signal_engine.py) :
      1. EMA100 daily aligné (BUY si bull, SELL si bear)
      2. ADX 1h > 25
      3. Heures FR (8h-21h UTC, hors 16h-18h)
      4. RSI 4h (BUY si RSI4h < 50, SELL si RSI4h > 50)
      5. Cooldown 2h par direction

    Les filtres sont appliqués sur les signaux AVANT la simulation du trade,
    ce qui est fidèle au comportement live (un signal filtré ne déclenche pas
    de cooldown et ne bloque pas l'entrée suivante).
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

        # ── Filtre EMA100 daily ──────────────────────────────────────────────
        if macro_mode == "aligned":
            if mt == "bull" and d != "BUY":  continue
            if mt == "bear" and d != "SELL": continue
            if mt == "neutral":              continue

        # ── Filtre ADX 1h > 25 ──────────────────────────────────────────────
        if adx1h_min > 0 and s.get("adx1h", 0) < adx1h_min:
            continue

        # ── Filtre heures FR (8h-21h UTC, hors 16h-18h) ─────────────────────
        if fr_hours_filter:
            dt = datetime.fromtimestamp(s["ts"], tz=timezone.utc)
            if dt.hour not in FR_HOURS:
                continue

        # ── Filtre RSI 4h ────────────────────────────────────────────────────
        if rsi4_filter and s.get("rsi4") is not None:
            if d == "BUY"  and s["rsi4"] >= 50: continue
            if d == "SELL" and s["rsi4"] <= 50: continue

        # ── Cooldown 2h par direction ────────────────────────────────────────
        if cooldown_h > 0 and (s["ts"] - last_ts[d]) < cooldown_h * 3600:
            continue

        # ── Simulation du trade ──────────────────────────────────────────────
        pnl, rsn, bars = _sim_custom_sl(candles, s["idx"], d, s["atr"], sl_mult)
        if rsn == "skip":
            continue

        last_ts[d] = s["ts"]
        trades.append({
            **s,
            "pnl_pct": pnl * 100,
            "pnl_eur": pnl * TRADE_SIZE,
            "reason": rsn,
            "bars": bars,
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
        bar = "█" * int(abs(net) / 30)
        sign = "+" if net >= 0 else ""
        print(f"  {yr}-{mo:02d} | N={len(pnls):2d} | WR {wr:4.0f}% | {sign}{net:+6.0f}€ | {bar}")


def main():
    print("\n" + "=" * 80)
    print("  BACKTEST BTC62WR — Confirmation bot live (état restauré v7)")
    print("  EMA100 daily + ADX>25 + Heures FR + RSI 4h + SL×2.0 + cooldown 2h")
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

    mk = {"wr": 0.0, "sh": -999.0}

    BASE = dict(
        thresh           = 70,
        adx1h_min        = 25,
        sl_mult          = 2.0,
        cooldown_h       = 2,
        macro_field      = "ema100_trend",
        macro_mode       = "aligned",
    )

    # ── Tableau comparatif : impact de chaque filtre ────────────────────────
    section("BOT LIVE — IMPACT DE CHAQUE FILTRE")
    print(HDR)

    configs = [
        ("EMA100 + ADX>25 seulement          (base)",  dict(rsi4_filter=False, fr_hours_filter=False)),
        ("+ Heures FR (8h-21h, hors 16-18h)",          dict(rsi4_filter=False, fr_hours_filter=True)),
        ("+ RSI 4h seulement",                         dict(rsi4_filter=True,  fr_hours_filter=False)),
        ("+ Heures FR + RSI 4h  ← BOT ACTUEL",        dict(rsi4_filter=True,  fr_hours_filter=True)),
    ]

    results = {}
    for label, extra in configs:
        t = run_bot_actuel(candles, sigs, **extra, **BASE)
        row(label, t, mk)
        results[label] = t

    # ── Config bot actuel : détail complet ──────────────────────────────────
    bot_label = "+ Heures FR + RSI 4h  ← BOT ACTUEL"
    bot = results[bot_label]
    s   = stats(bot)

    print(f"\n{SEP}")
    print(f"  ▶ DÉTAIL BOT ACTUEL — BUY vs SELL")
    print(SEP)

    if s:
        buys  = [t for t in bot if t["direction"] == "BUY"]
        sells = [t for t in bot if t["direction"] == "SELL"]
        print(HDR)
        row("  BUY  (macro BULL + EMA100 daily)", buys,  mk)
        row("  SELL (macro BEAR + EMA100 daily)", sells, mk)

    # ── Breakdown annuel par config ──────────────────────────────────────────
    print(f"\n{SEP}")
    print("  ▶ BREAKDOWN ANNUEL PAR CONFIG")
    print(SEP)
    for label, _ in configs:
        yearly_breakdown(candles, results[label], label)

    # ── Sortie détaillée du bot actuel ──────────────────────────────────────
    if s:
        print(f"\n{SEP}")
        exit_reasons(bot, bot_label)
        print_monthly(candles, bot, bot_label)

    # ── Résumé final ────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("  ★ BOT ACTUEL (EMA100d + ADX>25 + HeuresFR + RSI4h + SL×2.0)")
    if s:
        print(f"     N trades  : {s['n']}")
        print(f"     Win Rate  : {s['wr']:.1f}%")
        print(f"     Sharpe    : {s['sh']:+.2f}")
        print(f"     MDD       : -{s['mdd']*100:.1f}%")
        print(f"     Net total : {s['net_eur']:+.0f}€")
        print(f"     Avg/trade : {s['avg_eur']:+.0f}€")
    else:
        print("  ⚠️  Pas assez de trades pour les statistiques")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
