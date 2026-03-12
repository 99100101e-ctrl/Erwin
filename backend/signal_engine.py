"""
Signal engine for BTC Trading Advisor.
Implements ultra-precise signal logic with false-signal protection.
"""
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone


class SignalEngine:
    def __init__(self):
        self.last_signal_time: Dict[str, float] = {}  # "BUY" or "SELL" -> timestamp
        self.consecutive_signal: Dict[str, int] = {}  # signal_type -> count
        self.signal_history: List[Dict] = []
        self.max_history = 20
        self._pending_signal: Optional[str] = None  # signal waiting for 2nd confirmation
        self._pending_score: int = 0
        self._pending_count: int = 0

    def evaluate(self, indicators: Dict, current_price: float) -> Dict:
        """
        Evaluate all conditions and return signal dict.
        Returns: {
            signal: "STRONG_BUY" | "STRONG_SELL" | "MODERATE_BUY" | "MODERATE_SELL" | "HOLD" | "WAIT",
            score: 0-100,
            confidence: "High" | "Medium" | "Low",
            conditions_met: [...],
            conditions_failed: [...],
            stop_loss: float | None,
            tp1: float | None,
            tp2: float | None,
            tp3: float | None,
            risk_reward: float | None,
            reasoning: str,
            suppressed: bool,
            suppress_reason: str | None,
        }
        """
        now = time.time()
        utc_hour = datetime.now(timezone.utc).hour

        # Low volume window protection (00:00-06:00 UTC)
        if 0 <= utc_hour < 6:
            return self._build_suppressed("Low volume window (00:00-06:00 UTC)")

        # ATR volatility check (done before conditions)
        atr_pct = indicators.get("atr_pct")

        # --- Evaluate BUY conditions ---
        buy_conds, buy_met, buy_failed = self._check_buy_conditions(indicators, current_price, atr_pct)
        buy_score = len(buy_met) * 10

        # --- Evaluate SELL conditions ---
        sell_conds, sell_met, sell_failed = self._check_sell_conditions(indicators, current_price, atr_pct)
        sell_score = len(sell_met) * 10

        # Determine dominant direction
        if buy_score >= sell_score:
            score = buy_score
            direction = "BUY"
            conditions_met = buy_met
            conditions_failed = buy_failed
        else:
            score = sell_score
            direction = "SELL"
            conditions_met = sell_met
            conditions_failed = sell_failed

        # ATR extreme volatility suppression (still calculate but warn)
        volatility_extreme = atr_pct is not None and atr_pct > 2.5

        # Titan-style bonus: liquidity sweep adds +10 to the dominant direction
        sweep = indicators.get("sweep_1h") or {}
        if sweep.get("detected"):
            sweep_dir = sweep.get("direction")
            if (direction == "BUY" and sweep_dir == "bullish") or \
               (direction == "SELL" and sweep_dir == "bearish"):
                score = min(100, score + 10)
                conditions_met = conditions_met + [f"💎 Liquidity sweep ({sweep_dir})"]

        # Determine signal type
        if score >= 100:
            raw_signal = f"STRONG_{direction}"
        elif score >= 60:
            raw_signal = f"MODERATE_{direction}"
        else:
            raw_signal = "HOLD"

        # False signal protection: no repeat same direction within 4h
        if direction in ("BUY", "SELL"):
            last_same = self.last_signal_time.get(direction, 0)
            if (now - last_same) < 4 * 3600 and score >= 60:
                return self._build_suppressed(
                    f"Repeat {direction} signal too soon (< 4h since last)",
                    score=score,
                    conditions_met=conditions_met,
                    conditions_failed=conditions_failed,
                    direction=direction,
                )

        # ATR extreme suppression
        if volatility_extreme and score >= 60:
            return self._build_suppressed(
                f"ATR {atr_pct:.2f}% > 2.5% — Extreme volatility",
                score=score,
                conditions_met=conditions_met,
                conditions_failed=conditions_failed,
                direction=direction,
                volatility_extreme=True,
            )

        # 2-consecutive confirmation (60s cadence assumed from caller)
        if score >= 100:
            if self._pending_signal == raw_signal:
                self._pending_count += 1
            else:
                self._pending_signal = raw_signal
                self._pending_count = 1

            if self._pending_count < 2:
                return self._build_suppressed(
                    "Awaiting 2nd consecutive confirmation...",
                    score=score,
                    conditions_met=conditions_met,
                    conditions_failed=conditions_failed,
                    direction=direction,
                    awaiting_confirm=True,
                )
        else:
            self._pending_signal = None
            self._pending_count = 0

        # Calculate risk management
        risk = self._calculate_risk(direction, current_price, indicators)

        # Validate minimum R/R
        if risk and risk.get("risk_reward") and risk["risk_reward"] < 1.5 and score >= 60:
            return self._build_suppressed(
                f"R/R {risk['risk_reward']:.2f} < 1.5 minimum",
                score=score,
                conditions_met=conditions_met,
                conditions_failed=conditions_failed,
                direction=direction,
            )

        # Build final signal
        if score < 60:
            signal = "HOLD"
            confidence = "Low"
        elif score < 80:
            signal = f"MODERATE_{direction}"
            confidence = "Medium"
        else:
            signal = f"STRONG_{direction}"
            confidence = "High"

        if signal != "HOLD":
            self.last_signal_time[direction] = now
            self._pending_signal = None
            self._pending_count = 0
            self._add_to_history(signal, score, current_price, conditions_met)

        result = {
            "signal": signal,
            "score": score,
            "confidence": confidence,
            "direction": direction,
            "conditions_met": conditions_met,
            "conditions_failed": conditions_failed,
            "volatility_extreme": volatility_extreme,
            "suppressed": False,
            "suppress_reason": None,
            "atr_pct": atr_pct,
        }
        if risk:
            result.update(risk)
        else:
            result.update({"stop_loss": None, "tp1": None, "tp2": None, "tp3": None, "risk_reward": None})

        result["reasoning"] = self._build_reasoning(signal, conditions_met, conditions_failed, score)
        return result

    # -----------------------------------------------------------------------
    def _check_buy_conditions(
        self, ind: Dict, price: float, atr_pct: Optional[float]
    ) -> Tuple[List, List, List]:
        met = []
        failed = []

        rsi_1h = ind.get("rsi_1h")
        rsi_4h = ind.get("rsi_4h")
        stoch = ind.get("stoch_rsi_1h")
        macd_1h = ind.get("macd_1h")
        bb_1h = ind.get("bb_1h")
        emas_1h = ind.get("emas_1h") or {}
        emas_4h = ind.get("emas_4h") or {}
        vol_ratio = ind.get("volume_ratio_1h")
        sr = ind.get("sr_1h") or {}

        # 1. RSI oversold
        cond = "RSI-14 < 32 (1h) AND RSI-14 < 38 (4h)"
        if rsi_1h is not None and rsi_4h is not None and rsi_1h < 32 and rsi_4h < 38:
            met.append(cond)
        else:
            v1 = f"{rsi_1h:.1f}" if rsi_1h else "N/A"
            v4 = f"{rsi_4h:.1f}" if rsi_4h else "N/A"
            failed.append(f"{cond} [{v1}/{v4}]")

        # 2. Stochastic RSI oversold
        cond = "Stoch RSI < 25 (oversold)"
        if stoch and stoch["k"] < 25:
            met.append(cond)
        else:
            v = f"{stoch['k']:.1f}" if stoch else "N/A"
            failed.append(f"{cond} [{v}]")

        # 3. MACD bullish crossover
        cond = "MACD bullish crossover (1h)"
        if macd_1h and macd_1h.get("bullish_cross"):
            met.append(cond)
        else:
            failed.append(cond)

        # 4. Price near lower Bollinger Band
        cond = "Price within 0.5% of lower BB"
        if bb_1h and price <= bb_1h["lower"] * 1.005:
            met.append(cond)
        else:
            v = f"{bb_1h['lower']:.0f}" if bb_1h else "N/A"
            failed.append(f"{cond} [lower={v}]")

        # 5. EMA alignment
        cond = "EMA20 > EMA50 OR price on EMA200"
        ema20 = emas_1h.get("ema20")
        ema50 = emas_1h.get("ema50")
        ema200 = emas_1h.get("ema200")
        bull_ema = (ema20 and ema50 and ema20 > ema50) or (
            ema200 and price >= ema200 * 0.998 and price <= ema200 * 1.005
        )
        if bull_ema:
            met.append(cond)
        else:
            failed.append(cond)

        # 6. High volume
        cond = "Volume > 130% of 20-period average"
        if vol_ratio and vol_ratio >= 1.30:
            met.append(cond)
        else:
            v = f"{vol_ratio*100:.0f}%" if vol_ratio else "N/A"
            failed.append(f"{cond} [{v}]")

        # 7. Price above key support
        cond = "Price above key support level"
        support = sr.get("support")
        if support and price > support:
            met.append(cond)
        else:
            v = f"{support:.0f}" if support else "N/A"
            failed.append(f"{cond} [support={v}]")

        # 8. 4h trend bullish
        cond = "4h EMA20 > EMA50 (bullish trend)"
        ema20_4h = emas_4h.get("ema20")
        ema50_4h = emas_4h.get("ema50")
        if ema20_4h and ema50_4h and ema20_4h > ema50_4h:
            met.append(cond)
        else:
            failed.append(cond)

        # 8b. ADX trending (bonus condition — raises score without requiring it)
        adx_data = ind.get("adx_1h") or {}
        cond = "ADX > 25 (trending market)"
        if adx_data.get("trending") and adx_data.get("plus_di", 0) > adx_data.get("minus_di", 0):
            met.append(cond)
        else:
            v = f"{adx_data.get('adx', 'N/A')}"
            failed.append(f"{cond} [ADX={v}]")

        # 9 & 10 are handled at signal level (consecutive, ATR)
        # Add them as auto conditions for scoring
        cond = "2 consecutive confirmations"
        if self._pending_signal and "BUY" in self._pending_signal and self._pending_count >= 1:
            met.append(cond)
        else:
            failed.append(cond)

        cond = "ATR ≤ 2.5% (manageable volatility)"
        if atr_pct is not None and atr_pct <= 2.5:
            met.append(cond)
        else:
            v = f"{atr_pct:.2f}%" if atr_pct else "N/A"
            failed.append(f"{cond} [{v}]")

        return [], met, failed

    def _check_sell_conditions(
        self, ind: Dict, price: float, atr_pct: Optional[float]
    ) -> Tuple[List, List, List]:
        met = []
        failed = []

        rsi_1h = ind.get("rsi_1h")
        rsi_4h = ind.get("rsi_4h")
        stoch = ind.get("stoch_rsi_1h")
        macd_1h = ind.get("macd_1h")
        bb_1h = ind.get("bb_1h")
        emas_1h = ind.get("emas_1h") or {}
        emas_4h = ind.get("emas_4h") or {}
        vol_ratio = ind.get("volume_ratio_1h")
        sr = ind.get("sr_1h") or {}

        # 1. RSI overbought
        cond = "RSI-14 > 68 (1h) AND RSI-14 > 62 (4h)"
        if rsi_1h is not None and rsi_4h is not None and rsi_1h > 68 and rsi_4h > 62:
            met.append(cond)
        else:
            v1 = f"{rsi_1h:.1f}" if rsi_1h else "N/A"
            v4 = f"{rsi_4h:.1f}" if rsi_4h else "N/A"
            failed.append(f"{cond} [{v1}/{v4}]")

        # 2. Stochastic RSI overbought
        cond = "Stoch RSI > 75 (overbought)"
        if stoch and stoch["k"] > 75:
            met.append(cond)
        else:
            v = f"{stoch['k']:.1f}" if stoch else "N/A"
            failed.append(f"{cond} [{v}]")

        # 3. MACD bearish crossover
        cond = "MACD bearish crossover (1h)"
        if macd_1h and macd_1h.get("bearish_cross"):
            met.append(cond)
        else:
            failed.append(cond)

        # 4. Price near upper Bollinger Band
        cond = "Price within 0.5% of upper BB"
        if bb_1h and price >= bb_1h["upper"] * 0.995:
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

        # 6. High volume
        cond = "Volume > 130% of 20-period average"
        if vol_ratio and vol_ratio >= 1.30:
            met.append(cond)
        else:
            v = f"{vol_ratio*100:.0f}%" if vol_ratio else "N/A"
            failed.append(f"{cond} [{v}]")

        # 7. Price below key resistance
        cond = "Price below key resistance level"
        resistance = sr.get("resistance")
        if resistance and price < resistance:
            met.append(cond)
        else:
            v = f"{resistance:.0f}" if resistance else "N/A"
            failed.append(f"{cond} [resistance={v}]")

        # 8. 4h trend bearish
        cond = "4h EMA20 < EMA50 (bearish trend)"
        ema20_4h = emas_4h.get("ema20")
        ema50_4h = emas_4h.get("ema50")
        if ema20_4h and ema50_4h and ema20_4h < ema50_4h:
            met.append(cond)
        else:
            failed.append(cond)

        # 8b. ADX trending bearish
        adx_data = ind.get("adx_1h") or {}
        cond = "ADX > 25 (trending market)"
        if adx_data.get("trending") and adx_data.get("minus_di", 0) > adx_data.get("plus_di", 0):
            met.append(cond)
        else:
            v = f"{adx_data.get('adx', 'N/A')}"
            failed.append(f"{cond} [ADX={v}]")

        # 9. Consecutive
        cond = "2 consecutive confirmations"
        if self._pending_signal and "SELL" in self._pending_signal and self._pending_count >= 1:
            met.append(cond)
        else:
            failed.append(cond)

        # 10. ATR
        cond = "ATR ≤ 2.5% (manageable volatility)"
        if atr_pct is not None and atr_pct <= 2.5:
            met.append(cond)
        else:
            v = f"{atr_pct:.2f}%" if atr_pct else "N/A"
            failed.append(f"{cond} [{v}]")

        return [], met, failed

    def _calculate_risk(self, direction: str, price: float, ind: Dict) -> Optional[Dict]:
        atr = ind.get("atr_1h")
        if not atr or price <= 0:
            return None

        sl_dist = atr * 1.8
        if direction == "BUY":
            stop_loss = round(price - sl_dist, 2)
            risk_amt = price - stop_loss
            tp1 = round(price + risk_amt * 1.5, 2)
            tp2 = round(price + risk_amt * 2.5, 2)
            tp3 = round(price + risk_amt * 4.0, 2)
            rr = round(risk_amt * 1.5 / risk_amt, 2) if risk_amt > 0 else 0
        else:
            stop_loss = round(price + sl_dist, 2)
            risk_amt = stop_loss - price
            tp1 = round(price - risk_amt * 1.5, 2)
            tp2 = round(price - risk_amt * 2.5, 2)
            tp3 = round(price - risk_amt * 4.0, 2)
            rr = round(risk_amt * 1.5 / risk_amt, 2) if risk_amt > 0 else 0

        # Distances as %
        sl_pct = round(abs(price - stop_loss) / price * 100, 2)
        tp1_pct = round(abs(tp1 - price) / price * 100, 2)
        tp2_pct = round(abs(tp2 - price) / price * 100, 2)
        tp3_pct = round(abs(tp3 - price) / price * 100, 2)

        return {
            "stop_loss": stop_loss,
            "sl_pct": sl_pct,
            "tp1": tp1,
            "tp1_pct": tp1_pct,
            "tp2": tp2,
            "tp2_pct": tp2_pct,
            "tp3": tp3,
            "tp3_pct": tp3_pct,
            "risk_reward": rr,
            "entry_price": price,
        }

    def _build_suppressed(
        self,
        reason: str,
        score: int = 0,
        conditions_met: List = None,
        conditions_failed: List = None,
        direction: str = "BUY",
        volatility_extreme: bool = False,
        awaiting_confirm: bool = False,
    ) -> Dict:
        return {
            "signal": "WAIT",
            "score": score,
            "confidence": "Low",
            "direction": direction,
            "conditions_met": conditions_met or [],
            "conditions_failed": conditions_failed or [],
            "suppressed": True,
            "suppress_reason": reason,
            "volatility_extreme": volatility_extreme,
            "awaiting_confirm": awaiting_confirm,
            "stop_loss": None,
            "tp1": None,
            "tp2": None,
            "tp3": None,
            "risk_reward": None,
            "reasoning": reason,
        }

    def _add_to_history(self, signal: str, score: int, price: float, conditions: List):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "signal": signal,
            "score": score,
            "price": price,
            "conditions_count": len(conditions),
        }
        self.signal_history.insert(0, entry)
        if len(self.signal_history) > self.max_history:
            self.signal_history = self.signal_history[: self.max_history]

    def _build_reasoning(
        self, signal: str, met: List, failed: List, score: int
    ) -> str:
        if signal == "HOLD":
            return f"Score {score}/100 — insufficient conditions ({len(met)}/10 met). Top missed: {', '.join(failed[:3])}"
        prefix = "✅" if "BUY" in signal else "🔴"
        return (
            f"{prefix} {signal} — Score {score}/100. "
            f"Conditions met ({len(met)}): {'; '.join(met[:5])}. "
            f"Failed ({len(failed)}): {'; '.join(failed[:3])}"
        )
