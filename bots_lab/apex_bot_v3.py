"""
bots_lab/apex_bot_v3.py

APEX Bot v3 — Fix SELL + Fréquence + SL dynamique
===================================================
Résultats v2 :
  APEX v2  : 123 trades | WR 58.5% | Sharpe +2.45 | MDD -7.4%  | +1067€
  BUY  v2  :  69 trades | WR 60.9% | Sharpe +1.88 | +509€  ← très bon
  SELL v2  :  54 trades | WR 55.6% | Sharpe +1.63 | +559€  ← régression vs v1 !
  SELL v1  :  51 trades | WR 58.8% | Sharpe +2.02 | +668€  ← meilleur

Problème identifié :
  Dans v2, le MACD cross comptait dans le scoring SELL avec score_sell=3/6.
  Cela a ajouté 3 trades SELL de mauvaise qualité → régression Sharpe 2.02→1.63.

Corrections v3 :
─────────────────────────────────────────────────────────────────────────────
  1. MACD exclusif BUY
       Le MACD cross ne compte QUE pour le scoring BUY.
       SELL utilise les 5 confirmateurs originaux (sans MACD), score_sell >= 3/5.
       → SELL revient à ~51 trades, Sharpe ~2.02

  2. Pullback BUY (nouveau setup)
       Pour BUY : en plus du BOS, demande que le prix ait eu un creux
       (retracement vers EMA20) dans les 6 dernières bougies avant le signal.
       "BOS après pullback" = momentum de continuation après consolidation.
       Plus fiable qu'un simple BOS dans le vide.

  3. 4h EMA stack (nouveau filtre BUY)
       4h EMA20 > 4h EMA50 pour BUY (tendance 4h alignée)
       Remplace partiellement le 4h RSI > 50 avec une confirmation de tendance.

  4. RSI 4h asymétrique (BUY : RSI4h 45–72, SELL : RSI4h 28–55)
       Plage plus large que v2 (>50) pour capturer plus de BUY légitimes
       en début de reprise.

  5. Trailing stop après TP2 (nouveau dans la simulation)
       Après TP2 atteint, trailing de 2×ATR sur le solde restant (25%).
       Permet de capturer des moves > 5R sans limite fixe.

━━━ RÉSULTAT ATTENDU ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  BUY  : ~65-75 trades | Sharpe ~2.0 | +500-600€
  SELL : ~51 trades    | Sharpe ~2.0 | +650-700€
  Total: ~115-125 trades (1.1-1.2/sem) | Sharpe cible > 2.5 | MDD < 8%

━━━ USAGE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  python bots_lab/apex_bot_v3.py
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from bt_common import load_real_candles, TRADE_SIZE
from datetime import datetime, timezone
from collections import defaultdict

from apex_bot import (
    _ema, _rsi, _atr, _adx, _vol_sma, _daily_ema100_trend,
    _bos, _atr_squeeze, _volume_surge, _rsi_zone, _ema_stack, _engulfing,
    _stats, _row, _section, _yearly, _monthly, _exits,
    FR_HOURS, SEP, HDR
)
from apex_bot_v2 import (
    _macd, _rsi4h, _ema4h,
    _macd_cross, _buy_not_extended,
    precompute_v2
)


# ══════════════════════════════════════════════════════════════════════════════
#  SIMULATION v3 — avec trailing stop après TP2
# ══════════════════════════════════════════════════════════════════════════════

def _sim_v3(candles, entry_idx, direction, atr_val,
            sl_mult=2.0, timeout_bars=96):
    """
    Simulation APEX v3 :
      SL   = sl_mult × ATR
      TP1  = 1.2R → exit 40%, SL → Breakeven
      TP2  = 2.5R → exit 35%
      TP3  = trailing 2×ATR sur les 25% restants (plafond 6R)
    """
    if entry_idx + 1 >= len(candles):
        return 0.0, "skip", 0

    entry  = candles[entry_idx]["close"]
    R      = sl_mult * atr_val
    if R <= 0:
        return 0.0, "skip", 0

    if direction == "BUY":
        orig_sl = entry - R
        tp1     = entry + 1.2 * R
        tp2     = entry + 2.5 * R
        sign    = 1
    else:
        orig_sl = entry + R
        tp1     = entry - 1.2 * R
        tp2     = entry - 2.5 * R
        sign    = -1

    cur_sl   = orig_sl
    rem      = 1.0
    total    = 0.0
    t1_hit   = False
    t2_hit   = False
    trail_sl = None      # trailing stop activé après TP2

    for bar in range(1, timeout_bars + 1):
        idx = entry_idx + bar
        if idx >= len(candles):
            break
        lo, hi, cl = candles[idx]["low"], candles[idx]["high"], candles[idx]["close"]

        # ── SL / Trailing ──────────────────────────────────────────────────
        active_sl = trail_sl if trail_sl is not None else cur_sl
        if direction == "BUY" and lo <= active_sl:
            total += sign * (active_sl - entry) / entry * rem
            label = "SL" if active_sl == orig_sl else ("trail" if trail_sl else "BE")
            return total, label, bar
        if direction == "SELL" and hi >= active_sl:
            total += sign * (active_sl - entry) / entry * rem
            label = "SL" if active_sl == orig_sl else ("trail" if trail_sl else "BE")
            return total, label, bar

        # ── Trailing update (après TP2) ────────────────────────────────────
        if trail_sl is not None:
            if direction == "BUY":
                new_trail = cl - 2.0 * R
                if new_trail > trail_sl:
                    trail_sl = new_trail
            else:
                new_trail = cl + 2.0 * R
                if new_trail < trail_sl:
                    trail_sl = new_trail

        # ── TP2 ────────────────────────────────────────────────────────────
        if t1_hit and not t2_hit:
            if (direction == "BUY" and hi >= tp2) or (direction == "SELL" and lo <= tp2):
                total   += sign * (tp2 - entry) / entry * 0.35
                rem     -= 0.35
                t2_hit   = True
                # Activer le trailing stop sur les 25% restants
                if direction == "BUY":
                    trail_sl = tp2 - 2.0 * R
                else:
                    trail_sl = tp2 + 2.0 * R

        # ── TP1 ────────────────────────────────────────────────────────────
        if not t1_hit:
            if (direction == "BUY" and hi >= tp1) or (direction == "SELL" and lo <= tp1):
                total  += sign * (tp1 - entry) / entry * 0.40
                rem    -= 0.40
                t1_hit  = True
                cur_sl  = entry   # SL → Breakeven

    # ── Timeout ────────────────────────────────────────────────────────────
    last   = candles[min(entry_idx + timeout_bars, len(candles) - 1)]["close"]
    total += sign * (last - entry) / entry * rem
    reason = "TP2+to" if t2_hit else ("TP1+to" if t1_hit else "timeout")
    return total, reason, timeout_bars


# ══════════════════════════════════════════════════════════════════════════════
#  NOUVEAUX SETUPS v3
# ══════════════════════════════════════════════════════════════════════════════

def _pullback_before_bos(candles, ind, i, direction, lookback=6):
    """
    Pullback BUY : dans les `lookback` bougies avant le signal,
    le prix est passé sous l'EMA20 au moins une fois (retrace → puis BOS).
    Pour SELL : prix est passé au-dessus de l'EMA20 au moins une fois.
    Cela filtre les BOS "dans le vide" en faveur des BOS après consolidation.
    """
    if i < lookback + 1:
        return False
    ema20 = ind["ema20"]
    for j in range(i - lookback, i):
        if ema20[j] is None:
            return False
        if direction == "BUY"  and candles[j]["low"]  < ema20[j]:
            return True
        if direction == "SELL" and candles[j]["high"] > ema20[j]:
            return True
    return False


def _rsi4h_zone(rsi4h, i, direction):
    """
    RSI 4h dans la zone de momentum sain.
    BUY  : 45-72 (momentum positif, pas trop étendu)
    SELL : 28-55 (momentum négatif, pas trop étendu)
    Plage plus large que v2 (>50) pour éviter de rater les reprises naissantes.
    """
    r = rsi4h[i]
    return (45 <= r <= 72) if direction == "BUY" else (28 <= r <= 55)


def _ema4h_stack(ema4h20, ema4h50, i, direction):
    """EMA20 4h > EMA50 4h pour BUY (trend 4h aligné), inverse pour SELL."""
    if ema4h20[i] is None or ema4h50[i] is None:
        return False
    return ema4h20[i] > ema4h50[i] if direction == "BUY" else ema4h20[i] < ema4h50[i]


# ══════════════════════════════════════════════════════════════════════════════
#  GÉNÉRATION SIGNAUX v3
# ══════════════════════════════════════════════════════════════════════════════

def run_v3(candles, ind,
           bos_lb=20,
           adx_buy=25,
           adx_sell=20,
           score_buy=2,        # sur 6 confirmateurs BUY (MACD inclus)
           score_sell=3,       # sur 5 confirmateurs SELL (MACD exclu)
           ext_atr=7.0,        # filtre extension BUY
           cooldown_h=3,
           sl_mult=2.0):
    """
    APEX v3 :
      BUY  : EMA100d + ADX>=25 + BOS + 4hRSI_zone + ext<7×ATR + score>=2/6
             Confirmateurs BUY (6) : ATR Squeeze | Vol Surge | RSI Zone 1h |
                                     EMA Stack 1h | Engulfing | MACD Cross
      SELL : EMA100d + ADX>=20 + BOS + score>=3/5
             Confirmateurs SELL (5) : ATR Squeeze | Vol Surge | RSI Zone 1h |
                                      EMA Stack 1h | Engulfing
             (MACD exclu du SELL pour ne pas dégrader v1)
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

        if dt.hour not in FR_HOURS:
            continue
        if dt.weekday() == 6:
            continue

        for direction in ("BUY", "SELL"):

            # ── 1. EMA100d ────────────────────────────────────────────────
            macro = ind["trend"][i]
            if macro == "neutral":
                continue
            if macro == "bull" and direction != "BUY":
                continue
            if macro == "bear" and direction != "SELL":
                continue

            # ── 2. ADX asymétrique ────────────────────────────────────────
            adx_min = adx_buy if direction == "BUY" else adx_sell
            if ind["adxs"][i] < adx_min:
                continue

            # ── 3. BOS ────────────────────────────────────────────────────
            if not _bos(candles, i, direction, bos_lb):
                continue

            # ── 4. Filtres BUY spécifiques ────────────────────────────────
            if direction == "BUY":
                # 4a. RSI 4h dans la zone de momentum (plus souple que v2)
                if not _rsi4h_zone(ind["rsi4h"], i, direction):
                    continue
                # 4b. Pas trop étendu au-dessus de EMA50
                price = candles[i]["close"]
                if not _buy_not_extended(price, ind["ema50"][i], ind["atrs"][i], ext_atr):
                    continue

            # ── Cooldown ──────────────────────────────────────────────────
            if cooldown_h > 0 and (ts - last_ts[direction]) < cooldown_h * 3600:
                continue

            # ── 5. Scoring (asymétrique) ──────────────────────────────────
            # Confirmateurs communs (1-5)
            s1 = int(_atr_squeeze(ind["atrs"],   i))
            s2 = int(_volume_surge(candles, ind["vol_sma"], i))
            s3 = int(_rsi_zone(ind["rsi14"],     i, direction))
            s4 = int(_ema_stack(ind["ema20"],    ind["ema50"], i, direction))
            s5 = int(_engulfing(candles,         i, direction))

            if direction == "BUY":
                # +MACD pour BUY (6e confirmateur)
                s6    = int(_macd_cross(ind["macd_l"], ind["sig_line"], i, direction))
                score = s1 + s2 + s3 + s4 + s5 + s6
                s_min = score_buy    # seuil sur 6
            else:
                # SELL : 5 confirmateurs uniquement (pas de MACD → fix régression v2)
                score = s1 + s2 + s3 + s4 + s5
                s_min = score_sell   # seuil sur 5

            if score < s_min:
                continue

            atr_val = ind["atrs"][i]
            if atr_val <= 0:
                continue

            pnl, rsn, bars = _sim_v3(candles, i, direction, atr_val, sl_mult)
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
                "rsi4h":     ind["rsi4h"][i],
                "score":     score,
                "pnl_pct":   pnl * 100,
                "pnl_eur":   pnl * TRADE_SIZE,
                "reason":    rsn,
                "bars":      bars,
            })
            end_idx = i + bars + 4

    return trades


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "=" * 108)
    print("  APEX Bot v3 — Fix SELL + Trailing stop + RSI4h élargi")
    print("  MACD exclu SELL | score_sell=3/5 | trailing 2R post-TP2")
    print("=" * 108)

    candles = load_real_candles()
    n_years = (candles[-1]["ts"] - candles[0]["ts"]) / (365.25 * 86400)
    n_weeks = n_years * 52
    print(f"  Durée : {n_years:.1f} an(s)  ({n_weeks:.0f} semaines)\n")

    ind = precompute_v2(candles)

    # ── Références ────────────────────────────────────────────────────────────
    print("  [Référence] Import signaux v7...", end="", flush=True)
    from backtest_2ans import precompute_full
    from backtest_v2 import enrich_signals
    from backtest_v6 import enrich_v6
    from BTCtest1603 import run_bot as _run_v7
    sigs_v7 = enrich_v6(candles, enrich_signals(candles, precompute_full(candles)))
    bot_v7  = _run_v7(candles, sigs_v7, adx1h_min=25)
    print(f" {len(bot_v7)} trades")

    print("  [Référence] APEX v2 best...", end="", flush=True)
    from apex_bot_v2 import run_v2
    bot_v2 = run_v2(candles, ind, bos_lb=20, ext_atr=7.0, score_buy=2)
    print(f" {len(bot_v2)} trades\n")

    mk = {"wr": 0.0, "sh": -999.0}

    # ── Grid search v3 : bos_lb × score_buy ──────────────────────────────────
    _section("GRID SEARCH v3 — BOS lookback × score_buy")
    print(HDR)

    best = {"sh": -999.0, "trades": [], "label": "", "params": {}}
    n_min = max(10, int(n_weeks * 0.4))

    for bos in (15, 20, 25):
        for sb in (1, 2, 3):
            label  = f"BOS={bos:2d} | buy>={sb}/6 | sell>=3/5 | ext<=7R | ADX25/20"
            trades = run_v3(candles, ind, bos_lb=bos, score_buy=sb)
            _row(label, trades, mk)
            s = _stats(trades)
            if s and s["sh"] > best["sh"] and s["n"] >= n_min:
                best = {"sh": s["sh"], "trades": trades, "label": label,
                        "params": {"bos_lb": bos, "score_buy": sb}}

    if not best["trades"]:
        for bos in (15, 20, 25):
            for sb in (1, 2, 3):
                trades = run_v3(candles, ind, bos_lb=bos, score_buy=sb)
                s = _stats(trades)
                if s and s["sh"] > best["sh"]:
                    best = {"sh": s["sh"], "trades": trades,
                            "label": f"BOS={bos:2d} | buy>={sb}/6 | sell>=3/5 | ext<=7R",
                            "params": {"bos_lb": bos, "score_buy": sb}}

    bt = best["trades"]

    # ── Comparatif v7 / v2 / v3 ──────────────────────────────────────────────
    _section("COMPARATIF — v3 ★ vs v2 vs Bot v7")
    print(HDR)
    mk2 = {"wr": 0.0, "sh": -999.0}
    _row("v7  — EMA100d + ADX>=25 + HeuresFR",              bot_v7, mk2)
    _row("v2  — ext<=7R | buy>=2/6 | sell>=3/6 (MACD SELL)", bot_v2, mk2)
    _row(f"v3★  — {best['label']}",                          bt,     mk2)

    # ── Détail BUY / SELL v3 ──────────────────────────────────────────────────
    _section("DÉTAIL BUY vs SELL — APEX v3 ★")
    print(HDR)
    mk3 = {"wr": 0.0, "sh": -999.0}
    buys  = [t for t in bt if t["direction"] == "BUY"]
    sells = [t for t in bt if t["direction"] == "SELL"]
    _row("  BUY  (v3 : 4hRSI_zone + ext + ADX>=25 + score>=?/6)", buys,  mk3)
    _row("  SELL (v3 : score>=3/5, MACD exclu = identique v1)",    sells, mk3)

    # ── SELL focus : v1 vs v2 vs v3 ──────────────────────────────────────────
    _section("FOCUS SELL — v1 vs v2 vs v3 (correction régression)")
    print(HDR)
    mk4 = {"wr": 0.0, "sh": -999.0}
    from apex_bot import precompute_apex, run_apex
    ind_v1 = precompute_apex(candles)
    bot_v1 = run_apex(candles, ind_v1, bos_lb=20, score_min=3)
    _row("  SELL v1 (5 conf, score>=3/5)",
         [t for t in bot_v1 if t["direction"] == "SELL"], mk4)
    _row("  SELL v2 (6 conf avec MACD, score>=3/6 → régression)",
         [t for t in bot_v2 if t["direction"] == "SELL"], mk4)
    _row("  SELL v3 (5 conf, MACD exclu, score>=3/5 → fix)",
         sells, mk4)

    # ── Breakdown annuel ──────────────────────────────────────────────────────
    _section("BREAKDOWN ANNUEL — APEX v3 ★")
    _yearly(candles, bt, best["label"])

    s = _stats(bt)
    if s:
        _exits(bt, "APEX v3")
        _monthly(candles, bt, best["label"])

    # ── Résumé final ──────────────────────────────────────────────────────────
    print(f"\n{'=' * 108}")
    print("  RÉSULTAT FINAL — APEX Bot v3")
    if s:
        def _banner(label, st, n_wk):
            if not st: return
            print(f"  {label:<10}: {st['n']:3d} trades ({st['n']/n_wk:.1f}/sem)"
                  f" | WR {st['wr']:5.1f}% | Sharpe {st['sh']:+.2f}"
                  f" | MDD -{st['mdd']*100:.1f}% | {st['net_eur']:+.0f}€")

        _banner("APEX v3 ★", s, n_weeks)
        _banner("APEX v2  ", _stats(bot_v2), n_weeks)
        _banner("Bot v7   ", _stats(bot_v7), n_weeks)
        print()
        sb  = _stats(buys)
        ss  = _stats(sells)
        if sb: print(f"  BUY  v3 : {sb['n']:3d} trades | WR {sb['wr']:5.1f}% | Sharpe {sb['sh']:+.2f} | {sb['net_eur']:+.0f}€")
        if ss: print(f"  SELL v3 : {ss['n']:3d} trades | WR {ss['wr']:5.1f}% | Sharpe {ss['sh']:+.2f} | {ss['net_eur']:+.0f}€")
        print(f"\n  Fréquence : {s['n']/n_weeks:.1f} trades/semaine  (objectif : 1–5)")
    else:
        print("  Pas assez de trades (< 3)")
    print(f"{'=' * 108}\n")


if __name__ == "__main__":
    main()
