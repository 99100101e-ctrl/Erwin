"""
Backtest SuperTrend — BTC Trading Advisor
Données RÉELLES : backend/data/btc_1h_real.json (6 mois, Sep 2025 → Mar 2026)

Questions :
  1. SuperTrend(10, 3.0) vs EMA-trend vs aucun filtre : qui gagne ?
  2. Quel paramétrage SuperTrend est optimal (period × factor) ?
  3. SuperTrend + filtre horaire = combo ultime ?
  4. Quel impact sur BUY vs SELL séparément ?
"""
import numpy as np
from collections import defaultdict
from datetime import datetime, timezone
from bt_common import (load_real_candles, TRADE_SIZE, stats)
from indicators import calculate_all_indicators, calculate_supertrend
from signal_engine import SignalEngine


# ─────────────────────────────────────────────────────────────────────────────
# Precompute étendu : calcule aussi SuperTrend avec plusieurs paramétrisations
# ─────────────────────────────────────────────────────────────────────────────

ST_CONFIGS = [
    (7,  2.0), (7,  3.0), (7,  4.0),
    (10, 2.0), (10, 3.0), (10, 4.0),
    (14, 2.0), (14, 3.0), (14, 4.0),
]

BEST_HOURS = {0, 4, 12, 20}   # heures UTC rentables (backtest_heures)
AVOID_HOURS = {16, 17, 18}     # US open : 18.2% WR -140€


def precompute_st(candles, warmup=200, step=4, verbose=True):
    """Precompute signaux + SuperTrend multi-configs."""
    sigs = []; errors = 0
    total = (len(candles) - warmup) // step
    if verbose:
        print(f"  Calcul sur ~{total} points (step={step}h)...", end="", flush=True)

    _cur_trend = "sideways"; _trend_since_i = warmup

    for i in range(warmup, len(candles) - 73, step):
        w = candles[max(0, i - 249):i + 1]
        c = [x["close"] for x in w]; h = [x["high"] for x in w]
        l = [x["low"] for x in w];   v = [x["volume"] for x in w]
        ts = [x["ts"] for x in w]
        c4 = c[::4]; h4 = h[::4]; l4 = l[::4]; v4 = v[::4]
        if len(c4) < 15:
            continue
        try:
            ind = calculate_all_indicators(c, h, l, v, c4, h4, l4, v4, timestamps_1h=ts)
        except Exception:
            errors += 1; continue

        sig = SignalEngine().evaluate(ind, c[-1])
        if sig.get("score", 0) < 60:
            continue
        if not sig.get("stop_loss") or not sig.get("tp1"):
            continue
        atr = ind.get("atr_1h") or 0
        if atr <= 0:
            continue

        # Tendance EMA (bull/bear/sideways)
        emas = ind.get("emas_1h") or {}
        e20, e50, e200 = emas.get("ema20"), emas.get("ema50"), emas.get("ema200")
        if e20 and e50 and e200:
            if e20 > e50 > e200:   ema_trend = "bull"
            elif e20 < e50 < e200: ema_trend = "bear"
            else:                  ema_trend = "sideways"
        else:
            ema_trend = "sideways"

        # SuperTrend multi-configs
        st_dirs = {}
        for period, factor in ST_CONFIGS:
            st = calculate_supertrend(h, l, c, period=period, factor=factor)
            st_dirs[(period, factor)] = st["direction"] if st else "UNKNOWN"

        hour_utc = (candles[i]["ts"] % 86400) // 3600
        sigs.append({
            "idx": i, "score": sig["score"], "direction": sig["direction"],
            "price": c[-1], "atr": atr,
            "ema_trend": ema_trend,
            "st": st_dirs,          # {(period,factor): "UP"|"DOWN"|"UNKNOWN"}
            "hour": hour_utc,
            "ts": candles[i]["ts"],
        })
        if verbose and len(sigs) % 100 == 0:
            print(".", end="", flush=True)
    if verbose:
        print(f" {len(sigs)} signaux ({errors} erreurs)")
    return sigs


# ─────────────────────────────────────────────────────────────────────────────
# Simulation Stratégie E
# ─────────────────────────────────────────────────────────────────────────────

