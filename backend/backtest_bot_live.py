"""
backtest_bot_live.py — Backtest exact du bot actuel en production
=================================================================
Reproduit fidèlement TOUS les filtres de signal_engine.py :

  Filtres ACTIFS en live :
    1. Score ≥ 70
    2. EMA100 daily aligné (BUY si bull, SELL si bear, skip neutral)
    3. ADX 1h > 25
    4. Heures françaises : 8h-21h UTC, excl. 16h-17h-18h (US Open)
    5. Cooldown 2h
    6. SL × 2.0 — Stratégie E (TP1=1R @ 40% | TP2=2.5R @ 35% | TP3=5R @ 25%)
    7. ATR ≤ 2.5% (filtre volatilité extrême)

  Métriques produites :
    - Tableau comparatif : bot live vs sans filtre ATR vs ref v7
    - Breakdown annuel complet (2024 / 2025 / 2026)
    - Breakdown mensuel détaillé
    - Exit reasons (SL / BE / TP1+timeout / TP2+timeout / TP3)

Usage :
    python backend/backtest_bot_live.py
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

# ── Heures FR identiques au signal_engine.py ─────────────────────────────────
# signal_engine bloque : hors 8h-21h UTC  +  US Open 16h-17h-18h UTC
# => autorisé : {8,9,10,11,12,13,14,15,19,20,21}
FR_HOURS = set(range(8, 22)) - {16, 17, 18}

ATR_MAX_PCT = 2.5   # filtre volatilité extrême (signal_engine.py ligne 168)


# ─────────────────────────────────────────────────────────────────────────────
def run_bot_live(candles, sigs,
                 thresh=70,
                 sl_mult=2.0,
                 cooldown_h=2,
                 adx1h_min=25,
                 macro_field="ema100_trend",
                 macro_mode="aligned",
                 fr_hours_filter=True,
                 atr_pct_max=ATR_MAX_PCT):
    """
    Simulation exacte du bot live.
    Tous les filtres correspondent ligne-à-ligne à signal_engine.py.
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

        # ── Filtre EMA100 daily (macro aligné) ───────────────────────────────
        if macro_mode == "aligned":
            if mt == "bull"    and d != "BUY":  continue
            if mt == "bear"    and d != "SELL": continue
            if mt == "neutral":                 continue

        # ── ADX 1h > 25 ──────────────────────────────────────────────────────
        if adx1h_min > 0 and s.get("adx1h", 0) < adx1h_min:
            continue

        # ── Heures françaises (incl. exclusion US Open) ───────────────────────
        if fr_hours_filter:
            dt = datetime.fromtimestamp(s["ts"], tz=timezone.utc)
            if dt.hour not in FR_HOURS:
                continue

        # ── ATR ≤ 2.5% — filtre volatilité extrême ───────────────────────────
        if atr_pct_max > 0:
            price = s.get("price", 0)
            atr   = s.get("atr", 0)
            if price > 0 and atr > 0:
                atr_pct = atr / price * 100
                if atr_pct > atr_pct_max:
                    continue

        # ── Cooldown 2h ───────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────────
def print_monthly(candles, trades, label):
    """Affiche la décomposition P&L mois par mois."""
    if not trades:
        print(f"\n  P&L mensuel — {label} : aucun trade")
        return
    print(f"\n  P&L mensuel — {label}")
    print(f"  {'Mois':<10} | {'N':>4} | {'WR':>6} | {'Net EUR':>9} | Barre")
    print(f"  {'-'*10}-+-{'-'*4}-+-{'-'*6}-+-{'-'*9}-+-{'-'*24}")
    monthly = defaultdict(list)
    for t in trades:
        dt = datetime.fromtimestamp(candles[t["idx"]]["ts"], tz=timezone.utc)
        monthly[(dt.year, dt.month)].append(t["pnl_eur"])
    for (yr, mo), pnls in sorted(monthly.items()):
        wr  = sum(1 for p in pnls if p > 0) / len(pnls) * 100
        net = sum(pnls)
        bar = ("+" * int(abs(net) / 30)) if net >= 0 else ("-" * int(abs(net) / 30))
        sign = "+" if net >= 0 else ""
        print(f"  {yr}-{mo:02d}     | {len(pnls):>4} | {wr:>5.0f}% | {sign}{net:>8.0f}€ | {bar}")


# ─────────────────────────────────────────────────────────────────────────────
def print_detail(candles, trades, label):
    """Affiche yearly + exit reasons + monthly pour une config."""
    print(f"\n{SEP}")
    print(f"  {label}")
    print(SEP)
    s = stats(trades)
    if s:
        print(f"  N trades   : {s['n']}")
        print(f"  Win Rate   : {s['wr']:.1f}%")
        print(f"  Sharpe     : {s['sh']:+.2f}")
        print(f"  MDD        : -{s['mdd']*100:.1f}%")
        print(f"  Net total  : {s['net_eur']:+.0f} EUR")
        print(f"  Avg/trade  : {s['avg_eur']:+.0f} EUR")
        print(f"  Avg win    : {s['avg_win']:+.2f}%   Avg loss : {s['avg_loss']:+.2f}%")
        print(f"  Max drawdown streak : {s['max_streak']} pertes consécutives")
    else:
        print("  <3 trades — stats insuffisantes")
    yearly_breakdown(candles, trades, label)
    exit_reasons(trades, label)
    print_monthly(candles, trades, label)


