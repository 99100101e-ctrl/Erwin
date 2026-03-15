"""
Backtest v2 — Nouveaux indicateurs : CVD estimé, Absorption, EMA200 Daily, ADX1h
===================================================================================
Construit sur backtest_2ans.py — enrichit les signaux préexistants avec :
  • EMA200 Daily  : régime macro bull/bear (prix > EMA200 daily = macro haussier)
  • CVD estimé    : Cumulative Volume Delta depuis OHLCV (pente, divergence)
  • Absorption    : bougie haute-volume + petit corps + grande mèche → rejet institutionnel
  • ADX 1h        : force de tendance (filtre les ranges)
  • Multi-TF      : combo macro daily + EMA4h + EMA1h (3 timeframes alignés)

Méthode CVD : buy_vol = (close - low) / (high - low) * volume
              delta = buy_vol * 2 - volume (range -1 à +1 par bar)
              CVD   = cumsum(delta) → pression acheteurs vs vendeurs

Absorption    : mèche > 45% du range + corps < 35% + volume > 1.5× moyenne
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
from collections import defaultdict
from datetime import datetime, timezone

from bt_common import load_real_candles, sim_E, TRADE_SIZE
from indicators import calculate_adx
from backtest_2ans import (
    precompute_full,
    section, row, HDR, SEP,
    yearly_breakdown, exit_reasons,
    _sim_custom_sl,
)

FR_HOURS = set(range(8, 22)) - {16, 17, 18}


# ─────────────────────────────────────────────────────────────────
# HELPERS INDICATEURS
# ─────────────────────────────────────────────────────────────────

def _ema_arr(arr, period):
    """EMA classique sur tableau numpy."""
    result = np.full(len(arr), np.nan)
    if len(arr) < period:
        return result
    result[period - 1] = np.mean(arr[:period])
    k = 2.0 / (period + 1)
    for i in range(period, len(arr)):
        result[i] = arr[i] * k + result[i - 1] * (1 - k)
    return result


def compute_daily_ema200(candles):
    """
    Agrège les bougies 1h en daily, calcule EMA200 sur les closes journaliers.
    Retourne {day_timestamp → ema200_value}.
    """
    daily = defaultdict(list)
    for c in candles:
        daily[(c["ts"] // 86400) * 86400].append(c["close"])
    days = sorted(daily.keys())
    if len(days) < 200:
        return {}
    closes = np.array([daily[d][-1] for d in days], dtype=float)
    ema200 = _ema_arr(closes, 200)
    return {d: float(v) for d, v in zip(days, ema200) if not np.isnan(v)}


def estimate_cvd(candles_w):
    """
    Estime le CVD depuis OHLCV (méthode bar-close).
    Analyse les 30 dernières bougies de la fenêtre passée.
    Retourne : trend (up/down/neutral), div_bear, div_bull.
    """
    if len(candles_w) < 20:
        return {"trend": "neutral", "div_bear": False, "div_bull": False}

    c = np.array([x["close"]  for x in candles_w], dtype=float)
    h = np.array([x["high"]   for x in candles_w], dtype=float)
    l = np.array([x["low"]    for x in candles_w], dtype=float)
    v = np.array([x["volume"] for x in candles_w], dtype=float)

    rng   = np.where(h - l < 1e-8, 1e-8, h - l)
    delta = ((c - l) / rng * 2 - 1) * v   # -vol à +vol par barre
    cvd   = np.cumsum(delta)

    n  = min(30, len(cvd))
    xs = np.arange(n, dtype=float)
    cvd_slope   = float(np.polyfit(xs, cvd[-n:], 1)[0])
    price_slope = float(np.polyfit(xs, c[-n:],   1)[0])

    # Divergence : prix monte + CVD descend → distribution (bearish)
    # Prix descend + CVD monte → accumulation (bullish)
    div_bear = bool(price_slope > 0 and cvd_slope < 0)
    div_bull = bool(price_slope < 0 and cvd_slope > 0)

    # Tendance CVD : moyenne courte (10) vs longue (20)
    trend = "neutral"
    if len(cvd) >= 20:
        trend = "up" if np.mean(cvd[-10:]) > np.mean(cvd[-20:-10]) else "down"

    return {"trend": trend, "div_bear": div_bear, "div_bull": div_bull}


def detect_absorption(candles_w, lookback=20):
    """
    Détecte une bougie d'absorption sur la DERNIÈRE barre de la fenêtre.
    Absorption baissière : grande mèche haute + volume fort + petit corps
      → les vendeurs ont absorbé les achats (zone de résistance)
    Absorption haussière : grande mèche basse + volume fort + petit corps
      → les acheteurs ont absorbé les ventes (zone de support)
    Seuils : mèche > 45% du range, corps < 35%, volume > 1.5× moyenne.
    """
    if len(candles_w) < lookback + 1:
        return {"bear": False, "bull": False}

    vols = np.array([x["volume"] for x in candles_w], dtype=float)
    last = candles_w[-1]
    o, h, l, c = last["open"], last["high"], last["low"], last["close"]

    rng = h - l
    if rng < 1e-8:
        return {"bear": False, "bull": False}

    body = abs(c - o) / rng
    uwk  = (h - max(o, c)) / rng    # mèche haute
    lwk  = (min(o, c) - l) / rng    # mèche basse

    avg_v = float(np.mean(vols[-lookback - 1:-1]))
    vr    = vols[-1] / avg_v if avg_v > 1e-8 else 1.0

    return {
        "bear": bool(uwk > 0.45 and body < 0.35 and vr > 1.5),
        "bull": bool(lwk > 0.45 and body < 0.35 and vr > 1.5),
    }


# ─────────────────────────────────────────────────────────────────
# ENRICHISSEMENT DES SIGNAUX
# ─────────────────────────────────────────────────────────────────

def enrich_signals(candles, sigs_base):
    """
    Ajoute CVD, Absorption, EMA200 daily et ADX1h à chaque signal préexistant.
    Passe rapide (pas de signal_engine) — quelques secondes.
    """
    print("  Enrichissement CVD / Absorption / EMA200d / ADX1h...", end="", flush=True)
    ema200d_map = compute_daily_ema200(candles)

    enriched = []
    for s in sigs_base:
        i    = s["idx"]
        w50  = candles[max(0, i - 49):i + 1]   # 50 bars pour CVD + absorption
        w80  = candles[max(0, i - 79):i + 1]   # 80 bars pour ADX1h

        cvd = estimate_cvd(w50)
        ab  = detect_absorption(w50)

        adx_r = calculate_adx(
            [x["high"]  for x in w80],
            [x["low"]   for x in w80],
            [x["close"] for x in w80],
            period=14,
        )
        adx1h = adx_r.get("adx", 0) if adx_r else 0

        day   = (candles[i]["ts"] // 86400) * 86400
        e200d = ema200d_map.get(day)
        price = candles[i]["close"]
        if e200d:
            mt = "bull" if price > e200d * 1.001 else ("bear" if price < e200d * 0.999 else "neutral")
        else:
            mt = "neutral"

        enriched.append({
            **s,
            "cvd_trend":   cvd["trend"],
            "cvd_div_bear": cvd["div_bear"],
            "cvd_div_bull": cvd["div_bull"],
            "abs_bear":    ab["bear"],
            "abs_bull":    ab["bull"],
            "adx1h":       adx1h,
            "macro_trend": mt,
        })

    print(f" {len(enriched)} signaux enrichis")
    return enriched


# ─────────────────────────────────────────────────────────────────
# RUN v2 — avec tous les nouveaux filtres
# ─────────────────────────────────────────────────────────────────

def run_v2(candles, sigs,
           thresh=70,
           fr_hours=False,
           rsi4_filter=False,
           ema1_filter=False,
           ema4_filter=False,
           sl_mult=1.8,
           cooldown_h=2,
           direction_only=None,      # "BUY" | "SELL" | None
           macro_filter=None,        # "bull" | "bear" | "aligned" | None
           cvd_trend_filter=False,   # CVD trend doit confirmer la direction
           cvd_div_filter=False,     # Divergence prix/CVD doit être présente
           absorption_filter=False,  # Absorption doit être détectée
           adx1h_min=0,              # ADX1h minimum (ex: 20 → filtre les ranges)
           ):
    trades = []; end_idx = 0; prev = 0
    last_ts = {"BUY": 0, "SELL": 0}

    for s in sigs:
        if s["idx"] < end_idx:               prev = s["score"]; continue
        if not (prev < thresh <= s["score"]): prev = s["score"]; continue
        prev = s["score"]

        d = s["direction"]

        if direction_only and d != direction_only:          continue
        if fr_hours and s["hour"] not in FR_HOURS:          continue
        if rsi4_filter and s.get("rsi4") is not None:
            if d == "BUY"  and s["rsi4"] >= 50:             continue
            if d == "SELL" and s["rsi4"] <= 50:             continue
        if ema1_filter:
            if d == "BUY"  and s.get("ema1_trend") != "bull": continue
            if d == "SELL" and s.get("ema1_trend") != "bear": continue
        if ema4_filter:
            if d == "BUY"  and s.get("ema4_trend") != "bull": continue
            if d == "SELL" and s.get("ema4_trend") != "bear": continue

        if macro_filter:
            mt = s.get("macro_trend", "neutral")
            if macro_filter == "aligned":
                if d == "BUY"  and mt != "bull": continue
                if d == "SELL" and mt != "bear": continue
            elif mt != macro_filter:             continue

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

        if adx1h_min > 0 and s.get("adx1h", 0) < adx1h_min: continue

        if cooldown_h > 0 and (s["ts"] - last_ts[d]) < cooldown_h * 3600: continue

        if sl_mult != 1.8:
            pnl, rsn, bars = _sim_custom_sl(candles, s["idx"], d, s["atr"], sl_mult)
        else:
            pnl, rsn, bars = sim_E(candles, s["idx"], d, s["atr"])
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
    print("  BACKTEST v2 — CVD / Absorption / EMA200 Daily / ADX1h / Multi-TF")
    print("  Base : 2 ans BTC réel Binance — score≥70, SL×1.8, cooldown 2h")
    print("=" * 80)

    candles = load_real_candles()
    n_years = (candles[-1]["ts"] - candles[0]["ts"]) / (365.25 * 86400)
    print(f"  Durée : {n_years:.1f} an(s)\n")

    # Phase 1 : precompute complet (heavy — signal_engine sur chaque bar)
    sigs_base = precompute_full(candles)

    # Phase 2 : enrichissement rapide (CVD + absorption + EMA200d + ADX1h)
    sigs = enrich_signals(candles, sigs_base)

    mk = {"wr": 0.0, "sh": -999.0}

    # ─────────────────────────────────────────────────────
    # RÉFÉRENCE
    # ─────────────────────────────────────────────────────
    section("RÉFÉRENCE — rappel backtest_2ans.py")
    row("F5 baseline (aucun filtre)",
        run_v2(candles, sigs), mk)
    row("F5 + EMA1h (meilleur résultat précédent)",
        run_v2(candles, sigs, ema1_filter=True), mk)
    t_ref = run_v2(candles, sigs)
    row("SELL only baseline",
        [x for x in t_ref if x["direction"] == "SELL"], mk)

    # ─────────────────────────────────────────────────────
    # 8. EMA200 DAILY — régime macro
    # ─────────────────────────────────────────────────────
    section("8 — EMA200 DAILY — régime macro bull/bear (score≥70, SL×1.8)")
    row("Macro aligné (BUY=bull, SELL=bear)",
        run_v2(candles, sigs, macro_filter="aligned"), mk)
    row("Macro aligné + EMA1h",
        run_v2(candles, sigs, macro_filter="aligned", ema1_filter=True), mk)
    row("Macro aligné + EMA4h",
        run_v2(candles, sigs, macro_filter="aligned", ema4_filter=True), mk)
    t_mb = run_v2(candles, sigs, macro_filter="bear")
    row("SELL only — macro BEAR",
        [x for x in t_mb if x["direction"] == "SELL"], mk)
    t_mb2 = run_v2(candles, sigs, macro_filter="bear", ema1_filter=True)
    row("SELL only — macro BEAR + EMA1h",
        [x for x in t_mb2 if x["direction"] == "SELL"], mk)
    t_mb3 = run_v2(candles, sigs, macro_filter="bear", ema4_filter=True)
    row("SELL only — macro BEAR + EMA4h",
        [x for x in t_mb3 if x["direction"] == "SELL"], mk)

    # ─────────────────────────────────────────────────────
    # 9. CVD ESTIMÉ
    # ─────────────────────────────────────────────────────
    section("9 — CVD ESTIMÉ — volume delta acheteurs/vendeurs (score≥70, SL×1.8)")
    row("CVD tendance confirmée (dir. alignée)",
        run_v2(candles, sigs, cvd_trend_filter=True), mk)
    row("CVD divergence prix/CVD",
        run_v2(candles, sigs, cvd_div_filter=True), mk)
    row("CVD tendance + EMA1h",
        run_v2(candles, sigs, cvd_trend_filter=True, ema1_filter=True), mk)
    row("CVD divergence + EMA1h",
        run_v2(candles, sigs, cvd_div_filter=True, ema1_filter=True), mk)
    t_cv1 = run_v2(candles, sigs, cvd_trend_filter=True)
    row("SELL only + CVD trend down",
        [x for x in t_cv1 if x["direction"] == "SELL"], mk)
    t_cv2 = run_v2(candles, sigs, cvd_div_filter=True)
    row("SELL only + CVD divergence",
        [x for x in t_cv2 if x["direction"] == "SELL"], mk)
    t_cv3 = run_v2(candles, sigs, cvd_div_filter=True, ema1_filter=True)
    row("SELL only + CVD div + EMA1h",
        [x for x in t_cv3 if x["direction"] == "SELL"], mk)
    t_cv4 = run_v2(candles, sigs, cvd_trend_filter=True, ema1_filter=True)
    row("SELL only + CVD trend + EMA1h",
        [x for x in t_cv4 if x["direction"] == "SELL"], mk)

    # ─────────────────────────────────────────────────────
    # 10. ABSORPTION
    # ─────────────────────────────────────────────────────
    section("10 — ABSORPTION — rejet institutionnel (mèche+volume) (score≥70, SL×1.8)")
    row("Absorption confirmée (BUY + SELL)",
        run_v2(candles, sigs, absorption_filter=True), mk)
    row("Absorption + EMA1h",
        run_v2(candles, sigs, absorption_filter=True, ema1_filter=True), mk)
    t_ab1 = run_v2(candles, sigs, absorption_filter=True)
    row("SELL only + Absorption",
        [x for x in t_ab1 if x["direction"] == "SELL"], mk)
    t_ab2 = run_v2(candles, sigs, absorption_filter=True, ema1_filter=True)
    row("SELL only + Absorption + EMA1h",
        [x for x in t_ab2 if x["direction"] == "SELL"], mk)
    t_ab3 = run_v2(candles, sigs, absorption_filter=True, macro_filter="bear")
    row("SELL only + Absorption + macro BEAR",
        [x for x in t_ab3 if x["direction"] == "SELL"], mk)
    t_ab4 = run_v2(candles, sigs, absorption_filter=True, cvd_trend_filter=True)
    row("SELL only + Absorption + CVD down",
        [x for x in t_ab4 if x["direction"] == "SELL"], mk)

    # ─────────────────────────────────────────────────────
    # 11. ADX 1H — filtre range
    # ─────────────────────────────────────────────────────
    section("11 — ADX 1H — filtre marchés en range (score≥70, SL×1.8)")
    for adx_min in [15, 20, 25]:
        row(f"ADX1h > {adx_min}",
            run_v2(candles, sigs, adx1h_min=adx_min), mk)
    row("ADX1h > 20 + EMA1h",
        run_v2(candles, sigs, adx1h_min=20, ema1_filter=True), mk)
    row("ADX1h > 20 + macro aligné",
        run_v2(candles, sigs, adx1h_min=20, macro_filter="aligned"), mk)
    t_adx = run_v2(candles, sigs, adx1h_min=20)
    row("SELL only + ADX1h > 20",
        [x for x in t_adx if x["direction"] == "SELL"], mk)
    t_adx2 = run_v2(candles, sigs, adx1h_min=20, ema1_filter=True)
    row("SELL only + ADX1h > 20 + EMA1h",
        [x for x in t_adx2 if x["direction"] == "SELL"], mk)

    # ─────────────────────────────────────────────────────
    # 12. MULTI-TF (macro daily + EMA4h + EMA1h)
    # ─────────────────────────────────────────────────────
    section("12 — MULTI-TF — 3 timeframes alignés (score≥70, SL×1.8)")
    row("EMA4h seulement",
        run_v2(candles, sigs, ema4_filter=True), mk)
    row("EMA1h + EMA4h (2 TF)",
        run_v2(candles, sigs, ema1_filter=True, ema4_filter=True), mk)
    row("Macro daily + EMA1h (2 TF)",
        run_v2(candles, sigs, macro_filter="aligned", ema1_filter=True), mk)
    row("Macro daily + EMA4h (2 TF)",
        run_v2(candles, sigs, macro_filter="aligned", ema4_filter=True), mk)
    row("Macro daily + EMA4h + EMA1h (3 TF)",
        run_v2(candles, sigs, macro_filter="aligned", ema4_filter=True, ema1_filter=True), mk)
    row("3 TF + CVD trend",
        run_v2(candles, sigs, macro_filter="aligned", ema4_filter=True, ema1_filter=True, cvd_trend_filter=True), mk)
    row("3 TF + ADX1h > 20",
        run_v2(candles, sigs, macro_filter="aligned", ema4_filter=True, ema1_filter=True, adx1h_min=20), mk)
    t_3tf = run_v2(candles, sigs, macro_filter="aligned", ema4_filter=True, ema1_filter=True)
    row("3 TF — SELL only",
        [x for x in t_3tf if x["direction"] == "SELL"], mk)
    t_3tf_cvd = run_v2(candles, sigs, macro_filter="aligned", ema4_filter=True, ema1_filter=True, cvd_trend_filter=True)
    row("3 TF + CVD — SELL only",
        [x for x in t_3tf_cvd if x["direction"] == "SELL"], mk)

    # ─────────────────────────────────────────────────────
    # 13. MEILLEURES COMBOS v2
    # ─────────────────────────────────────────────────────
    section("13 — MEILLEURES COMBOS v2 (score≥70, SL×1.8, cooldown 2h)")
    top_combos = [
        ("F5 baseline",                         dict()),
        ("F5 + EMA1h",                          dict(ema1_filter=True)),
        ("Macro aligné + EMA1h",                dict(macro_filter="aligned", ema1_filter=True)),
        ("CVD trend + EMA1h",                   dict(cvd_trend_filter=True, ema1_filter=True)),
        ("CVD div + EMA1h",                     dict(cvd_div_filter=True, ema1_filter=True)),
        ("Absorption + EMA1h",                  dict(absorption_filter=True, ema1_filter=True)),
        ("ADX1h>20 + EMA1h",                    dict(adx1h_min=20, ema1_filter=True)),
        ("3 TF (macro+4h+1h)",                  dict(macro_filter="aligned", ema4_filter=True, ema1_filter=True)),
        ("3 TF + CVD trend",                    dict(macro_filter="aligned", ema4_filter=True, ema1_filter=True, cvd_trend_filter=True)),
        ("3 TF + ADX1h>20",                     dict(macro_filter="aligned", ema4_filter=True, ema1_filter=True, adx1h_min=20)),
        ("3 TF + Absorption",                   dict(macro_filter="aligned", ema4_filter=True, ema1_filter=True, absorption_filter=True)),
        # SELL only
        ("SELL + baseline",                     dict(direction_only="SELL")),
        ("SELL + EMA1h",                        dict(direction_only="SELL", ema1_filter=True)),
        ("SELL + macro BEAR",                   dict(direction_only="SELL", macro_filter="bear")),
        ("SELL + macro BEAR + EMA1h",           dict(direction_only="SELL", macro_filter="bear", ema1_filter=True)),
        ("SELL + CVD trend down",               dict(direction_only="SELL", cvd_trend_filter=True)),
        ("SELL + CVD div",                      dict(direction_only="SELL", cvd_div_filter=True)),
        ("SELL + CVD trend + EMA1h",            dict(direction_only="SELL", cvd_trend_filter=True, ema1_filter=True)),
        ("SELL + Absorption",                   dict(direction_only="SELL", absorption_filter=True)),
        ("SELL + Absorption + EMA1h",           dict(direction_only="SELL", absorption_filter=True, ema1_filter=True)),
        ("SELL + ADX1h>20 + EMA1h",             dict(direction_only="SELL", adx1h_min=20, ema1_filter=True)),
        ("SELL + macro + CVD + EMA1h",          dict(direction_only="SELL", macro_filter="bear", cvd_trend_filter=True, ema1_filter=True)),
        ("SELL + macro + Abs + EMA1h",          dict(direction_only="SELL", macro_filter="bear", absorption_filter=True, ema1_filter=True)),
        ("SELL + 3TF + CVD",                    dict(direction_only="SELL", macro_filter="bear", ema4_filter=True, ema1_filter=True, cvd_trend_filter=True)),
        ("SELL + 3TF + ADX>20",                 dict(direction_only="SELL", macro_filter="bear", ema4_filter=True, ema1_filter=True, adx1h_min=20)),
    ]
    for label, kwargs in top_combos:
        t = run_v2(candles, sigs, **kwargs)
        row(f"{label}", t, mk)

    # ─────────────────────────────────────────────────────
    # 14. BREAKDOWN ANNUEL — top configs
    # ─────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  ▶ 14 — BREAKDOWN ANNUEL (top configs v2)")
    print(SEP)

    annual_configs = [
        ("F5 baseline",                  dict()),
        ("Macro aligné + EMA1h",         dict(macro_filter="aligned", ema1_filter=True)),
        ("SELL + macro BEAR",            dict(direction_only="SELL", macro_filter="bear")),
        ("SELL + CVD trend + EMA1h",     dict(direction_only="SELL", cvd_trend_filter=True, ema1_filter=True)),
        ("SELL + 3TF + CVD",             dict(direction_only="SELL", macro_filter="bear", ema4_filter=True, ema1_filter=True, cvd_trend_filter=True)),
    ]
    for label, kwargs in annual_configs:
        t = run_v2(candles, sigs, **kwargs)
        yearly_breakdown(candles, t, label)
    print()
    t_exits1 = run_v2(candles, sigs, macro_filter="aligned", ema1_filter=True)
    t_exits2 = run_v2(candles, sigs, direction_only="SELL", macro_filter="bear", cvd_trend_filter=True, ema1_filter=True)
    exit_reasons(t_exits1, "Macro+EMA1h")
    exit_reasons(t_exits2, "SELL+macro+CVD+EMA1h")

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
