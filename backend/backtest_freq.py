"""
backtest_freq.py — Comparatif fréquence de trades
===================================================
Teste tous les leviers pour augmenter le nombre de trades
tout en maintenant une qualité acceptable.

Leviers testés :
  1. Score seuil : 60 / 65 / 70 (actuel)
  2. HeuresFR : activé / désactivé
  3. ADX minimum : 20 / 25 (actuel)
  4. Cooldown : 1h / 2h (actuel)

Base : EMA100d aligné + SL×2.0 (inchangés)
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from bt_common import load_real_candles, TRADE_SIZE
from backtest_2ans import precompute_full, stats, HDR, SEP, _sim_custom_sl, yearly_breakdown
from backtest_v2 import enrich_signals
from backtest_v6 import enrich_v6
from datetime import datetime, timezone

FR_HOURS = set(range(8, 22)) - {16, 17, 18}


def run_variant(candles, sigs,
                thresh=70,
                adx_min=25,
                fr_filter=True,
                cooldown_h=2,
                sl_mult=2.0,
                atr_max=0):
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

        d = s["direction"]
        mt = s.get("ema100_trend", "neutral")

        # EMA100d macro
        if mt == "bull"    and d != "BUY":  continue
        if mt == "bear"    and d != "SELL": continue
        if mt == "neutral":                 continue

        # ADX
        if adx_min > 0 and s.get("adx1h", 0) < adx_min:
            continue

        # HeuresFR
        if fr_filter:
            dt = datetime.fromtimestamp(s["ts"], tz=timezone.utc)
            if dt.hour not in FR_HOURS:
                continue

        # ATR max
        if atr_max > 0:
            price = s.get("price", 0)
            atr   = s.get("atr", 0)
            if price > 0 and atr > 0 and (atr / price * 100) > atr_max:
                continue

        # Cooldown
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


def row(label, trades, best):
    s = stats(trades)
    if not s:
        print(f"  {label:<55} | {'—':>5} | {'—':>6} | {'—':>7} | {'—':>6} | {'—':>7} | {'—':>9}")
        return
    mark_wr = " ◄WR" if s["wr"] > best.get("wr", 0) else ""
    mark_sh = " ◄SH" if s["sh"] > best.get("sh", -999) else ""
    if s["wr"] > best.get("wr", 0): best["wr"] = s["wr"]
    if s["sh"] > best.get("sh", -999): best["sh"] = s["sh"]
    print(
        f"  {label:<55} | {s['n']:>5} | {s['wr']:>5.1f}% | {s['avg_pct']:>+6.2f}% "
        f"| -{s['mdd']*100:>4.1f}% | {s['sh']:>+6.2f} | {s['net_eur']:>+8.0f}€"
        f"{mark_wr}{mark_sh}"
    )


def section(title):
    print(f"\n{'─'*110}")
    print(f"  ▶ {title}")
    print(f"{'─'*110}")
    print(f"  {'Config':<55} | {'N':>5} | {'WR':>6} | {'Avg':>7} | {'MDD':>6} | {'Sharpe':>7} | {'Net EUR':>9}")
    print(f"{'─'*110}")


def main():
    print("\n" + "=" * 110)
    print("  BACKTEST FRÉQUENCE — Leviers pour augmenter le nombre de trades")
    print("  Base : EMA100d aligné + SL×2.0 (stratégie v7 inchangée)")
    print("=" * 110)

    candles = load_real_candles()
    sigs_base = precompute_full(candles)
    sigs_v2   = enrich_signals(candles, sigs_base)
    sigs      = enrich_v6(candles, sigs_v2)

    best = {"wr": 0.0, "sh": -999.0}

    # ── RÉFÉRENCE ────────────────────────────────────────────────────────────
    section("RÉFÉRENCE — Bot live actuel")
    ref = run_variant(candles, sigs)
    row("★ BOT LIVE (score≥70, ADX≥25, HeuresFR, cooldown 2h)", ref, best)

    # ── LEVIER 1 : SCORE SEUIL ───────────────────────────────────────────────
    section("LEVIER 1 — Score seuil (ADX≥25, HeuresFR, cooldown 2h)")
    for thresh in [60, 65, 70]:
        label = f"Score ≥ {thresh}"
        if thresh == 70:
            label += " (actuel)"
        row(label, run_variant(candles, sigs, thresh=thresh), best)

    # ── LEVIER 2 : HEURES ────────────────────────────────────────────────────
    section("LEVIER 2 — Filtre heures (score≥70, ADX≥25, cooldown 2h)")
    row("HeuresFR actives — 8h-21h UTC hors 16-18h (actuel)", run_variant(candles, sigs), best)
    row("HeuresFR sans excl. US Open — 8h-21h UTC complet",   run_variant(candles, sigs, fr_filter=True), best)
    row("24h — pas de filtre horaire",                         run_variant(candles, sigs, fr_filter=False), best)

    # ── LEVIER 3 : ADX ───────────────────────────────────────────────────────
    section("LEVIER 3 — Seuil ADX (score≥70, HeuresFR, cooldown 2h)")
    for adx in [20, 22, 25]:
        label = f"ADX ≥ {adx}" + (" (actuel)" if adx == 25 else "")
        row(label, run_variant(candles, sigs, adx_min=adx), best)
    row("Sans filtre ADX", run_variant(candles, sigs, adx_min=0), best)

    # ── LEVIER 4 : COOLDOWN ──────────────────────────────────────────────────
    section("LEVIER 4 — Cooldown (score≥70, ADX≥25, HeuresFR)")
    for cd in [0, 1, 2]:
        label = f"Cooldown {cd}h" + (" (actuel)" if cd == 2 else ("" if cd else " (aucun)"))
        row(label, run_variant(candles, sigs, cooldown_h=cd), best)

    # ── COMBINAISONS PROMETTEUSES ─────────────────────────────────────────────
    section("COMBINAISONS — Score + ADX relâchés")
    row("Score≥60 + ADX≥20 + HeuresFR + cooldown 2h",
        run_variant(candles, sigs, thresh=60, adx_min=20), best)
    row("Score≥65 + ADX≥20 + HeuresFR + cooldown 2h",
        run_variant(candles, sigs, thresh=65, adx_min=20), best)
    row("Score≥60 + ADX≥25 + HeuresFR + cooldown 1h",
        run_variant(candles, sigs, thresh=60, cooldown_h=1), best)
    row("Score≥65 + ADX≥25 + HeuresFR + cooldown 1h",
        run_variant(candles, sigs, thresh=65, cooldown_h=1), best)
    row("Score≥60 + ADX≥20 + 24h + cooldown 2h",
        run_variant(candles, sigs, thresh=60, adx_min=20, fr_filter=False), best)
    row("Score≥65 + ADX≥20 + 24h + cooldown 2h",
        run_variant(candles, sigs, thresh=65, adx_min=20, fr_filter=False), best)
    row("Score≥70 + ADX≥20 + 24h + cooldown 1h",
        run_variant(candles, sigs, adx_min=20, fr_filter=False, cooldown_h=1), best)

    print(f"\n{'=' * 110}\n")


if __name__ == "__main__":
    main()
