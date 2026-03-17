"""
signal_engine_adx20.py — Bot v8 : ADX seuil abaissé à 20
==========================================================
Filtres EXACTEMENT reproduits du backtest backtest_freq.py :

  1. Score >= 70          (inchangé)
  2. EMA100 daily aligné  (inchangé)
  3. ADX 1h >= 20         (↓ vs 25 du bot actuel)
  4. Heures FR : 8h-21h UTC, hors US open (16h-18h)  (inchangé)
  5. Cooldown 2h          (inchangé)
  6. SL×2.0 | TP1=1.0xR | TP2=2.5xR | TP3=5.0xR     (inchangé)

Filtres RETIRÉS vs signal_engine.py (non testés en backtest) :
  ✗ ATR > 2.5% volatility extreme
  ✗ R/R < 0.8 minimum
  ✗ 2ème confirmation consécutive (score=100)

Résultats backtest 2 ans réels (17 Mar 2024 → 17 Mar 2026) :
  N=79 trades | WR 58.2% | Sharpe +1.31 | MDD -10.7% | Net +452€
  vs bot actuel ADX>25 : N=66 | WR 57.6% | Sharpe +1.19 | Net +390€
"""
import time
from typing import Dict, List, Optional
from datetime import datetime, timezone


MIN_SCORE    = 70
EARLY_REGIME_H = 48