def sim_E(candles, idx, direction, atr, max_bars=72):
    entry = candles[idx]["close"]
    sl_dist = atr * 1.8
    if direction == "BUY":
        sl, tp1, tp2, tp3 = entry-sl_dist, entry+sl_dist*1.0, entry+sl_dist*2.5, entry+sl_dist*5.0
    else:
        sl, tp1, tp2, tp3 = entry+sl_dist, entry-sl_dist*1.0, entry-sl_dist*2.5, entry-sl_dist*5.0
    rem = 1.0; total = 0.0; t1h = t2h = False; orig_sl = sl; cur_sl = sl
    for i in range(idx + 1, min(idx + max_bars + 1, len(candles))):
        h, l = candles[i]["high"], candles[i]["low"]; bars = i - idx
        if direction == "BUY":
            if l <= cur_sl: return total + (cur_sl-entry)/entry*rem, "SL" if cur_sl==orig_sl else "BE", bars
            if not t1h and h >= tp1: total += (tp1-entry)/entry*.40; rem -= .40; t1h=True; cur_sl=entry
            if t1h and not t2h and h >= tp2: total += (tp2-entry)/entry*.35; rem -= .35; t2h=True
            if t2h and h >= tp3: return total + (tp3-entry)/entry*.25, "TP3", bars
        else:
            if h >= cur_sl: return total + (entry-cur_sl)/entry*rem, "SL" if cur_sl==orig_sl else "BE", bars
            if not t1h and l <= tp1: total += (entry-tp1)/entry*.40; rem -= .40; t1h=True; cur_sl=entry
            if t1h and not t2h and l <= tp2: total += (entry-tp2)/entry*.35; rem -= .35; t2h=True
            if t2h and l <= tp3: return total + (entry-tp3)/entry*.25, "TP3", bars
    last = candles[min(idx+max_bars, len(candles)-1)]["close"]
    total += ((last-entry)/entry if direction=="BUY" else (entry-last)/entry) * rem
    return total, ("TP2+to" if t2h else "TP1+to" if t1h else "timeout"), max_bars


def run_filtered(candles, sigs, thresh=70, st_config=None, ema_filter=False,
                  buy_only_in_up=True, sell_only_in_down=True,
                  hour_filter=False):
    """
    Simule les trades avec différents filtres.
    - st_config  : (period, factor) ou None (pas de filtre ST)
    - ema_filter : utiliser EMA20>50>200 comme filtre direction
    - buy_only_in_up / sell_only_in_down : sens du filtre directeur
    - hour_filter : éviter les heures de la session US (16-18h UTC)
    """
    trades = []; end_idx = 0; prev = 0
    for s in sigs:
        if s["idx"] < end_idx:
            prev = s["score"]; continue
        if not (prev < thresh <= s["score"]):
            prev = s["score"]; continue
        prev = s["score"]

        # Filtre horaire (session US)
        if hour_filter and s.get("hour") in AVOID_HOURS:
            continue

        direction = s["direction"]

        # Filtre SuperTrend
        if st_config is not None:
            st_dir = s["st"].get(st_config, "UNKNOWN")
            if st_dir == "UNKNOWN":
                continue
            if buy_only_in_up and direction == "BUY" and st_dir != "UP":
                continue
            if sell_only_in_down and direction == "SELL" and st_dir != "DOWN":
                continue

        # Filtre EMA
        if ema_filter:
            ema_t = s.get("ema_trend", "sideways")
            if buy_only_in_up and direction == "BUY" and ema_t != "bull":
                continue
            if sell_only_in_down and direction == "SELL" and ema_t != "bear":
                continue

        pnl, rsn, bars = sim_E(candles, s["idx"], direction, s["atr"])
        if rsn == "skip":
            continue
        trades.append({**s, "pnl_pct": pnl*100, "pnl_eur": pnl*TRADE_SIZE, "reason": rsn, "bars": bars})
        end_idx = s["idx"] + bars + 4
    return trades


# ─────────────────────────────────────────────────────────────────────────────
# Partie 1 : Comparaison baseline vs EMA vs SuperTrend
# ─────────────────────────────────────────────────────────────────────────────

