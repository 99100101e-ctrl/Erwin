"""
apex_live/backtest.py — Backtest APEX v2 sur 6 mois de données BTC/USDT réelles

Télécharge les données depuis Binance public API (pas de clé requise).
Usage : python apex_live/backtest.py
"""

import json, math, time, sys
import requests
import numpy as np
from datetime import datetime, timezone, timedelta

# ── Config (mirrors config.py) ─────────────────────────────────────────────
SYMBOL        = "BTCUSDT"
SL_MULT       = 2.0
TP1_R         = 1.2
TP2_R         = 2.5
TP3_R         = 5.0
SCORE_BUY     = 2
SCORE_SELL    = 3
ADX_MIN_BUY   = 25
ADX_MIN_SELL  = 20
COOLDOWN_H    = 3
TIMEOUT_H     = 96
TRADE_SIZE    = 2000.0      # USDT par trade
EXT_ATR       = 7.0
BOS_LOOKBACK  = 20
ATR_SQZ_LOOK  = 20
ATR_SQZ_RATIO = 1.25
VOL_SURGE_R   = 1.5

BINANCE_BASE  = "https://api.binance.com/api/v3"

# ── Data fetching ───────────────────────────────────────────────────────────

def fetch_klines(symbol, interval, start_ms, end_ms, limit=1000):
    all_candles = []
    url    = f"{BINANCE_BASE}/klines"
    params = {"symbol": symbol, "interval": interval,
               "startTime": start_ms, "endTime": end_ms, "limit": limit}
    while True:
        resp = requests.get(url, params=params, timeout=20)
        data = resp.json()
        if not data or isinstance(data, dict):
            break
        all_candles.extend(data)
        if len(data) < limit:
            break
        params["startTime"] = int(data[-1][0]) + 1
        if params["startTime"] > end_ms:
            break
        time.sleep(0.08)
    return all_candles

# ── Indicateurs ─────────────────────────────────────────────────────────────

def ema(arr, period):
    out = np.full(len(arr), np.nan)
    if len(arr) < period:
        return out
    k = 2.0 / (period + 1)
    out[period - 1] = float(np.mean(arr[:period]))
    for i in range(period, len(arr)):
        out[i] = arr[i] * k + out[i - 1] * (1 - k)
    return out


def rsi(close, period=14):
    out = np.full(len(close), np.nan)
    if len(close) <= period:
        return out
    deltas = np.diff(close)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    ag = float(np.mean(gains[:period]))
    al = float(np.mean(losses[:period]))
    for i in range(period, len(close) - 1):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
        out[i + 1] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def atr(high, low, close, period=14):
    n   = len(close)
    out = np.full(n, np.nan)
    tr  = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i],
                    abs(high[i] - close[i - 1]),
                    abs(low[i]  - close[i - 1]))
    if n < period:
        return out
    out[period - 1] = float(np.mean(tr[:period]))
    for i in range(period, n):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def adx(high, low, close, period=14):
    """Wilder's ADX."""
    n   = len(close)
    out = np.full(n, np.nan)
    if n < period + 2:
        return out
    tr  = np.zeros(n)
    pdm = np.zeros(n)
    ndm = np.zeros(n)
    for i in range(1, n):
        hd = high[i] - high[i - 1]
        ld = low[i - 1] - low[i]
        pdm[i] = hd if hd > ld and hd > 0 else 0.0
        ndm[i] = ld if ld > hd and ld > 0 else 0.0
        tr[i]  = max(high[i] - low[i],
                     abs(high[i] - close[i - 1]),
                     abs(low[i]  - close[i - 1]))
    # First smoothed values
    atr_s  = float(np.sum(tr[1: period + 1]))
    pdm_s  = float(np.sum(pdm[1: period + 1]))
    ndm_s  = float(np.sum(ndm[1: period + 1]))
    dx_arr = np.full(n, np.nan)
    for i in range(period + 1, n):
        atr_s = atr_s - atr_s / period + tr[i]
        pdm_s = pdm_s - pdm_s / period + pdm[i]
        ndm_s = ndm_s - ndm_s / period + ndm[i]
        if atr_s == 0:
            continue
        pdi = 100 * pdm_s / atr_s
        ndi = 100 * ndm_s / atr_s
        dx_arr[i] = 100 * abs(pdi - ndi) / (pdi + ndi) if (pdi + ndi) > 0 else 0.0
    # Smooth DX → ADX
    first = next((i for i in range(n) if not np.isnan(dx_arr[i])), None)
    if first is None:
        return out
    out[first] = dx_arr[first]
    for i in range(first + 1, n):
        if not np.isnan(dx_arr[i]):
            out[i] = (out[i - 1] * (period - 1) + dx_arr[i]) / period
    return out


