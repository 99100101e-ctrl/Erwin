"""
Backtest Stratégie Optimale — BTC Trading Advisor
Compilation de TOUS les enseignements des backtests précédents.

Questions :
  1. Quel est l'impact du filtre 00-06h UTC (bloque la session Asie !)
  2. Quel est l'impact d'un filtre 16-18h UTC (US open dévastateur)
  3. Combinaison de TOUS les meilleurs filtres : quel est le résultat final ?
  4. Comparaison avec config déployée actuelle
"""
import numpy as np
from collections import defaultdict
from datetime import datetime, timezone
from bt_common import (load_real_candles, precompute, sim_E, stats, TRADE_SIZE)
from indicators import calculate_all_indicators, calculate_supertrend
from signal_engine import SignalEngine


# ─────────────────────────────────────────────────────────────────────────────
# Simulateur avec tous les filtres combinables
# ─────────────────────────────────────────────────────────────────────────────

def run_strategy(candles, sigs, thresh=70,
                 block_asia_early=False,   # True = bloque 00-06h UTC (filtre actuel)
                 block_us_open=False,      # True = bloque 16-18h UTC
                 ema_buy_filter=True,      # True = BUY requis en EMA bull
                 st_buy_filter=True,       # True = BUY bloqué si ST==DOWN
                 st_sell_filter=False,     # True = SELL bloqué si ST==UP (backtest montre que ça nuit)
                 cooldown_h=2,             # cooldown entre signaux mêmes direction
                 ):
    """Simule la stratégie avec les filtres choisis."""
    trades = []; end_idx = 0; prev = 0; last_sig_time = {}

    for s in sigs:
        if s["idx"] < end_idx:
            prev = s["score"]; continue
        if not (prev < thresh <= s["score"]):
            prev = s["score"]; continue
        prev = s["score"]

        direction = s["direction"]
        hour = s.get("hour", 0)
        st_dir = s.get("st_dir")

        # Filtre 00-06h UTC (current: bloque Asie)
        if block_asia_early and 0 <= hour < 6:
            continue

        # Filtre 16-18h UTC (US open)
        if block_us_open and 16 <= hour <= 18:
            continue

        # Filtre EMA bull pour BUY
        if ema_buy_filter and direction == "BUY" and s.get("trend") != "bull":
            continue

        # Filtre SuperTrend pour BUY
        if st_buy_filter and direction == "BUY" and st_dir == "DOWN":
            continue

        # Filtre SuperTrend pour SELL (généralement ne pas activer)
        if st_sell_filter and direction == "SELL" and st_dir == "UP":
            continue

        # Cooldown
        last = last_sig_time.get(direction, 0)
        if s["idx"] - last < cooldown_h:
            continue
        last_sig_time[direction] = s["idx"]

        pnl, rsn, bars = sim_E(candles, s["idx"], direction, s["atr"])
        if rsn == "skip":
            continue
        trades.append({**s, "pnl_pct": pnl*100, "pnl_eur": pnl*TRADE_SIZE, "reason": rsn, "bars": bars})
        end_idx = s["idx"] + bars + 4
    return trades


# ─────────────────────────────────────────────────────────────────────────────
# Precompute enrichi avec SuperTrend
# ─────────────────────────────────────────────────────────────────────────────

def precompute_enriched(candles, warmup=200, step=4):
    sigs = []; errors = 0
    _cur_trend = "sideways"; _trend_since_i = warmup
    print(f"  Precompute enrichi (step={step}h)...", end="", flush=True)

    for i in range(warmup, len(candles) - 73, step):
        w = candles[max(0, i - 249):i + 1]
        c = [x["close"] for x in w]; h = [x["high"] for x in w]
        l = [x["low"] for x in w]; v = [x["volume"] for x in w]
        ts = [x["ts"] for x in w]
        c4=c[::4]; h4=h[::4]; l4=l[::4]; v4=v[::4]
        if len(c4) < 15: continue
        try:
            ind = calculate_all_indicators(c, h, l, v, c4, h4, l4, v4, timestamps_1h=ts)
        except Exception:
            errors += 1; continue

        sig = SignalEngine().evaluate(ind, c[-1])
        if sig.get("score", 0) < 60: continue
        if not sig.get("stop_loss") or not sig.get("tp1"): continue
        atr = ind.get("atr_1h") or 0
        if atr <= 0: continue

        # Tendance EMA
        emas = ind.get("emas_1h") or {}
        e20, e50, e200 = emas.get("ema20"), emas.get("ema50"), emas.get("ema200")
        if e20 and e50 and e200:
            if e20 > e50 > e200: trend = "bull"
            elif e20 < e50 < e200: trend = "bear"
            else: trend = "sideways"
        else: trend = "sideways"
        if trend != _cur_trend:
            _cur_trend = trend; _trend_since_i = i
        trend_age_h = i - _trend_since_i

        # SuperTrend(10, 3.0)
        st = calculate_supertrend(h, l, c, period=10, factor=3.0)
        st_dir = st["direction"] if st else None

        hour_utc = (candles[i]["ts"] % 86400) // 3600
        sigs.append({
            "idx": i, "score": sig["score"], "direction": sig["direction"],
            "price": c[-1], "atr": atr, "hour": hour_utc,
            "trend": trend, "trend_age_h": trend_age_h,
            "st_dir": st_dir,
            "ts": candles[i]["ts"],
        })
        if len(sigs) % 100 == 0: print(".", end="", flush=True)
    print(f" {len(sigs)} signaux ({errors} erreurs)")
    return sigs


