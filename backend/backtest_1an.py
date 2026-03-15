"""
Backtest 1 AN — BTC Trading Advisor — Strategie E
- 2000 EUR par trade
- Seuils 70 / 80 / 90
- Analyse BUY vs SELL, regimes, heures, score vs win rate
- Correction bug opens_1h (parametre invalide dans l'ancien backtest)
"""
import random, numpy as np, math
from collections import defaultdict
from indicators import calculate_all_indicators
from signal_engine import SignalEngine


# ─────────────────────────────────────────────────────────────────────────────
# Generateur BTC synthetique — 1 an de bougies 1h
# ─────────────────────────────────────────────────────────────────────────────

def generate_btc_1an(n=8760, start=67000.0, seed=42):
    """Genere ~1 an de donnees OHLCV 1h avec regimes bull/bear/sideways."""
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
        cur_vol = 0.85 * cur_vol + 0.15 * ({"bull": .007, "bear": .010, "sideways": .005}[regime] * (0.5 + shock))
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
        h = max(o, c) + sp * random.uniform(.2, 1.); l = min(o, c) - sp * random.uniform(.2, 1.)
        candles.append({
            "ts": 1704067200 + i * 3600,
            "open": round(o, 2), "high": round(h, 2),
            "low": round(l, 2), "close": round(c, 2), "volume": round(v, 2),
            "regime": regimes_log[i - 1] if i > 0 else "bull",
        })
    return candles


# ─────────────────────────────────────────────────────────────────────────────
# Niveaux de risque
# ─────────────────────────────────────────────────────────────────────────────

def _levels(direction, entry, atr, sl_mult=1.8, tp1_rr=1.0, tp2_rr=2.5, tp3_rr=5.0):
    if not atr or atr <= 0:
        return None, None, None, None
    d = atr * sl_mult
    if direction == "BUY":
        return entry - d, entry + d * tp1_rr, entry + d * tp2_rr, entry + d * tp3_rr
    return entry + d, entry - d * tp1_rr, entry - d * tp2_rr, entry - d * tp3_rr


# ─────────────────────────────────────────────────────────────────────────────
# Simulation Strategie E (TP1=1.0xR + BE immediat)
# ─────────────────────────────────────────────────────────────────────────────

def sim_E(candles, idx, direction, atr, max_bars=72):
    entry = candles[idx]["close"]
    sl, tp1, tp2, tp3 = _levels(direction, entry, atr)
    if sl is None:
        return 0.0, "skip", 0
    rem = 1.0; total = 0.0; t1h = t2h = False
    orig_sl = sl; current_sl = sl
    for i in range(idx + 1, min(idx + max_bars + 1, len(candles))):
        h, l = candles[i]["high"], candles[i]["low"]; bars = i - idx
        if direction == "BUY":
            if l <= current_sl:
                return total + (current_sl - entry) / entry * rem, "SL" if current_sl == orig_sl else "BE", bars
            if not t1h and h >= tp1:
                total += (tp1 - entry) / entry * .40; rem -= .40; t1h = True; current_sl = entry
            if t1h and not t2h and h >= tp2:
                total += (tp2 - entry) / entry * .35; rem -= .35; t2h = True
            if t2h and h >= tp3:
                return total + (tp3 - entry) / entry * .25, "TP3", bars
        else:
            if h >= current_sl:
                return total + (entry - current_sl) / entry * rem, "SL" if current_sl == orig_sl else "BE", bars
            if not t1h and l <= tp1:
                total += (entry - tp1) / entry * .40; rem -= .40; t1h = True; current_sl = entry
            if t1h and not t2h and l <= tp2:
                total += (entry - tp2) / entry * .35; rem -= .35; t2h = True
            if t2h and l <= tp3:
                return total + (entry - tp3) / entry * .25, "TP3", bars
    last = candles[min(idx + max_bars, len(candles) - 1)]["close"]
    total += ((last - entry) / entry if direction == "BUY" else (entry - last) / entry) * rem
    return total, ("TP2+to" if t2h else "TP1+to" if t1h else "timeout"), max_bars


# ─────────────────────────────────────────────────────────────────────────────
# Precompute signaux — CORRECTION: sans opens_1h (parametre invalide)
# ─────────────────────────────────────────────────────────────────────────────