def macd(close, fast=12, slow=26, signal=9):
    ef  = ema(close, fast)
    es  = ema(close, slow)
    ml  = ef - es
    sl_ = ema(np.where(np.isnan(ml), 0, ml), signal)
    return ml, sl_

# ── Helpers ─────────────────────────────────────────────────────────────────

def is_trade_hour(ts_s):
    dt = datetime.fromtimestamp(ts_s, tz=timezone.utc)
    if dt.weekday() == 6:           # Dimanche
        return False
    h = dt.hour
    return 8 <= h < 22 and not (16 <= h < 18)

# ── Backtest principal ───────────────────────────────────────────────────────

def run_backtest():
    now   = datetime.now(tz=timezone.utc)
    end   = now - timedelta(hours=1)
    start = end - timedelta(days=183)

    start_fetch = start - timedelta(days=15)    # warmup indicateurs
    start_daily = start - timedelta(days=120)   # warmup EMA100 daily

    start_ms = int(start_fetch.timestamp() * 1000)
    end_ms   = int(end.timestamp() * 1000)

    print(f"\n  Période : {start.date()} → {end.date()}")
    print(f"  Téléchargement données 1h ...", end="", flush=True)
    raw_1h = fetch_klines(SYMBOL, "1h", start_ms, end_ms)
    print(f" {len(raw_1h)} bougies")

    print(f"  Téléchargement données daily ...", end="", flush=True)
    raw_1d = fetch_klines(SYMBOL, "1d",
                          int(start_daily.timestamp() * 1000), end_ms)
    print(f" {len(raw_1d)} bougies")

    # Arrays 1h
    ts_1h = np.array([c[0] / 1000 for c in raw_1h])
    o_1h  = np.array([float(c[1]) for c in raw_1h])
    h_1h  = np.array([float(c[2]) for c in raw_1h])
    l_1h  = np.array([float(c[3]) for c in raw_1h])
    c_1h  = np.array([float(c[4]) for c in raw_1h])
    v_1h  = np.array([float(c[5]) for c in raw_1h])

    # Arrays daily
    ts_1d = np.array([c[0] / 1000 for c in raw_1d])
    c_1d  = np.array([float(c[4]) for c in raw_1d])

    print("  Calcul indicateurs 1h ...", end="", flush=True)
    ema20_h   = ema(c_1h, 20)
    ema50_h   = ema(c_1h, 50)
    rsi14_h   = rsi(c_1h, 14)
    atr14_h   = atr(h_1h, l_1h, c_1h, 14)
    adx14_h   = adx(h_1h, l_1h, c_1h, 14)
    volsma_h  = np.array([
        np.mean(v_1h[max(0, i - 19): i + 1]) if i >= 19 else np.nan
        for i in range(len(v_1h))
    ])
    macd_l_h, macd_s_h = macd(c_1h)

    # EMA100 daily
    ema100_d = ema(c_1d, 100)
    print(" OK")

    # 4h series (reconstruit depuis 1h)
    print("  Calcul indicateurs 4h ...", end="", flush=True)
    c4h, ts4h, h4h, l4h = [], [], [], []
    for i in range(3, len(c_1h), 4):
        c4h.append(c_1h[i])
        ts4h.append(ts_1h[i - 3])
        h4h.append(np.max(h_1h[i - 3: i + 1]))
        l4h.append(np.min(l_1h[i - 3: i + 1]))
    c4h  = np.array(c4h)
    ts4h = np.array(ts4h)
    rsi4h_arr  = rsi(c4h, 14)
    ema4h20_arr = ema(c4h, 20)
    ema4h50_arr = ema(c4h, 50)
    print(" OK")

    def get_macro(ts_s):
        idx = int(np.searchsorted(ts_1d, ts_s, side='right')) - 1
        if idx < 1 or np.isnan(ema100_d[idx]):
            return "neutral"
        return "bull" if c_1d[idx] > ema100_d[idx] else "bear"

    def get_4h(i):
        t = ts_1h[i]
        idx = int(np.searchsorted(ts4h, t, side='right')) - 1
        if idx < 0:
            return np.nan, np.nan, np.nan
        r  = rsi4h_arr[idx]  if idx < len(rsi4h_arr)  else np.nan
        e2 = ema4h20_arr[idx] if idx < len(ema4h20_arr) else np.nan
        e5 = ema4h50_arr[idx] if idx < len(ema4h50_arr) else np.nan
        return r, e2, e5

    # ── Simulation candle par candle ─────────────────────────────────────
    start_sim = start.timestamp()
    trades     = []
    last_sig   = {"BUY": 0.0, "SELL": 0.0}
    pos        = None

    print("  Simulation ...", end="", flush=True)
    n = len(c_1h)

    for i in range(60, n):
        ts = ts_1h[i]
        if ts < start_sim:
            continue

        # ── Gestion position ouverte ──────────────────────────────────
        if pos is not None:
            d   = pos["direction"]
            hi  = h_1h[i]
            lo  = l_1h[i]
            cl  = c_1h[i]
            sgn = 1 if d == "BUY" else -1

            sl_hit   = (lo <= pos["sl"]) if d == "BUY" else (hi >= pos["sl"])
            tp3_hit  = (hi >= pos["tp3"]) if d == "BUY" else (lo <= pos["tp3"])
            tp2_hit  = (hi >= pos["tp2"]) if d == "BUY" else (lo <= pos["tp2"])
            tp1_hit  = (hi >= pos["tp1"]) if d == "BUY" else (lo <= pos["tp1"])
            timeout  = (ts - pos["entry_ts"]) >= TIMEOUT_H * 3600

            # Ordre de priorité : SL > TP1 > TP2 > TP3
            if sl_hit:
                exit_p = pos["sl"]
                pnl = sgn * (exit_p - pos["entry"]) / pos["entry"]
                if pos["tp1_done"] and pos["tp2_done"]:
                    pnl_tot = pos["p1"] + pos["p2"] + pnl * 0.25
                elif pos["tp1_done"]:
                    pnl_tot = pos["p1"] + pnl * 0.60
                else:
                    pnl_tot = pnl
                trades.append(_make_trade(pos, exit_p, ts, "SL",
                                          pnl_tot, pos["tp1_done"], pos["tp2_done"]))
                pos = None
                continue

            # TP hits (peuvent se cumuler sur la même bougie)
            if tp1_hit and not pos["tp1_done"]:
                pos["p1"] = sgn * (pos["tp1"] - pos["entry"]) / pos["entry"] * 0.40
                pos["tp1_done"] = True
                pos["sl"] = pos["entry"]    # breakeven

            if tp2_hit and pos["tp1_done"] and not pos["tp2_done"]:
                pos["p2"] = sgn * (pos["tp2"] - pos["entry"]) / pos["entry"] * 0.35
                pos["tp2_done"] = True

            if tp3_hit and pos["tp2_done"]:
                pnl3    = sgn * (pos["tp3"] - pos["entry"]) / pos["entry"] * 0.25
                pnl_tot = pos["p1"] + pos["p2"] + pnl3
                trades.append(_make_trade(pos, pos["tp3"], ts, "TP3",
                                          pnl_tot, True, True))
                pos = None
                continue

            if timeout:
                pnl = sgn * (cl - pos["entry"]) / pos["entry"]
                if pos["tp1_done"] and pos["tp2_done"]:
                    pnl_tot = pos["p1"] + pos["p2"] + pnl * 0.25
                elif pos["tp1_done"]:
                    pnl_tot = pos["p1"] + pnl * 0.60
                else:
                    pnl_tot = pnl
                trades.append(_make_trade(pos, cl, ts, "TIMEOUT",
                                          pnl_tot, pos["tp1_done"], pos["tp2_done"]))
                pos = None
                continue

            continue     # encore en position → pas de nouveau signal

        # ── Recherche signal ──────────────────────────────────────────
        if not is_trade_hour(ts):
            continue

        v = [ema20_h[i], ema50_h[i], rsi14_h[i], atr14_h[i], adx14_h[i], volsma_h[i]]
        if any(np.isnan(x) for x in v):
            continue

        macro = get_macro(ts)
        if macro == "neutral":
            continue

        if i < BOS_LOOKBACK:
            continue
        bos_hi = float(np.max(h_1h[i - BOS_LOOKBACK: i]))
        bos_lo = float(np.min(l_1h[i - BOS_LOOKBACK: i]))

        cl_now = c_1h[i]
        op_now = o_1h[i]
        r4h, e4h20, e4h50 = get_4h(i)

        for direction in ("BUY", "SELL"):
            if direction == "BUY"  and macro != "bull":  continue
            if direction == "SELL" and macro != "bear":  continue
            adx_min = ADX_MIN_BUY if direction == "BUY" else ADX_MIN_SELL
            if adx14_h[i] < adx_min:                     continue
            if direction == "BUY"  and cl_now <= bos_hi: continue
            if direction == "SELL" and cl_now >= bos_lo:  continue
            if direction == "BUY":
                if np.isnan(r4h) or not (45 <= r4h <= 72): continue
                if (cl_now - ema50_h[i]) > EXT_ATR * atr14_h[i]: continue
            if (ts - last_sig[direction]) < COOLDOWN_H * 3600: continue

            # Confirmateurs
            atr_now = atr14_h[i]
            atr_max = float(np.max(atr14_h[i - ATR_SQZ_LOOK: i])) if i >= ATR_SQZ_LOOK else np.nan
            s1 = (not np.isnan(atr_max)) and (atr_now < atr_max / ATR_SQZ_RATIO)
            s2 = v_1h[i] > VOL_SURGE_R * volsma_h[i]
            s3 = (45 <= rsi14_h[i] <= 68) if direction == "BUY" else (32 <= rsi14_h[i] <= 55)
            s4 = (ema20_h[i] > ema50_h[i]) if direction == "BUY" else (ema20_h[i] < ema50_h[i])
            body_c = abs(cl_now - op_now)
            body_p = abs(c_1h[i - 1] - o_1h[i - 1]) if i > 0 else 0
            if direction == "BUY":
                s5 = cl_now > op_now and body_c > 1.3 * body_p
            else:
                s5 = cl_now < op_now and body_c > 1.3 * body_p
            if direction == "BUY" and i > 0:
                s6 = (not any(np.isnan([macd_l_h[i], macd_s_h[i],
                                        macd_l_h[i-1], macd_s_h[i-1]])) and
                      macd_l_h[i] > macd_s_h[i] and
                      macd_l_h[i-1] <= macd_s_h[i-1])
            else:
                s6 = False

            score     = sum([s1, s2, s3, s4, s5, s6]) if direction == "BUY" else sum([s1, s2, s3, s4, s5])
            score_min = SCORE_BUY if direction == "BUY" else SCORE_SELL
            if score < score_min:
                continue

            R = SL_MULT * atr_now
            if direction == "BUY":
                sl_p  = cl_now - R
                tp1_p = cl_now + TP1_R * R
                tp2_p = cl_now + TP2_R * R
                tp3_p = cl_now + TP3_R * R
            else:
                sl_p  = cl_now + R
                tp1_p = cl_now - TP1_R * R
                tp2_p = cl_now - TP2_R * R
                tp3_p = cl_now - TP3_R * R

            pos = {
                "entry_ts":  ts,
                "direction": direction,
                "entry":     cl_now,
                "sl":        sl_p,
                "tp1":       tp1_p,
                "tp2":       tp2_p,
                "tp3":       tp3_p,
                "tp1_done":  False,
                "tp2_done":  False,
                "p1":        0.0,
                "p2":        0.0,
                "score":     score,
                "atr":       atr_now,
            }
            last_sig[direction] = ts
            break

    # Clôture position encore ouverte en fin de données
    if pos is not None:
        i   = n - 1
        cl  = c_1h[i]
        sgn = 1 if pos["direction"] == "BUY" else -1
        pnl = sgn * (cl - pos["entry"]) / pos["entry"]
        if pos["tp1_done"] and pos["tp2_done"]:
            pnl_tot = pos["p1"] + pos["p2"] + pnl * 0.25
        elif pos["tp1_done"]:
            pnl_tot = pos["p1"] + pnl * 0.60
        else:
            pnl_tot = pnl
        trades.append(_make_trade(pos, cl, ts_1h[i], "END",
                                  pnl_tot, pos["tp1_done"], pos["tp2_done"]))

    print(f" {len(trades)} trades\n")
    return trades


