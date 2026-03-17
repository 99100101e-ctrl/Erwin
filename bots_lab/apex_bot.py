"""
bots_lab/apex_bot.py

APEX Bot — Adaptive Price EXecution
====================================
Stratégie innovante BTC/USDT 1h — entièrement autonome.
N'utilise PAS le signal_engine existant — calcule ses propres indicateurs
depuis le raw OHLCV pour explorer des setups originaux.

━━━ INNOVATIONS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. Break of Structure (BOS)
       Le prix ferme AU-DESSUS du range des N dernières bougies (BUY)
       ou EN-DESSOUS (SELL) → cassure confirmée de structure de marché.

  2. ATR Squeeze → Expansion
       L'ATR était comprimé sous sa médiane sur les dernières bougies
       puis explose → détecte les breakouts APRÈS compression de volatilité.

  3. Volume Surge institutionnel
       Volume > 1.5× SMA20 volume → participation anormale = signal fort.

  4. RSI Power Zone
       RSI 14 dans la zone 45-68 (BUY) ou 32-55 (SELL).
       Évite les entrées en surachat/survente, cible le momentum sain.

  5. EMA Stack 1h
       EMA20 > EMA50 (BUY) ou EMA20 < EMA50 (SELL)
       → alignement tendance court terme.

  6. Engulfing Power Candle
       Corps actuel > 1.3× corps précédent dans la direction du signal
       → bougie d'impulsion directionnelle (piège / accélération).

━━━ LOGIQUE D'ENTRÉE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  OBLIGATOIRE : EMA100 daily aligné + ADX 1h >= 20 + BOS
  SCORING     : au moins 2 des 5 confirmateurs ci-dessus

━━━ SORTIE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SL  = 2.0 × ATR
  TP1 = 1.2R → exit 40%, SL → Breakeven
  TP2 = 2.5R → exit 35%
  TP3 = 5.0R → exit 25% (ou timeout 96h)

━━━ USAGE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  python bots_lab/apex_bot.py
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from bt_common import load_real_candles, TRADE_SIZE
from datetime import datetime, timezone
from collections import defaultdict

# ── Constantes ────────────────────────────────────────────────────────────────
FR_HOURS = set(range(8, 22)) - {16, 17, 18}   # 8h-21h UTC, hors US open 16h-18h
SEP = "─" * 108
HDR = (f"  {'Config':<54} | {'N':>5} | {'WR':>6} | {'Avg':>7} | "
       f"{'MDD':>6} | {'Sharpe':>7} | {'Net EUR':>9} | {'SL%':>4} | {'TP3%':>4}")


# ══════════════════════════════════════════════════════════════════════════════
#  INDICATEURS (calculés depuis le raw OHLCV)
# ══════════════════════════════════════════════════════════════════════════════

def _ema(values, period):
    """EMA standard — retourne liste de même longueur (None pendant warmup)."""
    if len(values) < period:
        return [None] * len(values)
    k = 2.0 / (period + 1)
    out = [None] * (period - 1)
    out.append(sum(values[:period]) / period)
    for v in values[period:]:
        out.append(out[-1] * (1 - k) + v * k)
    return out


def _rsi(closes, period=14):
    """RSI Wilder — retourne float par bougie (50.0 pendant warmup)."""
    n = len(closes)
    out = [50.0] * n
    if n < period + 2:
        return out
    avg_g = avg_l = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        avg_g += max(d, 0)
        avg_l += max(-d, 0)
    avg_g /= period
    avg_l /= period
    out[period] = 100 - 100 / (1 + avg_g / avg_l) if avg_l > 0 else 100.0
    for i in range(period + 1, n):
        d = closes[i] - closes[i - 1]
        avg_g = (avg_g * (period - 1) + max(d, 0)) / period
        avg_l = (avg_l * (period - 1) + max(-d, 0)) / period
        out[i] = 100 - 100 / (1 + avg_g / avg_l) if avg_l > 0 else 100.0
    return out


def _atr(candles, period=14):
    """ATR Wilder — retourne float par bougie (0.0 pendant warmup)."""
    n = len(candles)
    out = [0.0] * n
    if n < period + 2:
        return out
    trs = []
    for i in range(1, n):
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    val = sum(trs[:period]) / period
    out[period] = val
    for i in range(period, n - 1):
        val = (val * (period - 1) + trs[i]) / period
        out[i + 1] = val
    return out


def _adx(candles, period=14):
    """ADX Wilder — retourne float par bougie (0.0 pendant warmup)."""
    n = len(candles)
    out = [0.0] * n
    if n < period * 2 + 5:
        return out

    trs, pdms, mdms = [], [], []
    for i in range(1, n):
        h, l   = candles[i]["high"],     candles[i]["low"]
        ph, pl = candles[i-1]["high"],   candles[i-1]["low"]
        pc     = candles[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        up, dn = h - ph, pl - l
        pdms.append(up if up > dn and up > 0 else 0.0)
        mdms.append(dn if dn > up and dn > 0 else 0.0)

    def _wilder(vals):
        s = [0.0] * len(vals)
        s[period - 1] = sum(vals[:period])
        for i in range(period, len(vals)):
            s[i] = s[i-1] - s[i-1] / period + vals[i]
        return s

    str_ = _wilder(trs)
    spdm = _wilder(pdms)
    smdm = _wilder(mdms)

    dx_vals = []
    for i in range(period - 1, len(str_)):
        if str_[i] == 0:
            dx_vals.append(0.0)
            continue
        pdi   = 100 * spdm[i] / str_[i]
        mdi   = 100 * smdm[i] / str_[i]
        denom = pdi + mdi
        dx_vals.append(100 * abs(pdi - mdi) / denom if denom > 0 else 0.0)

    adx_vals = _wilder(dx_vals)
    # Alignement : trs commence à candle 1, adx_vals[0] ↔ candle 2*(period-1)+1
    offset = 2 * (period - 1) + 1
    for i, v in enumerate(adx_vals):
        idx = offset + i
        if idx < n:
            out[idx] = v
    return out


def _vol_sma(candles, period=20):
    """SMA volume."""
    vols = [c["volume"] for c in candles]
    out  = [0.0] * len(vols)
    for i in range(period - 1, len(vols)):
        out[i] = sum(vols[i - period + 1 : i + 1]) / period
    return out


def _daily_ema100_trend(candles):
    """
    Agrège les bougies 1h en daily, calcule EMA100 daily,
    retourne 'bull' / 'bear' / 'neutral' pour chaque bougie 1h.
    """
    daily_close = defaultdict(list)
    for c in candles:
        dt = datetime.fromtimestamp(c["ts"], tz=timezone.utc)
        daily_close[(dt.year, dt.month, dt.day)].append(c["close"])

    sorted_days   = sorted(daily_close.keys())
    day_closes    = [daily_close[d][-1] for d in sorted_days]
    ema100_series = _ema(day_closes, 100)

    day_ema = {d: ema100_series[i] for i, d in enumerate(sorted_days)}

    out = []
    for c in candles:
        dt  = datetime.fromtimestamp(c["ts"], tz=timezone.utc)
        key = (dt.year, dt.month, dt.day)
        ev  = day_ema.get(key)
        if ev is None:
            out.append("neutral")
        elif c["close"] > ev:
            out.append("bull")
        else:
            out.append("bear")
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  SETUPS INNOVANTS
# ══════════════════════════════════════════════════════════════════════════════

def _bos(candles, i, direction, lookback):
    """
    Break of Structure : price ferme au-delà du range des `lookback` bougies.
    BUY  → close > max(high[i-lookback : i])
    SELL → close < min(low[i-lookback  : i])
    """
    if i < lookback:
        return False
    close = candles[i]["close"]
    if direction == "BUY":
        return close > max(c["high"] for c in candles[i - lookback : i])
    else:
        return close < min(c["low"]  for c in candles[i - lookback : i])


def _atr_squeeze(atrs, i, lookback=20, ratio=1.25):
    """
    ATR Squeeze + Expansion :
    - Au moins 2 des 3 dernières bougies avaient ATR < médiane (compression)
    - L'ATR actuel est > médiane × ratio (expansion)
    """
    if i < lookback + 3:
        return False
    window = atrs[i - lookback : i]
    if not window or max(window) == 0:
        return False
    median = sorted(window)[len(window) // 2]
    if median == 0:
        return False
    compressed = sum(1 for a in atrs[i - 3 : i] if a < median)
    return compressed >= 2 and atrs[i] > median * ratio


def _volume_surge(candles, vol_sma, i, ratio=1.5):
    """Volume actuel > ratio × SMA20."""
    return vol_sma[i] > 0 and candles[i]["volume"] > vol_sma[i] * ratio


def _rsi_zone(rsi_vals, i, direction):
    """
    RSI Power Zone : momentum sain sans extension.
    BUY  → RSI ∈ [45, 68]
    SELL → RSI ∈ [32, 55]
    """
    r = rsi_vals[i]
    return (45 <= r <= 68) if direction == "BUY" else (32 <= r <= 55)


def _ema_stack(ema20, ema50, i, direction):
    """EMA20 > EMA50 pour BUY, inverse pour SELL."""
    if ema20[i] is None or ema50[i] is None:
        return False
    return ema20[i] > ema50[i] if direction == "BUY" else ema20[i] < ema50[i]


def _engulfing(candles, i, direction):
    """
    Bougie englobante directionnelle :
    corps actuel > 1.3× corps précédent, dans le sens du signal.
    """
    if i < 1:
        return False
    c, p = candles[i], candles[i - 1]
    body_now  = abs(c["close"] - c["open"])
    body_prev = abs(p["close"] - p["open"])
    if body_prev == 0:
        return False
    if direction == "BUY":
        return c["close"] > c["open"] and body_now > body_prev * 1.3
    else:
        return c["close"] < c["open"] and body_now > body_prev * 1.3


# ══════════════════════════════════════════════════════════════════════════════
#  SIMULATION TRADE
# ══════════════════════════════════════════════════════════════════════════════

def _sim(candles, entry_idx, direction, atr_val,
         sl_mult=2.0, timeout_bars=96):
    """
    Simulation APEX multi-TP :
      SL  = sl_mult × ATR
      TP1 = 1.2R → exit 40%, SL → Breakeven
      TP2 = 2.5R → exit 35%
      TP3 = 5.0R → exit 25% (ou timeout)
    Retourne (pnl_fraction, reason, n_bars)
    """
    if entry_idx + 1 >= len(candles):
        return 0.0, "skip", 0

    entry = candles[entry_idx]["close"]
    R     = sl_mult * atr_val
    if R <= 0:
        return 0.0, "skip", 0

    if direction == "BUY":
        orig_sl = entry - R
        tp1     = entry + 1.2 * R
        tp2     = entry + 2.5 * R
        tp3     = entry + 5.0 * R
        sign    = 1
    else:
        orig_sl = entry + R
        tp1     = entry - 1.2 * R
        tp2     = entry - 2.5 * R
        tp3     = entry - 5.0 * R
        sign    = -1

    cur_sl   = orig_sl
    rem      = 1.0
    total    = 0.0
    t1_hit   = False
    t2_hit   = False

    for bar in range(1, timeout_bars + 1):
        idx = entry_idx + bar
        if idx >= len(candles):
            break
        lo, hi = candles[idx]["low"], candles[idx]["high"]

        # ── Stop Loss (priorité maximale) ──────────────────────────────────
        if direction == "BUY" and lo <= cur_sl:
            total += sign * (cur_sl - entry) / entry * rem
            return total, "SL" if cur_sl == orig_sl else "BE", bar
        if direction == "SELL" and hi >= cur_sl:
            total += sign * (cur_sl - entry) / entry * rem
            return total, "SL" if cur_sl == orig_sl else "BE", bar

        # ── TP3 ────────────────────────────────────────────────────────────
        if t2_hit:
            if (direction == "BUY" and hi >= tp3) or (direction == "SELL" and lo <= tp3):
                total += sign * (tp3 - entry) / entry * rem
                return total, "TP3", bar

        # ── TP2 ────────────────────────────────────────────────────────────
        if t1_hit and not t2_hit:
            if (direction == "BUY" and hi >= tp2) or (direction == "SELL" and lo <= tp2):
                total += sign * (tp2 - entry) / entry * 0.35
                rem   -= 0.35
                t2_hit = True

        # ── TP1 ────────────────────────────────────────────────────────────
        if not t1_hit:
            if (direction == "BUY" and hi >= tp1) or (direction == "SELL" and lo <= tp1):
                total  += sign * (tp1 - entry) / entry * 0.40
                rem    -= 0.40
                t1_hit  = True
                cur_sl  = entry                              # SL → Breakeven

    # ── Timeout ────────────────────────────────────────────────────────────
    last   = candles[min(entry_idx + timeout_bars, len(candles) - 1)]["close"]
    total += sign * (last - entry) / entry * rem
    reason = "TP2+to" if t2_hit else ("TP1+to" if t1_hit else "timeout")
    return total, reason, timeout_bars


# ══════════════════════════════════════════════════════════════════════════════
#  GÉNÉRATION DES SIGNAUX + RUN
# ══════════════════════════════════════════════════════════════════════════════

def precompute_apex(candles):
    """Calcule tous les indicateurs APEX depuis le OHLCV brut."""
    print(f"  Calcul indicateurs APEX ({len(candles)} bougies 1h)...", end="", flush=True)
    closes  = [c["close"] for c in candles]
    ind = {
        "ema20":   _ema(closes, 20),
        "ema50":   _ema(closes, 50),
        "rsi14":   _rsi(closes, 14),
        "atrs":    _atr(candles, 14),
        "adxs":    _adx(candles, 14),
        "vol_sma": _vol_sma(candles, 20),
        "trend":   _daily_ema100_trend(candles),
    }
    print(" OK")
    return ind


def run_apex(candles, ind,
             adx_min=20,
             bos_lb=12,
             score_min=2,
             cooldown_h=3,
             sl_mult=2.0):
    """
    Génère les signaux et simule les trades APEX.

    Conditions OBLIGATOIRES : EMA100d + ADX>=adx_min + BOS
    SCORING (need score_min / 5) :
        ATR Squeeze | Volume Surge | RSI Zone | EMA Stack | Engulfing
    """
    trades   = []
    end_idx  = 0
    last_ts  = {"BUY": 0, "SELL": 0}
    warmup   = max(260, bos_lb + 30)

    for i in range(warmup, len(candles) - 100):
        if i < end_idx:
            continue

        ts = candles[i]["ts"]
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)

        # Filtre heure FR
        if dt.hour not in FR_HOURS:
            continue
        # Evite le dimanche (crypto choppy)
        if dt.weekday() == 6:
            continue

        for direction in ("BUY", "SELL"):

            # ── 1. EMA100d (macro) ─────────────────────────────────────────
            macro = ind["trend"][i]
            if macro == "neutral":
                continue
            if macro == "bull" and direction != "BUY":
                continue
            if macro == "bear" and direction != "SELL":
                continue

            # ── 2. ADX ────────────────────────────────────────────────────
            if ind["adxs"][i] < adx_min:
                continue

            # ── 3. BOS (obligatoire) ───────────────────────────────────────
            if not _bos(candles, i, direction, bos_lb):
                continue

            # ── Cooldown ──────────────────────────────────────────────────
            if cooldown_h > 0 and (ts - last_ts[direction]) < cooldown_h * 3600:
                continue

            # ── Scoring (5 confirmateurs) ──────────────────────────────────
            score = 0
            if _atr_squeeze(ind["atrs"],   i):                          score += 1
            if _volume_surge(candles, ind["vol_sma"], i):               score += 1
            if _rsi_zone(ind["rsi14"],     i, direction):               score += 1
            if _ema_stack(ind["ema20"],    ind["ema50"], i, direction): score += 1
            if _engulfing(candles,         i, direction):               score += 1

            if score < score_min:
                continue

            atr_val = ind["atrs"][i]
            if atr_val <= 0:
                continue

            pnl, rsn, bars = _sim(candles, i, direction, atr_val, sl_mult)
            if rsn == "skip":
                continue

            last_ts[direction] = ts
            trades.append({
                "idx":       i,
                "ts":        ts,
                "direction": direction,
                "atr":       atr_val,
                "adx":       ind["adxs"][i],
                "rsi":       ind["rsi14"][i],
                "score":     score,
                "pnl_pct":   pnl * 100,
                "pnl_eur":   pnl * TRADE_SIZE,
                "reason":    rsn,
                "bars":      bars,
            })
            end_idx = i + bars + 4

    return trades


# ══════════════════════════════════════════════════════════════════════════════
#  STATISTIQUES & REPORTING
# ══════════════════════════════════════════════════════════════════════════════

def _stats(trades):
    if len(trades) < 3:
        return None
    pnls  = [t["pnl_pct"] for t in trades]
    eurs  = [t["pnl_eur"] for t in trades]
    wins  = [p for p in pnls if p > 0]
    loses = [p for p in pnls if p <= 0]
    avg   = sum(pnls) / len(pnls)
    std   = (sum((p - avg) ** 2 for p in pnls) / len(pnls)) ** 0.5 or 0.001
    eq = pk = 1.0; mdd = 0.0
    for p in pnls:
        eq *= (1 + p / 100)
        pk  = max(pk, eq)
        mdd = max(mdd, (pk - eq) / pk)
    return {
        "n":        len(trades),
        "wr":       len(wins) / len(pnls) * 100,
        "avg":      avg,
        "mdd":      mdd,
        "sh":       avg / std * (len(pnls) ** 0.5),
        "net_eur":  sum(eurs),
        "avg_eur":  sum(eurs) / len(eurs),
        "avg_win":  sum(wins)  / len(wins)  if wins  else 0,
        "avg_loss": sum(loses) / len(loses) if loses else 0,
        "sl_pct":   sum(1 for t in trades if t["reason"] == "SL")  / len(trades) * 100,
        "be_pct":   sum(1 for t in trades if t["reason"] == "BE")  / len(trades) * 100,
        "tp3_pct":  sum(1 for t in trades if t["reason"] == "TP3") / len(trades) * 100,
    }


def _row(label, trades, best):
    s = _stats(trades)
    if not s:
        print(f"  {label:<54} | {'<3':>5} |")
        return
    mk = ""
    if s["wr"] > best["wr"]: best["wr"] = s["wr"]; mk += " ◄WR"
    if s["sh"] > best["sh"]: best["sh"] = s["sh"]; mk += " ◄SH"
    print(f"  {label:<54} | {s['n']:>5} | {s['wr']:>5.1f}% | {s['avg']:>+6.2f}% "
          f"| -{s['mdd']*100:>4.1f}% | {s['sh']:>+6.2f} | {s['net_eur']:>+9.0f}€ "
          f"| {s['sl_pct']:>3.0f}% | {s['tp3_pct']:>3.0f}%{mk}")


def _section(title):
    print(f"\n{SEP}\n  {title}\n{SEP}")


def _yearly(candles, trades, label):
    by_yr = defaultdict(list)
    for t in trades:
        yr = datetime.fromtimestamp(candles[t["idx"]]["ts"], tz=timezone.utc).year
        by_yr[yr].append(t["pnl_eur"])
    print(f"  Détail annuel — {label}")
    for yr, pnls in sorted(by_yr.items()):
        wr  = sum(1 for p in pnls if p > 0) / len(pnls) * 100
        net = sum(pnls)
        avg = sum(pnls) / len(pnls)
        std = (sum((p - avg)**2 for p in pnls) / len(pnls))**0.5 or 0.001
        sh  = (avg / std) * (len(pnls) ** 0.5)
        print(f"    {yr} : {len(pnls):3d} trades | WR {wr:5.1f}% | Sharpe {sh:+.2f} | {net:+.0f}€")


def _monthly(candles, trades, label):
    monthly = defaultdict(list)
    for t in trades:
        dt = datetime.fromtimestamp(candles[t["idx"]]["ts"], tz=timezone.utc)
        monthly[(dt.year, dt.month)].append(t["pnl_eur"])
    print(f"\n  P&L mensuel — {label}")
    print(f"  {'Mois':<10} | {'N':>4} | {'WR':>6} | {'Net EUR':>9} | Barre")
    print(f"  {'-'*10}-+-{'-'*4}-+-{'-'*6}-+-{'-'*9}-+-{'-'*30}")
    for (yr, mo), pnls in sorted(monthly.items()):
        wr   = sum(1 for p in pnls if p > 0) / len(pnls) * 100
        net  = sum(pnls)
        ch   = "+" if net >= 0 else "-"
        bar  = ch * min(int(abs(net) / 40), 30)
        print(f"  {yr}-{mo:02d}     | {len(pnls):>4} | {wr:>5.0f}% | {net:>+8.0f}€ | {bar}")


def _exits(trades, label):
    reasons = defaultdict(int)
    for t in trades:
        reasons[t["reason"]] += 1
    total = len(trades)
    parts = " | ".join(
        f"{r}={v/total*100:.0f}%"
        for r, v in sorted(reasons.items(), key=lambda x: -x[1])
    )
    print(f"  Sorties — {label} : {parts}")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "=" * 108)
    print("  APEX Bot — Adaptive Price EXecution")
    print("  BOS + ATR Squeeze + Volume Surge + RSI Power Zone + EMA Stack + Engulfing")
    print("=" * 108)

    candles = load_real_candles()
    n_years = (candles[-1]["ts"] - candles[0]["ts"]) / (365.25 * 86400)
    n_weeks = n_years * 52
    print(f"  Durée : {n_years:.1f} an(s)  ({n_weeks:.0f} semaines)\n")

    ind = precompute_apex(candles)

    # ── Référence v7 ──────────────────────────────────────────────────────────
    print("\n  [Référence] Import signaux v7...", end="", flush=True)
    from backtest_2ans import precompute_full
    from backtest_v2 import enrich_signals
    from backtest_v6 import enrich_v6
    from BTCtest1603 import run_bot as _run_v7
    sigs_v7  = enrich_v6(candles, enrich_signals(candles, precompute_full(candles)))
    bot_v7   = _run_v7(candles, sigs_v7, adx1h_min=25)
    print(f" {len(bot_v7)} trades\n")

    mk = {"wr": 0.0, "sh": -999.0}

    # ── Grid search ───────────────────────────────────────────────────────────
    _section("GRID SEARCH — score_min × BOS lookback")
    print(HDR)

    best = {"sh": -999.0, "trades": [], "label": "", "params": {}}
    n_min = max(10, int(n_weeks * 0.5))   # au moins 1 trade/2 semaines

    for score_min in (1, 2, 3):
        for bos_lb in (8, 12, 20):
            label  = f"BOS={bos_lb:2d} candles | score>={score_min}/5"
            trades = run_apex(candles, ind, bos_lb=bos_lb, score_min=score_min)
            _row(label, trades, mk)
            s = _stats(trades)
            if s and s["sh"] > best["sh"] and s["n"] >= n_min:
                best = {"sh": s["sh"], "trades": trades, "label": label,
                        "params": {"bos_lb": bos_lb, "score_min": score_min}}

    # ── Fallback si aucune config n'atteint le seuil ─────────────────────────
    if not best["trades"]:
        # Prendre la config avec le meilleur Sharpe parmi toutes
        for score_min in (1, 2, 3):
            for bos_lb in (8, 12, 20):
                trades = run_apex(candles, ind, bos_lb=bos_lb, score_min=score_min)
                s = _stats(trades)
                if s and s["sh"] > best["sh"]:
                    best = {"sh": s["sh"], "trades": trades,
                            "label": f"BOS={bos_lb:2d} candles | score>={score_min}/5",
                            "params": {"bos_lb": bos_lb, "score_min": score_min}}

    # ── Comparatif meilleure APEX vs v7 ───────────────────────────────────────
    _section("COMPARATIF — Meilleure APEX vs Bot v7 (référence)")
    print(HDR)
    mk2 = {"wr": 0.0, "sh": -999.0}
    _row("v7 — EMA100d + ADX>=25 + HeuresFR (référence)", bot_v7,        mk2)
    _row(f"APEX ★ — {best['label']}",                     best["trades"], mk2)

    bt = best["trades"]

    # ── Détail BUY / SELL ──────────────────────────────────────────────────────
    _section("DÉTAIL — BUY vs SELL (meilleure config APEX)")
    print(HDR)
    mk3 = {"wr": 0.0, "sh": -999.0}
    _row("  BUY  (EMA100d BULL)", [t for t in bt if t["direction"] == "BUY"],  mk3)
    _row("  SELL (EMA100d BEAR)", [t for t in bt if t["direction"] == "SELL"], mk3)

    # ── Breakdown annuel ───────────────────────────────────────────────────────
    _section("BREAKDOWN ANNUEL")
    _yearly(candles, bt, f"APEX — {best['label']}")

    # ── Sorties + mensuel ──────────────────────────────────────────────────────
    s = _stats(bt)
    if s:
        _exits(bt, "APEX")
        _monthly(candles, bt, f"APEX — {best['label']}")

    # ── Résumé final ───────────────────────────────────────────────────────────
    print(f"\n{'=' * 108}")
    print("  RÉSULTAT FINAL — APEX Bot")
    if s:
        freq = s["n"] / n_weeks
        print(f"     Config     : {best['label']}")
        print(f"     N trades   : {s['n']}  ({freq:.1f} trades/semaine)")
        print(f"     Win Rate   : {s['wr']:.1f}%")
        print(f"     Sharpe     : {s['sh']:+.2f}")
        print(f"     MDD        : -{s['mdd']*100:.1f}%")
        print(f"     Net total  : {s['net_eur']:+.0f} EUR  (sur {n_years:.1f} ans)")
        print(f"     Avg/trade  : {s['avg_eur']:+.0f} EUR")
        print(f"     Avg win    : {s['avg_win']:+.2f}%   |  Avg loss : {s['avg_loss']:+.2f}%")
        print()
        print(f"  ─── Référence v7 ────────────────────────────────────────────────")
        sv = _stats(bot_v7)
        if sv:
            print(f"     N trades   : {sv['n']}  ({sv['n']/n_weeks:.1f} trades/semaine)")
            print(f"     Win Rate   : {sv['wr']:.1f}%")
            print(f"     Sharpe     : {sv['sh']:+.2f}")
            print(f"     Net total  : {sv['net_eur']:+.0f} EUR")
    else:
        print("  Pas assez de trades (< 3)")
    print(f"{'=' * 108}\n")


if __name__ == "__main__":
    main()
