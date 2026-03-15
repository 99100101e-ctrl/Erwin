"""
Module commun pour tous les backtests BTC Trading Advisor.
Contient : generateur de donnees, precompute, simulation Strategie E, stats.
"""
import random, math
import numpy as np
from collections import defaultdict
from indicators import calculate_all_indicators
from signal_engine import SignalEngine

TRADE_SIZE = 2000  # EUR par trade


# ─────────────────────────────────────────────────────────────────────────────
# Generateur synthetique BTC 1 an (1h candles)
# ─────────────────────────────────────────────────────────────────────────────

def generate_btc_1an(n=8760, start=67000.0, seed=42):
    random.seed(seed); np.random.seed(seed)
    prices = [start]; vols = [1000.0]
    regime = "bull"; remaining = random.randint(200, 600); cur_vol = 0.008
    regimes_log = []
    for i in range(1, n):
        remaining -= 1
        if remaining <= 0:
            regime = random.choices(["bull", "bear", "sideways"], weights=[.40, .25, .35])[0]
            remaining = random.randint(100, 500)
        shock = abs(random.gauss(0, 1))
        cur_vol = 0.85 * cur_vol + 0.15 * (
            {"bull": .007, "bear": .010, "sideways": .005}[regime] * (0.5 + shock))
        drift = {"bull": .00015, "bear": -.00012, "sideways": 0.0}[regime]
        ret = random.gauss(drift, cur_vol)
        if random.random() < 0.005:
            ret += random.choice([-1, 1]) * random.uniform(.02, .04)
        prices.append(max(prices[-1] * math.exp(ret), 1000))
        vols.append(random.uniform(400, 1200) * (1 + 3 * abs(ret) / max(cur_vol, 1e-9)))
        regimes_log.append(regime)
    candles = []
    for i, (c, v) in enumerate(zip(prices, vols)):
        sp = c * random.uniform(.001, .004); o = prices[i - 1] if i > 0 else c
        h = max(o, c) + sp * random.uniform(.2, 1.)
        l = min(o, c) - sp * random.uniform(.2, 1.)
        candles.append({
            "ts": 1704067200 + i * 3600,
            "open": round(o, 2), "high": round(h, 2),
            "low": round(l, 2), "close": round(c, 2), "volume": round(v, 2),
            "regime": regimes_log[i - 1] if i > 0 else "bull",
        })
    return candles


# ─────────────────────────────────────────────────────────────────────────────
# Precompute signaux (SANS opens_1h — parametre invalide corrige)
# ─────────────────────────────────────────────────────────────────────────────

def precompute(candles, warmup=200, step=4, verbose=True):
    sigs = []; errors = 0
    total = (len(candles) - warmup) // step
    if verbose:
        print(f"  Calcul sur ~{total} points (step={step}h)...", end="", flush=True)
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
        sig = SignalEngine().evaluate(ind, c[-1])
        if sig.get("suppressed") or sig.get("signal") in ("HOLD", "WAIT"):
            continue
        if not sig.get("stop_loss") or not sig.get("tp1"):
            continue
        atr = ind.get("atr_1h") or 0
        if atr <= 0:
            continue
        hour_utc = (candles[i]["ts"] % 86400) // 3600
        day_of_week = (candles[i]["ts"] // 86400) % 7  # 0=Jeu (epoch=Thu)
        sigs.append({
            "idx": i, "score": sig["score"], "direction": sig["direction"],
            "price": c[-1], "atr": atr,
            "regime": candles[i].get("regime", "unknown"),
            "hour": hour_utc,
            "dow": day_of_week,
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

def run_backtest(candles, sigs, thresh=70):
    trades = []; end_idx = 0; prev = 0
    for s in sigs:
        if s["idx"] < end_idx:
            prev = s["score"]; continue
        if not (prev < thresh <= s["score"]):
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
    # Serie de pertes consecutives max
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