def _make_trade(pos, exit_p, exit_ts, reason, pnl_pct, tp1d, tp2d):
    return {
        "entry_ts":  pos["entry_ts"],
        "exit_ts":   exit_ts,
        "direction": pos["direction"],
        "entry":     round(pos["entry"], 1),
        "exit":      round(exit_p, 1),
        "sl":        round(pos["sl"], 1),
        "tp1":       round(pos["tp1"], 1),
        "tp2":       round(pos["tp2"], 1),
        "tp3":       round(pos["tp3"], 1),
        "reason":    reason,
        "pnl_pct":   round(pnl_pct * 100, 3),
        "pnl_usdt":  round(pnl_pct * TRADE_SIZE, 2),
        "tp1_done":  tp1d,
        "tp2_done":  tp2d,
        "score":     pos["score"],
        "atr":       round(pos["atr"], 1),
    }

# ── Statistiques ────────────────────────────────────────────────────────────

def compute_stats(trades):
    if not trades:
        return {}
    pnl    = [t["pnl_usdt"] for t in trades]
    n      = len(trades)
    wins   = sum(1 for p in pnl if p > 0)
    total  = sum(pnl)

    equity = [10_000.0]
    for p in pnl:
        equity.append(equity[-1] + p)

    peak, max_dd = equity[0], 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = (peak - e) / peak * 100
        if dd > max_dd:
            max_dd = dd

    daily = np.diff(equity)
    sharpe = (np.mean(daily) / np.std(daily) * math.sqrt(252)
              if len(daily) > 1 and np.std(daily) > 0 else 0.0)

    avg_w = float(np.mean([p for p in pnl if p > 0])) if wins > 0 else 0.0
    avg_l = float(np.mean([p for p in pnl if p <= 0])) if (n - wins) > 0 else 0.0
    rr    = abs(avg_w / avg_l) if avg_l != 0 else 0.0

    buy_n   = sum(1 for t in trades if t["direction"] == "BUY")
    sell_n  = n - buy_n
    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1

    return {
        "n": n, "wins": wins, "wr": wins / n * 100,
        "total_pnl": total, "equity_final": equity[-1],
        "max_dd": max_dd, "sharpe": sharpe,
        "avg_win": avg_w, "avg_loss": avg_l, "rr": rr,
        "buy_n": buy_n, "sell_n": sell_n,
        "reasons": reasons,
    }