class SignalEngine:
    def __init__(self):
        self.last_signal_time: Dict[str, float] = {}
        self.signal_history: List[Dict] = []
        self.max_history = 50
        self._last_trend: Optional[str] = None
        self._trend_since: float = 0.0

    # ─────────────────────────────────────────────────────────────────────────
    def evaluate(self, indicators: Dict, current_price: float) -> Dict:
        """
        Évalue les conditions et retourne un dict complet.
        Filtres de suppression alignés EXACTEMENT sur le backtest.
        """
        now      = time.time()
        utc_hour = datetime.now(timezone.utc).hour
        atr_pct  = indicators.get("atr_pct")

        # ── Score BUY / SELL ─────────────────────────────────────────────────
        _, buy_met,  buy_failed  = self._check_buy(indicators, current_price, atr_pct)
        _, sell_met, sell_failed = self._check_sell(indicators, current_price, atr_pct)
        buy_score  = len(buy_met)  * 10
        sell_score = len(sell_met) * 10

        if buy_score >= sell_score:
            score, direction = buy_score, "BUY"
            conditions_met, conditions_failed = buy_met, buy_failed
        else:
            score, direction = sell_score, "SELL"
            conditions_met, conditions_failed = sell_met, sell_failed

        # ── Liquidity sweep bonus ─────────────────────────────────────────────
        sweep = indicators.get("sweep_1h") or {}
        if sweep.get("detected"):
            sweep_dir = sweep.get("direction")
            if (direction == "BUY"  and sweep_dir == "bullish") or \
               (direction == "SELL" and sweep_dir == "bearish"):
                score = min(100, score + 10)
                conditions_met = conditions_met + [f"💎 Liquidity sweep ({sweep_dir})"]

        # ── Titan Sniper bonuses ──────────────────────────────────────────────
        msb = indicators.get("msb_1h") or {}
        cvd = indicators.get("cvd_absorption_1h") or {}
        div = indicators.get("rsi_divergence_1h") or {}

        titan_bonuses = []
        if direction == "BUY":
            if msb.get("bullish"):  titan_bonuses.append("⚔️ MSB/CHoCH (bullish break)")
            if cvd.get("bullish"):  titan_bonuses.append("🐳 CVD Absorption (whale buying)")
            if div.get("bullish"):  titan_bonuses.append("🌟 RSI Gold Divergence (bullish)")
        else:
            if msb.get("bearish"):  titan_bonuses.append("⚔️ MSB/CHoCH (bearish break)")
            if cvd.get("bearish"):  titan_bonuses.append("🐳 CVD Distribution (whale selling)")
            if div.get("bearish"):  titan_bonuses.append("🌟 RSI Gold Divergence (bearish)")

        for bonus in titan_bonuses:
            score = min(100, score + 10)
            conditions_met = conditions_met + [bonus]

        is_titan = len(titan_bonuses) >= 2 and score >= 80

        # ── Approche ─────────────────────────────────────────────────────────
        if is_titan and score >= 80:    approach = "titan"
        elif score >= 80:               approach = "strong"
        elif score >= 50:               approach = "approaching"
        elif score >= 30:               approach = "building"
        else:                           approach = "weak"

        # ── Trend + régime ────────────────────────────────────────────────────
        trend = self._detect_trend(indicators)
        if trend != self._last_trend:
            self._last_trend  = trend
            self._trend_since = now
        trend_age_h  = (now - self._trend_since) / 3600
        early_regime = trend_age_h < EARLY_REGIME_H

        # ── SuperTrend ────────────────────────────────────────────────────────
        supertrend = indicators.get("supertrend_1h") or {}
        st_dir     = supertrend.get("direction")
        st_flipped = supertrend.get("flipped", False)

        # ── Suppression — UNIQUEMENT les 4 filtres du backtest ───────────────
        suppress_reasons = []

        # 1. EMA100 daily aligné
        # Backtest : EMA100d aligné obligatoire (BUY=bull, SELL=bear)
        ema100_trend = indicators.get("ema100_daily_trend", "neutral")
        if score >= MIN_SCORE:
            if direction == "BUY" and ema100_trend != "bull":
                suppress_reasons.append(
                    f"Macro EMA100d '{ema100_trend}' — BUY bloqué (prix sous EMA100 daily)"
                )
            elif direction == "SELL" and ema100_trend != "bear":
                suppress_reasons.append(
                    f"Macro EMA100d '{ema100_trend}' — SELL bloqué (prix sur EMA100 daily)"
                )

        # 2. ADX 1h >= 20 (seuil backtest)
        # Backtest ADX>=20 : N=79, WR 58.2%, Sharpe +1.31 vs ADX>=25 : N=66, Sharpe +1.19
        adx_live    = indicators.get("adx_1h") or {}
        adx_1h_val  = adx_live.get("adx", 0) or 0
        if score >= MIN_SCORE and adx_1h_val < 20:
            suppress_reasons.append(
                f"ADX 1h {adx_1h_val:.1f} < 20 — marché en range (signal peu fiable)"
            )

        # 3. HeuresFR : 8h-21h UTC, hors US Open (16h-18h)
        # Backtest : HeuresFR activé
        if not (8 <= utc_hour <= 21):
            suppress_reasons.append(
                f"Hors heures françaises ({utc_hour:02d}h UTC) — trading actif 8h-21h UTC"
            )
        if 16 <= utc_hour <= 18:
            suppress_reasons.append(
                "US Open volatile (16h-18h UTC) — algos institutionnels"
            )

        # 4. Cooldown 2h par direction
        # Backtest : cooldown_h=2 (ne bloque aucun trade sur 2 ans, mais conservé)
        last_same         = self.last_signal_time.get(direction, 0)
        cooldown_remaining = 0
        if (now - last_same) < 2 * 3600 and score >= MIN_SCORE:
            cooldown_remaining = int(2 * 3600 - (now - last_same))
            m, s_rem = divmod(cooldown_remaining, 60)
            suppress_reasons.append(f"Cooldown {m}m{s_rem:02d}s remaining")

        # ── Signal final ──────────────────────────────────────────────────────
        suppressed = len(suppress_reasons) > 0

        if suppressed or score < MIN_SCORE:
            confidence = "Low"
        elif score < 80:
            confidence = "Medium"
        else:
            confidence = "High"

        if suppressed:
            signal_label = "WAIT" if score >= MIN_SCORE else "HOLD"
        elif score < MIN_SCORE:
            signal_label = "HOLD"
        elif score < 80:
            signal_label = f"MODERATE_{direction}"
        else:
            signal_label = f"STRONG_{direction}"

        volatility_extreme = atr_pct is not None and atr_pct > 2.5

        # ── Historique (seulement signaux propres non supprimés) ─────────────
        if not suppressed and signal_label not in ("HOLD", "WAIT"):
            self.last_signal_time[direction] = now
            self._add_to_history(signal_label, score, current_price, conditions_met)

        # ── Risk management ───────────────────────────────────────────────────
        risk = self._calculate_risk(direction, current_price, indicators)

        result = {
            "signal":               signal_label,
            "score":                score,
            "confidence":           confidence,
            "direction":            direction,
            "approach":             approach,
            "is_titan":             is_titan,
            "conditions_met":       conditions_met,
            "conditions_failed":    conditions_failed,
            "conditions_total":     len(conditions_met) + len(conditions_failed),
            "volatility_extreme":   volatility_extreme,
            "suppressed":           suppressed,
            "suppress_reason":      "; ".join(suppress_reasons) if suppress_reasons else None,
            "suppress_reasons":     suppress_reasons,
            "cooldown_remaining":   cooldown_remaining,
            "atr_pct":              atr_pct,
            "trend":                trend,
            "trend_age_h":          round(trend_age_h, 1),
            "early_regime":         early_regime,
            "supertrend_dir":       st_dir,
            "supertrend_flipped":   st_flipped,
            "ema100_daily_trend":   ema100_trend,
            "adx_1h_val":           round(adx_1h_val, 1),
        }
        if risk:
            result.update(risk)
        else:
            result.update({"stop_loss": None, "tp1": None, "tp2": None,
                           "tp3": None, "risk_reward": None})

        result["reasoning"] = self._build_reasoning(
            signal_label, approach, conditions_met, conditions_failed, score
        )
        return result

    # ─────────────────────────────────────────────────────────────────────────
    def _detect_trend(self, ind: Dict) -> str:
        emas   = ind.get("emas_1h") or {}
        ema20  = emas.get("ema20")
        ema50  = emas.get("ema50")
        ema200 = emas.get("ema200")
        if not (ema20 and ema50 and ema200):
            return "sideways"
        if ema20 > ema50 > ema200: return "bull"
        if ema20 < ema50 < ema200: return "bear"
        return "sideways"

    # ─────────────────────────────────────────────────────────────────────────
    def _check_buy(self, ind, price, atr_pct):
        met, failed = [], []

        rsi_1h    = ind.get("rsi_1h")
        rsi_4h    = ind.get("rsi_4h")
        stoch     = ind.get("stoch_rsi_1h")
        macd_1h   = ind.get("macd_1h")
        bb_1h     = ind.get("bb_1h")
        emas_1h   = ind.get("emas_1h") or {}
        emas_4h   = ind.get("emas_4h") or {}
        vol_ratio = ind.get("volume_ratio_1h")
        sr        = ind.get("sr_1h") or {}
        adx_data  = ind.get("adx_1h") or {}

        cond = "RSI-14 < 35 (1h) AND < 42 (4h)"
        if rsi_1h is not None and rsi_4h is not None and rsi_1h < 35 and rsi_4h < 42:
            met.append(cond)
        else:
            v1 = f"{rsi_1h:.1f}" if rsi_1h else "N/A"
            v4 = f"{rsi_4h:.1f}" if rsi_4h else "N/A"
            failed.append(f"{cond} [{v1}/{v4}]")

        cond = "Stoch RSI < 25 (oversold)"
        if stoch and stoch["k"] < 25:
            met.append(cond)
        else:
            v = f"{stoch['k']:.1f}" if stoch else "N/A"
            failed.append(f"{cond} [{v}]")

        cond = "MACD bullish crossover"
        if macd_1h and macd_1h.get("bullish_cross"):
            met.append(cond)
        else:
            failed.append(cond)

        cond = "Price within 0.8% of lower BB"
        if bb_1h and price <= bb_1h["lower"] * 1.008:
            met.append(cond)
        else:
            v = f"{bb_1h['lower']:.0f}" if bb_1h else "N/A"
            failed.append(f"{cond} [lower={v}]")

        cond = "EMA20 > EMA50 OR price near EMA200"
        ema20  = emas_1h.get("ema20")
        ema50  = emas_1h.get("ema50")
        ema200 = emas_1h.get("ema200")
        bull_ema = (ema20 and ema50 and ema20 > ema50) or (
            ema200 and ema200 * 0.997 <= price <= ema200 * 1.005)
        if bull_ema:
            met.append(cond)
        else:
            failed.append(cond)

        cond = "Volume > 120% of 20-bar avg"
        if vol_ratio and vol_ratio >= 1.20:
            met.append(cond)
        else:
            v = f"{vol_ratio*100:.0f}%" if vol_ratio else "N/A"
            failed.append(f"{cond} [{v}]")

        cond = "Price above key support"
        support = sr.get("support")
        if support and price > support:
            met.append(cond)
        else:
            v = f"{support:.0f}" if support else "N/A"
            failed.append(f"{cond} [support={v}]")

        cond = "4h EMA20 > EMA50 (bullish trend)"
        e20_4h = emas_4h.get("ema20")
        e50_4h = emas_4h.get("ema50")
        if e20_4h and e50_4h and e20_4h > e50_4h:
            met.append(cond)
        else:
            failed.append(cond)

        cond = "ADX > 25 (trending) + DI+ > DI-"
        if adx_data.get("trending") and (adx_data.get("plus_di") or 0) > (adx_data.get("minus_di") or 0):
            met.append(cond)
        else:
            v = f"{adx_data.get('adx', 'N/A')}"
            failed.append(f"{cond} [ADX={v}]")

        cond = "ATR ≤ 2.5% (manageable)"
        if atr_pct is not None and atr_pct <= 2.5:
            met.append(cond)
        else:
            v = f"{atr_pct:.2f}%" if atr_pct else "N/A"
            failed.append(f"{cond} [{v}]")

        return [], met, failed

    # ─────────────────────────────────────────────────────────────────────────
    def _check_sell(self, ind, price, atr_pct):
        met, failed = [], []

        rsi_1h    = ind.get("rsi_1h")
        rsi_4h    = ind.get("rsi_4h")
        stoch     = ind.get("stoch_rsi_1h")
        macd_1h   = ind.get("macd_1h")
        bb_1h     = ind.get("bb_1h")
        emas_1h   = ind.get("emas_1h") or {}
        emas_4h   = ind.get("emas_4h") or {}
        vol_ratio = ind.get("volume_ratio_1h")
        sr        = ind.get("sr_1h") or {}
        adx_data  = ind.get("adx_1h") or {}

        cond = "RSI-14 > 65 (1h) AND > 60 (4h)"
        if rsi_1h is not None and rsi_4h is not None and rsi_1h > 65 and rsi_4h > 60:
            met.append(cond)
        else:
            v1 = f"{rsi_1h:.1f}" if rsi_1h else "N/A"
            v4 = f"{rsi_4h:.1f}" if rsi_4h else "N/A"
            failed.append(f"{cond} [{v1}/{v4}]")

        cond = "Stoch RSI > 75 (overbought)"
        if stoch and stoch["k"] > 75:
            met.append(cond)
        else:
            v = f"{stoch['k']:.1f}" if stoch else "N/A"
            failed.append(f"{cond} [{v}]")

        cond = "MACD bearish crossover"
        if macd_1h and macd_1h.get("bearish_cross"):
            met.append(cond)
        else:
            failed.append(cond)

        cond = "Price within 0.8% of upper BB"
        if bb_1h and price >= bb_1h["upper"] * 0.992:
            met.append(cond)
        else:
            v = f"{bb_1h['upper']:.0f}" if bb_1h else "N/A"
            failed.append(f"{cond} [upper={v}]")

        cond = "EMA20 < EMA50 (1h)"
        ema20 = emas_1h.get("ema20")
        ema50 = emas_1h.get("ema50")
        if ema20 and ema50 and ema20 < ema50:
            met.append(cond)
        else:
            failed.append(cond)

        cond = "Volume > 120% of 20-bar avg"
        if vol_ratio and vol_ratio >= 1.20:
            met.append(cond)
        else:
            v = f"{vol_ratio*100:.0f}%" if vol_ratio else "N/A"
            failed.append(f"{cond} [{v}]")

        cond = "Price below key resistance"
        resistance = sr.get("resistance")
        if resistance and price < resistance:
            met.append(cond)
        else:
            v = f"{resistance:.0f}" if resistance else "N/A"
            failed.append(f"{cond} [resistance={v}]")

        cond = "4h EMA20 < EMA50 (bearish trend)"
        e20_4h = emas_4h.get("ema20")
        e50_4h = emas_4h.get("ema50")
        if e20_4h and e50_4h and e20_4h < e50_4h:
            met.append(cond)
        else:
            failed.append(cond)

        cond = "ADX > 25 (trending) + DI- > DI+"
        if adx_data.get("trending") and (adx_data.get("minus_di") or 0) > (adx_data.get("plus_di") or 0):
            met.append(cond)
        else:
            v = f"{adx_data.get('adx', 'N/A')}"
            failed.append(f"{cond} [ADX={v}]")

        cond = "ATR ≤ 2.5% (manageable)"
        if atr_pct is not None and atr_pct <= 2.5:
            met.append(cond)
        else:
            v = f"{atr_pct:.2f}%" if atr_pct else "N/A"
            failed.append(f"{cond} [{v}]")

        return [], met, failed

    # ─────────────────────────────────────────────────────────────────────────
    def _calculate_risk(self, direction, price, ind):
        """
        Paramètres SL/TP inchangés (backtest v7 → v8 identiques).

        Backtest ADX>=20, 2 ans réels :
          N=79 | WR 58.2% | Sharpe +1.31 | MDD -10.7% | Net +452€
          SL=42% | BE=33% | TP2+to=14% | TP3=8% | TP1+to=3%

        SL  = 2.0×ATR
        TP1 = 1.0×R  → déclenche BE
        TP2 = 2.5×R
        TP3 = 5.0×R
        """
        atr = ind.get("atr_1h")
        if not atr or price <= 0:
            return None

        sl_dist = atr * 2.0
        if direction == "BUY":
            stop_loss = round(price - sl_dist, 2)
            risk_amt  = price - stop_loss
            tp1 = round(price + risk_amt * 1.0, 2)
            tp2 = round(price + risk_amt * 2.5, 2)
            tp3 = round(price + risk_amt * 5.0, 2)
        else:
            stop_loss = round(price + sl_dist, 2)
            risk_amt  = stop_loss - price
            tp1 = round(price - risk_amt * 1.0, 2)
            tp2 = round(price - risk_amt * 2.5, 2)
            tp3 = round(price - risk_amt * 5.0, 2)

        if risk_amt <= 0:
            return None

        return {
            "stop_loss":          stop_loss,
            "sl_pct":             round(abs(price - stop_loss) / price * 100, 2),
            "tp1": tp1,           "tp1_pct": round(abs(tp1 - price) / price * 100, 2),
            "tp2": tp2,           "tp2_pct": round(abs(tp2 - price) / price * 100, 2),
            "tp3": tp3,           "tp3_pct": round(abs(tp3 - price) / price * 100, 2),
            "risk_reward":        1.0,
            "entry_price":        price,
            "breakeven_after_tp1": True,
            "strategy":           "BTC_ADX20",
        }

    # ─────────────────────────────────────────────────────────────────────────
    def _add_to_history(self, signal, score, price, conditions):
        entry = {
            "timestamp":        datetime.now(timezone.utc).isoformat(),
            "signal":           signal,
            "score":            score,
            "price":            price,
            "conditions_count": len(conditions),
        }
        self.signal_history.insert(0, entry)
        if len(self.signal_history) > self.max_history:
            self.signal_history = self.signal_history[:self.max_history]

    def _build_reasoning(self, signal, approach, met, failed, score):
        total = len(met) + len(failed)
        if signal in ("HOLD", "WAIT"):
            top_missed = ", ".join([f.split(" [")[0] for f in failed[:3]])
            return (
                f"Score {score}/{total*10} — {len(met)}/{total} conditions active. "
                f"Status: {approach}. Missing: {top_missed or 'N/A'}"
            )
        prefix = "✅" if "BUY" in signal else "🔴"
        return (
            f"{prefix} {signal} — Score {score}/{total*10}. "
            f"Met ({len(met)}): {'; '.join(met[:4])}. "
            f"Missing ({len(failed)}): {'; '.join([f.split(' [')[0] for f in failed[:2]])}"
        )
