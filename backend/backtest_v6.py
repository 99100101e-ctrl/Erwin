"""
Backtest v6 — Comparaison filtres macro alternatifs à l'EMA200 daily
=====================================================================
Problème v5 : EMA200 daily trop lente (200j lag) + trop filtrante (N=76)

7 filtres macro testés sur ADX>25 + SL×1.5 :
  1. EMA200 daily       (référence — N=80)
  2. EMA100 daily       (moitié moins de lag)
  3. EMA50  daily       (3× plus réactif)
  4. Supertrend daily   (adaptatif ATR, pas de lag fixe)
  5. LR Slope 30j       (régression linéaire 30j — zéro lag)
  6. DI+/DI- daily      (directionnel pur de l'ADX, déjà calculé)
  7. Donchian 20j daily (breakout canal — le plus simple)

Objectif : trouver le filtre qui donne N≥100/2ans (5-6/mois)
           avec Sharpe ≥ 1.8 et MDD ≤ 10%
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
from collections import defaultdict
from datetime import datetime, timezone

from bt_common import load_real_candles, TRADE_SIZE
from indicators import calculate_adx, calculate_supertrend
from backtest_2ans import (
    section, row, HDR, SEP,
    yearly_breakdown, exit_reasons,
    _sim_custom_sl, stats,
)
from backtest_v2 import precompute_full, enrich_signals, _ema_arr


# ─────────────────────────────────────────────────────────────────
# HELPERS DAILY
# ─────────────────────────────────────────────────────────────────

def _build_daily(candles):
    """Agrège les bougies 1h en daily OHLCV. Retourne liste triée par ts."""
    daily = defaultdict(lambda: {"o": None, "h": -1e18, "l": 1e18, "c": None, "v": 0.0})
    for c in candles:
        day = (c["ts"] // 86400) * 86400
        d   = daily[day]
        if d["o"] is None: d["o"] = c["open"]
        d["h"] = max(d["h"], c["high"])
        d["l"] = min(d["l"], c["low"])
        d["c"] = c["close"]
        d["v"] += c["volume"]
        d["ts"] = day
    return sorted(daily.values(), key=lambda x: x["ts"])


# ─────────────────────────────────────────────────────────────────
# CALCUL DE TOUS LES FILTRES MACRO SUR DAILY
# ─────────────────────────────────────────────────────────────────

def compute_macro_filters(candles):
    """
    Pour chaque bougie daily, calcule 7 filtres de tendance.
    Retourne {day_ts → dict de tendances}.
    """
    daily = _build_daily(candles)
    n     = len(daily)
    if n < 210:
        return {}

    closes = np.array([d["c"] for d in daily], dtype=float)
    highs  = np.array([d["h"] for d in daily], dtype=float)
    lows   = np.array([d["l"] for d in daily], dtype=float)

    # ── 1. EMA200 / EMA100 / EMA50 ──────────────────────────────
    ema200 = _ema_arr(closes, 200)
    ema100 = _ema_arr(closes, 100)
    ema50  = _ema_arr(closes, 50)

    # ── 2. Supertrend daily (ATR×3, period=10) ──────────────────
    st_list = list(highs); st_h = [float(x) for x in st_list]
    st_l    = [float(x) for x in lows]
    st_c    = [float(x) for x in closes]
    st_res  = calculate_supertrend(st_h, st_l, st_c, period=10, factor=3.0)
    # On recalcule pour avoir la série complète (calculate_supertrend retourne
    # uniquement le dernier point → on refait barre par barre)
    st_dirs = _supertrend_series(highs, lows, closes, period=10, factor=3.0)

    # ── 3. Linear Regression Slope 30j ──────────────────────────
    lr_slope = np.full(n, np.nan)
    for i in range(29, n):
        xs = np.arange(30, dtype=float)
        lr_slope[i] = float(np.polyfit(xs, closes[i-29:i+1], 1)[0])

    # ── 4. DI+/DI- (ADX daily) ──────────────────────────────────
    di_bull  = np.full(n, False)
    di_bear  = np.full(n, False)
    for i in range(40, n):
        r = calculate_adx(
            list(highs[max(0,i-39):i+1]),
            list(lows[max(0,i-39):i+1]),
            list(closes[max(0,i-39):i+1]),
            period=14,
        )
        if r and r.get("plus_di") and r.get("minus_di"):
            di_bull[i] = r["plus_di"] > r["minus_di"]
            di_bear[i] = r["minus_di"] > r["plus_di"]

    # ── 5. Donchian 20j midline ──────────────────────────────────
    don_bull = np.full(n, False)
    don_bear = np.full(n, False)
    for i in range(19, n):
        hi20  = float(np.max(highs[i-19:i+1]))
        lo20  = float(np.min(lows[i-19:i+1]))
        mid   = (hi20 + lo20) / 2.0
        don_bull[i] = closes[i] > mid * 1.005
        don_bear[i] = closes[i] < mid * 0.995

    # ── Construction du mapping {day_ts → filtres} ───────────────
    result = {}
    for i, d in enumerate(daily):
        p = closes[i]
        result[d["ts"]] = {
            # EMA200
            "ema200_trend": (
                "bull" if (not np.isnan(ema200[i]) and p > ema200[i] * 1.001)
                else "bear" if (not np.isnan(ema200[i]) and p < ema200[i] * 0.999)
                else "neutral"
            ),
            # EMA100
            "ema100_trend": (
                "bull" if (not np.isnan(ema100[i]) and p > ema100[i] * 1.001)
                else "bear" if (not np.isnan(ema100[i]) and p < ema100[i] * 0.999)
                else "neutral"
            ),
            # EMA50
            "ema50_trend": (
                "bull" if (not np.isnan(ema50[i]) and p > ema50[i] * 1.001)
                else "bear" if (not np.isnan(ema50[i]) and p < ema50[i] * 0.999)
                else "neutral"
            ),
            # Supertrend daily
            "st_daily_trend": st_dirs[i] if i < len(st_dirs) else "neutral",
            # LR Slope 30j
            "lr_trend": (
                "bull" if (not np.isnan(lr_slope[i]) and lr_slope[i] > 0)
                else "bear" if (not np.isnan(lr_slope[i]) and lr_slope[i] < 0)
                else "neutral"
            ),
            # DI+/DI-
            "di_trend": (
                "bull" if di_bull[i]
                else "bear" if di_bear[i]
                else "neutral"
            ),
            # Donchian
            "don_trend": (
                "bull" if don_bull[i]
                else "bear" if don_bear[i]
                else "neutral"
            ),
        }
    return result


def _supertrend_series(highs, lows, closes, period=10, factor=3.0):
    """Calcule Supertrend barre par barre et retourne liste de 'bull'/'bear'/'neutral'."""
    n   = len(closes)
    out = ["neutral"] * n
    for i in range(period + 10, n):
        r = calculate_supertrend(
            list(highs[max(0,i-period*4):i+1]),
            list(lows[max(0,i-period*4):i+1]),
            list(closes[max(0,i-period*4):i+1]),
            period=period, factor=factor,
        )
        if r:
            out[i] = "bull" if r["direction"] == "UP" else "bear"
    return out


# ─────────────────────────────────────────────────────────────────
# ENRICHISSEMENT v6
# ─────────────────────────────────────────────────────────────────

def enrich_v6(candles, sigs_v2):
    """Ajoute les 7 filtres macro à chaque signal."""
    print("  Enrichissement v6 (7 filtres macro daily)...", end="", flush=True)
    macro_map = compute_macro_filters(candles)

    out = []
    for s in sigs_v2:
        day = (s["ts"] // 86400) * 86400
        m   = macro_map.get(day, {})
        out.append({**s, **m})
    print(f" {len(out)} signaux enrichis")
    return out


# ─────────────────────────────────────────────────────────────────
# RUN v6 — filtre macro configurable
# ─────────────────────────────────────────────────────────────────

def run_v6(candles, sigs,
           thresh=70, sl_mult=1.8, cooldown_h=2,
           direction_only=None,
           adx1h_min=0,
           ema1_filter=False,
           cvd_trend_filter=False,
           rsi4_filter=False,
           macro_field=None,          # ex: "ema200_trend", "st_daily_trend"...
           macro_mode="aligned",      # "aligned" | "directional" | "bull" | "bear"
           ):
    """
    macro_field  : champ de tendance dans le signal enrichi
    macro_mode   :
      "aligned"     → BUY si bull, SELL si bear (skip neutral)
      "directional" → BUY si bull, SELL si bear (idem mais mode runtime)
      "bull"        → filtre uniquement les signaux en régime bull
      "bear"        → filtre uniquement les signaux en régime bear
    """
    trades = []; end_idx = 0; prev = 0
    last_ts = {"BUY": 0, "SELL": 0}

    for s in sigs:
        if s["idx"] < end_idx:               prev = s["score"]; continue
        if not (prev < thresh <= s["score"]): prev = s["score"]; continue
        prev = s["score"]

        d  = s["direction"]
        mt = s.get(macro_field, "neutral") if macro_field else "neutral"

        if macro_field:
            if macro_mode in ("aligned", "directional"):
                if mt == "bull" and d != "BUY":  continue
                if mt == "bear" and d != "SELL": continue
                if mt == "neutral":              continue
            elif macro_mode == "bull":
                if mt != "bull":                 continue
            elif macro_mode == "bear":
                if mt != "bear":                 continue

        if direction_only and d != direction_only: continue
        if adx1h_min > 0 and s.get("adx1h", 0) < adx1h_min: continue

        if ema1_filter:
            if d == "BUY"  and s.get("ema1_trend") != "bull": continue
            if d == "SELL" and s.get("ema1_trend") != "bear": continue

        if cvd_trend_filter:
            ct = s.get("cvd_trend", "neutral")
            if d == "BUY"  and ct != "up":   continue
            if d == "SELL" and ct != "down":  continue

        if rsi4_filter and s.get("rsi4") is not None:
            if d == "BUY"  and s["rsi4"] >= 50: continue
            if d == "SELL" and s["rsi4"] <= 50: continue

        if cooldown_h > 0 and (s["ts"] - last_ts[d]) < cooldown_h * 3600: continue

        pnl, rsn, bars = _sim_custom_sl(candles, s["idx"], d, s["atr"], sl_mult)
        if rsn == "skip": continue

        last_ts[d] = s["ts"]
        trades.append({**s, "pnl_pct": pnl*100, "pnl_eur": pnl*TRADE_SIZE,
                       "reason": rsn, "bars": bars})
        end_idx = s["idx"] + bars + 4

    return trades


def _regime_stats(candles, sigs, macro_field):
    """Affiche la répartition bull/bear/neutral pour un filtre macro."""
    counts = defaultdict(int)
    for s in sigs:
        counts[s.get(macro_field, "neutral")] += 1
    total = len(sigs)
    bull  = counts.get("bull", 0)
    bear  = counts.get("bear", 0)
    neu   = counts.get("neutral", 0)
    print(f"    {macro_field:<20} : bull={bull:4d} ({bull/total*100:.0f}%) "
          f"bear={bear:4d} ({bear/total*100:.0f}%) "
          f"neutral={neu:4d} ({neu/total*100:.0f}%)")


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 80)
    print("  BACKTEST v6 — Comparaison 7 filtres macro (EMA/Supertrend/LR/DI/Donchian)")
    print("  Base : 2 ans BTC réel Binance — ADX>25, SL×1.5 sauf mention")
    print("=" * 80)

    candles   = load_real_candles()
    n_years   = (candles[-1]["ts"] - candles[0]["ts"]) / (365.25 * 86400)
    print(f"  Durée : {n_years:.1f} an(s)\n")

    sigs_base = precompute_full(candles)
    sigs_v2   = enrich_signals(candles, sigs_base)
    sigs      = enrich_v6(candles, sigs_v2)
    mk        = {"wr": 0.0, "sh": -999.0}

    # ── Répartition des régimes par filtre ──────────────────────
    print(f"\n{SEP}")
    print("  ▶ RÉPARTITION DES RÉGIMES (sur 1830 signaux)")
    print(SEP)
    for field in ["ema200_trend","ema100_trend","ema50_trend",
                  "st_daily_trend","lr_trend","di_trend","don_trend"]:
        _regime_stats(candles, sigs, field)
    print()

    # ─────────────────────────────────────────────────────────────
    # RÉFÉRENCE
    # ─────────────────────────────────────────────────────────────
    section("RÉFÉRENCE")
    row("F5 baseline (no macro)",
        run_v6(candles, sigs), mk)
    row("ADX>25 no macro (SL×1.5)",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5), mk)
    row("EMA200 aligné + ADX>25 + SL×1.5  ← best v5",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5,
               macro_field="ema200_trend", macro_mode="aligned"), mk)
    row("BUY + EMA200 BULL + ADX>25 + SL×1.5  ← #1 v5",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5,
               macro_field="ema200_trend", macro_mode="bull"), mk)

    # ─────────────────────────────────────────────────────────────
    # 1. EMA100 daily
    # ─────────────────────────────────────────────────────────────
    section("1 — EMA100 daily × ADX>25 + SL×1.5")
    row("EMA100 aligné",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5,
               macro_field="ema100_trend", macro_mode="aligned"), mk)
    row("BUY + EMA100 BULL",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5,
               macro_field="ema100_trend", macro_mode="bull"), mk)
    row("SELL + EMA100 BEAR",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5,
               macro_field="ema100_trend", macro_mode="bear"), mk)
    row("EMA100 aligné + EMA1h",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5, ema1_filter=True,
               macro_field="ema100_trend", macro_mode="aligned"), mk)
    row("EMA100 aligné + CVD trend",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5, cvd_trend_filter=True,
               macro_field="ema100_trend", macro_mode="aligned"), mk)
    row("EMA100 aligné + SL×1.8",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.8,
               macro_field="ema100_trend", macro_mode="aligned"), mk)
    row("EMA100 aligné + SL×2.0",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0,
               macro_field="ema100_trend", macro_mode="aligned"), mk)

    # ─────────────────────────────────────────────────────────────
    # 2. EMA50 daily
    # ─────────────────────────────────────────────────────────────
    section("2 — EMA50 daily × ADX>25 + SL×1.5")
    row("EMA50 aligné",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5,
               macro_field="ema50_trend", macro_mode="aligned"), mk)
    row("BUY + EMA50 BULL",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5,
               macro_field="ema50_trend", macro_mode="bull"), mk)
    row("SELL + EMA50 BEAR",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5,
               macro_field="ema50_trend", macro_mode="bear"), mk)
    row("EMA50 aligné + EMA1h",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5, ema1_filter=True,
               macro_field="ema50_trend", macro_mode="aligned"), mk)
    row("EMA50 aligné + CVD trend",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5, cvd_trend_filter=True,
               macro_field="ema50_trend", macro_mode="aligned"), mk)
    row("EMA50 aligné + SL×1.8",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.8,
               macro_field="ema50_trend", macro_mode="aligned"), mk)
    row("EMA50 aligné + SL×2.0",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0,
               macro_field="ema50_trend", macro_mode="aligned"), mk)
    row("BUY + EMA50 BULL + SL×1.5",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5,
               macro_field="ema50_trend", macro_mode="bull"), mk)

    # ─────────────────────────────────────────────────────────────
    # 3. Supertrend daily
    # ─────────────────────────────────────────────────────────────
    section("3 — Supertrend daily × ADX>25 + SL×1.5")
    row("ST daily aligné",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5,
               macro_field="st_daily_trend", macro_mode="aligned"), mk)
    row("BUY + ST daily BULL",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5,
               macro_field="st_daily_trend", macro_mode="bull"), mk)
    row("SELL + ST daily BEAR",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5,
               macro_field="st_daily_trend", macro_mode="bear"), mk)
    row("ST daily aligné + EMA1h",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5, ema1_filter=True,
               macro_field="st_daily_trend", macro_mode="aligned"), mk)
    row("ST daily aligné + CVD trend",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5, cvd_trend_filter=True,
               macro_field="st_daily_trend", macro_mode="aligned"), mk)
    row("ST daily aligné + SL×1.8",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.8,
               macro_field="st_daily_trend", macro_mode="aligned"), mk)
    row("ST daily aligné + SL×2.0",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0,
               macro_field="st_daily_trend", macro_mode="aligned"), mk)
    row("BUY + ST daily BULL + SL×1.5",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5,
               macro_field="st_daily_trend", macro_mode="bull"), mk)

    # ─────────────────────────────────────────────────────────────
    # 4. Linear Regression Slope 30j
    # ─────────────────────────────────────────────────────────────
    section("4 — LR Slope 30j daily × ADX>25 + SL×1.5")
    row("LR Slope aligné",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5,
               macro_field="lr_trend", macro_mode="aligned"), mk)
    row("BUY + LR Slope BULL",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5,
               macro_field="lr_trend", macro_mode="bull"), mk)
    row("SELL + LR Slope BEAR",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5,
               macro_field="lr_trend", macro_mode="bear"), mk)
    row("LR Slope aligné + EMA1h",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5, ema1_filter=True,
               macro_field="lr_trend", macro_mode="aligned"), mk)
    row("LR Slope aligné + CVD trend",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5, cvd_trend_filter=True,
               macro_field="lr_trend", macro_mode="aligned"), mk)
    row("LR Slope aligné + SL×1.8",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.8,
               macro_field="lr_trend", macro_mode="aligned"), mk)
    row("LR Slope aligné + SL×2.0",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0,
               macro_field="lr_trend", macro_mode="aligned"), mk)

    # ─────────────────────────────────────────────────────────────
    # 5. DI+/DI- daily
    # ─────────────────────────────────────────────────────────────
    section("5 — DI+/DI- daily × ADX>25 + SL×1.5")
    row("DI aligné",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5,
               macro_field="di_trend", macro_mode="aligned"), mk)
    row("BUY + DI BULL",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5,
               macro_field="di_trend", macro_mode="bull"), mk)
    row("SELL + DI BEAR",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5,
               macro_field="di_trend", macro_mode="bear"), mk)
    row("DI aligné + EMA1h",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5, ema1_filter=True,
               macro_field="di_trend", macro_mode="aligned"), mk)
    row("DI aligné + SL×1.8",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.8,
               macro_field="di_trend", macro_mode="aligned"), mk)
    row("DI aligné + SL×2.0",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0,
               macro_field="di_trend", macro_mode="aligned"), mk)
    row("BUY + DI BULL + SL×1.5",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5,
               macro_field="di_trend", macro_mode="bull"), mk)

    # ─────────────────────────────────────────────────────────────
    # 6. Donchian 20j
    # ─────────────────────────────────────────────────────────────
    section("6 — Donchian 20j daily × ADX>25 + SL×1.5")
    row("Donchian aligné",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5,
               macro_field="don_trend", macro_mode="aligned"), mk)
    row("BUY + Donchian BULL",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5,
               macro_field="don_trend", macro_mode="bull"), mk)
    row("SELL + Donchian BEAR",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5,
               macro_field="don_trend", macro_mode="bear"), mk)
    row("Donchian aligné + EMA1h",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.5, ema1_filter=True,
               macro_field="don_trend", macro_mode="aligned"), mk)
    row("Donchian aligné + SL×1.8",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=1.8,
               macro_field="don_trend", macro_mode="aligned"), mk)
    row("Donchian aligné + SL×2.0",
        run_v6(candles, sigs, adx1h_min=25, sl_mult=2.0,
               macro_field="don_trend", macro_mode="aligned"), mk)

    # ─────────────────────────────────────────────────────────────
    # 7. COMBOS — deux filtres macro simultanés
    # ─────────────────────────────────────────────────────────────
    section("7 — COMBOS de filtres macro (EMA200 + autre)")

    def run_combo(sigs, f1, f2, adx=25, sl=1.5):
        """Filtre combiné : deux champs macro doivent être alignés."""
        trades = []; end_idx = 0; prev = 0
        last_ts = {"BUY": 0, "SELL": 0}
        for s in sigs:
            if s["idx"] < end_idx:               prev = s["score"]; continue
            if not (prev < 70 <= s["score"]):     prev = s["score"]; continue
            prev = s["score"]
            d   = s["direction"]
            m1  = s.get(f1, "neutral")
            m2  = s.get(f2, "neutral")
            if d == "BUY"  and (m1 != "bull" or m2 != "bull"): continue
            if d == "SELL" and (m1 != "bear" or m2 != "bear"): continue
            if m1 == "neutral" or m2 == "neutral":             continue
            if s.get("adx1h", 0) < adx:                        continue
            if (s["ts"] - last_ts[d]) < 2 * 3600:             continue
            pnl, rsn, bars = _sim_custom_sl(candles, s["idx"], d, s["atr"], sl)
            if rsn == "skip": continue
            last_ts[d] = s["ts"]
            trades.append({**s, "pnl_pct": pnl*100, "pnl_eur": pnl*TRADE_SIZE,
                           "reason": rsn, "bars": bars})
            end_idx = s["idx"] + bars + 4
        return trades

    combos = [
        ("EMA200 + EMA100",   "ema200_trend", "ema100_trend"),
        ("EMA200 + EMA50",    "ema200_trend", "ema50_trend"),
        ("EMA200 + ST daily", "ema200_trend", "st_daily_trend"),
        ("EMA200 + LR Slope", "ema200_trend", "lr_trend"),
        ("EMA200 + DI",       "ema200_trend", "di_trend"),
        ("EMA200 + Donchian", "ema200_trend", "don_trend"),
        ("EMA100 + ST daily", "ema100_trend", "st_daily_trend"),
        ("EMA100 + LR Slope", "ema100_trend", "lr_trend"),
        ("EMA100 + DI",       "ema100_trend", "di_trend"),
        ("EMA50 + ST daily",  "ema50_trend",  "st_daily_trend"),
        ("EMA50 + LR Slope",  "ema50_trend",  "lr_trend"),
        ("EMA50 + DI",        "ema50_trend",  "di_trend"),
        ("ST daily + LR",     "st_daily_trend","lr_trend"),
        ("ST daily + DI",     "st_daily_trend","di_trend"),
        ("LR + DI",           "lr_trend",      "di_trend"),
    ]
    for label, f1, f2 in combos:
        row(f"ADX>25+SL×1.5 + {label}", run_combo(sigs, f1, f2), mk)

    # ─────────────────────────────────────────────────────────────
    # 8. BREAKDOWN ANNUEL des meilleurs filtres
    # ─────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  ▶ 8 — BREAKDOWN ANNUEL (top configs v6)")
    print(SEP)

    annual = [
        ("No macro + ADX>25 + SL×1.5",
         dict(adx1h_min=25, sl_mult=1.5)),
        ("EMA200 aligné (référence v5)",
         dict(adx1h_min=25, sl_mult=1.5, macro_field="ema200_trend", macro_mode="aligned")),
        ("EMA100 aligné",
         dict(adx1h_min=25, sl_mult=1.5, macro_field="ema100_trend", macro_mode="aligned")),
        ("EMA50 aligné",
         dict(adx1h_min=25, sl_mult=1.5, macro_field="ema50_trend",  macro_mode="aligned")),
        ("ST daily aligné",
         dict(adx1h_min=25, sl_mult=1.5, macro_field="st_daily_trend", macro_mode="aligned")),
        ("LR Slope aligné",
         dict(adx1h_min=25, sl_mult=1.5, macro_field="lr_trend",     macro_mode="aligned")),
        ("DI aligné",
         dict(adx1h_min=25, sl_mult=1.5, macro_field="di_trend",     macro_mode="aligned")),
        ("Donchian aligné",
         dict(adx1h_min=25, sl_mult=1.5, macro_field="don_trend",    macro_mode="aligned")),
        ("BUY + EMA200 BULL + ADX>25",
         dict(adx1h_min=25, sl_mult=1.5, macro_field="ema200_trend", macro_mode="bull")),
        ("BUY + ST daily BULL + ADX>25",
         dict(adx1h_min=25, sl_mult=1.5, macro_field="st_daily_trend", macro_mode="bull")),
        ("BUY + LR Slope BULL + ADX>25",
         dict(adx1h_min=25, sl_mult=1.5, macro_field="lr_trend",     macro_mode="bull")),
        ("SELL baseline",
         dict(direction_only="SELL")),
    ]
    for label, kwargs in annual:
        t = run_v6(candles, sigs, **kwargs)
        yearly_breakdown(candles, t, label)

    # ─────────────────────────────────────────────────────────────
    # RÉSUMÉ
    # ─────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print(f"  Meilleur Win Rate : {mk['wr']:.1f}%")
    print(f"  Meilleur Sharpe   : {mk['sh']:+.2f}")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