# ── Affichage ────────────────────────────────────────────────────────────────

def print_results(trades):
    print(f"  {'Date':12} {'Dir':5} {'Entrée':>8} {'Sortie':>8}  {'Raison':8} {'PnL%':>7}  {'PnL$':>8}  TP1 TP2")
    print("  " + "─" * 78)
    for t in trades:
        dt  = datetime.fromtimestamp(t["entry_ts"], tz=timezone.utc).strftime("%d/%m %H:%M")
        arr = "▲" if t["direction"] == "BUY" else "▼"
        t1  = "✓" if t["tp1_done"] else "·"
        t2  = "✓" if t["tp2_done"] else "·"
        sgn = "+" if t["pnl_usdt"] >= 0 else ""
        print(f"  {dt:12} {arr}{t['direction']:4} {t['entry']:>8.0f} {t['exit']:>8.0f}  "
              f"{t['reason']:8} {t['pnl_pct']:>+7.2f}%  {sgn}{t['pnl_usdt']:>+7.0f}$   {t1}   {t2}")


def print_stats(s):
    col_ok  = "\033[92m"
    col_bad = "\033[91m"
    col_neu = "\033[93m"
    rst     = "\033[0m"

    def c(v, good):
        return col_ok if v >= good else col_bad

    print()
    print("  ┌─────────────────────────────────────────┐")
    print("  │        RÉSULTATS BACKTEST 6 MOIS        │")
    print("  ├─────────────────────────────────────────┤")
    print(f"  │  Trades           : {s['n']:>5}               │")
    print(f"  │  BUY / SELL       : {s['buy_n']:>3} / {s['sell_n']:<3}            │")
    wr_c = c(s['wr'], 50)
    print(f"  │  Win Rate         : {wr_c}{s['wr']:>5.1f}%{rst}  ({s['wins']}/{s['n']})      │")
    pnl_c = col_ok if s['total_pnl'] >= 0 else col_bad
    print(f"  │  PnL total        : {pnl_c}{s['total_pnl']:>+8.0f} USDT{rst}        │")
    print(f"  │  Equity finale    : {s['equity_final']:>8,.0f} USDT         │")
    dd_c = c(-s['max_dd'], -15)
    print(f"  │  Max Drawdown     : {col_bad}-{s['max_dd']:.1f}%{rst}               │")
    sh_c = c(s['sharpe'], 1.0)
    print(f"  │  Sharpe           : {sh_c}{s['sharpe']:>5.2f}{rst}               │")
    print(f"  │  Gain moyen (win) : {s['avg_win']:>+8.0f} USDT         │")
    print(f"  │  Perte moy.(loss) : {s['avg_loss']:>+8.0f} USDT         │")
    rr_c = c(s['rr'], 1.5)
    print(f"  │  Ratio R/R        : {rr_c}{s['rr']:>5.2f}{rst}               │")
    print(f"  │  Sorties          : {str(s['reasons']):<23}│")
    print("  └─────────────────────────────────────────┘")


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  BACKTEST APEX v2 — BTCUSDT — 6 mois")
    print("=" * 60)

    trades = run_backtest()

    if not trades:
        print("  Aucun trade détecté sur la période.")
        sys.exit(0)

    print_results(trades)
    s = compute_stats(trades)
    print_stats(s)

    out = {
        "date_backtest": datetime.now(tz=timezone.utc).isoformat(),
        "periode": "6 mois",
        "stats": s,
        "trades": trades,
    }
    with open("apex_live/backtest_results.json", "w") as f:
        json.dump(out, f, indent=2, default=str)

    print(f"\n  Résultats sauvegardés → apex_live/backtest_results.json\n")
