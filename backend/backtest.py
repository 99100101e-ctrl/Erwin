"""
Backtest 6 mois — BTC Trading Advisor
Comparaison de 6 stratégies de gestion du risque
Données RÉELLES : backend/data/btc_1h_real.json (Binance BTCUSDT 1h)
"""
import numpy as np
from datetime import datetime, timezone
from bt_common import (load_real_candles, precompute as bt_precompute,
                        TRADE_SIZE)
from indicators import calculate_all_indicators
from signal_engine import SignalEngine


# ─────────────────────────────────────────────────────────────────────────────
# Calcul des niveaux de risque
# ─────────────────────────────────────────────────────────────────────────────

def _levels_from_atr(direction, entry, atr, sl_mult=1.8, tp1_rr=1.5, tp2_rr=2.5, tp3_rr=5.0):
    if not atr or atr <= 0:
        return None, None, None, None
    sl_dist = atr * sl_mult
    if direction == "BUY":
        return entry - sl_dist, entry + sl_dist * tp1_rr, entry + sl_dist * tp2_rr, entry + sl_dist * tp3_rr
    return entry + sl_dist, entry - sl_dist * tp1_rr, entry - sl_dist * tp2_rr, entry - sl_dist * tp3_rr


# ─────────────────────────────────────────────────────────────────────────────
# Strategie A : baseline, pas de BE ni trailing
# ─────────────────────────────────────────────────────────────────────────────

def sim_trade_A(candles, idx, direction, atr, max_bars=72):
    entry = candles[idx]["close"]
    sl, tp1, tp2, tp3 = _levels_from_atr(direction, entry, atr)
    if sl is None: return 0.0, "skip", 0
    rem = 1.0; total = 0.0; t1h = t2h = False
    for i in range(idx + 1, min(idx + max_bars + 1, len(candles))):
        h, l = candles[i]["high"], candles[i]["low"]; bars = i - idx
        if direction == "BUY":
            if l <= sl: return total + (sl - entry) / entry * rem, "SL", bars
            if not t1h and h >= tp1: total += (tp1 - entry) / entry * .40; rem -= .40; t1h = True
            if t1h and not t2h and h >= tp2: total += (tp2 - entry) / entry * .35; rem -= .35; t2h = True
            if t2h and h >= tp3: return total + (tp3 - entry) / entry * .25, "TP3", bars
        else:
            if h >= sl: return total + (entry - sl) / entry * rem, "SL", bars
            if not t1h and l <= tp1: total += (entry - tp1) / entry * .40; rem -= .40; t1h = True
            if t1h and not t2h and l <= tp2: total += (entry - tp2) / entry * .35; rem -= .35; t2h = True
            if t2h and l <= tp3: return total + (entry - tp3) / entry * .25, "TP3", bars
    last = candles[min(idx + max_bars, len(candles) - 1)]["close"]
    total += ((last - entry) / entry if direction == "BUY" else (entry - last) / entry) * rem
    return total, ("TP2+to" if t2h else "TP1+to" if t1h else "timeout"), max_bars


# ─────────────────────────────────────────────────────────────────────────────
# Strategie B : breakeven apres TP1
# ─────────────────────────────────────────────────────────────────────────────

def sim_trade_B(candles, idx, direction, atr, max_bars=72):
    entry = candles[idx]["close"]
    sl, tp1, tp2, tp3 = _levels_from_atr(direction, entry, atr)
    if sl is None: return 0.0, "skip", 0
    rem = 1.0; total = 0.0; t1h = t2h = False
    orig_sl = sl; current_sl = sl
    for i in range(idx + 1, min(idx + max_bars + 1, len(candles))):
        h, l = candles[i]["high"], candles[i]["low"]; bars = i - idx
        if direction == "BUY":
            if l <= current_sl: return total + (current_sl - entry) / entry * rem, "SL" if current_sl == orig_sl else "BE", bars
            if not t1h and h >= tp1: total += (tp1 - entry) / entry * .40; rem -= .40; t1h = True; current_sl = entry
            if t1h and not t2h and h >= tp2: total += (tp2 - entry) / entry * .35; rem -= .35; t2h = True
            if t2h and h >= tp3: return total + (tp3 - entry) / entry * .25, "TP3", bars
        else:
            if h >= current_sl: return total + (entry - current_sl) / entry * rem, "SL" if current_sl == orig_sl else "BE", bars
            if not t1h and l <= tp1: total += (entry - tp1) / entry * .40; rem -= .40; t1h = True; current_sl = entry
            if t1h and not t2h and l <= tp2: total += (entry - tp2) / entry * .35; rem -= .35; t2h = True
            if t2h and l <= tp3: return total + (entry - tp3) / entry * .25, "TP3", bars
    last = candles[min(idx + max_bars, len(candles) - 1)]["close"]
    total += ((last - entry) / entry if direction == "BUY" else (entry - last) / entry) * rem
    return total, ("TP2+to" if t2h else "TP1+to" if t1h else "timeout"), max_bars