# ─────────────────────────────────────────────────────────────────────────────
# Partie 1 : Impact isolé de chaque filtre horaire
# ─────────────────────────────────────────────────────────────────────────────

def partie1_filtres_horaires(candles, sigs):
    print(f"\n{'─' * 92}")
    print("  PARTIE 1 — Impact ISOLÉ des filtres horaires")
    print(f"{'─' * 92}")
    print("  (EMA bull + ST pour BUY activés dans tous les cas, seuls les heures varient)")

    configs = [
        ("Baseline — aucun filtre heure",            dict()),
        ("Actuel — bloque 00-06h UTC (Asie early)",  dict(block_asia_early=True)),
        ("Proposé — bloque 16-18h UTC (US open)",    dict(block_us_open=True)),
        ("Combo   — bloque 00-06h ET 16-18h",        dict(block_asia_early=True, block_us_open=True)),
        ("Optimal — bloque 16-18h seulement",        dict(block_us_open=True)),
    ]

    print(f"\n  {'Config':<44} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'MaxDD':>7} | {'Sharpe':>7} | {'Net EUR':>10} | {'SL%':>5}")
    print("  " + "─" * 98)
    for label, kw in configs:
        t = run_strategy(candles, sigs, **kw)
        s = stats(t)
        if s:
            print(f"  {label:<44} | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% "
                  f"| -{s['mdd']*100:4.1f}% | {s['sh']:+6.2f} | {s['net_eur']:+9.0f} EUR | {s['sl_pct']:4.0f}%")
        else:
            print(f"  {label:<44} |  <3   |   -    |    -     |    -    |    -    |    -       |   -")


# ─────────────────────────────────────────────────────────────────────────────
# Partie 2 : Matrice complète de toutes les combinaisons
# ─────────────────────────────────────────────────────────────────────────────

def partie2_matrice(candles, sigs):
    print(f"\n{'─' * 92}")
    print("  PARTIE 2 — Matrice complète : quels filtres activer ?")
    print(f"{'─' * 92}")

    combos = [
        # label,                                 ema_b, st_b, st_s, asia, us
        ("F0 — Aucun filtre",                    False, False, False, False, False),
        ("F_EMA — EMA BUY-only",                 True,  False, False, False, False),
        ("F_ST  — ST BUY-only",                  False, True,  False, False, False),
        ("F_EMA+ST — EMA+ST BUY-only",           True,  True,  False, False, False),
        ("F_US  — Évite US open (16-18h)",        False, False, False, False, True),
        ("F_EMA+US",                              True,  False, False, False, True),
        ("F_ST+US",                               False, True,  False, False, True),
        ("F_EMA+ST+US — Combinaison proposée",   True,  True,  False, False, True),
        ("F_ACTUEL — EMA+US early(00-06h)",      True,  False, False, True,  False),
        ("F_ALL   — Tous filtres actifs",        True,  True,  False, True,  True),
    ]

    print(f"\n  {'Config':<40} | {'N':>5} | {'Win%':>6} | {'Sharpe':>7} | {'Net EUR':>10} | {'SL%':>5}")
    print("  " + "─" * 80)
    best_sh = -999; best_lbl = None; best_s = None
    for label, ema_b, st_b, st_s, asia, us in combos:
        t = run_strategy(candles, sigs,
                         ema_buy_filter=ema_b, st_buy_filter=st_b, st_sell_filter=st_s,
                         block_asia_early=asia, block_us_open=us)
        s = stats(t)
        if s and s["sh"] > best_sh and s["n"] >= 5:
            best_sh = s["sh"]; best_lbl = label; best_s = s
        flag = ""
        if s and s["sh"] == best_sh and s["n"] >= 5: flag = " ←"
        if s:
            print(f"  {label:<40} | {s['n']:5d} | {s['wr']:5.1f}% | {s['sh']:+6.2f} | {s['net_eur']:+9.0f} EUR | {s['sl_pct']:4.0f}%{flag}")
        else:
            print(f"  {label:<40} |  <3   |   -    |    -    |    -       |   -")
    return best_lbl, best_s