def precompute(candles, warmup=200, step=4):
    sigs = []
    total_points = (len(candles) - warmup) // step
    print(f"  Calcul sur ~{total_points} points (step={step}h)...", end="", flush=True)
    errors = 0
    for i in range(warmup, len(candles) - 73, step):
        w = candles[max(0, i - 249):i + 1]
        c = [x["close"] for x in w]; h = [x["high"] for x in w]
        l = [x["low"] for x in w]; v = [x["volume"] for x in w]
        ts = [x["ts"] for x in w]
        c4 = c[::4]; h4 = h[::4]; l4 = l[::4]; v4 = v[::4]
        if len(c4) < 15:
            continue
        try:
            # CORRECTION: pas de opens_1h (parametre inexistant dans calculate_all_indicators)
            ind = calculate_all_indicators(c, h, l, v, c4, h4, l4, v4, timestamps_1h=ts)
        except Exception as e:
            errors += 1
            continue
        sig = SignalEngine().evaluate(ind, c[-1])
        if sig.get("suppressed") or sig.get("signal") in ("HOLD", "WAIT"):
            continue
        if not sig.get("stop_loss") or not sig.get("tp1"):
            continue
        atr = ind.get("atr_1h") or 0
        if atr <= 0:
            continue
        hour = (candles[i]["ts"] % 86400) // 3600
        sigs.append({
            "idx": i, "score": sig["score"], "direction": sig["direction"],
            "price": c[-1], "atr": atr,
            "regime": candles[i].get("regime", "unknown"),
            "hour": hour,
        })
        if len(sigs) % 100 == 0:
            print(".", end="", flush=True)
    print(f" {len(sigs)} signaux ({errors} erreurs ignorees)")
    return sigs


# ─────────────────────────────────────────────────────────────────────────────
# Backtest par seuil (Strategie E, 2000 EUR/trade)
# ─────────────────────────────────────────────────────────────────────────────

TRADE_SIZE = 2000  # EUR par trade

def bt_threshold(candles, sigs, thresh):
    trades = []; end_idx = 0; prev = 0
    for s in sigs:
        if s["idx"] < end_idx:
            prev = s["score"]; continue
        crossed = (prev < thresh <= s["score"]); prev = s["score"]
        if not crossed:
            continue
        pnl, rsn, bars = sim_E(candles, s["idx"], s["direction"], s["atr"])
        if rsn == "skip":
            continue
        trades.append({**s, "pnl_pct": pnl * 100, "pnl_eur": pnl * TRADE_SIZE, "reason": rsn, "bars": bars})
        end_idx = s["idx"] + bars + 4
    return trades