# ─────────────────────────────────────────────────────────────────────────────
# Strategie C : SL plus large = 2.5×ATR
# ─────────────────────────────────────────────────────────────────────────────

def sim_trade_C(candles, idx, direction, atr, max_bars=72):
    entry = candles[idx]["close"]
    sl, tp1, tp2, tp3 = _levels_from_atr(direction, entry, atr, sl_mult=2.5)
    if sl is None: return 0.0, "skip", 0
    rem = 1.0; total = 0.0; t1h = t2h = False
    for i in range(idx + 1, min(idx + max_bars + 1, len(candles))):
        h, l = candles[i]["high"], candles[i]["low"]; bars = i - idx
        if direction == "BUY":
            if l <= sl: return total + (sl - entry) / entry * rem, "SL", bars
            if not t1h and h >= tp1: total += (tp1 - entry) / entry * .40; rem -= .40; t1h = True
            if t1h and not t2h and h >= tp2: total += (tp2 - entry) / entry * .35; rem -= .35; t2h = True
            if t2h and h >= tp3: return total + (tp3 - entry) / entry * .25, "TP3", bars
        else:
            if h >= sl: return total + (entry - sl) / entry * rem, "SL", bars
            if not t1h and l <= tp1: total += (entry - tp1) / entry * .40; rem -= .40; t1h = True
            if t1h and not t2h and l <= tp2: total += (entry - tp2) / entry * .35; rem -= .35; t2h = True
            if t2h and l <= tp3: return total + (entry - tp3) / entry * .25, "TP3", bars
    last = candles[min(idx + max_bars, len(candles) - 1)]["close"]
    total += ((last - entry) / entry if direction == "BUY" else (entry - last) / entry) * rem
    return total, ("TP2+to" if t2h else "TP1+to" if t1h else "timeout"), max_bars


# ─────────────────────────────────────────────────────────────────────────────
# Strategie D : trailing stop 1.5×ATR apres TP1
# ─────────────────────────────────────────────────────────────────────────────

def sim_trade_D(candles, idx, direction, atr, max_bars=72):
    entry = candles[idx]["close"]
    sl, tp1, tp2, tp3 = _levels_from_atr(direction, entry, atr)
    if sl is None: return 0.0, "skip", 0
    rem = 1.0; total = 0.0; t1h = t2h = False
    current_sl = sl; trail_dist = atr * 1.5; best_price = entry
    for i in range(idx + 1, min(idx + max_bars + 1, len(candles))):
        h, l = candles[i]["high"], candles[i]["low"]; bars = i - idx
        if direction == "BUY":
            if t1h: best_price = max(best_price, h); current_sl = max(current_sl, best_price - trail_dist)
            if l <= current_sl: return total + (current_sl - entry) / entry * rem, "SL" if not t1h else "Trail", bars
            if not t1h and h >= tp1:
                total += (tp1 - entry) / entry * .40; rem -= .40; t1h = True
                best_price = h; current_sl = max(sl, h - trail_dist)
            if t1h and not t2h and h >= tp2: total += (tp2 - entry) / entry * .35; rem -= .35; t2h = True
            if t2h and h >= tp3: return total + (tp3 - entry) / entry * .25, "TP3", bars
        else:
            if t1h: best_price = min(best_price, l); current_sl = min(current_sl, best_price + trail_dist)
            if h >= current_sl: return total + (entry - current_sl) / entry * rem, "SL" if not t1h else "Trail", bars
            if not t1h and l <= tp1:
                total += (entry - tp1) / entry * .40; rem -= .40; t1h = True
                best_price = l; current_sl = min(sl, l + trail_dist)
            if t1h and not t2h and l <= tp2: total += (entry - tp2) / entry * .35; rem -= .35; t2h = True
            if t2h and l <= tp3: return total + (entry - tp3) / entry * .25, "TP3", bars
    last = candles[min(idx + max_bars, len(candles) - 1)]["close"]
    total += ((last - entry) / entry if direction == "BUY" else (entry - last) / entry) * rem
    return total, ("TP2+to" if t2h else "TP1+to" if t1h else "timeout"), max_bars