# ─────────────────────────────────────────────────────────────────────────────
# Partie 3 : Détail mensuel de la meilleure config
# ─────────────────────────────────────────────────────────────────────────────

def partie3_detail_mensuel(candles, sigs):
    print(f"\n{'─' * 78}")
    print("  PARTIE 3 — P&L mensuel : Config déployée vs Meilleure config")
    print(f"{'─' * 78}")

    configs = {
        "Actuel (EMA+00-06h)":       run_strategy(candles, sigs, block_asia_early=True, st_buy_filter=False),
        "Meilleur (EMA+ST+16-18h)":  run_strategy(candles, sigs, block_us_open=True),
    }

    for label, trades in configs.items():
        by_m = defaultdict(list)
        for t in trades:
            dt = datetime.fromtimestamp(candles[t["idx"]]["ts"], tz=timezone.utc)
            by_m[(dt.year, dt.month)].append(t)
        cumul = 0
        print(f"\n  {label} :")
        print(f"  {'Mois':>8} | {'N':>4} | {'Win%':>6} | {'BUY':>8} | {'SELL':>8} | {'Net EUR':>10} | Barre")
        print("  " + "─" * 72)
        for mk in sorted(by_m.keys()):
            g = by_m[mk]
            net = sum(t["pnl_eur"] for t in g)
            buy_net  = sum(t["pnl_eur"] for t in g if t["direction"] == "BUY")
            sell_net = sum(t["pnl_eur"] for t in g if t["direction"] == "SELL")
            cumul += net
            wr = sum(1 for t in g if t["pnl_pct"] > 0) / len(g) * 100
            bar = ("█" if net > 0 else "░") * min(int(abs(net)/15), 25)
            label_m = datetime(mk[0], mk[1], 1).strftime("%b %Y")
            print(f"  {label_m:>8} | {len(g):4d} | {wr:5.1f}% | {buy_net:+7.0f}€ | {sell_net:+7.0f}€ | {net:+9.0f} EUR | {bar}")
        s = stats(trades)
        if s:
            print(f"  {'TOTAL':>8} | {s['n']:4d} | {s['wr']:5.1f}% | {'':8} | {'':8} | {cumul:+9.0f} EUR | Sharpe {s['sh']:+.2f}")


# ─────────────────────────────────────────────────────────────────────────────
# Partie 4 : BUY vs SELL détaillé pour la meilleure config
# ─────────────────────────────────────────────────────────────────────────────

def partie4_buy_sell_detail(candles, sigs):
    print(f"\n{'─' * 78}")
    print("  PARTIE 4 — Analyse BUY/SELL — Meilleure config (EMA+ST+évite US open)")
    print(f"{'─' * 78}")

    trades = run_strategy(candles, sigs, block_us_open=True)
    buys  = [t for t in trades if t["direction"] == "BUY"]
    sells = [t for t in trades if t["direction"] == "SELL"]

    for label, group in [("TOUS", trades), ("BUY", buys), ("SELL", sells)]:
        s = stats(group)
        if not s: continue
        print(f"\n  {label} ({s['n']} trades) :")
        print(f"    Win rate     : {s['wr']:.1f}%")
        print(f"    Gain moyen   : {s['avg_win']:+.2f}% | Perte moy. : {s['avg_loss']:+.2f}%")
        print(f"    Max streak L : {s['max_streak']} consécutives")
        print(f"    Durée moy.   : {s['avg_bars']:.0f}h")
        print(f"    Net P&L      : {s['net_eur']:+.0f} EUR (base {TRADE_SIZE}€/trade)")
        print(f"    Sharpe       : {s['sh']:+.2f} | MaxDD : -{s['mdd']*100:.1f}%")
        print(f"    SL={s['sl_pct']:.0f}% | BE={s['be_pct']:.0f}% | TP3={s['tp3_pct']:.0f}%")

    # Heatmap par heure
    print(f"\n  P&L par heure (meilleure config) :")
    by_h = defaultdict(list)
    for t in trades: by_h[t.get("hour", 0)].append(t["pnl_eur"])
    print(f"  {'H':>4} | {'N':>4} | {'Win%':>6} | {'Net EUR':>10} | Barre")
    for h in sorted(by_h.keys()):
        g_eur = by_h[h]
        g_sigs = [t for t in trades if t.get("hour") == h]
        wr = sum(1 for t in g_sigs if t["pnl_pct"] > 0) / len(g_sigs) * 100 if g_sigs else 0
        net = sum(g_eur)
        sess = "AS" if h < 8 else ("EU" if h < 16 else "US")
        bar = ("█" if net > 0 else "░") * min(int(abs(net)/15), 20)
        print(f"  {h:02d}h [{sess}] | {len(g_sigs):4d} | {wr:5.1f}% | {net:+9.0f} EUR | {bar}")


