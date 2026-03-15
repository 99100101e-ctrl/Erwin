"""
Backtest Analyse Horaire — BTC Trading Advisor
Questions cles :
  - Quelles heures UTC genèrent les meilleurs signaux ?
  - Faut-il eviter certaines plages (nuit, faible liquidite) ?
  - Les sessions Asia / Europe / US ont-elles des performances differentes ?
"""
from bt_common import (generate_btc_1an, precompute, run_backtest,
                        stats, TRADE_SIZE)
import numpy as np
from collections import defaultdict


# Sessions de trading (UTC)
SESSIONS = {
    "Asie    (00h-08h UTC)": range(0, 8),
    "Europe  (08h-16h UTC)": range(8, 16),
    "US      (16h-24h UTC)": range(16, 24),
}

JOURS = ["Jeu", "Ven", "Sam", "Dim", "Lun", "Mar", "Mer"]  # epoch=Thu


# ─────────────────────────────────────────────────────────────────────────────
# Partie 1 — Performance par session de trading
# ─────────────────────────────────────────────────────────────────────────────

def analyse_sessions(trades):
    print(f"\n{'─' * 70}")
    print("  PARTIE 1 — Performance par session de trading")
    print(f"{'─' * 70}")
    print(f"\n  {'Session':<28} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'Net EUR':>10} | {'SL%':>5}")
    print("  " + "─" * 68)
    for session, hours in SESSIONS.items():
        group = [t for t in trades if t.get("hour", 0) in hours]
        s = stats(group)
        if s:
            flag = "  <- meilleure" if s["net_eur"] == max(
                stats([t for t in trades if t.get("hour", 0) in h])["net_eur"]
                for h in SESSIONS.values()
                if stats([t for t in trades if t.get("hour", 0) in h])
            ) else ""
            print(f"  {session:<28} | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% | {s['net_eur']:+9.0f} EUR | {s['sl_pct']:4.0f}%{flag}")
        else:
            print(f"  {session:<28} |  <3   |   -    |    -     |    -       |   -")


# ─────────────────────────────────────────────────────────────────────────────
# Partie 2 — Classement de chaque heure UTC (0-23)
# ─────────────────────────────────────────────────────────────────────────────

def analyse_heure_par_heure(trades):
    print(f"\n{'─' * 70}")
    print("  PARTIE 2 — Classement heure par heure (0h-23h UTC)")
    print(f"{'─' * 70}")

    by_hour = {}
    for h in range(24):
        group = [t for t in trades if t.get("hour") == h]
        if len(group) >= 3:
            by_hour[h] = (group, stats(group))

    if not by_hour:
        print("  Pas assez de donnees par heure."); return

    ranked = sorted(by_hour.items(), key=lambda x: x[1][1]["net_eur"] if x[1][1] else 0, reverse=True)

    print(f"\n  {'Heure':>7} | {'N':>4} | {'Win%':>6} | {'P&L moy':>8} | {'Net EUR':>10} | Barre")
    print("  " + "─" * 65)
    for h, (group, s) in ranked:
        if not s: continue
        session = "AS" if h < 8 else ("EU" if h < 16 else "US")
        bar = ("█" if s["net_eur"] > 0 else "░") * min(int(abs(s["net_eur"]) / 15), 20)
        print(f"  {h:02d}h [{session}] | {s['n']:4d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% | {s['net_eur']:+9.0f} EUR | {bar}")


# ─────────────────────────────────────────────────────────────────────────────
# Partie 3 — Performance par jour de la semaine
# ─────────────────────────────────────────────────────────────────────────────

def analyse_jour_semaine(trades):
    print(f"\n{'─' * 70}")
    print("  PARTIE 3 — Performance par jour de la semaine")
    print(f"{'─' * 70}")
    print(f"\n  {'Jour':<10} | {'N':>5} | {'Win%':>6} | {'P&L moy':>8} | {'Net EUR':>10} | Barre")
    print("  " + "─" * 62)
    for d in range(7):
        group = [t for t in trades if t.get("dow") == d]
        s = stats(group)
        if s:
            bar = ("█" if s["net_eur"] > 0 else "░") * min(int(abs(s["net_eur"]) / 15), 20)
            print(f"  {JOURS[d]:<10} | {s['n']:5d} | {s['wr']:5.1f}% | {s['avg']:+7.2f}% | {s['net_eur']:+9.0f} EUR | {bar}")
        else:
            print(f"  {JOURS[d]:<10} |  <3   |   -    |    -     |    -")


# ─────────────────────────────────────────────────────────────────────────────
# Partie 4 — Heatmap Heure x Session (ASCII)
# ─────────────────────────────────────────────────────────────────────────────

def heatmap_session_direction(trades):
    print(f"\n{'─' * 70}")
    print("  PARTIE 4 — Win rate par heure et direction (ASCII heatmap)")
    print(f"{'─' * 70}")
    for direction in ["BUY", "SELL"]:
        dir_trades = [t for t in trades if t["direction"] == direction]
        print(f"\n  {direction} :")
        print("  H  : ", end="")
        print("  ".join(f"{h:02d}" for h in range(0, 24, 2)))
        print("  WR : ", end="")
        for h in range(0, 24, 2):
            group = [t for t in dir_trades if t.get("hour") in (h, h+1)]
            if len(group) >= 2:
                wr = sum(1 for t in group if t["pnl_pct"] > 0) / len(group) * 100
                symbol = "██" if wr > 60 else ("▓▓" if wr > 50 else ("░░" if wr > 40 else "  "))
                print(symbol, end=" ")
            else:
                print("?? ", end="")
        print()
        print("       " + "  ".join(["AS"] * 4 + ["EU"] * 4 + ["US"] * 4))
        print("       Legende: ██=WR>60%  ▓▓=50-60%  ░░=40-50%  __=<40%  ??=insuf.")