# ─────────────────────────────────────────────────────────────────────────────
# Strategie E : TP1 rapproche (1.0×R) + BE immediat
# ─────────────────────────────────────────────────────────────────────────────

def sim_trade_E(candles, idx, direction, atr, max_bars=72):
    entry = candles[idx]["close"]
    sl, tp1, tp2, tp3 = _levels_from_atr(direction, entry, atr, tp1_rr=1.0, tp2_rr=2.5, tp3_rr=5.0)
    if sl is None: return 0.0, "skip", 0
    rem = 1.0; total = 0.0; t1h = t2h = False
    orig_sl = sl; current_sl = sl
    for i in range(idx + 1, min(idx + max_bars + 1, len(candles))):
        h, l = candles[i]["high"], candles[i]["low"]; bars = i - idx
        if direction == "BUY":
            if l <= current_sl: return total + (current_sl - entry) / entry * rem, "SL" if current_sl == orig_sl else "BE", bars
            if not t1h and h >= tp1: total += (tp1 - entry) / entry * .40; rem -= .40; t1h = True; current_sl = entry
            if t1h and not t2h and h >= tp2: total += (tp2 - entry) / entry * .35; rem -= .35; t2h = True
            if t2h and h >= tp3: return total + (tp3 - entry) / entry * .25, "TP3", bars
        else:
            if h >= current_sl: return total + (entry - current_sl) / entry * rem, "SL" if current_sl == orig_sl else "BE", bars
            if not t1h and l <= tp1: total += (entry - tp1) / entry * .40; rem -= .40; t1h = True; current_sl = entry
            if t1h and not t2h and l <= tp2: total += (entry - tp2) / entry * .35; rem -= .35; t2h = True
            if t2h and l <= tp3: return total + (entry - tp3) / entry * .25, "TP3", bars
    last = candles[min(idx + max_bars, len(candles) - 1)]["close"]
    total += ((last - entry) / entry if direction == "BUY" else (entry - last) / entry) * rem
    return total, ("TP2+to" if t2h else "TP1+to" if t1h else "timeout"), max_bars


# ─────────────────────────────────────────────────────────────────────────────
# Precompute (version locale pour backtest.py, stocke les EMAs)
# ─────────────────────────────────────────────────────────────────────────────

def precompute(candles, warmup=200, step=6):
    sigs = []
    N = (len(candles) - warmup) // step
    print(f"  Calcul sur {N} points (step={step}h)...", end="", flush=True)
    for i in range(warmup, len(candles) - 73, step):
        w = candles[max(0, i - 249):i + 1]
        c = [x["close"] for x in w]; h = [x["high"] for x in w]
        l = [x["low"] for x in w]; v = [x["volume"] for x in w]
        ts = [x["ts"] for x in w]
        c4 = c[::4]; h4 = h[::4]; l4 = l[::4]; v4 = v[::4]
        if len(c4) < 15: continue
        try:
            ind = calculate_all_indicators(c, h, l, v, c4, h4, l4, v4, timestamps_1h=ts)
        except Exception:
            continue
        sig = SignalEngine().evaluate(ind, c[-1])
        if not sig.get("stop_loss") or not sig.get("tp1"): continue
        atr = ind.get("atr_1h") or 0
        if atr <= 0: continue
        sigs.append({
            "idx": i, "score": sig["score"], "direction": sig["direction"],
            "price": c[-1], "atr": atr, "emas_1h": ind.get("emas_1h") or {},
        })
        if len(sigs) % 50 == 0: print(".", end="", flush=True)
    print(f" {len(sigs)} signaux")
    return sigs


# ─────────────────────────────────────────────────────────────────────────────
# Filtre tendance pour strategie F
# ─────────────────────────────────────────────────────────────────────────────

def _get_trend_filter(sig):
    emas = sig.get("emas_1h") or {}
    e20 = emas.get("ema20"); e50 = emas.get("ema50"); e200 = emas.get("ema200")
    price = sig["price"]
    if e20 and e50 and e200:
        if e20 > e50 and price > e200: trend = "Bullish"
        elif e20 > e50: trend = "Mildly Bullish"
        elif e20 < e50 and price < e200: trend = "Bearish"
        elif e20 < e50: trend = "Mildly Bearish"
        else: trend = "Neutral"
    elif e20 and e50:
        trend = "Mildly Bullish" if e20 > e50 else "Mildly Bearish"
    else:
        trend = "Neutral"
    if sig["direction"] == "BUY" and trend in {"Bullish", "Mildly Bullish"}: return True
    if sig["direction"] == "SELL" and trend in {"Bearish", "Mildly Bearish"}: return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Backtest par seuil et par strategie
