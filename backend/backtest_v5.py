"""
Backtest v5 — Validation & Optimisation du TOP DU TOP
======================================================
Hypothèse centrale issue de v1→v4 :
  "ADX>25 + macro aligné + SL×1.5" est le meilleur filtre du système.
  La variante directionnelle (BUY en BULL / SELL en BEAR) n'a jamais été
  testée de façon propre et pourrait être le Saint-Graal.

Plan v5 :
  A) SL granulaire sur ADX>25+macro : 1.2 / 1.3 / 1.5 / 1.6 / 1.8 / 2.0 / 2.2
  B) Macro directionnelle PURE :
       - BUY only quand macro=BULL
       - SELL only quand macro=BEAR
       - Stratégie adaptive : suit le régime (BUY en BULL + SELL en BEAR dans le même run)
  C) BUY+macro BULL — approfondissement (best BUY config trouvée v4 : Sharpe +2.06)
  D) Absorption seuils SOUPLES (mèche>35%, corps<45%, vol>1.2×) → augmenter N
  E) CVD trend + SL granulaire → trouver le sweet spot
  F) COMBO ULTIME — tester les hypothèses combinées
  G) Résistance 2026 — vérifier que les tops ne crashent pas en 2026
  H) TABLEAU FINAL — top 25 configs toutes versions confondues
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
from bt_common import load_real_candles, TRADE_SIZE
from backtest_2ans import (
    section, row, HDR, SEP,
    yearly_breakdown, exit_reasons,
    _sim_custom_sl,
    stats,
)
from backtest_v2 import (
    precompute_full,
    enrich_signals,
    run_v2,
)
from collections import defaultdict
from datetime import datetime, timezone


# ─────────────────────────────────────────────────────────────────
# ENRICHISSEMENT v5 — absorption seuils souples
# ─────────────────────────────────────────────────────────────────

def enrich_v5(sigs):
    """
    Ajoute abs_soft_bear / abs_soft_bull avec seuils relâchés :
      mèche > 35% (vs 45%), corps < 45% (vs 35%), vol > 1.2× (vs 1.5×)
    Opère directement sur les signaux déjà enrichis par enrich_signals().
    """
    print("  Enrichissement absorption souple...", end="", flush=True)
    out = []
    for s in sigs:
        # On recalcule depuis les candles stockés dans le signal → non disponible
        # On détecte via abs_bear/abs_bull déjà présents + heuristique souple
        # Note : sans accès direct aux bougies brutes ici, on marque "souple = standard"
        # Les champs abs_bear/abs_bull standard sont déjà dans le signal (enrich_signals)
        # On crée abs_soft = True si abs_bear OU si proche-absorption (mèche moderate)
        out.append({
            **s,
            "abs_soft_bear": s.get("abs_bear", False),
            "abs_soft_bull": s.get("abs_bull", False),
        })
    print(f" {len(out)} signaux")
    return out


def enrich_v5_full(candles, sigs):
    """
    Recalcule l'absorption avec seuils souples directement depuis les bougies.
    mèche > 35%, corps < 45%, volume > 1.2× moyenne
    """
    print("  Enrichissement absorption souple (recalcul complet)...", end="", flush=True)
    out = []
    for s in sigs:
        i    = s["idx"]
        w    = candles[max(0, i - 20):i + 1]
        soft = _detect_absorption_soft(w)
        out.append({
            **s,
            "abs_soft_bear": soft["bear"],
            "abs_soft_bull": soft["bull"],
        })
    print(f" {len(out)} signaux")
    return out


def _detect_absorption_soft(candles_w, lookback=20):
    """Absorption seuils souples : mèche>35%, corps<45%, vol>1.2×."""
    if len(candles_w) < lookback + 1:
        return {"bear": False, "bull": False}
    vols = np.array([x["volume"] for x in candles_w], dtype=float)
    last = candles_w[-1]
    o, h, l, c = last["open"], last["high"], last["low"], last["close"]
    rng = h - l
    if rng < 1e-8:
        return {"bear": False, "bull": False}
    body = abs(c - o) / rng
    uwk  = (h - max(o, c)) / rng
    lwk  = (min(o, c) - l) / rng
    avg_v = float(np.mean(vols[-lookback - 1:-1]))
    vr    = vols[-1] / avg_v if avg_v > 1e-8 else 1.0
    return {
        "bear": bool(uwk > 0.35 and body < 0.45 and vr > 1.2),
        "bull": bool(lwk > 0.35 and body < 0.45 and vr > 1.2),
    }


# ─────────────────────────────────────────────────────────────────
# RUN v5 — ajoute macro_directional + abs_soft
# ─────────────────────────────────────────────────────────────────

def run_v5(candles, sigs,
           thresh=70,
           sl_mult=1.8,
           cooldown_h=2,
           direction_only=None,
           macro_filter=None,
           macro_directional=False,   # BUY si BULL, SELL si BEAR, skip si neutral
           adx1h_min=0,
           ema1_filter=False,
           ema4_filter=False,
           cvd_trend_filter=False,
           cvd_div_filter=False,
           rsi4_filter=False,
           absorption_filter=False,   # seuils standards
           abs_soft_filter=False,     # seuils souples
           ):
    """Étend run_v2 avec macro_directional et abs_soft."""
    trades = []; end_idx = 0; prev = 0
    last_ts = {"BUY": 0, "SELL": 0}

    for s in sigs:
        if s["idx"] < end_idx:               prev = s["score"]; continue
        if not (prev < thresh <= s["score"]): prev = s["score"]; continue
        prev = s["score"]

        d  = s["direction"]
        mt = s.get("macro_trend", "neutral")

        # Mode directional pur : suit le régime macro
        if macro_directional:
            if mt == "bull" and d != "BUY":   continue
            if mt == "bear" and d != "SELL":  continue
            if mt == "neutral":               continue
        else:
            if direction_only and d != direction_only: continue
            if macro_filter:
                if macro_filter == "aligned":
                    if d == "BUY"  and mt != "bull": continue
                    if d == "SELL" and mt != "bear": continue
                elif mt != macro_filter:             continue

        if adx1h_min > 0 and s.get("adx1h", 0) < adx1h_min: continue

        if ema1_filter:
            if d == "BUY"  and s.get("ema1_trend") != "bull": continue
            if d == "SELL" and s.get("ema1_trend") != "bear": continue
        if ema4_filter:
            if d == "BUY"  and s.get("ema4_trend") != "bull": continue
            if d == "SELL" and s.get("ema4_trend") != "bear": continue

        if rsi4_filter and s.get("rsi4") is not None:
            if d == "BUY"  and s["rsi4"] >= 50: continue
            if d == "SELL" and s["rsi4"] <= 50: continue

        if cvd_trend_filter:
            ct = s.get("cvd_trend", "neutral")
            if d == "BUY"  and ct != "up":   continue
            if d == "SELL" and ct != "down":  continue

        if cvd_div_filter:
            if d == "BUY"  and not s.get("cvd_div_bull"): continue
            if d == "SELL" and not s.get("cvd_div_bear"):  continue

        if absorption_filter:
            if d == "BUY"  and not s.get("abs_bull"): continue
            if d == "SELL" and not s.get("abs_bear"):  continue

        if abs_soft_filter:
            if d == "BUY"  and not s.get("abs_soft_bull"): continue
            if d == "SELL" and not s.get("abs_soft_bear"):  continue

        if cooldown_h > 0 and (s["ts"] - last_ts[d]) < cooldown_h * 3600: continue

        pnl, rsn, bars = _sim_custom_sl(candles, s["idx"], d, s["atr"], sl_mult)
        if rsn == "skip": continue

        last_ts[d] = s["ts"]
        trades.append({**s, "pnl_pct": pnl * 100, "pnl_eur": pnl * TRADE_SIZE,
                       "reason": rsn, "bars": bars})
        end_idx = s["idx"] + bars + 4

    return trades


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 80)
    print("  BACKTEST v5 — Validation TOP DU TOP : macro directionnelle + SL fin")
    print("  Base : 2 ans BTC réel Binance — score≥70, cooldown 2h (défaut)")
    print("=" * 80)

    candles   = load_real_candles()
    n_years   = (candles[-1]["ts"] - candles[0]["ts"]) / (365.25 * 86400)
    print(f"  Durée : {n_years:.1f} an(s)\n")

    sigs_base = precompute_full(candles)
    sigs_v2   = enrich_signals(candles, sigs_base)
    sigs      = enrich_v5_full(candles, sigs_v2)   # + absorption souple
    mk        = {"wr": 0.0, "sh": -999.0}

    # ─────────────────────────────────────────────────────────────
    # RÉFÉRENCE — tops confirmés v1→v4
    # ─────────────────────────────────────────────────────────────
    section("RÉFÉRENCE — tops v1→v4 confirmés")
    row("F5 baseline",
        run_v5(candles, sigs), mk)
    row("ADX>25 + macro (SL×1.8)",
        run_v5(candles, sigs, adx1h_min=25, macro_filter="aligned"), mk)
    row("ADX>25 + macro + SL×1.5  ← #1 v4",
        run_v5(candles, sigs, adx1h_min=25, macro_filter="aligned", sl_mult=1.5), mk)
    row("BUY + ADX>25 + macro BULL ← #2 v4",
        run_v5(candles, sigs, direction_only="BUY", adx1h_min=25, macro_filter="bull"), mk)
    row("ADX>25 + CVD trend + SL×2.2 ← #3 v4",
        run_v5(candles, sigs, adx1h_min=25, cvd_trend_filter=True, sl_mult=2.2), mk)
    row("ADX>25 + EMA1h + SL×2.2",
        run_v5(candles, sigs, adx1h_min=25, ema1_filter=True, sl_mult=2.2), mk)
    row("SELL baseline",
        run_v5(candles, sigs, direction_only="SELL"), mk)

    # ─────────────────────────────────────────────────────────────
    # A — SL GRANULAIRE sur ADX>25+macro
    # ─────────────────────────────────────────────────────────────
    section("A — SL granulaire sur ADX>25+macro (×1.0 → ×2.5)")
    for sl in [1.0, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.5]:
        row(f"ADX>25 + macro + SL×{sl}",
            run_v5(candles, sigs, adx1h_min=25, macro_filter="aligned", sl_mult=sl), mk)

    section("A2 — SL granulaire sur BUY+macro BULL")
    for sl in [1.0, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.5]:
        row(f"BUY + macro BULL + SL×{sl}",
            run_v5(candles, sigs, direction_only="BUY", macro_filter="bull", sl_mult=sl), mk)

    section("A3 — SL granulaire sur ADX>25+CVD trend")
    for sl in [1.2, 1.5, 1.8, 2.0, 2.2, 2.5]:
        row(f"ADX>25 + CVD trend + SL×{sl}",
            run_v5(candles, sigs, adx1h_min=25, cvd_trend_filter=True, sl_mult=sl), mk)

    # ─────────────────────────────────────────────────────────────
    # B — MACRO DIRECTIONNELLE PURE
    # ─────────────────────────────────────────────────────────────
    section("B — MACRO DIRECTIONNELLE (BUY en BULL / SELL en BEAR)")
    row("Macro directionnelle — no ADX",
        run_v5(candles, sigs, macro_directional=True), mk)
    row("Macro directionnelle + ADX>20",
        run_v5(candles, sigs, macro_directional=True, adx1h_min=20), mk)
    row("Macro directionnelle + ADX>22",
        run_v5(candles, sigs, macro_directional=True, adx1h_min=22), mk)
    row("Macro directionnelle + ADX>25",
        run_v5(candles, sigs, macro_directional=True, adx1h_min=25), mk)
    row("Macro directionnelle + ADX>25 + SL×1.5",
        run_v5(candles, sigs, macro_directional=True, adx1h_min=25, sl_mult=1.5), mk)
    row("Macro directionnelle + ADX>25 + SL×1.8",
        run_v5(candles, sigs, macro_directional=True, adx1h_min=25, sl_mult=1.8), mk)
    row("Macro directionnelle + ADX>25 + SL×2.2",
        run_v5(candles, sigs, macro_directional=True, adx1h_min=25, sl_mult=2.2), mk)
    row("Macro directionnelle + ADX>25 + EMA1h",
        run_v5(candles, sigs, macro_directional=True, adx1h_min=25, ema1_filter=True), mk)
    row("Macro directionnelle + ADX>25 + CVD trend",
        run_v5(candles, sigs, macro_directional=True, adx1h_min=25, cvd_trend_filter=True), mk)
    row("Macro directionnelle + ADX>25 + RSI4h",
        run_v5(candles, sigs, macro_directional=True, adx1h_min=25, rsi4_filter=True), mk)
    row("Macro directionnelle + ADX>25 + CVD trend + SL×1.5",
        run_v5(candles, sigs, macro_directional=True, adx1h_min=25, cvd_trend_filter=True, sl_mult=1.5), mk)
    row("Macro directionnelle + ADX>25 + CVD trend + SL×2.2",
        run_v5(candles, sigs, macro_directional=True, adx1h_min=25, cvd_trend_filter=True, sl_mult=2.2), mk)
    row("Macro directionnelle + ADX>25 + EMA1h + SL×1.5",
        run_v5(candles, sigs, macro_directional=True, adx1h_min=25, ema1_filter=True, sl_mult=1.5), mk)
    row("Macro directionnelle + ADX>22 + SL×1.5",
        run_v5(candles, sigs, macro_directional=True, adx1h_min=22, sl_mult=1.5), mk)

    # ─────────────────────────────────────────────────────────────
    # C — BUY+macro BULL approfondissement
    # ─────────────────────────────────────────────────────────────
    section("C — BUY + macro BULL — approfondissement")
    row("BUY + macro BULL seul",
        run_v5(candles, sigs, direction_only="BUY", macro_filter="bull"), mk)
    row("BUY + macro BULL + ADX>25",
        run_v5(candles, sigs, direction_only="BUY", macro_filter="bull", adx1h_min=25), mk)
    row("BUY + macro BULL + ADX>22",
        run_v5(candles, sigs, direction_only="BUY", macro_filter="bull", adx1h_min=22), mk)
    row("BUY + macro BULL + ADX>20",
        run_v5(candles, sigs, direction_only="BUY", macro_filter="bull", adx1h_min=20), mk)
    row("BUY + macro BULL + EMA1h",
        run_v5(candles, sigs, direction_only="BUY", macro_filter="bull", ema1_filter=True), mk)
    row("BUY + macro BULL + EMA4h",
        run_v5(candles, sigs, direction_only="BUY", macro_filter="bull", ema4_filter=True), mk)
    row("BUY + macro BULL + CVD trend",
        run_v5(candles, sigs, direction_only="BUY", macro_filter="bull", cvd_trend_filter=True), mk)
    row("BUY + macro BULL + RSI4h",
        run_v5(candles, sigs, direction_only="BUY", macro_filter="bull", rsi4_filter=True), mk)
    row("BUY + macro BULL + absorption souple",
        run_v5(candles, sigs, direction_only="BUY", macro_filter="bull", abs_soft_filter=True), mk)
    row("BUY + macro BULL + ADX>25 + SL×1.5",
        run_v5(candles, sigs, direction_only="BUY", macro_filter="bull", adx1h_min=25, sl_mult=1.5), mk)
    row("BUY + macro BULL + ADX>25 + SL×1.3",
        run_v5(candles, sigs, direction_only="BUY", macro_filter="bull", adx1h_min=25, sl_mult=1.3), mk)
    row("BUY + macro BULL + ADX>25 + CVD trend",
        run_v5(candles, sigs, direction_only="BUY", macro_filter="bull", adx1h_min=25, cvd_trend_filter=True), mk)
    row("BUY + macro BULL + ADX>25 + EMA1h",
        run_v5(candles, sigs, direction_only="BUY", macro_filter="bull", adx1h_min=25, ema1_filter=True), mk)
    row("BUY + macro BULL + ADX>22 + SL×1.5",
        run_v5(candles, sigs, direction_only="BUY", macro_filter="bull", adx1h_min=22, sl_mult=1.5), mk)
    row("BUY + macro BULL + ADX>20 + SL×1.5",
        run_v5(candles, sigs, direction_only="BUY", macro_filter="bull", adx1h_min=20, sl_mult=1.5), mk)

    # ─────────────────────────────────────────────────────────────
    # D — ABSORPTION SOUPLES
    # ─────────────────────────────────────────────────────────────
    section("D — ABSORPTION seuils souples (mèche>35%, corps<45%, vol>1.2×)")
    row("Absorption souple seule",
        run_v5(candles, sigs, abs_soft_filter=True), mk)
    row("Absorption souple + ADX>25",
        run_v5(candles, sigs, abs_soft_filter=True, adx1h_min=25), mk)
    row("Absorption souple + macro aligné",
        run_v5(candles, sigs, abs_soft_filter=True, macro_filter="aligned"), mk)
    row("Absorption souple + ADX>25 + macro",
        run_v5(candles, sigs, abs_soft_filter=True, adx1h_min=25, macro_filter="aligned"), mk)
    row("Absorption souple + ADX>25 + macro + SL×1.5",
        run_v5(candles, sigs, abs_soft_filter=True, adx1h_min=25, macro_filter="aligned", sl_mult=1.5), mk)
    row("Absorption souple + macro directionnelle",
        run_v5(candles, sigs, abs_soft_filter=True, macro_directional=True), mk)
    row("Absorption souple + macro dir + ADX>25",
        run_v5(candles, sigs, abs_soft_filter=True, macro_directional=True, adx1h_min=25), mk)
    row("Absorption standard + ADX>25 + macro (ref)",
        run_v5(candles, sigs, absorption_filter=True, adx1h_min=25, macro_filter="aligned"), mk)

    # ─────────────────────────────────────────────────────────────
    # E — COMBOS ULTIMES
    # ─────────────────────────────────────────────────────────────
    section("E — COMBOS ULTIMES — meilleur de chaque piste combinés")
    row("ADX>25 + macro + SL×1.5",
        run_v5(candles, sigs, adx1h_min=25, macro_filter="aligned", sl_mult=1.5), mk)
    row("ADX>25 + macro + SL×1.5 + CVD trend",
        run_v5(candles, sigs, adx1h_min=25, macro_filter="aligned", sl_mult=1.5, cvd_trend_filter=True), mk)
    row("ADX>25 + macro + SL×1.5 + EMA1h",
        run_v5(candles, sigs, adx1h_min=25, macro_filter="aligned", sl_mult=1.5, ema1_filter=True), mk)
    row("ADX>25 + macro + SL×1.5 + RSI4h",
        run_v5(candles, sigs, adx1h_min=25, macro_filter="aligned", sl_mult=1.5, rsi4_filter=True), mk)
    row("ADX>25 + macro dir + SL×1.5",
        run_v5(candles, sigs, macro_directional=True, adx1h_min=25, sl_mult=1.5), mk)
    row("ADX>25 + macro dir + SL×1.5 + CVD trend",
        run_v5(candles, sigs, macro_directional=True, adx1h_min=25, sl_mult=1.5, cvd_trend_filter=True), mk)
    row("ADX>25 + macro dir + SL×1.5 + EMA1h",
        run_v5(candles, sigs, macro_directional=True, adx1h_min=25, sl_mult=1.5, ema1_filter=True), mk)
    row("BUY macro BULL + ADX>25 + SL×1.5",
        run_v5(candles, sigs, direction_only="BUY", macro_filter="bull", adx1h_min=25, sl_mult=1.5), mk)
    row("SELL macro BEAR + ADX>25 + SL×1.5",
        run_v5(candles, sigs, direction_only="SELL", macro_filter="bear", adx1h_min=25, sl_mult=1.5), mk)
    row("ADX>25 + CVD trend + SL×1.5",
        run_v5(candles, sigs, adx1h_min=25, cvd_trend_filter=True, sl_mult=1.5), mk)
    row("ADX>25 + macro + CVD trend + SL×1.5",
        run_v5(candles, sigs, adx1h_min=25, macro_filter="aligned", cvd_trend_filter=True, sl_mult=1.5), mk)
    row("ADX>25 + EMA1h + SL×1.5",
        run_v5(candles, sigs, adx1h_min=25, ema1_filter=True, sl_mult=1.5), mk)
    row("ADX>22 + macro dir + SL×1.5",
        run_v5(candles, sigs, macro_directional=True, adx1h_min=22, sl_mult=1.5), mk)
    row("ADX>20 + macro dir + SL×1.5",
        run_v5(candles, sigs, macro_directional=True, adx1h_min=20, sl_mult=1.5), mk)

    # ─────────────────────────────────────────────────────────────
    # F — BREAKDOWN ANNUEL — top configs v5
    # ─────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  ▶ F — BREAKDOWN ANNUEL (top configs v5 + refs solides)")
    print(SEP)

    annual_configs = [
        ("F5 baseline",                              dict()),
        ("ADX>25 + macro + SL×1.5",                 dict(adx1h_min=25, macro_filter="aligned", sl_mult=1.5)),
        ("ADX>25 + macro + SL×1.3",                 dict(adx1h_min=25, macro_filter="aligned", sl_mult=1.3)),
        ("ADX>25 + macro (SL×1.8)",                 dict(adx1h_min=25, macro_filter="aligned")),
        ("Macro directionnelle + ADX>25 + SL×1.5",  dict(macro_directional=True, adx1h_min=25, sl_mult=1.5)),
        ("Macro directionnelle + ADX>25 (SL×1.8)",  dict(macro_directional=True, adx1h_min=25)),
        ("BUY + macro BULL + ADX>25",               dict(direction_only="BUY", macro_filter="bull", adx1h_min=25)),
        ("BUY + macro BULL + ADX>25 + SL×1.5",     dict(direction_only="BUY", macro_filter="bull", adx1h_min=25, sl_mult=1.5)),
        ("SELL baseline",                           dict(direction_only="SELL")),
        ("SELL + macro BEAR + ADX>25",              dict(direction_only="SELL", macro_filter="bear", adx1h_min=25)),
        ("ADX>25 + CVD trend + SL×2.2",             dict(adx1h_min=25, cvd_trend_filter=True, sl_mult=2.2)),
        ("ADX>25 + EMA1h + SL×2.2",                dict(adx1h_min=25, ema1_filter=True, sl_mult=2.2)),
    ]

    for label, kwargs in annual_configs:
        t = run_v5(candles, sigs, **kwargs)
        yearly_breakdown(candles, t, label)

    # Exit reasons
    print()
    configs_exits = [
        ("ADX>25+macro+SL×1.5",             dict(adx1h_min=25, macro_filter="aligned", sl_mult=1.5)),
        ("MacroDir+ADX>25+SL×1.5",          dict(macro_directional=True, adx1h_min=25, sl_mult=1.5)),
        ("BUY+macroBULL+ADX>25+SL×1.5",    dict(direction_only="BUY", macro_filter="bull", adx1h_min=25, sl_mult=1.5)),
    ]
    for label, kwargs in configs_exits:
        t = run_v5(candles, sigs, **kwargs)
        exit_reasons(t, label)

    # ─────────────────────────────────────────────────────────────
    # G — TABLEAU FINAL — TOP 25 toutes versions
    # ─────────────────────────────────────────────────────────────
    section("G — TABLEAU FINAL — TOP 25 configs (v1→v5, N≥30)")
    final = [
        # v5 candidates
        ("★ ADX>25 + macro + SL×1.5",                dict(adx1h_min=25, macro_filter="aligned", sl_mult=1.5)),
        ("★ ADX>25 + macro + SL×1.3",                dict(adx1h_min=25, macro_filter="aligned", sl_mult=1.3)),
        ("★ Macro dir + ADX>25 + SL×1.5",            dict(macro_directional=True, adx1h_min=25, sl_mult=1.5)),
        ("★ Macro dir + ADX>25 (SL×1.8)",            dict(macro_directional=True, adx1h_min=25)),
        ("★ BUY macro BULL + ADX>25 + SL×1.5",       dict(direction_only="BUY", macro_filter="bull", adx1h_min=25, sl_mult=1.5)),
        ("★ BUY macro BULL + ADX>22 + SL×1.5",       dict(direction_only="BUY", macro_filter="bull", adx1h_min=22, sl_mult=1.5)),
        ("★ ADX>25 + macro dir + CVD trend + SL×1.5", dict(macro_directional=True, adx1h_min=25, cvd_trend_filter=True, sl_mult=1.5)),
        # v4 confirmés
        ("✓ ADX>25 + macro (SL×1.8)",                dict(adx1h_min=25, macro_filter="aligned")),
        ("✓ ADX>25 + macro + SL×2.2",                dict(adx1h_min=25, macro_filter="aligned", sl_mult=2.2)),
        ("✓ ADX>25 + CVD trend + SL×2.2",            dict(adx1h_min=25, cvd_trend_filter=True, sl_mult=2.2)),
        ("✓ ADX>25 + CVD trend (SL×1.8)",            dict(adx1h_min=25, cvd_trend_filter=True)),
        ("✓ ADX>25 + EMA1h + SL×2.2",               dict(adx1h_min=25, ema1_filter=True, sl_mult=2.2)),
        ("✓ ADX>25 + EMA1h (SL×1.8)",               dict(adx1h_min=25, ema1_filter=True)),
        ("✓ BUY + ADX>25 + macro BULL",              dict(direction_only="BUY", macro_filter="bull", adx1h_min=25)),
        ("✓ SELL baseline",                          dict(direction_only="SELL")),
        ("✓ SELL + RSI4h",                           dict(direction_only="SELL", rsi4_filter=True)),
        ("✓ ADX>25 + macro + CVD trend",             dict(adx1h_min=25, macro_filter="aligned", cvd_trend_filter=True)),
        # v3 confirmés
        ("  ADX>25 seul (SL×1.8)",                   dict(adx1h_min=25)),
        ("  ADX>25 + macro + EMA4h",                 dict(adx1h_min=25, macro_filter="aligned", ema4_filter=True)),
        ("  Macro aligné + EMA1h",                   dict(macro_filter="aligned", ema1_filter=True)),
        # v2/v1
        ("  ADX>25 + SL×2.2",                        dict(adx1h_min=25, sl_mult=2.2)),
        ("  SELL + EMA4h",                           dict(direction_only="SELL", ema4_filter=True)),
        ("  SELL + RSI4h + SL×2.2",                  dict(direction_only="SELL", rsi4_filter=True, sl_mult=2.2)),
        ("  SELL + RSI4h + ADX>22",                  dict(direction_only="SELL", rsi4_filter=True, adx1h_min=22)),
        ("  F5 baseline",                            dict()),
    ]
    for label, kwargs in final:
        row(label, run_v5(candles, sigs, **kwargs), mk)

    # ─────────────────────────────────────────────────────────────
    # RÉSUMÉ
    # ─────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print(f"  Meilleur Win Rate : {mk['wr']:.1f}%")
    print(f"  Meilleur Sharpe   : {mk['sh']:+.2f}")
    print(f"  (◄WR / ◄SH dans les tableaux)")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
