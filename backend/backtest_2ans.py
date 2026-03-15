"""
Backtest complet 2 ans — BTC réel Binance
==========================================
Teste les stratégies F5 et BTC62WR sur données réelles avec variation de :
  • Score d'entrée     : 60 / 70 / 80 / 90
  • Filtre heure FR    : activé / désactivé
  • Filtre RSI 4h      : activé / désactivé
  • Multiplicateur SL  : 1.5x / 1.8x (défaut) / 2.2x ATR
  • Cooldown           : 0h / 2h / 4h entre deux signaux

Prérequis : btc_1h_real.json couvrant 2 ans (lancé par fetch_btc_data.py).
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
from collections import defaultdict
from datetime import datetime, timezone

from bt_common import load_real_candles, sim_E, stats, TRADE_SIZE
from indicators import calculate_all_indicators, calculate_supertrend
from signal_engine import SignalEngine

FR_HOURS = set(range(8, 22)) - {16, 17, 18}  # 8h-21h UTC hors 16h-18h

# ─────────────────────────────────────────────────────────────────
# PRECOMPUTE  (enrichi : RSI4h, EMA4h, ST1h, ST4h, heure)
# ─────────────────────────────────────────────────────────────────

def precompute_full(candles, warmup=250, step=4):
    """
    Calcule tous les indicateurs nécessaires sur la fenêtre glissante.
    Ne tient PAS compte des filtres de suppression (heure, cooldown, RSI4h)
    pour permettre de les tester en post-processing.
    """
    sigs = []; errors = 0
    total = (len(candles) - warmup) // step
    print(f"  Precompute {len(candles)} bougies (~{total} itérations)...", end="", flush=True)

    for i in range(warmup, len(candles) - 73, step):
        w   = candles[max(0, i - 249):i + 1]
        c   = [x["close"] for x in w]; h = [x["high"] for x in w]
        l   = [x["low"]   for x in w]; v = [x["volume"] for x in w]
        ts  = [x["ts"]    for x in w]
        c4  = c[::4]; h4 = h[::4]; l4 = l[::4]; v4 = v[::4]
        if len(c4) < 15: continue

        try:
            ind = calculate_all_indicators(c, h, l, v, c4, h4, l4, v4, timestamps_1h=ts)
        except Exception:
            errors += 1; continue

        # Score brut via signal_engine (sans filtre runtime)
        se  = SignalEngine()
        atr_pct = ind.get("atr_pct")
        _, buy_met,  buy_fail  = se._check_buy(ind,  c[-1], atr_pct)
        _, sell_met, sell_fail = se._check_sell(ind, c[-1], atr_pct)
        buy_score  = len(buy_met)  * 10
        sell_score = len(sell_met) * 10

        # Bonus Titan + Sweep (comme dans evaluate())
        sweep = ind.get("sweep_1h") or {}
        msb   = ind.get("msb_1h") or {}
        cvd   = ind.get("cvd_absorption_1h") or {}
        div   = ind.get("rsi_divergence_1h") or {}

        if buy_score >= sell_score:
            score = buy_score; direction = "BUY"; met = buy_met
        else:
            score = sell_score; direction = "SELL"; met = sell_met

        if sweep.get("detected"):
            sd = sweep.get("direction")
            if (direction == "BUY" and sd == "bullish") or (direction == "SELL" and sd == "bearish"):
                score = min(100, score + 10)
        if direction == "BUY":
            if msb.get("bullish"):  score = min(100, score + 10)
            if cvd.get("bullish"):  score = min(100, score + 10)
            if div.get("bullish"):  score = min(100, score + 10)
        else:
            if msb.get("bearish"):  score = min(100, score + 10)
            if cvd.get("bearish"):  score = min(100, score + 10)
            if div.get("bearish"):  score = min(100, score + 10)

        if score < 60: continue

        # Recalcul SL/TP via signal engine complet pour les niveaux
        full_sig = se.evaluate(ind, c[-1])
        if not full_sig.get("stop_loss") or not full_sig.get("tp1"): continue

        atr = ind.get("atr_1h") or 0
        if atr <= 0: continue

        # EMA 1h trend
        emas1  = ind.get("emas_1h") or {}
        e20, e50, e200 = emas1.get("ema20"), emas1.get("ema50"), emas1.get("ema200")
        if e20 and e50 and e200:
            if   e20 > e50 > e200: ema1_trend = "bull"
            elif e20 < e50 < e200: ema1_trend = "bear"
            else:                  ema1_trend = "sideways"
        else:
            ema1_trend = "sideways"

        # EMA 4h trend
        emas4   = ind.get("emas_4h") or {}
        e20_4, e50_4 = emas4.get("ema20"), emas4.get("ema50")
        if e20_4 and e50_4:
            ema4_trend = "bull" if e20_4 > e50_4 else "bear"
        else:
            ema4_trend = "sideways"

        # SuperTrend 1h / 4h
        st1 = calculate_supertrend(h, l, c, period=10, factor=3.0)
        st4 = calculate_supertrend(h4, l4, c4, period=10, factor=3.0)
        st1_dir = st1["direction"] if st1 else None
        st4_dir = st4["direction"] if st4 else None

        # RSI 4h
        rsi4 = ind.get("rsi_4h")
        # ADX 4h
        adx4_raw = ind.get("adx_4h") or {}
        adx4 = adx4_raw.get("adx", 0) if isinstance(adx4_raw, dict) else 0

        hour     = (candles[i]["ts"] % 86400) // 3600
        dow      = (candles[i]["ts"] // 86400) % 7
        ts_val   = candles[i]["ts"]

        sigs.append({
            "idx": i, "score": score, "direction": direction,
            "price": c[-1], "atr": atr, "hour": hour, "dow": dow, "ts": ts_val,
            "ema1_trend": ema1_trend, "ema4_trend": ema4_trend,
            "st1_dir": st1_dir, "st4_dir": st4_dir,
            "rsi4": rsi4, "adx4": adx4,
        })
        if len(sigs) % 200 == 0: print(".", end="", flush=True)

    print(f" {len(sigs)} signaux ({errors} erreurs)")
    return sigs


# ─────────────────────────────────────────────────────────────────
# RUN avec paramètres variables
# ─────────────────────────────────────────────────────────────────

def run(candles, sigs,
        thresh=70,
        fr_hours=False,       # True = restreint 8h-21h UTC hors 16-18h
        rsi4_filter=False,    # True = BUY si RSI4<50 / SELL si RSI4>50
        ema1_filter=False,    # True = BUY si EMA1h bull / SELL si EMA1h bear
        sl_mult=1.8,          # multiplicateur ATR pour SL
        cooldown_h=2,         # heures min entre 2 signaux même direction
        ):
    trades = []; end_idx = 0; prev = 0
    last_ts = {"BUY": 0, "SELL": 0}

    for s in sigs:
        if s["idx"] < end_idx: prev = s["score"]; continue
        if not (prev < thresh <= s["score"]): prev = s["score"]; continue
        prev = s["score"]

        d = s["direction"]; h = s["hour"]

        # Filtre heures françaises
        if fr_hours and h not in FR_HOURS: continue

        # Filtre RSI 4h
        if rsi4_filter and s.get("rsi4") is not None:
            r4 = s["rsi4"]
            if d == "BUY"  and r4 >= 50: continue
            if d == "SELL" and r4 <= 50: continue

        # Filtre EMA 1h (F5)
        if ema1_filter:
            if d == "BUY"  and s.get("ema1_trend") != "bull": continue
            if d == "SELL" and s.get("ema1_trend") != "bear": continue

        # Cooldown
        if cooldown_h > 0 and (s["ts"] - last_ts[d]) < cooldown_h * 3600: continue

        pnl, rsn, bars = sim_E(candles, s["idx"], d, s["atr"],
                                # on passe le sl_mult via monkey-patch rapide
                                )
        # Re-simulation avec sl_mult personnalisé si différent du défaut
        if sl_mult != 1.8:
            from bt_common import _levels
            pnl, rsn, bars = _sim_custom_sl(candles, s["idx"], d, s["atr"], sl_mult)

        if rsn == "skip": continue

        last_ts[d] = s["ts"]
        trades.append({**s, "pnl_pct": pnl*100, "pnl_eur": pnl*TRADE_SIZE,
                       "reason": rsn, "bars": bars})
        end_idx = s["idx"] + bars + 4

    return trades


def _sim_custom_sl(candles, idx, direction, atr, sl_mult, max_bars=72):
    """Simulation avec SL multiplier personnalisé."""
    entry = candles[idx]["close"]
    d     = atr * sl_mult
    if direction == "BUY":
        sl, tp1, tp2, tp3 = entry - d, entry + d*1.0, entry + d*2.5, entry + d*5.0
    else:
        sl, tp1, tp2, tp3 = entry + d, entry - d*1.0, entry - d*2.5, entry - d*5.0

    rem = 1.0; total = 0.0; t1h = t2h = False
    orig_sl = sl; cur_sl = sl
    for i in range(idx + 1, min(idx + max_bars + 1, len(candles))):
        hi, lo = candles[i]["high"], candles[i]["low"]; bars = i - idx
        if direction == "BUY":
            if lo <= cur_sl:
                return total + (cur_sl - entry)/entry * rem, "SL" if cur_sl == orig_sl else "BE", bars
            if not t1h and hi >= tp1:
                total += (tp1 - entry)/entry * .40; rem -= .40; t1h = True; cur_sl = entry
            if t1h and not t2h and hi >= tp2:
                total += (tp2 - entry)/entry * .35; rem -= .35; t2h = True
            if t2h and hi >= tp3:
                return total + (tp3 - entry)/entry * .25, "TP3", bars
        else:
            if hi >= cur_sl:
                return total + (entry - cur_sl)/entry * rem, "SL" if cur_sl == orig_sl else "BE", bars
            if not t1h and lo <= tp1:
                total += (entry - tp1)/entry * .40; rem -= .40; t1h = True; cur_sl = entry
            if t1h and not t2h and lo <= tp2:
                total += (entry - tp2)/entry * .35; rem -= .35; t2h = True
            if t2h and lo <= tp3:
                return total + (entry - tp3)/entry * .25, "TP3", bars
    last = candles[min(idx + max_bars, len(candles) - 1)]["close"]
    total += ((last - entry)/entry if direction == "BUY" else (entry - last)/entry) * rem
    return total, ("TP2+to" if t2h else "TP1+to" if t1h else "timeout"), max_bars


# ─────────────────────────────────────────────────────────────────
# AFFICHAGE
# ─────────────────────────────────────────────────────────────────

HDR = (f"  {'Config':<52} | {'N':>5} | {'WR':>6} | {'Avg':>7} | "
       f"{'MDD':>6} | {'Sharpe':>7} | {'Net EUR':>9} | {'SL%':>5} | {'TP3%':>5}")
SEP = "  " + "─" * 116

def row(label, trades, markers):
    s = stats(trades)
    if not s or s["n"] < 3:
        print(f"  {label:<52} |  < 3  |   —    |    —    |   —   |    —    |      —    |   —  |   —")
        return
    wr_flag = " ◄WR" if s["wr"] > markers["wr"] else ""
    sh_flag = " ◄SH" if s["sh"] > markers["sh"] else ""
    if s["wr"] > markers["wr"]: markers["wr"] = s["wr"]
    if s["sh"] > markers["sh"]: markers["sh"] = s["sh"]
    flag = (wr_flag + sh_flag).strip()
    print(f"  {label:<52} | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+6.2f}% "
          f"| -{s['mdd']*100:4.1f}% | {s['sh']:+6.2f} | {s['net_eur']:+9.0f}€ "
          f"| {s['sl_pct']:4.0f}% | {s['tp3_pct']:4.0f}%  {flag}")


def section(title):
    print(f"\n{SEP}")
    print(f"  ▶ {title}")
    print(SEP)
    print(HDR)
    print(SEP)


def yearly_breakdown(candles, trades, label):
    """Affiche WR + net par année."""
    by_year = defaultdict(list)
    for t in trades:
        y = datetime.fromtimestamp(t["ts"], tz=timezone.utc).year
        by_year[y].append(t)
    print(f"\n  Détail par an — {label}")
    for y in sorted(by_year):
        s = stats(by_year[y])
        if s:
            print(f"    {y} : {s['n']:3d} trades | {s['wr']:5.1f}% WR | "
                  f"Sharpe {s['sh']:+.2f} | {s['net_eur']:+.0f}€")


def exit_reasons(trades, label):
    """Distribution des sorties."""
    reasons = defaultdict(int)
    for t in trades:
        reasons[t["reason"]] += 1
    total = len(trades)
    parts = [f"{r}={c/total*100:.0f}%" for r, c in sorted(reasons.items(), key=lambda x: -x[1])]
    print(f"  Sorties {label}: {' | '.join(parts)}")


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 80)
    print("  BACKTEST 2 ANS — BTC réel Binance")
    print("  Stratégies : F5 (24h/7j) vs BTC62WR (heures FR + RSI4h)")
    print("=" * 80)

    candles = load_real_candles()
    n_years = (candles[-1]["ts"] - candles[0]["ts"]) / (365.25 * 86400)
    print(f"  Durée réelle   : {n_years:.1f} an(s)\n")

    if n_years < 1.5:
        print("  ⚠  Moins de 18 mois de données.")
        print("  ⚠  Lance fetch_btc_data.py sur Windows pour obtenir 2 ans, puis git push.\n")

    sigs = precompute_full(candles)
    mk   = {"wr": 0.0, "sh": -999.0}  # marqueurs meilleur WR / Sharpe

    # ─────────────────────────────────────────────────────
    # 1. SCORE D'ENTRÉE — impact le plus important
    # ─────────────────────────────────────────────────────
    section("1 — SCORE D'ENTRÉE (F5, 24h, SL×1.8, cooldown 2h)")
    for thresh in [60, 70, 80, 90]:
        t = run(candles, sigs, thresh=thresh)
        row(f"Score ≥ {thresh}", t, mk)

    section("1b — SCORE D'ENTRÉE (BTC62WR : heures FR + RSI4h)")
    for thresh in [60, 70, 80, 90]:
        t = run(candles, sigs, thresh=thresh, fr_hours=True, rsi4_filter=True)
        row(f"Score ≥ {thresh}  [FR + RSI4h]", t, mk)

    # ─────────────────────────────────────────────────────
    # 2. FILTRES MTF — heures + RSI4h séparément
    # ─────────────────────────────────────────────────────
    section("2 — FILTRES MTF  (score ≥ 70, SL×1.8, cooldown 2h)")
    t = run(candles, sigs, thresh=70)
    row("Baseline F5 (aucun filtre)", t, mk)
    t = run(candles, sigs, thresh=70, fr_hours=True)
    row("+ Heures FR seulement", t, mk)
    t = run(candles, sigs, thresh=70, rsi4_filter=True)
    row("+ RSI4h seulement", t, mk)
    t = run(candles, sigs, thresh=70, fr_hours=True, rsi4_filter=True)
    row("+ Heures FR + RSI4h (= BTC62WR)", t, mk)
    t = run(candles, sigs, thresh=70, ema1_filter=True)
    row("+ EMA1h directionnel (F5 actuel)", t, mk)
    t = run(candles, sigs, thresh=70, ema1_filter=True, rsi4_filter=True)
    row("+ EMA1h + RSI4h", t, mk)

    # ─────────────────────────────────────────────────────
    # 3. SL MULTIPLIER ATR — risque / récompense
    # ─────────────────────────────────────────────────────
    section("3 — SL MULTIPLIER ATR  (score ≥ 70, F5 24h)")
    for sl in [1.5, 1.8, 2.2]:
        t = run(candles, sigs, thresh=70, sl_mult=sl)
        row(f"SL ×{sl} ATR", t, mk)

    section("3b — SL MULTIPLIER ATR  (score ≥ 70, BTC62WR)")
    for sl in [1.5, 1.8, 2.2]:
        t = run(candles, sigs, thresh=70, fr_hours=True, rsi4_filter=True, sl_mult=sl)
        row(f"SL ×{sl} ATR  [FR + RSI4h]", t, mk)

    # ─────────────────────────────────────────────────────
    # 4. COOLDOWN ENTRE SIGNAUX
    # ─────────────────────────────────────────────────────
    section("4 — COOLDOWN  (score ≥ 70, F5 24h, SL×1.8)")
    for cd in [0, 2, 4, 6]:
        t = run(candles, sigs, thresh=70, cooldown_h=cd)
        row(f"Cooldown {cd}h", t, mk)

    # ─────────────────────────────────────────────────────
    # 5. DIRECTION BUY / SELL séparément
    # ─────────────────────────────────────────────────────
    section("5 — DIRECTION  (score ≥ 70, F5 24h, SL×1.8)")
    t_all  = run(candles, sigs, thresh=70)
    t_buy  = [x for x in t_all if x["direction"] == "BUY"]
    t_sell = [x for x in t_all if x["direction"] == "SELL"]
    row("BUY + SELL (total)", t_all,  mk)
    row("BUY  seulement",     t_buy,  mk)
    row("SELL seulement",     t_sell, mk)

    section("5b — DIRECTION  (score ≥ 70, BTC62WR)")
    t_all2  = run(candles, sigs, thresh=70, fr_hours=True, rsi4_filter=True)
    t_buy2  = [x for x in t_all2 if x["direction"] == "BUY"]
    t_sell2 = [x for x in t_all2 if x["direction"] == "SELL"]
    row("BUY + SELL (total)  [BTC62WR]", t_all2,  mk)
    row("BUY  seulement      [BTC62WR]", t_buy2,  mk)
    row("SELL seulement      [BTC62WR]", t_sell2, mk)

    # ─────────────────────────────────────────────────────
    # 6. MEILLEURES COMBOS
    # ─────────────────────────────────────────────────────
    section("6 — MEILLEURES COMBOS")
    combos = [
        ("F5  score≥70, SL×1.8, cd2h",              dict(thresh=70, sl_mult=1.8, cooldown_h=2)),
        ("F5  score≥80, SL×1.8, cd2h",              dict(thresh=80, sl_mult=1.8, cooldown_h=2)),
        ("F5  score≥70, SL×1.5, cd2h",              dict(thresh=70, sl_mult=1.5, cooldown_h=2)),
        ("F5  score≥80, SL×1.5, cd4h",              dict(thresh=80, sl_mult=1.5, cooldown_h=4)),
        ("62WR score≥70, SL×1.8, cd2h",             dict(thresh=70, fr_hours=True, rsi4_filter=True, sl_mult=1.8, cooldown_h=2)),
        ("62WR score≥80, SL×1.8, cd2h",             dict(thresh=80, fr_hours=True, rsi4_filter=True, sl_mult=1.8, cooldown_h=2)),
        ("62WR score≥70, SL×1.5, cd2h",             dict(thresh=70, fr_hours=True, rsi4_filter=True, sl_mult=1.5, cooldown_h=2)),
        ("62WR score≥80, SL×1.5, cd4h",             dict(thresh=80, fr_hours=True, rsi4_filter=True, sl_mult=1.5, cooldown_h=4)),
        ("62WR+EMA1h score≥70, SL×1.8",             dict(thresh=70, fr_hours=True, rsi4_filter=True, ema1_filter=True, sl_mult=1.8)),
        ("62WR+EMA1h score≥80, SL×1.5",             dict(thresh=80, fr_hours=True, rsi4_filter=True, ema1_filter=True, sl_mult=1.5)),
        ("SELL only 62WR score≥70",                  dict(thresh=70, fr_hours=True, rsi4_filter=True)),  # SELL filtered below
    ]
    for label, kwargs in combos[:-1]:
        t = run(candles, sigs, **kwargs)
        row(label, t, mk)
    # SELL only 62WR
    t_tmp = run(candles, sigs, thresh=70, fr_hours=True, rsi4_filter=True)
    t_sell_only = [x for x in t_tmp if x["direction"] == "SELL"]
    row("SELL only 62WR score≥70", t_sell_only, mk)

    # ─────────────────────────────────────────────────────
    # 7. DÉTAIL ANNUEL — F5 vs BTC62WR
    # ─────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  ▶ 7 — BREAKDOWN ANNUEL")
    print(SEP)
    t_f5  = run(candles, sigs, thresh=70)
    t_62  = run(candles, sigs, thresh=70, fr_hours=True, rsi4_filter=True)
    yearly_breakdown(candles, t_f5, "F5 (score≥70, 24h)")
    yearly_breakdown(candles, t_62, "BTC62WR (score≥70, heures FR + RSI4h)")
    print()
    exit_reasons(t_f5, "F5")
    exit_reasons(t_62, "BTC62WR")

    # ─────────────────────────────────────────────────────
    # RÉSUMÉ FINAL
    # ─────────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"  Meilleur Win Rate atteint : {mk['wr']:.1f}%")
    print(f"  Meilleur Sharpe atteint   : {mk['sh']:+.2f}")
    print(f"  (marqueur ◄WR / ◄SH dans les tableaux)")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
