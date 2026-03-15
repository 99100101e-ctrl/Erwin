"""
Module commun pour tous les backtests BTC Trading Advisor.
Contient : chargement données réelles, precompute, simulation Strategie E, stats.

DONNÉES : lit backend/data/btc_1h_real.json (généré par fetch_btc_data.py).
Si le fichier est absent, une erreur claire est levée — plus de données inventées.
"""
import json, os, math
import numpy as np
from collections import defaultdict
from indicators import calculate_all_indicators
from signal_engine import SignalEngine

TRADE_SIZE = 2000  # EUR par trade

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "btc_1h_real.json")


# ─────────────────────────────────────────────────────────────────────────────
# Chargement données réelles BTC
# ─────────────────────────────────────────────────────────────────────────────

def load_real_candles(path=DATA_PATH):
    """
    Charge les bougies réelles depuis btc_1h_real.json.
    Lève une erreur claire si le fichier est absent.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"\n\n❌  DONNÉES RÉELLES MANQUANTES\n"
            f"   Fichier attendu : {path}\n\n"
            f"   Lance d'abord sur ta machine Windows :\n"
            f"       python fetch_btc_data.py\n"
            f"   puis :\n"
            f"       git add backend/data/btc_1h_real.json && git push\n"
        )
    with open(path) as f:
        candles = json.load(f)
    candles = sorted(candles, key=lambda x: x["ts"])
    print(f"  Données réelles : {len(candles)} bougies 1h chargées")
    from datetime import datetime, timezone
    d0 = datetime.fromtimestamp(candles[0]["ts"], tz=timezone.utc).strftime("%d %b %Y")
    d1 = datetime.fromtimestamp(candles[-1]["ts"], tz=timezone.utc).strftime("%d %b %Y")
    print(f"  Période         : {d0} → {d1}")
    print(f"  Prix            : ${candles[0]['close']:,.0f} → ${candles[-1]['close']:,.0f}")
    return candles


# ─────────────────────────────────────────────────────────────────────────────
# Precompute signaux
# ─────────────────────────────────────────────────────────────────────────────

def _ema_trend(ind: dict) -> str:
    emas = ind.get("emas_1h") or {}
    e20, e50, e200 = emas.get("ema20"), emas.get("ema50"), emas.get("ema200")
    if e20 and e50 and e200:
        if e20 > e50 > e200:
            return "bull"
        if e20 < e50 < e200:
            return "bear"
    return "sideways"


def precompute(candles, warmup=200, step=4, verbose=True):
    sigs = []; errors = 0
    total = (len(candles) - warmup) // step
    if verbose:
        print(f"  Calcul sur ~{total} points (step={step}h)...", end="", flush=True)

    _cur_trend = "sideways"
    _trend_since_i = warmup

    for i in range(warmup, len(candles) - 73, step):
        w = candles[max(0, i - 249):i + 1]
        c = [x["close"] for x in w]; h = [x["high"] for x in w]
        l = [x["low"] for x in w]; v = [x["volume"] for x in w]
        ts = [x["ts"] for x in w]
        c4 = c[::4]; h4 = h[::4]; l4 = l[::4]; v4 = v[::4]
        if len(c4) < 15:
            continue
        try:
            ind = calculate_all_indicators(c, h, l, v, c4, h4, l4, v4, timestamps_1h=ts)
        except Exception:
            errors += 1; continue

        trend = _ema_trend(ind)
        if trend != _cur_trend:
            _cur_trend = trend
            _trend_since_i = i
        trend_age_h = i - _trend_since_i

        sig = SignalEngine().evaluate(ind, c[-1])
        if sig.get("score", 0) < 60:
            continue
        if not sig.get("stop_loss") or not sig.get("tp1"):
            continue
        atr = ind.get("atr_1h") or 0
        if atr <= 0:
            continue
        hour_utc = (candles[i]["ts"] % 86400) // 3600
        day_of_week = (candles[i]["ts"] // 86400) % 7
        sigs.append({
            "idx": i, "score": sig["score"], "direction": sig["direction"],
            "price": c[-1], "atr": atr,
            "stop_loss": sig.get("stop_loss"), "tp1": sig.get("tp1"),
            "tp2": sig.get("tp2"), "tp3": sig.get("tp3"),
            "hour": hour_utc, "dow": day_of_week,
            "trend": trend, "trend_age_h": trend_age_h,
            "ts": candles[i]["ts"],
        })
        if verbose and len(sigs) % 100 == 0:
            print(".", end="", flush=True)
    if verbose:
        print(f" {len(sigs)} signaux ({errors} erreurs)")
    return sigs


# ─────────────────────────────────────────────────────────────────────────────
# Simulation Strategie E : TP1=1.0xR + Breakeven immediat
# ─────────────────────────────────────────────────────────────────────────────

def _levels(direction, entry, atr, sl_mult=1.8, tp1=1.0, tp2=2.5, tp3=5.0):
    if not atr or atr <= 0:
        return None, None, None, None
    d = atr * sl_mult
    if direction == "BUY":
        return entry - d, entry + d * tp1, entry + d * tp2, entry + d * tp3
    return entry + d, entry - d * tp1, entry - d * tp2, entry - d * tp3


def sim_E(candles, idx, direction, atr, max_bars=72):
    entry = candles[idx]["close"]
    sl, tp1, tp2, tp3 = _levels(direction, entry, atr)
    if sl is None:
        return 0.0, "skip", 0
    rem = 1.0; total = 0.0; t1h = t2h = False
    orig_sl = sl; cur_sl = sl
    for i in range(idx + 1, min(idx + max_bars + 1, len(candles))):
        h, l = candles[i]["high"], candles[i]["low"]; bars = i - idx
        if direction == "BUY":
            if l <= cur_sl:
                return total + (cur_sl - entry) / entry * rem, "SL" if cur_sl == orig_sl else "BE", bars
            if not t1h and h >= tp1:
                total += (tp1 - entry) / entry * .40; rem -= .40; t1h = True; cur_sl = entry
            if t1h and not t2h and h >= tp2:
                total += (tp2 - entry) / entry * .35; rem -= .35; t2h = True
            if t2h and h >= tp3:
                return total + (tp3 - entry) / entry * .25, "TP3", bars
        else:
            if h >= cur_sl:
                return total + (entry - cur_sl) / entry * rem, "SL" if cur_sl == orig_sl else "BE", bars
            if not t1h and l <= tp1:
                total += (entry - tp1) / entry * .40; rem -= .40; t1h = True; cur_sl = entry
            if t1h and not t2h and l <= tp2:
                total += (entry - tp2) / entry * .35; rem -= .35; t2h = True
            if t2h and l <= tp3:
                return total + (entry - tp3) / entry * .25, "TP3", bars
    last = candles[min(idx + max_bars, len(candles) - 1)]["close"]
    total += ((last - entry) / entry if direction == "BUY" else (entry - last) / entry) * rem
    return total, ("TP2+to" if t2h else "TP1+to" if t1h else "timeout"), max_bars


# ─────────────────────────────────────────────────────────────────────────────
# Backtest sur un groupe de signaux (Strategie E)
# ─────────────────────────────────────────────────────────────────────────────

def run_backtest(candles, sigs, thresh=70, trend_filter=False, min_trend_age=0):
    trades = []; end_idx = 0; prev = 0
    for s in sigs:
        if s["idx"] < end_idx:
            prev = s["score"]; continue
        if not (prev < thresh <= s["score"]):
            prev = s["score"]; continue
        if trend_filter:
            if s["direction"] == "BUY" and s.get("trend") != "bull":
                prev = s["score"]; continue
            if s["direction"] == "SELL" and s.get("trend") != "bear":
                prev = s["score"]; continue
        if min_trend_age > 0 and s.get("trend_age_h", 9999) < min_trend_age:
            prev = s["score"]; continue
        prev = s["score"]
        pnl, rsn, bars = sim_E(candles, s["idx"], s["direction"], s["atr"])
        if rsn == "skip":
            continue
        trades.append({
            **s,
            "pnl_pct": pnl * 100,
            "pnl_eur": pnl * TRADE_SIZE,
            "reason": rsn,
            "bars": bars,
        })
        end_idx = s["idx"] + bars + 4
    return trades


# ─────────────────────────────────────────────────────────────────────────────
# Statistiques completes sur une liste de trades
# ─────────────────────────────────────────────────────────────────────────────

def stats(trades):
    if len(trades) < 3:
        return None
    pnls = [t["pnl_pct"] for t in trades]
    eurs = [t["pnl_eur"] for t in trades]
    wins = [p for p in pnls if p > 0]
    wr = len(wins) / len(pnls) * 100
    avg = np.mean(pnls); std = np.std(pnls) or .001
    eq = np.cumprod([1 + p / 100 for p in pnls]); pk = 1.0; mdd = 0.0
    for v in eq:
        if v > pk: pk = v
        mdd = max(mdd, (pk - v) / pk)
    losses = [p for p in pnls if p < 0]
    max_streak = cur_streak = 0
    for p in pnls:
        if p < 0:
            cur_streak += 1; max_streak = max(max_streak, cur_streak)
        else:
            cur_streak = 0
    return {
        "n": len(trades), "wr": wr, "avg": avg, "med": np.median(pnls),
        "mdd": mdd, "sh": avg / std * np.sqrt(min(len(trades), 252)),
        "sl_pct": sum(1 for t in trades if t["reason"] == "SL") / len(trades) * 100,
        "be_pct": sum(1 for t in trades if t["reason"] == "BE") / len(trades) * 100,
        "tp1_pct": sum(1 for t in trades if t["reason"] in ("TP1+to",)) / len(trades) * 100,
        "tp3_pct": sum(1 for t in trades if t["reason"] == "TP3") / len(trades) * 100,
        "avg_bars": np.mean([t["bars"] for t in trades]),
        "net_eur": sum(eurs),
        "best_eur": max(eurs), "worst_eur": min(eurs),
        "avg_eur": np.mean(eurs),
        "max_streak": max_streak,
        "avg_loss": np.mean(losses) if losses else 0,
        "avg_win": np.mean(wins) if wins else 0,
    }


def print_stats_row(label, s, width=22):
    if not s:
        print(f"  {label:<{width}} |  <3   |   -    |    -     |    -    |    -    |    -       |   -")
        return
    print(f"  {label:<{width}} | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% "
          f"| -{s['mdd']*100:4.1f}% | {s['sh']:+6.2f} | {s['net_eur']:+9.0f} EUR | {s['sl_pct']:4.0f}%")
