"""
bots_lab/apex_bot_v2.py

APEX Bot v2 — Asymétrique BUY/SELL
====================================
Corrections issues du diagnostic v1 :

  ❌ PROBLÈME v1 : BUY côté catastrophique (Sharpe +0.15, WR 48.7%)
     Cause : BOS=20 achète chaque cassure haute dans un fort bull run
             → entrée au TOP de chaque poussée, pullback immédiat → SL

  ✅ CORRECTIONS v2 (BUY uniquement, ne touche pas aux SELL qui marchent bien) :

  1. Filtre 4h RSI > 50 (BUY)
       Calcul RSI sur closes agrégées 4h — n'entre en BUY que si le
       momentum 4h est haussier. Évite d'acheter dans une correction 4h.

  2. Filtre extension EMA50 (BUY)
       Refuse le signal si le prix est trop loin de l'EMA50 (> ext_atr×ATR).
       En bull run fort (Sep-Nov 2024), l'EMA50 est très en dessous →
       signal rejeté. Évite de chaser les breakouts en zone surachetée.

  3. ADX asymétrique
       BUY  : ADX >= 25 (tendance forte requise, pas de faux breakout)
       SELL : ADX >= 18 (tendance faible suffit, confirmation par autres filtres)

  4. Score asymétrique
       BUY  : score >= 3 / 5 confirmateurs
       SELL : score >= 2 / 5 confirmateurs
       → la barre est plus haute pour BUY.

  5. Nouveau confirmateur : MACD Cross (6e confirmateur)
       MACD line croise signal line à la hausse (BUY) ou à la baisse (SELL)
       sur la dernière bougie → momentum de court terme.

━━━ STRATÉGIE COMPLÈTE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  OBLIGATOIRE (tous) : EMA100d aligné + BOS + FR hours
  BUY  seulement    : ADX>=25 + 4h RSI>50 + extension<ext_atr×ATR + score>=3/6
  SELL seulement    : ADX>=18 + score>=2/6

  SL  = 2.0 × ATR
  TP1 = 1.2R → 40%, SL→BE
  TP2 = 2.5R → 35%
  TP3 = 5.0R → 25% (ou timeout 96h)

━━━ USAGE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  python bots_lab/apex_bot_v2.py
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from bt_common import load_real_candles, TRADE_SIZE
from datetime import datetime, timezone
from collections import defaultdict

# ── Réutilise les fonctions de base d'apex_bot ───────────────────────────────
from apex_bot import (
    _ema, _rsi, _atr, _adx, _vol_sma, _daily_ema100_trend,
    _bos, _atr_squeeze, _volume_surge, _rsi_zone, _ema_stack, _engulfing,
    _sim, _stats, _row, _section, _yearly, _monthly, _exits,
    FR_HOURS, SEP, HDR
)

# ══════════════════════════════════════════════════════════════════════════════
#  NOUVEAUX INDICATEURS v2
# ══════════════════════════════════════════════════════════════════════════════

def _macd(closes, fast=12, slow=26, signal=9):
    """
    MACD — retourne (macd_line, signal_line) pour chaque bougie.
    macd_line = EMA_fast − EMA_slow
    signal    = EMA9(macd_line)
    """
    n       = len(closes)
    ema_f   = _ema(closes, fast)
    ema_s   = _ema(closes, slow)
    macd_l  = [None] * n
    for i in range(n):
        if ema_f[i] is not None and ema_s[i] is not None:
            macd_l[i] = ema_f[i] - ema_s[i]
    # Signal = EMA9 of macd_line
    valid_idx = next((i for i, v in enumerate(macd_l) if v is not None), n)
    sig_vals  = [v for v in macd_l if v is not None]
    sig_ema   = _ema(sig_vals, signal) if len(sig_vals) >= signal else [None] * len(sig_vals)
    sig_line  = [None] * n
    vi = 0
    for i in range(valid_idx, n):
        if vi < len(sig_ema):
            sig_line[i] = sig_ema[vi]
        vi += 1
    return macd_l, sig_line


def _rsi4h(candles):
    """
    RSI 14 calculé sur closes 4h (agrégées depuis 1h).
    Retourne une liste de même longueur que candles (valeur du 4h en cours).
    """
    n = len(candles)
    # Prendre le close de chaque 4ème bougie comme close 4h
    closes_4h = [candles[i]["close"] for i in range(0, n, 4)]
    rsi_4h_series = _rsi(closes_4h, 14)
    # Mapper : candle 1h i → close 4h de l'index i//4
    out = []
    for i in range(n):
        idx_4h = min(i // 4, len(rsi_4h_series) - 1)
        out.append(rsi_4h_series[idx_4h])
    return out


def _ema4h(candles, period):
    """
    EMA(period) calculée sur les closes 4h, mappée sur chaque bougie 1h.
    """
    n = len(candles)
    closes_4h = [candles[i]["close"] for i in range(0, n, 4)]
    ema_4h = _ema(closes_4h, period)
    out = []
    for i in range(n):
        idx_4h = min(i // 4, len(ema_4h) - 1)
        out.append(ema_4h[idx_4h])
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  NOUVEAUX SETUPS v2
# ══════════════════════════════════════════════════════════════════════════════

def _macd_cross(macd_l, sig_line, i, direction):
    """
    MACD cross directionnel : croisement sur la bougie i−1→i.
    BUY  : macd croise signal à la hausse (macd[i-1] < sig[i-1] et macd[i] > sig[i])
    SELL : macd croise signal à la baisse
    """
    if i < 1:
        return False
    m0, m1 = macd_l[i - 1], macd_l[i]
    s0, s1 = sig_line[i - 1], sig_line[i]
    if None in (m0, m1, s0, s1):
        return False
    if direction == "BUY":
        return m0 < s0 and m1 > s1
    else:
        return m0 > s0 and m1 < s1


def _buy_not_extended(price, ema50_val, atr_val, max_atr=5.0):
    """
    Filtre extension (BUY seulement) :
    Refuse si le prix est à plus de max_atr × ATR au-dessus de l'EMA50.
    Évite les entrées BUY en zone très surachetée / loin de la valeur fair.
    """
    if ema50_val is None or atr_val <= 0:
        return True   # pas de donnée → laisser passer
    dist = (price - ema50_val) / atr_val
    return dist <= max_atr


def _rsi4h_bull(rsi4h, i):
    """4h RSI > 50 → momentum 4h haussier."""
    return rsi4h[i] > 50.0


def _rsi4h_bear(rsi4h, i):
    """4h RSI < 50 → momentum 4h baissier."""
    return rsi4h[i] < 50.0


# ══════════════════════════════════════════════════════════════════════════════
#  PRECOMPUTE v2
# ══════════════════════════════════════════════════════════════════════════════

def precompute_v2(candles):
    """Calcule tous les indicateurs APEX v2."""
    print(f"  Calcul indicateurs APEX v2 ({len(candles)} bougies 1h)...", end="", flush=True)
    closes = [c["close"] for c in candles]
    macd_l, sig_line = _macd(closes)
    ind = {
        "ema20":    _ema(closes, 20),
        "ema50":    _ema(closes, 50),
        "rsi14":    _rsi(closes, 14),
        "atrs":     _atr(candles, 14),
        "adxs":     _adx(candles, 14),
        "vol_sma":  _vol_sma(candles, 20),
        "trend":    _daily_ema100_trend(candles),
        # v2
        "rsi4h":    _rsi4h(candles),
        "ema4h20":  _ema4h(candles, 20),
        "ema4h50":  _ema4h(candles, 50),
        "macd_l":   macd_l,
        "sig_line": sig_line,
    }
    print(" OK")
    return ind


# ══════════════════════════════════════════════════════════════════════════════
#  GÉNÉRATION SIGNAUX v2 (asymétrique BUY/SELL)
# ══════════════════════════════════════════════════════════════════════════════

def run_v2(candles, ind,
           bos_lb=20,
           adx_buy=25,
           adx_sell=20,      # identique à v1 : pas de régression SELL
           score_buy=3,
           score_sell=3,     # même rigueur que v1 best (3/5 → 3/6 avec MACD)
           ext_atr=5.0,
           cooldown_h=3,
           sl_mult=2.0):
    """
    Signaux APEX v2 avec filtres asymétriques BUY/SELL.

    BUY  : EMA100d bull + ADX>=adx_buy + BOS + 4hRSI>50 + non-étendu + score>=score_buy/6
    SELL : EMA100d bear + ADX>=adx_sell + BOS + score>=score_sell/6
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
        if dt.weekday() == 6:        # dimanche : évité
            continue

        for direction in ("BUY", "SELL"):

            # ── 1. EMA100d macro ──────────────────────────────────────────
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

            # ── 3. BOS obligatoire ────────────────────────────────────────
            if not _bos(candles, i, direction, bos_lb):
                continue

            # ── 4. Filtres exclusifs BUY (v2) ─────────────────────────────
            if direction == "BUY":
                # 4a. 4h RSI doit être > 50 (momentum 4h haussier)
                if not _rsi4h_bull(ind["rsi4h"], i):
                    continue
                # 4b. Prix pas trop étendu au-dessus de l'EMA50
                price = candles[i]["close"]
                if not _buy_not_extended(price, ind["ema50"][i], ind["atrs"][i], ext_atr):
                    continue

            # ── Cooldown ──────────────────────────────────────────────────
            if cooldown_h > 0 and (ts - last_ts[direction]) < cooldown_h * 3600:
                continue

            # ── 5. Scoring 6 confirmateurs ────────────────────────────────
            score = 0
            if _atr_squeeze(ind["atrs"],   i):                           score += 1
            if _volume_surge(candles, ind["vol_sma"], i):                score += 1
            if _rsi_zone(ind["rsi14"],     i, direction):                score += 1
            if _ema_stack(ind["ema20"],    ind["ema50"], i, direction):  score += 1
            if _engulfing(candles,         i, direction):                score += 1
            if _macd_cross(ind["macd_l"],  ind["sig_line"], i, direction): score += 1

            s_min = score_buy if direction == "BUY" else score_sell
            if score < s_min:
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
    print("  APEX Bot v2 — Asymétrique BUY/SELL")
    print("  4h RSI | Extension filter | ADX asymétrique | MACD cross | score asymétrique")
    print("=" * 108)

    candles = load_real_candles()
    n_years = (candles[-1]["ts"] - candles[0]["ts"]) / (365.25 * 86400)
    n_weeks = n_years * 52
    print(f"  Durée : {n_years:.1f} an(s)  ({n_weeks:.0f} semaines)\n")

    ind = precompute_v2(candles)

    # ── Référence v7 ──────────────────────────────────────────────────────────
    print("  [Référence] Import signaux v7...", end="", flush=True)
    from backtest_2ans import precompute_full
    from backtest_v2 import enrich_signals
    from backtest_v6 import enrich_v6
    from BTCtest1603 import run_bot as _run_v7
    sigs_v7 = enrich_v6(candles, enrich_signals(candles, precompute_full(candles)))
    bot_v7  = _run_v7(candles, sigs_v7, adx1h_min=25)
    print(f" {len(bot_v7)} trades")

    # ── APEX v1 (référence interne) ────────────────────────────────────────────
    print("  [Référence] APEX v1 best (BOS=20, score>=3/5)...", end="", flush=True)
    from apex_bot import precompute_apex, run_apex
    ind_v1  = precompute_apex(candles)
    bot_v1  = run_apex(candles, ind_v1, bos_lb=20, score_min=3)
    print(f" {len(bot_v1)} trades\n")

    mk = {"wr": 0.0, "sh": -999.0}

    # ── Grid search v2 : ext_atr × score_buy ─────────────────────────────────
    _section("GRID SEARCH v2 — ext_atr (extension filter) × score_buy")
    print(HDR)

    best = {"sh": -999.0, "trades": [], "label": "", "params": {}}
    n_min = max(10, int(n_weeks * 0.4))

    for ext in (3.0, 5.0, 7.0):
        for sb in (2, 3, 4):
            label  = f"ext<={ext:.0f}×ATR | buy>={sb}/6 | sell>=3/6 | ADX_buy=25"
            trades = run_v2(candles, ind, ext_atr=ext, score_buy=sb)
            _row(label, trades, mk)
            s = _stats(trades)
            if s and s["sh"] > best["sh"] and s["n"] >= n_min:
                best = {"sh": s["sh"], "trades": trades, "label": label,
                        "params": {"ext_atr": ext, "score_buy": sb}}

    # Fallback
    if not best["trades"]:
        for ext in (3.0, 5.0, 7.0):
            for sb in (2, 3, 4):
                trades = run_v2(candles, ind, ext_atr=ext, score_buy=sb)
                s = _stats(trades)
                if s and s["sh"] > best["sh"]:
                    best = {"sh": s["sh"], "trades": trades,
                            "label": f"ext<={ext:.0f}×ATR | buy>={sb}/6 | sell>=3/6 | ADX_buy=25",
                            "params": {"ext_atr": ext, "score_buy": sb}}

    # ── Comparatif v1 / v2 / v7 ──────────────────────────────────────────────
    _section("COMPARATIF — APEX v2 ★ vs APEX v1 vs Bot v7")
    print(HDR)
    mk2 = {"wr": 0.0, "sh": -999.0}
    _row("v7     — EMA100d + ADX>=25 + HeuresFR (référence)",  bot_v7,        mk2)
    _row("APEX v1— BOS=20 | score>=3/5",                       bot_v1,        mk2)
    _row(f"APEX v2★ — {best['label']}",                        best["trades"], mk2)

    bt = best["trades"]

    # ── Détail BUY / SELL v2 ──────────────────────────────────────────────────
    _section("DÉTAIL BUY vs SELL — APEX v2 ★")
    print(HDR)
    mk3 = {"wr": 0.0, "sh": -999.0}
    buys  = [t for t in bt if t["direction"] == "BUY"]
    sells = [t for t in bt if t["direction"] == "SELL"]
    _row("  BUY  (EMA100d BULL + 4hRSI>50 + extension filtre)", buys,  mk3)
    _row("  SELL (EMA100d BEAR)",                                sells, mk3)

    # ── Comparatif BUY : v1 vs v2 ────────────────────────────────────────────
    _section("FOCUS BUY — v1 vs v2 (correction clé)")
    print(HDR)
    mk4 = {"wr": 0.0, "sh": -999.0}
    _row("  BUY v1 — BOS=20, score>=3/5 (non filtré)",
         [t for t in bot_v1 if t["direction"] == "BUY"],  mk4)
    _row("  BUY v2 — + 4hRSI>50 + ext filter (filtré)",
         buys, mk4)

    # ── Breakdown annuel ──────────────────────────────────────────────────────
    _section("BREAKDOWN ANNUEL — APEX v2 ★")
    _yearly(candles, bt, best["label"])

    s = _stats(bt)
    if s:
        _exits(bt, "APEX v2")
        _monthly(candles, bt, best["label"])

    # ── Résumé ────────────────────────────────────────────────────────────────
    print(f"\n{'=' * 108}")
    print("  RÉSULTAT FINAL — APEX Bot v2")
    if s:
        sv1 = _stats(bot_v1)
        sv7 = _stats(bot_v7)
        freq = s["n"] / n_weeks

        def _banner(label, st):
            if not st:
                print(f"  {label:<12}: N/A")
                return
            print(f"  {label:<12}: {st['n']:3d} trades ({st['n']/(n_weeks or 1):.1f}/sem)"
                  f" | WR {st['wr']:5.1f}% | Sharpe {st['sh']:+.2f}"
                  f" | MDD -{st['mdd']*100:.1f}% | {st['net_eur']:+.0f}€")

        _banner("APEX v2 ★", s)
        _banner("APEX v1  ", sv1)
        _banner("Bot v7   ", sv7)
        print()

        sb  = _stats(buys)
        ss  = _stats(sells)
        if sb: print(f"  BUY  v2 : {sb['n']:3d} trades | WR {sb['wr']:5.1f}% | Sharpe {sb['sh']:+.2f} | {sb['net_eur']:+.0f}€")
        if ss: print(f"  SELL v2 : {ss['n']:3d} trades | WR {ss['wr']:5.1f}% | Sharpe {ss['sh']:+.2f} | {ss['net_eur']:+.0f}€")
        print()
        print(f"  Fréquence : {freq:.1f} trades/semaine  (objectif : 1-5)")
    else:
        print("  Pas assez de trades (< 3)")
    print(f"{'=' * 108}\n")


if __name__ == "__main__":
    main()
