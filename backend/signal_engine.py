"""
Signal engine for BTC Trading Advisor.
Always evaluates conditions and returns a score, even when trade execution
is suppressed — so the UI always shows progress toward the next signal.
"""
import time
from typing import Dict, List, Optional
from datetime import datetime, timezone


MIN_SCORE = 70          # seuil minimum pour un signal actionnable
EARLY_REGIME_H = 48    # info UI : nb heures pour qu'un regime soit considere etabli (pas de filtre actif)


class SignalEngine:
    def __init__(self):
        self.last_signal_time: Dict[str, float] = {}
        self.signal_history: List[Dict] = []
        self.max_history = 50          # spec: last 50 signals
        self._pending_signal: Optional[str] = None
        self._pending_count: int = 0
        self._last_trend: Optional[str] = None   # "bull" | "bear" | "sideways"
        self._trend_since: float = 0.0           # timestamp du debut du regime actuel

    # ─────────────────────────────────────────────────────────────────────────
    def evaluate(self, indicators: Dict, current_price: float) -> Dict:
        """
        Always evaluates all conditions and returns a full score dict.
        Suppression flags are advisory only — the score is always visible.
        """
        now = time.time()
        utc_hour = datetime.now(timezone.utc).hour
        atr_pct = indicators.get("atr_pct")

        # ── Evaluate BUY conditions ──────────────────────────────────────────
        _, buy_met, buy_failed = self._check_buy(indicators, current_price, atr_pct)
        buy_score = len(buy_met) * 10

        # ── Evaluate SELL conditions ─────────────────────────────────────────
        _, sell_met, sell_failed = self._check_sell(indicators, current_price, atr_pct)
        sell_score = len(sell_met) * 10

        # ── Dominant direction ───────────────────────────────────────────────
        if buy_score >= sell_score:
            score, direction = buy_score, "BUY"
            conditions_met, conditions_failed = buy_met, buy_failed
        else:
            score, direction = sell_score, "SELL"
            conditions_met, conditions_failed = sell_met, sell_failed

        # ── Liquidity sweep bonus (+10 toward dominant direction) ────────────
        sweep = indicators.get("sweep_1h") or {}
        if sweep.get("detected"):
            sweep_dir = sweep.get("direction")
            if (direction == "BUY" and sweep_dir == "bullish") or \
               (direction == "SELL" and sweep_dir == "bearish"):
                score = min(100, score + 10)
                conditions_met = conditions_met + [f"💎 Liquidity sweep ({sweep_dir})"]

        # ── Titan Sniper bonuses (+10 each, capped at 100) ───────────────────
        msb = indicators.get("msb_1h") or {}
        cvd = indicators.get("cvd_absorption_1h") or {}
        div = indicators.get("rsi_divergence_1h") or {}

        titan_bonuses = []
        if direction == "BUY":
            if msb.get("bullish"):
                titan_bonuses.append("⚔️ MSB/CHoCH (bullish break)")
            if cvd.get("bullish"):
                titan_bonuses.append("🐳 CVD Absorption (whale buying)")
            if div.get("bullish"):
                titan_bonuses.append(f"🌟 RSI Gold Divergence (bullish)")
        else:
            if msb.get("bearish"):
                titan_bonuses.append("⚔️ MSB/CHoCH (bearish break)")
            if cvd.get("bearish"):
                titan_bonuses.append("🐳 CVD Distribution (whale selling)")
            if div.get("bearish"):
                titan_bonuses.append("🌟 RSI Gold Divergence (bearish)")

        for bonus in titan_bonuses:
            score = min(100, score + 10)
            conditions_met = conditions_met + [bonus]

        # Tag as TITAN signal if 2+ Titan bonuses fired at high score
        is_titan = len(titan_bonuses) >= 2 and score >= 80

        volatility_extreme = atr_pct is not None and atr_pct > 2.5

        # ── Trend detection + regime age ─────────────────────────────────────
        trend = self._detect_trend(indicators)
        if trend != self._last_trend:
            self._last_trend = trend
            self._trend_since = now
        trend_age_h = (now - self._trend_since) / 3600  # heures dans le regime actuel
        early_regime = trend_age_h < EARLY_REGIME_H

        # ── Classify raw signal ──────────────────────────────────────────────
        if score >= 100:
            raw_signal = f"STRONG_{direction}"
        elif score >= MIN_SCORE:
            raw_signal = f"MODERATE_{direction}"
        else:
            raw_signal = "HOLD"

        # ── Approach label (shows even while suppressed) ─────────────────────
        if is_titan and score >= 80:
            approach = "titan"
        elif score >= 80:
            approach = "strong"
        elif score >= 50:
            approach = "approaching"
        elif score >= 30:
            approach = "building"
        else:
            approach = "weak"

        # ── SuperTrend ────────────────────────────────────────────────────────
        supertrend = indicators.get("supertrend_1h") or {}
        st_dir     = supertrend.get("direction")   # "UP" | "DOWN" | None
        st_flipped = supertrend.get("flipped", False)

        # ── Suppression checks ────────────────────────────────────────────────
        suppress_reasons = []

        # ── Filtre macro EMA100 daily (stratégie définitive v7) ──────────────
        # BUY  → bloqué si prix ≤ EMA100 daily (macro baissier ou neutre)
        # SELL → bloqué si prix ≥ EMA100 daily (macro haussier ou neutre)
        #
        # Backtest 2 ans réels (v1→v7, 2024-2026) :
        #   EMA100 + ADX>25 + SL×2.0 : N=94 | WR 62.8% | Sharpe +2.78 | MDD -6%
        #   +209€(2024) +637€(2025) +207€(2026) = +1053€ — 3/3 années positives
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

        # ── ADX 1h > 25 : filtre les marchés en range ────────────────────────
        # Sans ADX : Sharpe +1.67, MDD -13.5%
        # Avec ADX>25 : Sharpe +2.78, MDD -6.0%  (amélioration majeure)
        adx_live = indicators.get("adx_1h") or {}
        adx_1h_val = adx_live.get("adx", 0) or 0
        if score >= MIN_SCORE and adx_1h_val < 25:
            suppress_reasons.append(
                f"ADX 1h {adx_1h_val:.1f} < 25 — marché en range (signal peu fiable)"
            )

        if 16 <= utc_hour <= 18:
            suppress_reasons.append(
                "US Open volatile (16h-18h UTC) — 18% WR historique, algos institutionnels"
            )

        # ── Heures françaises : nuit exclue (22h–7h UTC) ─────────────────────
        # 8h-21h UTC = 9h-22h CET (hiver) / 10h-23h CEST (été)
        # Backtest : WR passe de 65.9% (24h) → 55.2% en heures FR
        # Edge principal concentré sur sessions asiatiques — on ne trade pas la nuit
        if not (8 <= utc_hour <= 21):
            suppress_reasons.append(
                f"Hors heures françaises ({utc_hour:02d}h UTC) — trading actif 8h-21h UTC"
            )

        if volatility_extreme and score >= 60:
            suppress_reasons.append(f"Extreme volatility (ATR {atr_pct:.2f}%)")

        last_same = self.last_signal_time.get(direction, 0)
        cooldown_remaining = 0
        if (now - last_same) < 2 * 3600 and score >= 60:
            cooldown_remaining = int(2 * 3600 - (now - last_same))
            m, s = divmod(cooldown_remaining, 60)
            suppress_reasons.append(f"Cooldown {m}m{s:02d}s remaining")

        if score >= 100:
            if self._pending_signal == raw_signal:
                self._pending_count += 1
            else:
                self._pending_signal = raw_signal
                self._pending_count = 1
            if self._pending_count < 2:
                suppress_reasons.append("Awaiting 2nd consecutive confirmation…")
        else:
            self._pending_signal = None
            self._pending_count = 0

        # ── Risk management ──────────────────────────────────────────────────
        risk = self._calculate_risk(direction, current_price, indicators)

        # Stratégie E : TP1=1.0xR → R/R initial = 1.0, acceptable car BE protège le trade
        # Le R/R global reste très favorable (TP2=2.5xR, TP3=5.0xR)
        min_rr = 0.8
        if risk and risk.get("risk_reward") and risk["risk_reward"] < min_rr and score >= 60:
            suppress_reasons.append(f"R/R {risk['risk_reward']:.2f} < {min_rr} minimum")

        suppressed = len(suppress_reasons) > 0

        # ── Confidence & final signal label ──────────────────────────────────
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

        # ── Record to history only for clean (unsuppressed) actionable signals
        if not suppressed and signal_label not in ("HOLD", "WAIT"):
            self.last_signal_time[direction] = now
            self._pending_signal = None
            self._pending_count = 0
            self._add_to_history(signal_label, score, current_price, conditions_met)

        # ── Build response ────────────────────────────────────────────────────
        result = {
            "signal": signal_label,
            "score": score,
            "confidence": confidence,
            "direction": direction,
            "approach": approach,                    # building/approaching/strong/titan
            "is_titan": is_titan,                    # True when 2+ Titan bonuses at score>=80
            "conditions_met": conditions_met,
            "conditions_failed": conditions_failed,
            "conditions_total": len(conditions_met) + len(conditions_failed),
            "volatility_extreme": volatility_extreme,
            "suppressed": suppressed,
            "suppress_reason": "; ".join(suppress_reasons) if suppress_reasons else None,
            "suppress_reasons": suppress_reasons,    # list for multi-reason display
            "cooldown_remaining": cooldown_remaining,
            "atr_pct": atr_pct,
            "trend": trend,                          # "bull" | "bear" | "sideways"
            "trend_age_h": round(trend_age_h, 1),    # heures dans le regime actuel
            "early_regime": early_regime,            # True si < 48h depuis changement tendance
            "supertrend_dir": st_dir,                # "UP" | "DOWN" | None
            "supertrend_flipped": st_flipped,        # True = vient de changer de sens
            "ema100_daily_trend": ema100_trend,      # "bull" | "bear" | "neutral"
            "adx_1h_val": round(adx_1h_val, 1),     # valeur ADX 1h courante
        }
        if risk:
            result.update(risk)
        else:
            result.update({"stop_loss": None, "tp1": None, "tp2": None, "tp3": None, "risk_reward": None})

        result["reasoning"] = self._build_reasoning(signal_label, approach, conditions_met, conditions_failed, score)
        return result

    # ─────────────────────────────────────────────────────────────────────────
    def _detect_trend(self, ind: Dict) -> str:
        """
        Determine le regime de tendance a partir des EMAs 1h.
        bull     : EMA20 > EMA50 > EMA200  (alignement haussier complet)
        bear     : EMA20 < EMA50 < EMA200  (alignement baissier complet)
        sideways : tout autre cas (EMAs entrelacees, pas de direction claire)
        """
        emas = ind.get("emas_1h") or {}
        ema20  = emas.get("ema20")
        ema50  = emas.get("ema50")
        ema200 = emas.get("ema200")
        if not (ema20 and ema50 and ema200):
            return "sideways"
        if ema20 > ema50 > ema200:
            return "bull"
        if ema20 < ema50 < ema200:
            return "bear"
        return "sideways"

    # ─────────────────────────────────────────────────────────────────────────
    def _check_buy(self, ind, price, atr_pct):
        met, failed = [], []

        rsi_1h   = ind.get("rsi_1h")
        rsi_4h   = ind.get("rsi_4h")
        stoch    = ind.get("stoch_rsi_1h")
        macd_1h  = ind.get("macd_1h")
        bb_1h    = ind.get("bb_1h")
        emas_1h  = ind.get("emas_1h") or {}
        emas_4h  = ind.get("emas_4h") or {}
        vol_ratio = ind.get("volume_ratio_1h")
        sr       = ind.get("sr_1h") or {}
        adx_data = ind.get("adx_1h") or {}

        # 1. RSI oversold (1h < 35, 4h < 42)
        cond = "RSI-14 < 35 (1h) AND < 42 (4h)"
        if rsi_1h is not None and rsi_4h is not None and rsi_1h < 35 and rsi_4h < 42:
            met.append(cond)
        else:
            v1 = f"{rsi_1h:.1f}" if rsi_1h else "N/A"
            v4 = f"{rsi_4h:.1f}" if rsi_4h else "N/A"
            failed.append(f"{cond} [{v1}/{v4}]")

        # 2. Stoch RSI oversold
        cond = "Stoch RSI < 25 (oversold)"
        if stoch and stoch["k"] < 25:
            met.append(cond)
        else:
            v = f"{stoch['k']:.1f}" if stoch else "N/A"
            failed.append(f"{cond} [{v}]")

        # 3. MACD bullish crossover
        cond = "MACD bullish crossover"
        if macd_1h and macd_1h.get("bullish_cross"):
            met.append(cond)
        else:
            failed.append(cond)

        # 4. Price near lower BB (within 0.8%)
        cond = "Price within 0.8% of lower BB"
        if bb_1h and price <= bb_1h["lower"] * 1.008:
            met.append(cond)
        else:
            v = f"{bb_1h['lower']:.0f}" if bb_1h else "N/A"
            failed.append(f"{cond} [lower={v}]")

        # 5. EMA alignment bullish
        cond = "EMA20 > EMA50 OR price near EMA200"
        ema20 = emas_1h.get("ema20")
        ema50 = emas_1h.get("ema50")
        ema200 = emas_1h.get("ema200")
        bull_ema = (ema20 and ema50 and ema20 > ema50) or (
            ema200 and ema200 * 0.997 <= price <= ema200 * 1.005)
        if bull_ema:
            met.append(cond)
        else:
            failed.append(cond)

        # 6. Volume spike
        cond = "Volume > 120% of 20-bar avg"
        if vol_ratio and vol_ratio >= 1.20:
            met.append(cond)
        else:
            v = f"{vol_ratio*100:.0f}%" if vol_ratio else "N/A"
            failed.append(f"{cond} [{v}]")

        # 7. Price above support
        cond = "Price above key support"
        support = sr.get("support")
        if support and price > support:
            met.append(cond)
        else:
            v = f"{support:.0f}" if support else "N/A"
            failed.append(f"{cond} [support={v}]")

        # 8. 4h EMA bullish
        cond = "4h EMA20 > EMA50 (bullish trend)"
        e20_4h = emas_4h.get("ema20")
        e50_4h = emas_4h.get("ema50")
        if e20_4h and e50_4h and e20_4h > e50_4h:
            met.append(cond)
        else:
            failed.append(cond)

        # 9. ADX trending with bullish DI alignment
        cond = "ADX > 25 (trending) + DI+ > DI-"
        if adx_data.get("trending") and (adx_data.get("plus_di") or 0) > (adx_data.get("minus_di") or 0):
            met.append(cond)
        else:
            v = f"{adx_data.get('adx', 'N/A')}"
            failed.append(f"{cond} [ADX={v}]")

        # 10. ATR manageable
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

        rsi_1h   = ind.get("rsi_1h")
        rsi_4h   = ind.get("rsi_4h")
        stoch    = ind.get("stoch_rsi_1h")
        macd_1h  = ind.get("macd_1h")
        bb_1h    = ind.get("bb_1h")
        emas_1h  = ind.get("emas_1h") or {}
        emas_4h  = ind.get("emas_4h") or {}
        vol_ratio = ind.get("volume_ratio_1h")
        sr       = ind.get("sr_1h") or {}
        adx_data = ind.get("adx_1h") or {}

        # 1. RSI overbought
        cond = "RSI-14 > 65 (1h) AND > 60 (4h)"
        if rsi_1h is not None and rsi_4h is not None and rsi_1h > 65 and rsi_4h > 60:
            met.append(cond)
        else:
            v1 = f"{rsi_1h:.1f}" if rsi_1h else "N/A"
            v4 = f"{rsi_4h:.1f}" if rsi_4h else "N/A"
            failed.append(f"{cond} [{v1}/{v4}]")

        # 2. Stoch RSI overbought
        cond = "Stoch RSI > 75 (overbought)"
        if stoch and stoch["k"] > 75:
            met.append(cond)
        else:
            v = f"{stoch['k']:.1f}" if stoch else "N/A"
            failed.append(f"{cond} [{v}]")

        # 3. MACD bearish crossover
        cond = "MACD bearish crossover"
        if macd_1h and macd_1h.get("bearish_cross"):
            met.append(cond)
        else:
            failed.append(cond)

        # 4. Price near upper BB
        cond = "Price within 0.8% of upper BB"
        if bb_1h and price >= bb_1h["upper"] * 0.992:
            met.append(cond)
        else:
            v = f"{bb_1h['upper']:.0f}" if bb_1h else "N/A"
            failed.append(f"{cond} [upper={v}]")

        # 5. EMA bearish
        cond = "EMA20 < EMA50 (1h)"
        ema20 = emas_1h.get("ema20")
        ema50 = emas_1h.get("ema50")
        if ema20 and ema50 and ema20 < ema50:
            met.append(cond)
        else:
            failed.append(cond)

        # 6. Volume spike
        cond = "Volume > 120% of 20-bar avg"
        if vol_ratio and vol_ratio >= 1.20:
            met.append(cond)
        else:
            v = f"{vol_ratio*100:.0f}%" if vol_ratio else "N/A"
            failed.append(f"{cond} [{v}]")

        # 7. Price below resistance
        cond = "Price below key resistance"
        resistance = sr.get("resistance")
        if resistance and price < resistance:
            met.append(cond)
        else:
            v = f"{resistance:.0f}" if resistance else "N/A"
            failed.append(f"{cond} [resistance={v}]")

        # 8. 4h EMA bearish
        cond = "4h EMA20 < EMA50 (bearish trend)"
        e20_4h = emas_4h.get("ema20")
        e50_4h = emas_4h.get("ema50")
        if e20_4h and e50_4h and e20_4h < e50_4h:
            met.append(cond)
        else:
            failed.append(cond)

        # 9. ADX trending with bearish DI alignment
        cond = "ADX > 25 (trending) + DI- > DI+"
        if adx_data.get("trending") and (adx_data.get("minus_di") or 0) > (adx_data.get("plus_di") or 0):
            met.append(cond)
        else:
            v = f"{adx_data.get('adx', 'N/A')}"
            failed.append(f"{cond} [ADX={v}]")

        # 10. ATR manageable
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
        Stratégie définitive (backtest v7, 2 ans réels BTC Binance).

        Backtest EMA100daily + ADX>25 + SL×2.0 :
          N=94 trades | WR 62.8% | Sharpe +2.78 | MDD -6.0%
          +209€(2024) +637€(2025) +207€(2026) = +1053€/2ans

        Paramètres optimisés (sweet spot trouvé par granularité SL×1.0→×2.5) :
          SL  = 2.0×ATR  (donne de l'espace — évite SL dans le bruit)
          TP1 = 1.0×R    (=ATR×2.0 — déclenche BE immédiatement)
          TP2 = 2.5×R    (=ATR×5.0)
          TP3 = 5.0×R    (=ATR×10.0 — laisse courir les grands mouvements)
          breakeven_after_tp1 = True
          Répartition : 40% à TP1 | 35% à TP2 | 25% à TP3
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
            "stop_loss": stop_loss,
            "sl_pct":    round(abs(price - stop_loss) / price * 100, 2),
            "tp1": tp1,  "tp1_pct": round(abs(tp1 - price) / price * 100, 2),
            "tp2": tp2,  "tp2_pct": round(abs(tp2 - price) / price * 100, 2),
            "tp3": tp3,  "tp3_pct": round(abs(tp3 - price) / price * 100, 2),
            "risk_reward": 1.0,
            "entry_price": price,
            # Flag pour le frontend et le systeme d'execution
            "breakeven_after_tp1": True,
            "strategy": "BTC62WR",
        }

    # ─────────────────────────────────────────────────────────────────────────
    def _add_to_history(self, signal, score, price, conditions):
        from datetime import datetime, timezone
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "signal": signal,
            "score": score,
            "price": price,
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