# ─────────────────────────────────────────────────────────────────────────────

def bt_thresh(candles, sigs, thresh):
    trades = []; end_idx = 0; prev = 0
    for s in sigs:
        if s["idx"] < end_idx: prev = s["score"]; continue
        crossed = (prev < thresh <= s["score"]); prev = s["score"]
        if not crossed: continue
        pnl, rsn, bars = sim_trade_A(candles, s["idx"], s["direction"], s["atr"])
        if rsn == "skip": continue
        trades.append({**s, "pnl": pnl * 100, "reason": rsn, "bars": bars})
        end_idx = s["idx"] + bars + 4
    return trades


def bt_strategies(candles, sigs, thresh=80):
    filtered = []; prev = 0
    for s in sigs:
        crossed = (prev < thresh <= s["score"]); prev = s["score"]
        if crossed: filtered.append(s)

    def run_strat(sim_fn, sigs_list):
        trades = []; end_idx = 0
        for s in sigs_list:
            if s["idx"] < end_idx: continue
            pnl, rsn, bars = sim_fn(s)
            if rsn == "skip": continue
            trades.append({**s, "pnl": pnl * 100, "reason": rsn, "bars": bars})
            end_idx = s["idx"] + bars + 4
        return trades

    return {
        "A": run_strat(lambda s: sim_trade_A(candles, s["idx"], s["direction"], s["atr"]), filtered),
        "B": run_strat(lambda s: sim_trade_B(candles, s["idx"], s["direction"], s["atr"]), filtered),
        "C": run_strat(lambda s: sim_trade_C(candles, s["idx"], s["direction"], s["atr"]), filtered),
        "D": run_strat(lambda s: sim_trade_D(candles, s["idx"], s["direction"], s["atr"]), filtered),
        "E": run_strat(lambda s: sim_trade_E(candles, s["idx"], s["direction"], s["atr"]), filtered),
        "F": run_strat(
            lambda s: sim_trade_A(candles, s["idx"], s["direction"], s["atr"]),
            [s for s in filtered if _get_trend_filter(s)],
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Statistiques
# ─────────────────────────────────────────────────────────────────────────────

def stats(trades):
    if len(trades) < 3: return None
    pnls = [t["pnl"] for t in trades]; wins = [p for p in pnls if p > 0]
    wr = len(wins) / len(pnls) * 100; avg = np.mean(pnls); std = np.std(pnls) or .001
    eq = np.cumprod([1 + p / 100 for p in pnls]); pk = 1.0; mdd = 0.0
    for v in eq:
        if v > pk: pk = v
        mdd = max(mdd, (pk - v) / pk)
    net_eur = sum(p / 100 * TRADE_SIZE for p in pnls)
    return {
        "n": len(trades), "wr": wr, "avg": avg, "med": np.median(pnls), "mdd": mdd,
        "sh": avg / std * np.sqrt(min(len(trades), 252)),
        "sl_pct": sum(1 for t in trades if t["reason"] == "SL") / len(trades) * 100,
        "be_pct": sum(1 for t in trades if t["reason"] == "BE") / len(trades) * 100,
        "tp3_pct": sum(1 for t in trades if t["reason"] == "TP3") / len(trades) * 100,
        "avg_bars": np.mean([t["bars"] for t in trades]),
        "net_eur": net_eur,
    }


def score_strategy(s):
    if not s: return -999
    wr_bonus = 1.0 if s["wr"] > 50 else (0.7 if s["wr"] > 42 else 0.4)
    return s["sh"] * wr_bonus / (1 + s["mdd"]) * (1 if s["avg"] > 0 else 0.1)


# ─────────────────────────────────────────────────────────────────────────────
# Point d'entree
# ─────────────────────────────────────────────────────────────────────────────

def run():
    print("\n" + "=" * 70)
    print("  BACKTEST 6 MOIS — Comparaison 6 strategies — DONNÉES RÉELLES BINANCE")
    print("=" * 70 + "\n")

    candles = load_real_candles()
    p0, p1 = candles[200]["close"], candles[-1]["close"]
    d0 = datetime.fromtimestamp(candles[200]["ts"], tz=timezone.utc).strftime("%d %b %Y")
    d1 = datetime.fromtimestamp(candles[-1]["ts"], tz=timezone.utc).strftime("%d %b %Y")
    print(f"  BTC réel : ${p0:,.0f} ({d0}) -> ${p1:,.0f} ({d1})  ({(p1/p0-1)*100:+.1f}%)\n")

    # ── Phase 1 : Seuil optimal ──────────────────────────────────────────────
    print("─" * 70)
    print("  PHASE 1 : Seuil optimal (strategie baseline A)")
    print("─" * 70)
    sigs = precompute(candles, step=6)
    thresholds = [30, 40, 50, 60, 70, 80, 90]
    results_thresh = {t: bt_thresh(candles, sigs, t) for t in thresholds}
    st_thresh = {t: stats(results_thresh[t]) for t in thresholds}

    print(f"\n{'Seuil':>7} | {'N':>5} | {'Win%':>6} | {'Moy P&L':>8} | {'MaxDD':>7} | {'Sharpe':>7} | {'SL%':>5}")
    print("─" * 62)
    for t in thresholds:
        s = st_thresh[t]
        if not s:
            print(f"  >= {t:3d}  |  <3   |   -    |    -     |    -    |    -    |   -")
            continue
        flag = "  * " if (s["wr"] > 45 and s["avg"] > 0.5) else ("  + " if s["avg"] > 0 and s["mdd"] < .25 else "")
        print(f"  >= {t:3d}  | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% | -{s['mdd']*100:4.1f}% | {s['sh']:+6.2f} | {s['sl_pct']:4.0f}%{flag}")
    print("─" * 62 + "  * Optimal  + Acceptable")

    scored = {t: st_thresh[t]["sh"] * (1 if st_thresh[t]["wr"] > 45 else .5) / max(st_thresh[t]["mdd"], .05)
              for t in thresholds if st_thresh[t] and st_thresh[t]["n"] >= 3}
    best_thresh = max(scored, key=scored.get) if scored else 80

    # ── Phase 2 : Comparaison des 6 strategies ───────────────────────────────
    print(f"\n{'─' * 70}")
    print(f"  PHASE 2 : Comparaison 6 strategies (seuil = {best_thresh})")
    print(f"{'─' * 70}\n")
    print("  A = Baseline (SL=1.8xATR, TP1=1.5xR, pas de BE/trailing)")
    print("  B = Breakeven apres TP1")
    print("  C = SL large 2.5xATR")
    print("  D = Trailing stop 1.5xATR apres TP1")
    print("  E = TP1 rapproche (1.0xR) + BE immediat  [RECOMMANDE]")
    print("  F = Filtre tendance EMA (BUY=Bullish, SELL=Bearish)\n")

    strat_results = bt_strategies(candles, sigs, thresh=best_thresh)
    strat_stats = {k: stats(v) for k, v in strat_results.items()}

    names = {
        "A": "A - Baseline        ", "B": "B - Breakeven/TP1   ",
        "C": "C - SL large 2.5xATR", "D": "D - Trailing Stop   ",
        "E": "E - TP1 proche+BE   ", "F": "F - Filtre tendance ",
    }

    print(f"{'Strategie':<22} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'MaxDD':>7} | {'Sharpe':>7} | {'Net EUR':>10}")
    print("─" * 80)
    best_strat = None; best_score_val = -999
    valid_scores = {k: score_strategy(strat_stats[k]) for k in strat_stats if strat_stats[k]}
    best_score_overall = max(valid_scores.values()) if valid_scores else -999
    for k in ["A", "B", "C", "D", "E", "F"]:
        s = strat_stats[k]
        if not s:
            print(f"  {names[k]} |  <3   |   -    |    -     |    -    |    -    |    -")
            continue
        sc = score_strategy(s)
        flag = " *" if sc == best_score_overall else ""
        if sc > best_score_val: best_score_val = sc; best_strat = k
        print(f"  {names[k]} | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% | -{s['mdd']*100:4.1f}% | {s['sh']:+6.2f} | {s['net_eur']:+9.0f}€{flag}")
    print("─" * 80 + "  * Meilleure strategie")

    print(f"\n{'=' * 70}")
    print(f"  RECOMMANDATION : {best_strat} — {names.get(best_strat,'').strip()} | seuil >= {best_thresh}")
    print(f"  Données : RÉELLES — Binance BTCUSDT 1h")
    print(f"{'=' * 70}\n")

    return best_strat, best_thresh, strat_stats


if __name__ == "__main__":
    run()