def partie1_comparaison(candles, sigs):
    print(f"\n{'─' * 90}")
    print("  PARTIE 1 — Baseline vs EMA-trend vs SuperTrend(10,3.0) vs Combo")
    print(f"{'─' * 90}")

    configs = [
        ("F0  — Aucun filtre (baseline)",       dict()),
        ("F5  — EMA BUY-only en Bull",           dict(ema_filter=True, sell_only_in_down=False)),
        ("F5b — EMA BUY+SELL alignés",           dict(ema_filter=True)),
        ("ST  — SuperTrend(10,3.0) BUY-only",   dict(st_config=(10,3.0), sell_only_in_down=False)),
        ("STb — SuperTrend(10,3.0) BUY+SELL",   dict(st_config=(10,3.0))),
        ("STH — ST(10,3.0) + filtre heures",    dict(st_config=(10,3.0), hour_filter=True)),
        ("STHb— ST+heure BUY+SELL alignés",     dict(st_config=(10,3.0), hour_filter=True)),
    ]

    print(f"\n  {'Config':<36} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'MaxDD':>7} | {'Sharpe':>7} | {'Net EUR':>10} | {'SL%':>5}")
    print("  " + "─" * 92)

    results = {}
    for label, kwargs in configs:
        trades = run_filtered(candles, sigs, thresh=70, **kwargs)
        s = stats(trades)
        results[label] = (trades, s)
        if s:
            print(f"  {label:<36} | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% "
                  f"| -{s['mdd']*100:4.1f}% | {s['sh']:+6.2f} | {s['net_eur']:+9.0f} EUR | {s['sl_pct']:4.0f}%")
        else:
            print(f"  {label:<36} |  <3   |   -    |    -     |    -    |    -    |    -       |   -")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Partie 2 : Grille de paramètres SuperTrend (period × factor)
# ─────────────────────────────────────────────────────────────────────────────

def partie2_grille_params(candles, sigs):
    print(f"\n{'─' * 90}")
    print("  PARTIE 2 — Grille SuperTrend : period × factor (BUY+SELL alignés, seuil 70)")
    print(f"{'─' * 90}")
    print(f"\n  {'Config':<14} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'Sharpe':>7} | {'Net EUR':>10} | {'SL%':>5}")
    print("  " + "─" * 65)

    best_sh = -999; best_cfg = None
    for period, factor in ST_CONFIGS:
        trades = run_filtered(candles, sigs, thresh=70, st_config=(period,factor))
        s = stats(trades)
        label = f"ST({period:2d}, {factor:.1f})"
        if s:
            flag = " *" if s["sh"] > best_sh and s["n"] >= 5 else ""
            if s["sh"] > best_sh and s["n"] >= 5:
                best_sh = s["sh"]; best_cfg = (period, factor)
            print(f"  {label:<14} | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% "
                  f"| {s['sh']:+6.2f} | {s['net_eur']:+9.0f} EUR | {s['sl_pct']:4.0f}%{flag}")
        else:
            print(f"  {label:<14} |  <3   |   -    |    -     |    -    |    -       |   -")
    print(f"\n  Meilleur paramétrage : ST{best_cfg}" if best_cfg else "")
    return best_cfg


# ─────────────────────────────────────────────────────────────────────────────
# Partie 3 : BUY vs SELL avec le meilleur SuperTrend
# ─────────────────────────────────────────────────────────────────────────────

def partie3_buy_sell(candles, sigs, best_cfg):
    print(f"\n{'─' * 78}")
    print(f"  PARTIE 3 — BUY vs SELL avec SuperTrend{best_cfg}")
    print(f"{'─' * 78}")

    configs = [
        ("Baseline (aucun filtre)",        dict()),
        (f"ST{best_cfg} BUY-only en UP",   dict(st_config=best_cfg, sell_only_in_down=False)),
        (f"ST{best_cfg} SELL-only en DOWN",dict(st_config=best_cfg, buy_only_in_up=False)),
        (f"ST{best_cfg} BUY+SELL alignés", dict(st_config=best_cfg)),
    ]

    for label, kwargs in configs:
        trades = run_filtered(candles, sigs, thresh=70, **kwargs)
        buys  = [t for t in trades if t["direction"] == "BUY"]
        sells = [t for t in trades if t["direction"] == "SELL"]
        sb = stats(buys); ss = stats(sells); st = stats(trades)
        print(f"\n  ── {label} ──")
        print(f"  {'Dir':8} | {'N':>5} | {'Win%':>6} | {'Net EUR':>10} | {'SL%':>5}")
        print("  " + "─" * 40)
        for dir_label, s in [("TOUS", st), ("BUY", sb), ("SELL", ss)]:
            if s:
                print(f"  {dir_label:<8} | {s['n']:5d} | {s['wr']:5.1f}% | {s['net_eur']:+9.0f} EUR | {s['sl_pct']:4.0f}%")
            else:
                print(f"  {dir_label:<8} |  <3   |   -    |    -       |   -")