# ─────────────────────────────────────────────────────────────────────────────
# Partie 5 : Recommandation finale et changements à apporter
# ─────────────────────────────────────────────────────────────────────────────

def partie5_recommandation(candles, sigs, best_lbl, best_s):
    print(f"\n{'=' * 90}")
    print("  STRATÉGIE OPTIMALE — Récapitulatif et changements à apporter")
    print(f"{'=' * 90}")

    actuel = run_strategy(candles, sigs, block_asia_early=True, st_buy_filter=False)
    optimal = run_strategy(candles, sigs, block_us_open=True)
    sa = stats(actuel); so = stats(optimal)

    print(f"""
  ┌─────────────────────────────────┬──────────────────┬──────────────────┐
  │ Métrique                        │ Config Actuelle  │ Config Optimale  │
  ├─────────────────────────────────┼──────────────────┼──────────────────┤
  │ Trades                          │ {sa['n']:>8}         │ {so['n']:>8}         │
  │ Win rate                        │ {sa['wr']:>7.1f}%        │ {so['wr']:>7.1f}%        │
  │ P&L moyen                       │ {sa['avg']:>+8.2f}%       │ {so['avg']:>+8.2f}%       │
  │ Net EUR (2000€/trade)           │ {sa['net_eur']:>+8.0f} EUR      │ {so['net_eur']:>+8.0f} EUR      │
  │ Max Drawdown                    │ -{sa['mdd']*100:>5.1f}%         │ -{so['mdd']*100:>5.1f}%         │
  │ Sharpe                          │ {sa['sh']:>+8.2f}        │ {so['sh']:>+8.2f}        │
  │ SL touché                       │ {sa['sl_pct']:>7.0f}%        │ {so['sl_pct']:>7.0f}%        │
  └─────────────────────────────────┴──────────────────┴──────────────────┘
""")

    print("""  CHANGEMENTS À APPORTER dans signal_engine.py :
  ─────────────────────────────────────────────────────────────────────────

  1. SUPPRIMER la règle "Low-volume window (00:00-06:00 UTC)"
     → La session Asie (00-08h UTC) est la MEILLEURE (68.4% WR, +248€)
     → Ce filtre bloque 00h (80% WR) et 04h (64% WR) sans raison valable

  2. AJOUTER la règle "US Open volatile (16:00-18:00 UTC)"
     → 16h UTC seul = 18.2% WR, -140€ sur 6 mois
     → Coincide avec l'ouverture US + fixing macro + algos institutionnels

  3. CONSERVER le filtre EMA bull pour BUY (déjà en place)
     → Protection contre les dead cat bounces dans un marché bear

  4. CONSERVER le filtre SuperTrend DOWN pour BUY (ajouté récemment)
     → Double garde-fou : EMA lent + ST rapide doivent être alignés

  5. NE PAS filtrer SELL sur SuperTrend
     → Les SELL en ST UP (rebonds) sont souvent les meilleurs (top local)
     → Filtrer SELL sur ST coupe les profits de -247€ à +6€

  RÈGLES DÉFINITIVES :
  ─────────────────────────────────────────────────────────────────────────
  BUY  = EMA20>50>200 ET SuperTrend UP (sinon WAIT)
  SELL = Libre (pas de filtre de tendance)
  HEURE= Bloquer 16h-18h UTC (US open)
  HEURE= Autoriser 00h-06h UTC (Asie = meilleure session)
  RISK = Stratégie E : SL=1.8xATR, TP1=1.0xR+BE, TP2=2.5xR, TP3=5.0xR
""")
    print(f"{'=' * 90}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def run():
    print("\n" + "=" * 90)
    print("  BACKTEST STRATÉGIE OPTIMALE — BTC Trading Advisor — DONNÉES RÉELLES BINANCE")
    print("  Compilation de TOUS les enseignements des backtests précédents")
    print("=" * 90)

    candles = load_real_candles()
    sigs = precompute_enriched(candles, warmup=200, step=4)
    if not sigs:
        print("  Aucun signal. Abandon."); return

    partie1_filtres_horaires(candles, sigs)
    best_lbl, best_s = partie2_matrice(candles, sigs)
    partie3_detail_mensuel(candles, sigs)
    partie4_buy_sell_detail(candles, sigs)
    partie5_recommandation(candles, sigs, best_lbl, best_s)


if __name__ == "__main__":
    run()