# ─────────────────────────────────────────────────────────────────────────────
# Statistiques completes
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
    return {
        "n": len(trades), "wr": wr, "avg": avg, "med": np.median(pnls),
        "mdd": mdd, "sh": avg / std * np.sqrt(min(len(trades), 252)),
        "sl_pct": sum(1 for t in trades if t["reason"] == "SL") / len(trades) * 100,
        "be_pct": sum(1 for t in trades if t["reason"] == "BE") / len(trades) * 100,
        "tp3_pct": sum(1 for t in trades if t["reason"] == "TP3") / len(trades) * 100,
        "avg_bars": np.mean([t["bars"] for t in trades]),
        "net_eur": sum(eurs),
        "best_eur": max(eurs), "worst_eur": min(eurs),
        "avg_eur": np.mean(eurs),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Analyse BUY vs SELL
# ─────────────────────────────────────────────────────────────────────────────

def analyse_direction(trades):
    buys = [t for t in trades if t["direction"] == "BUY"]
    sells = [t for t in trades if t["direction"] == "SELL"]
    print(f"\n{'─' * 70}")
    print("  ANALYSE : BUY vs SELL")
    print(f"{'─' * 70}")
    print(f"{'Direction':<10} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'Net EUR':>10}")
    print("─" * 50)
    for label, group in [("BUY", buys), ("SELL", sells)]:
        if not group:
            print(f"  {label:<8} |   0   |   -    |    -     |    -")
            continue
        s = stats(group)
        if s:
            print(f"  {label:<8} | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% | {s['net_eur']:+9.0f} EUR")


# ─────────────────────────────────────────────────────────────────────────────
# Analyse par regime de marche
# ─────────────────────────────────────────────────────────────────────────────

def analyse_regimes(trades):
    print(f"\n{'─' * 70}")
    print("  ANALYSE : Performance par regime de marche")
    print(f"{'─' * 70}")
    print(f"{'Regime':<12} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'Net EUR':>10}")
    print("─" * 55)
    for regime in ["bull", "sideways", "bear"]:
        group = [t for t in trades if t.get("regime") == regime]
        if not group:
            print(f"  {regime:<10} |   0   |   -    |    -     |    -")
            continue
        s = stats(group)
        if s:
            flag = " <- attention" if s["wr"] < 40 else (" <- optimal" if s["wr"] > 60 else "")
            print(f"  {regime:<10} | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% | {s['net_eur']:+9.0f} EUR{flag}")


# ─────────────────────────────────────────────────────────────────────────────
# Analyse horaire (heure UTC)
# ─────────────────────────────────────────────────────────────────────────────

def analyse_hours(trades):
    print(f"\n{'─' * 70}")
    print("  ANALYSE : Performance par heure UTC (top 6 et flop 6)")
    print(f"{'─' * 70}")
    by_hour = defaultdict(list)
    for t in trades:
        by_hour[t.get("hour", 0)].append(t)
    hour_stats = {}
    for h, group in by_hour.items():
        if len(group) >= 3:
            s = stats(group)
            if s:
                hour_stats[h] = s
    if not hour_stats:
        print("  Pas assez de donnees par heure.")
        return
    sorted_hours = sorted(hour_stats.items(), key=lambda x: x[1]["net_eur"], reverse=True)
    print(f"\n  Meilleures heures :")
    print(f"  {'Heure':>6} | {'N':>4} | {'Win%':>6} | {'Net EUR':>10}")
    print("  " + "─" * 35)
    for h, s in sorted_hours[:6]:
        print(f"  {h:02d}h UTC | {s['n']:4d} | {s['wr']:5.1f}% | {s['net_eur']:+9.0f} EUR")
    print(f"\n  Pires heures :")
    print(f"  {'Heure':>6} | {'N':>4} | {'Win%':>6} | {'Net EUR':>10}")
    print("  " + "─" * 35)
    for h, s in sorted_hours[-6:]:
        print(f"  {h:02d}h UTC | {s['n']:4d} | {s['wr']:5.1f}% | {s['net_eur']:+9.0f} EUR")


# ─────────────────────────────────────────────────────────────────────────────
# Analyse score vs win rate
# ─────────────────────────────────────────────────────────────────────────────

def analyse_score_quality(trades):
    print(f"\n{'─' * 70}")
    print("  ANALYSE : Score du signal vs taux de reussite reel")
    print(f"{'─' * 70}")
    bands = [(60, 69), (70, 79), (80, 89), (90, 100)]
    print(f"  {'Score':^10} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'Net EUR':>10}")
    print("  " + "─" * 52)
    for lo, hi in bands:
        group = [t for t in trades if lo <= t["score"] <= hi]
        if not group:
            print(f"  {lo:3d}-{hi:3d}    |   0   |   -    |    -     |    -")
            continue
        s = stats(group)
        if s:
            print(f"  {lo:3d}-{hi:3d}    | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% | {s['net_eur']:+9.0f} EUR")


# ─────────────────────────────────────────────────────────────────────────────
# Courbe d'equite mensuelle
# ─────────────────────────────────────────────────────────────────────────────

def analyse_monthly(candles, trades):
    print(f"\n{'─' * 70}")
    print("  ANALYSE : P&L mensuel (2000 EUR/trade)")
    print(f"{'─' * 70}")
    by_month = defaultdict(list)
    for t in trades:
        ts = candles[t["idx"]]["ts"]
        month = (ts - 1704067200) // (30 * 24 * 3600)
        by_month[month].append(t)
    months = ["Jan", "Feb", "Mar", "Avr", "Mai", "Jun", "Jul", "Aou", "Sep", "Oct", "Nov", "Dec"]
    print(f"\n  {'Mois':>5} | {'N':>4} | {'Win%':>6} | {'Net EUR':>10} | Barre")
    print("  " + "─" * 55)
    cumul = 0
    for m in sorted(by_month.keys()):
        group = by_month[m]
        if not group:
            continue
        net = sum(t["pnl_eur"] for t in group)
        cumul += net
        wr = sum(1 for t in group if t["pnl_pct"] > 0) / len(group) * 100
        bar = "+" * int(abs(net) / 20) if net > 0 else "-" * int(abs(net) / 20)
        bar = bar[:30]
        label = months[m % 12] if m < 12 else f"M{m+1}"
        print(f"  {label:>5} | {len(group):4d} | {wr:5.1f}% | {net:+9.0f} EUR | {'█' * len(bar) if net > 0 else '░' * len(bar)}")
    print(f"  {'─' * 40}")
    print(f"  {'TOTAL':>5} | {len(trades):4d} |       | {cumul:+9.0f} EUR |")


# ─────────────────────────────────────────────────────────────────────────────
# Point d'entree
# ─────────────────────────────────────────────────────────────────────────────

def run():
    print("\n" + "=" * 70)
    print("  BACKTEST 1 AN — BTC Trading Advisor — Strategie E")
    print(f"  Capital par trade : {TRADE_SIZE} EUR")
    print("=" * 70 + "\n")

    candles = generate_btc_1an(n=8760)
    p0 = candles[200]["close"]; p1 = candles[-1]["close"]
    print(f"  BTC simule : ${p0:,.0f} -> ${p1:,.0f}  ({(p1 / p0 - 1) * 100:+.1f}% sur 1 an)\n")

    print("  Precompute des signaux...")
    sigs = precompute(candles, warmup=200, step=4)

    if not sigs:
        print("\n  ERREUR: aucun signal genere. Verifiez le signal_engine.")
        return

    # ── Tableau principal : seuils 70 / 80 / 90 ──────────────────────────────
    print(f"\n{'─' * 70}")
    print("  RESULTATS — Strategie E par seuil d'entree (2000 EUR/trade)")
    print(f"{'─' * 70}\n")
    print(f"  {'Seuil':>7} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'MaxDD':>7} | {'Sharpe':>7} | {'Net EUR':>11} | {'SL%':>5}")
    print("  " + "─" * 72)

    thresholds = [60, 70, 80, 90]
    all_trades = {}
    best_thresh = 80
    best_score = -999

    for t in thresholds:
        trades = bt_threshold(candles, sigs, t)
        all_trades[t] = trades
        s = stats(trades)
        if not s:
            print(f"  >= {t:3d}  |  <3   |   -    |    -     |    -    |    -    |    -        |   -")
            continue
        sc = s["sh"] * (1 if s["wr"] > 45 else .5) / max(s["mdd"], .05)
        flag = "  <- OPTIMAL" if sc > best_score and s["n"] >= 5 else ""
        if sc > best_score and s["n"] >= 5:
            best_score = sc; best_thresh = t
        print(f"  >= {t:3d}  | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% | -{s['mdd'] * 100:4.1f}% | {s['sh']:+6.2f} | {s['net_eur']:+10.0f} EUR | {s['sl_pct']:4.0f}%{flag}")

    print(f"\n  SL = 1.8xATR | TP1 = 1.0xR (+BE) | TP2 = 2.5xR | TP3 = 5.0xR | max 72h/trade")

    # ── Detail du seuil optimal ───────────────────────────────────────────────
    best_trades = all_trades.get(best_thresh, [])
    s = stats(best_trades)
    if s:
        print(f"\n{'═' * 70}")
        print(f"  DETAIL — Seuil >= {best_thresh} (meilleur compromis)")
        print(f"{'═' * 70}")
        print(f"  Nb trades           : {s['n']}")
        print(f"  Win rate            : {s['wr']:.1f}%")
        print(f"  P&L moyen / trade   : {s['avg']:+.2f}%  ({s['avg_eur']:+.0f} EUR)")
        print(f"  P&L median / trade  : {s['med']:+.2f}%")
        print(f"  Meilleur trade      : {s['best_eur']:+.0f} EUR")
        print(f"  Pire trade          : {s['worst_eur']:+.0f} EUR")
        print(f"  Max Drawdown        : -{s['mdd'] * 100:.1f}%")
        print(f"  Sharpe              : {s['sh']:+.2f}")
        print(f"  Duree moy. trade    : {s['avg_bars']:.0f}h")
        print(f"  Stop loss touches   : {s['sl_pct']:.0f}%")
        print(f"  Breakeven touches   : {s['be_pct']:.0f}%")
        print(f"  TP3 complet         : {s['tp3_pct']:.0f}%")
        print(f"  Net P&L annuel      : {s['net_eur']:+.0f} EUR  (sur {TRADE_SIZE} EUR/trade)")

    # ── Analyses complementaires ──────────────────────────────────────────────
    if best_trades:
        analyse_direction(best_trades)
        analyse_regimes(best_trades)
        analyse_score_quality(best_trades)
        analyse_hours(best_trades)
        analyse_monthly(candles, best_trades)

    print(f"\n{'=' * 70}")
    print(f"  RESUME — Seuil recommande : >= {best_thresh}")
    print(f"  Capital requis suggere    : {TRADE_SIZE} EUR x 3 trades simultanes max = {TRADE_SIZE * 3} EUR")
    print(f"  Strategie                 : E (TP1=1.0xR + Breakeven immediat)")
    print(f"{'=' * 70}\n")
    print("  Note : donnees synthetiques (GBM + regimes). Tendances relatives fiables,")
    print("  chiffres absolus a valider sur donnees reelles Binance.")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    run()