# ─────────────────────────────────────────────────────────────────────────────
# Partie 4 : SuperTrend + filtre horaire — analyse détaillée
# ─────────────────────────────────────────────────────────────────────────────

def partie4_combo_horaire(candles, sigs, best_cfg):
    print(f"\n{'─' * 78}")
    print(f"  PARTIE 4 — SuperTrend{best_cfg} + filtres horaires combinés")
    print(f"{'─' * 78}")

    combos = [
        ("ST seul",                 dict(st_config=best_cfg)),
        ("ST + évite US (16-18h)",  dict(st_config=best_cfg, hour_filter=True)),
        ("ST + Asie only (00-08h)", dict(st_config=best_cfg, _asie_only=True)),
    ]

    print(f"\n  {'Config':<30} | {'N':>5} | {'Win%':>6} | {'Sharpe':>7} | {'Net EUR':>10} | {'MaxDD':>7}")
    print("  " + "─" * 72)
    for label, kwargs in combos:
        asie_only = kwargs.pop("_asie_only", False)
        trades = run_filtered(candles, sigs, thresh=70, **kwargs)
        if asie_only:
            trades = [t for t in trades if t.get("hour", 0) < 8]
        s = stats(trades)
        if s:
            print(f"  {label:<30} | {s['n']:5d} | {s['wr']:5.1f}% | {s['sh']:+6.2f} | {s['net_eur']:+9.0f} EUR | -{s['mdd']*100:4.1f}%")
        else:
            print(f"  {label:<30} |  <3   |   -    |    -    |    -       |   -")

    # Equité mensuelle du meilleur combo
    print(f"\n  P&L mensuel — ST{best_cfg} + filtre heures :")
    best_trades = run_filtered(candles, sigs, thresh=70, st_config=best_cfg, hour_filter=True)
    by_month = defaultdict(list)
    for t in best_trades:
        dt = datetime.fromtimestamp(candles[t["idx"]]["ts"], tz=timezone.utc)
        by_month[(dt.year, dt.month)].append(t)
    print(f"  {'Mois':>8} | {'N':>4} | {'Win%':>6} | {'Net EUR':>10} | Barre")
    print("  " + "─" * 50)
    cumul = 0
    for mk in sorted(by_month.keys()):
        g = by_month[mk]
        net = sum(t["pnl_eur"] for t in g)
        cumul += net
        wr = sum(1 for t in g if t["pnl_pct"] > 0) / len(g) * 100
        bar = ("█" if net > 0 else "░") * min(int(abs(net)/15), 28)
        label = datetime(mk[0], mk[1], 1).strftime("%b %Y")
        print(f"  {label:>8} | {len(g):4d} | {wr:5.1f}% | {net:+9.0f} EUR | {bar}")
    print(f"  {'TOTAL':>8} | {len(best_trades):4d} |       | {cumul:+9.0f} EUR |")


# ─────────────────────────────────────────────────────────────────────────────
# Partie 5 : Fréquence des flips SuperTrend (combien de fois il change de sens)
# ─────────────────────────────────────────────────────────────────────────────