# ─────────────────────────────────────────────────────────────────────────────
# Partie 5 — Simulation avec filtre horaire (eviter les pires heures)
# ─────────────────────────────────────────────────────────────────────────────

def analyse_filtre_horaire(candles, sigs):
    print(f"\n{'─' * 70}")
    print("  PARTIE 5 — Impact d'un filtre horaire sur les performances")
    print(f"{'─' * 70}")
    trades_all = run_backtest(candles, sigs, thresh=70)
    if not trades_all: return

    # Identifier les heures rentables (net > 0)
    by_hour = defaultdict(list)
    for t in trades_all:
        by_hour[t.get("hour", 0)].append(t["pnl_eur"])
    good_hours = {h for h, pnls in by_hour.items() if sum(pnls) > 0 and len(pnls) >= 3}
    bad_hours  = {h for h, pnls in by_hour.items() if sum(pnls) <= 0 and len(pnls) >= 3}

    trades_good = [t for t in trades_all if t.get("hour") in good_hours]
    trades_bad  = [t for t in trades_all if t.get("hour") in bad_hours]
    trades_sessions = {
        "Asie seulement (00-08h)":    [t for t in trades_all if t.get("hour", 0) < 8],
        "Europe seulement (08-16h)":  [t for t in trades_all if 8 <= t.get("hour", 0) < 16],
        "US seulement (16-24h)":      [t for t in trades_all if t.get("hour", 0) >= 16],
    }

    print(f"\n  {'Filtre':<32} | {'N':>5} | {'Win%':>6} | {'Net EUR':>10} | {'SL%':>5}")
    print("  " + "─" * 62)
    s = stats(trades_all)
    if s: print(f"  {'Aucun filtre (baseline)':<32} | {s['n']:5d} | {s['wr']:5.1f}% | {s['net_eur']:+9.0f} EUR | {s['sl_pct']:4.0f}%")
    s = stats(trades_good)
    if s:
        good_list = sorted(good_hours)
        print(f"  {'Heures rentables seulement':<32} | {s['n']:5d} | {s['wr']:5.1f}% | {s['net_eur']:+9.0f} EUR | {s['sl_pct']:4.0f}%")
        print(f"    -> heures incluses : {good_list}")
    for label, group in trades_sessions.items():
        s = stats(group)
        if s:
            print(f"  {label:<32} | {s['n']:5d} | {s['wr']:5.1f}% | {s['net_eur']:+9.0f} EUR | {s['sl_pct']:4.0f}%")
        else:
            print(f"  {label:<32} |  <3   |   -    |    -       |   -")


# ─────────────────────────────────────────────────────────────────────────────
# Recommandation
# ─────────────────────────────────────────────────────────────────────────────

def recommandation(trades):
    print(f"\n{'=' * 70}")
    print("  RECOMMANDATION — Heures")
    print(f"{'=' * 70}")

    session_stats = {}
    for session, hours in SESSIONS.items():
        group = [t for t in trades if t.get("hour", 0) in hours]
        s = stats(group)
        if s:
            session_stats[session] = s

    if session_stats:
        best = max(session_stats.items(), key=lambda x: x[1]["net_eur"])
        worst = min(session_stats.items(), key=lambda x: x[1]["net_eur"])
        print(f"\n  Meilleure session : {best[0].strip()}  ({best[1]['wr']:.1f}% WR, {best[1]['net_eur']:+.0f} EUR)")
        print(f"  Pire session      : {worst[0].strip()}  ({worst[1]['wr']:.1f}% WR, {worst[1]['net_eur']:+.0f} EUR)")
        if worst[1]["net_eur"] < -50:
            print(f"\n  -> Envisager d'eviter la session {worst[0].strip()} ou de reduire la taille de position.")
        else:
            print("\n  -> Toutes les sessions sont acceptables. Pas de filtre horaire necessaire.")

    print(f"{'=' * 70}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def run():
    print("\n" + "=" * 70)
    print("  BACKTEST ANALYSE HORAIRE — BTC Trading Advisor — 1 an — 2000 EUR/trade")
    print("  Sessions : Asie (00-08h) | Europe (08-16h) | US (16-24h)")
    print("=" * 70)

    candles = generate_btc_1an()
    p0 = candles[200]["close"]; p1 = candles[-1]["close"]
    print(f"\n  BTC simule : ${p0:,.0f} -> ${p1:,.0f}  ({(p1/p0-1)*100:+.1f}%)\n")

    print("  Precompute signaux...")
    sigs = precompute(candles)
    if not sigs:
        print("  Aucun signal. Abandon."); return

    trades = run_backtest(candles, sigs, thresh=70)
    if not trades:
        print("  Aucun trade au seuil 70."); return

    print(f"  {len(trades)} trades total au seuil >= 70")

    analyse_sessions(trades)
    analyse_heure_par_heure(trades)
    analyse_jour_semaine(trades)
    heatmap_session_direction(trades)
    analyse_filtre_horaire(candles, sigs)
    recommandation(trades)


if __name__ == "__main__":
    run()