# ─────────────────────────────────────────────────────────────────────────────
def main():
    print("\n" + "=" * 80)
    print("  BACKTEST BOT LIVE — Reproduction exacte du bot actuel en production")
    print("  Filtres : EMA100d aligné | ADX>25 | HeuresFR | Cooldown 2h | SL×2.0 | ATR≤2.5%")
    print("=" * 80)

    candles = load_real_candles()
    n_years = (candles[-1]["ts"] - candles[0]["ts"]) / (365.25 * 86400)
    print(f"  Durée   : {n_years:.1f} an(s)\n")

    # ── Enrichissement complet (même pipeline que v7) ─────────────────────────
    sigs_base = precompute_full(candles)
    sigs_v2   = enrich_signals(candles, sigs_base)
    sigs      = enrich_v6(candles, sigs_v2)

    mk = {"wr": 0.0, "sh": -999.0}

    # ─────────────────────────────────────────────────────────────────────────
    # TABLEAU COMPARATIF
    # ─────────────────────────────────────────────────────────────────────────
    section("TABLEAU COMPARATIF — Bot live vs variantes de référence")
    print(HDR)

    # Référence v7 officielle (sans filtre heures ni ATR%)
    row("Ref v7 : EMA100 + ADX>25 + SL×2.0 (base)",
        run_bot_live(candles, sigs,
                     fr_hours_filter=False, atr_pct_max=0), mk)

    # Bot live sans filtre ATR% — pour mesurer l'impact exact
    row("Bot live — sans filtre ATR% (HeuresFR + cooldown actifs)",
        run_bot_live(candles, sigs,
                     atr_pct_max=0), mk)

    # Bot live complet — TOUS les filtres actifs
    row("★ BOT LIVE COMPLET — tous filtres (incl. ATR≤2.5%)",
        run_bot_live(candles, sigs), mk)

    # Variante sans exclusion US Open (pour mesurer l'apport du filtre 16h-18h)
    fr_sans_usopen = set(range(8, 22))  # 8h-21h sans exclusion 16-18
    row("Variante : HeuresFR sans excl. US Open (16h-18h autorisé)",
        run_bot_live(candles, sigs,
                     fr_hours_filter=True,
                     atr_pct_max=0), mk)

    # ─────────────────────────────────────────────────────────────────────────
    # ANALYSE DÉTAILLÉE DU BOT LIVE
    # ─────────────────────────────────────────────────────────────────────────
    print(f"\n\n{'=' * 80}")
    print("  ANALYSE DÉTAILLÉE — BOT LIVE COMPLET")
    print(f"{'=' * 80}")

    trades_live = run_bot_live(candles, sigs)
    print_detail(candles, trades_live,
                 "BOT LIVE — EMA100d + ADX>25 + HeuresFR + Cooldown 2h + SL×2.0 + ATR≤2.5%")

    # ─────────────────────────────────────────────────────────────────────────
    # ANALYSE SANS FILTRE ATR (pour comparaison directe)
    # ─────────────────────────────────────────────────────────────────────────
    trades_no_atr = run_bot_live(candles, sigs, atr_pct_max=0)
    print_detail(candles, trades_no_atr,
                 "BOT sans filtre ATR% — EMA100d + ADX>25 + HeuresFR + Cooldown 2h + SL×2.0")

    # ─────────────────────────────────────────────────────────────────────────
    # IMPACT DU FILTRE ATR
    # ─────────────────────────────────────────────────────────────────────────
    n_live    = len(trades_live)
    n_no_atr  = len(trades_no_atr)
    n_blocked = n_no_atr - n_live
    if n_no_atr > 0:
        print(f"\n{SEP}")
        print("  IMPACT DU FILTRE ATR ≤ 2.5%")
        print(SEP)
        print(f"  Trades sans filtre ATR : {n_no_atr}")
        print(f"  Trades avec filtre ATR : {n_live}")
        print(f"  Trades bloqués         : {n_blocked} ({n_blocked/n_no_atr*100:.1f}%)")
        s1 = stats(trades_live)
        s2 = stats(trades_no_atr)
        if s1 and s2:
            print(f"  WR    : {s2['wr']:.1f}% → {s1['wr']:.1f}%  (delta {s1['wr']-s2['wr']:+.1f}%)")
            print(f"  Sharpe: {s2['sh']:+.2f} → {s1['sh']:+.2f}  (delta {s1['sh']-s2['sh']:+.2f})")
            print(f"  MDD   : -{s2['mdd']*100:.1f}% → -{s1['mdd']*100:.1f}%")
            print(f"  Net   : {s2['net_eur']:+.0f}€ → {s1['net_eur']:+.0f}€  (delta {s1['net_eur']-s2['net_eur']:+.0f}€)")

    print(f"\n{'=' * 80}\n")


if __name__ == "__main__":
    main()