def partie5_flips(candles, best_cfg):
    period, factor = best_cfg
    print(f"\n{'─' * 78}")
    print(f"  PARTIE 5 — Fiabilité SuperTrend({period},{factor}) : flips et durées")
    print(f"{'─' * 78}")

    c = [x["close"] for x in candles]
    h = [x["high"]  for x in candles]
    l = [x["low"]   for x in candles]

    # Calculer SuperTrend sur toute la série, barre par barre
    flips = 0; streak = 0; streaks = []; last_dir = None
    for i in range(period + 10, len(candles)):
        st = calculate_supertrend(h[:i+1], l[:i+1], c[:i+1], period, factor)
        if st is None:
            continue
        d = st["direction"]
        if last_dir is None:
            last_dir = d; streak = 1; continue
        if d != last_dir:
            streaks.append((last_dir, streak))
            flips += 1
            last_dir = d; streak = 1
        else:
            streak += 1
    if last_dir:
        streaks.append((last_dir, streak))

    up_streaks   = [s for dir_, s in streaks if dir_ == "UP"]
    down_streaks = [s for dir_, s in streaks if dir_ == "DOWN"]

    print(f"\n  Nombre total de flips sur 6 mois : {flips}")
    print(f"  Durée moy. phase UP   : {np.mean(up_streaks):.0f}h  (min {min(up_streaks) if up_streaks else 0}h, max {max(up_streaks) if up_streaks else 0}h)")
    print(f"  Durée moy. phase DOWN : {np.mean(down_streaks):.0f}h  (min {min(down_streaks) if down_streaks else 0}h, max {max(down_streaks) if down_streaks else 0}h)")
    print(f"  % du temps en UP      : {sum(up_streaks)/(sum(up_streaks)+sum(down_streaks))*100:.1f}%")
    print(f"  % du temps en DOWN    : {sum(down_streaks)/(sum(up_streaks)+sum(down_streaks))*100:.1f}%")

    # Vérifier cohérence avec le marché (ATH oct, chute nov-mars)
    print(f"\n  Chronologie des flips (sens × durée en heures) :")
    for dir_, s in streaks:
        arrow = "↑ UP  " if dir_ == "UP" else "↓ DOWN"
        bar = ("█" if dir_ == "UP" else "░") * min(s // 50, 30)
        print(f"    {arrow} {s:5d}h  {bar}")


# ─────────────────────────────────────────────────────────────────────────────
# Partie 6 : Recommandation finale
# ─────────────────────────────────────────────────────────────────────────────

def partie6_recommandation(results, best_cfg):
    print(f"\n{'=' * 78}")
    print("  RECOMMANDATION FINALE")
    print(f"{'=' * 78}")

    # Trouver le meilleur par Sharpe
    best_sh = -999; best_label = None; best_s = None
    for label, (trades, s) in results.items():
        if s and s["n"] >= 5 and s["sh"] > best_sh:
            best_sh = s["sh"]; best_label = label; best_s = s

    if best_s:
        print(f"""
  Meilleure config : {best_label}
  ─────────────────────────────────────────────────────────────────
  Trades          : {best_s['n']}
  Win rate        : {best_s['wr']:.1f}%
  P&L moyen       : {best_s['avg']:+.2f}%  ({best_s['avg']*TRADE_SIZE/100:+.0f} EUR)
  Max Drawdown    : -{best_s['mdd']*100:.1f}%
  Sharpe          : {best_s['sh']:+.2f}
  Net P&L         : {best_s['net_eur']:+.0f} EUR  (sur {TRADE_SIZE} EUR/trade)
  Stop loss       : {best_s['sl_pct']:.0f}%

  À IMPLÉMENTER dans signal_engine.py :
  ─────────────────────────────────────────────────────────────────
  1. Calculer SuperTrend({best_cfg[0]}, {best_cfg[1]}) sur closes/highs/lows 1h
  2. BUY  autorisé uniquement si ST direction == "UP"
  3. SELL autorisé uniquement si ST direction == "DOWN"
  4. Éviter trades à 16h-18h UTC (session US open, 18.2% WR)

  LOGIQUE DE SUPPRESSION (remplace/complète EMA-trend actuel) :
    if direction == "BUY"  and supertrend_1h["direction"] != "UP":
        suppress("SuperTrend DOWN — BUY bloqué")
    if direction == "SELL" and supertrend_1h["direction"] != "DOWN":
        suppress("SuperTrend UP — SELL bloqué")
""")
    print(f"{'=' * 78}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def run():
    print("\n" + "=" * 90)
    print("  BACKTEST SUPERTREND — BTC Trading Advisor — DONNÉES RÉELLES BINANCE")
    print("  Période : Sep 2025 → Mar 2026 | BTC : +ATH $126K puis -35%")
    print("=" * 90)

    candles = load_real_candles()
    print("\n  Precompute signaux + SuperTrend multi-configs...")
    sigs = precompute_st(candles, warmup=200, step=4, verbose=True)
    if not sigs:
        print("  Aucun signal. Abandon."); return

    results = partie1_comparaison(candles, sigs)
    best_cfg = partie2_grille_params(candles, sigs)
    if not best_cfg:
        best_cfg = (10, 3.0)
    partie3_buy_sell(candles, sigs, best_cfg)
    partie4_combo_horaire(candles, sigs, best_cfg)
    partie5_flips(candles, best_cfg)
    partie6_recommandation(results, best_cfg)


if __name__ == "__main__":
    run()
