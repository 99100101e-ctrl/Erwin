"""
Risk Manager — Position sizing dynamique + Circuit breaker.

Fonctionnalités :
  - Position sizing : % du capital risqué par trade (défaut 2%)
  - Circuit breaker : pause après X pertes consécutives ou drawdown max
  - Calcul automatique de la taille de position basée sur la distance SL
  - Filtre de régime de marché (ADX)
  - Score de confiance du signal
"""

import logging
import numpy as np
from typing import Optional

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

class RiskConfig:
    """Paramètres de gestion du risque."""

    def __init__(
        self,
        # Position sizing
        risk_per_trade_pct: float = 2.0,     # % du capital risqué par trade
        max_position_pct: float = 50.0,       # % max du capital par position
        min_position_usd: float = 100.0,      # Position minimum en USD

        # Circuit breaker
        max_consecutive_losses: int = 3,      # Pause après X pertes d'affilée
        max_daily_loss_pct: float = 5.0,      # Pause si perte journalière > X%
        max_drawdown_pct: float = 15.0,       # Pause si drawdown > X%
        cooldown_hours: int = 24,             # Durée de la pause en heures

        # Filtre régime de marché
        adx_min: float = 20.0,               # ADX minimum pour trader (tendance)
        adx_period: int = 14,                 # Période ADX

        # Confiance
        min_confidence: int = 3,              # Score minimum pour entrer (sur 5)
    ):
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_position_pct = max_position_pct
        self.min_position_usd = min_position_usd
        self.max_consecutive_losses = max_consecutive_losses
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.cooldown_hours = cooldown_hours
        self.adx_min = adx_min
        self.adx_period = adx_period
        self.min_confidence = min_confidence


# ══════════════════════════════════════════════════════════════════════════════
# POSITION SIZING
# ══════════════════════════════════════════════════════════════════════════════

def calculate_position_size(
    equity: float,
    entry_price: float,
    sl_price: float,
    config: RiskConfig,
) -> dict:
    """
    Calcule la taille de position optimale basée sur le risque.

    Retourne:
        {
            "position_usd": montant en USD,
            "position_btc": montant en BTC,
            "risk_usd": montant risqué en USD,
            "risk_pct": % du capital risqué,
            "sl_distance_pct": distance du SL en %,
        }
    """
    sl_distance = abs(entry_price - sl_price)
    sl_distance_pct = sl_distance / entry_price * 100

    if sl_distance_pct == 0:
        log.warning("SL distance = 0, impossible de calculer la taille")
        return {"position_usd": 0, "position_btc": 0, "risk_usd": 0,
                "risk_pct": 0, "sl_distance_pct": 0}

    # Montant risqué = equity * risk%
    risk_usd = equity * config.risk_per_trade_pct / 100

    # Position = risk / (SL distance %)
    position_usd = risk_usd / (sl_distance_pct / 100)

    # Caps
    max_pos = equity * config.max_position_pct / 100
    position_usd = min(position_usd, max_pos)
    position_usd = max(position_usd, config.min_position_usd)

    # Recalculer le risque réel après caps
    actual_risk = position_usd * sl_distance_pct / 100
    actual_risk_pct = actual_risk / equity * 100

    position_btc = position_usd / entry_price

    return {
        "position_usd": round(position_usd, 2),
        "position_btc": round(position_btc, 6),
        "risk_usd": round(actual_risk, 2),
        "risk_pct": round(actual_risk_pct, 2),
        "sl_distance_pct": round(sl_distance_pct, 2),
    }


# ══════════════════════════════════════════════════════════════════════════════
# CIRCUIT BREAKER
# ══════════════════════════════════════════════════════════════════════════════

class CircuitBreaker:
    """Arrête le trading en cas de pertes excessives."""

    def __init__(self, config: RiskConfig):
        self.config = config
        self.consecutive_losses = 0
        self.daily_pnl_pct = 0.0
        self.peak_equity = 0.0
        self.is_paused = False
        self.pause_reason = ""
        self.pause_start = None

    def update_after_trade(self, pnl_pct: float, current_equity: float,
                           initial_equity: float) -> bool:
        """
        Met à jour après un trade. Retourne True si le circuit breaker se déclenche.
        """
        # Track peak equity
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity

        # Consecutive losses
        if pnl_pct <= 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        # Daily P&L
        self.daily_pnl_pct += pnl_pct

        # Drawdown
        drawdown = (self.peak_equity - current_equity) / self.peak_equity * 100

        # Check triggers
        if self.consecutive_losses >= self.config.max_consecutive_losses:
            self.is_paused = True
            self.pause_reason = (
                f"Circuit Breaker: {self.consecutive_losses} pertes consecutives"
            )
            log.warning(self.pause_reason)
            return True

        if abs(self.daily_pnl_pct) >= self.config.max_daily_loss_pct and self.daily_pnl_pct < 0:
            self.is_paused = True
            self.pause_reason = (
                f"Circuit Breaker: perte journaliere {self.daily_pnl_pct:.2f}% "
                f"(max {self.config.max_daily_loss_pct}%)"
            )
            log.warning(self.pause_reason)
            return True

        if drawdown >= self.config.max_drawdown_pct:
            self.is_paused = True
            self.pause_reason = (
                f"Circuit Breaker: drawdown {drawdown:.2f}% "
                f"(max {self.config.max_drawdown_pct}%)"
            )
            log.warning(self.pause_reason)
            return True

        return False

    def reset_daily(self):
        """Reset le compteur journalier (à appeler chaque jour)."""
        self.daily_pnl_pct = 0.0
        log.info("Circuit breaker: reset journalier")

    def resume(self):
        """Reprend le trading après une pause."""
        self.is_paused = False
        self.pause_reason = ""
        self.consecutive_losses = 0
        self.pause_start = None
        log.info("Circuit breaker: trading repris")

    def can_trade(self) -> tuple[bool, str]:
        """Vérifie si on peut trader. Retourne (ok, raison)."""
        if self.is_paused:
            return False, self.pause_reason
        return True, "OK"

    def to_dict(self) -> dict:
        return {
            "consecutive_losses": self.consecutive_losses,
            "daily_pnl_pct": self.daily_pnl_pct,
            "peak_equity": self.peak_equity,
            "is_paused": self.is_paused,
            "pause_reason": self.pause_reason,
        }

    @classmethod
    def from_dict(cls, data: dict, config: RiskConfig) -> "CircuitBreaker":
        cb = cls(config)
        cb.consecutive_losses = data.get("consecutive_losses", 0)
        cb.daily_pnl_pct = data.get("daily_pnl_pct", 0.0)
        cb.peak_equity = data.get("peak_equity", 0.0)
        cb.is_paused = data.get("is_paused", False)
        cb.pause_reason = data.get("pause_reason", "")
        return cb


# ══════════════════════════════════════════════════════════════════════════════
# FILTRE REGIME DE MARCHE (ADX)
# ══════════════════════════════════════════════════════════════════════════════

def calculate_adx(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                  period: int = 14) -> np.ndarray:
    """
    Calcule l'ADX (Average Directional Index).
    ADX > 20 = tendance, ADX < 20 = range/choppy.
    """
    n = len(close)
    if n < period * 2:
        return np.full(n, np.nan)

    # True Range
    tr = np.empty(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i],
                     abs(high[i] - close[i - 1]),
                     abs(low[i] - close[i - 1]))

    # +DM / -DM
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move

    # Smoothed TR, +DM, -DM (Wilder's)
    def wilder_smooth(src, length):
        result = np.full(n, np.nan)
        result[length] = np.sum(src[1:length + 1])
        for i in range(length + 1, n):
            result[i] = result[i - 1] - result[i - 1] / length + src[i]
        return result

    atr_s = wilder_smooth(tr, period)
    pdm_s = wilder_smooth(plus_dm, period)
    mdm_s = wilder_smooth(minus_dm, period)

    # +DI / -DI
    plus_di = np.where(atr_s > 0, pdm_s / atr_s * 100, 0)
    minus_di = np.where(atr_s > 0, mdm_s / atr_s * 100, 0)

    # DX
    di_sum = plus_di + minus_di
    dx = np.where(di_sum > 0, np.abs(plus_di - minus_di) / di_sum * 100, 0)

    # ADX = Wilder smooth of DX
    adx = np.full(n, np.nan)
    start = period * 2
    if start < n:
        adx[start] = np.mean(dx[period + 1:start + 1])
        for i in range(start + 1, n):
            if not np.isnan(adx[i - 1]):
                adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

    return adx


def check_market_regime(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                        config: RiskConfig) -> dict:
    """
    Analyse le régime de marché.
    Retourne: {"regime": "trending"/"choppy", "adx": valeur, "can_trade": bool}
    """
    adx_vals = calculate_adx(high, low, close, config.adx_period)
    current_adx = adx_vals[-2] if len(adx_vals) > 1 else np.nan

    if np.isnan(current_adx):
        return {"regime": "unknown", "adx": 0, "can_trade": True}

    is_trending = current_adx >= config.adx_min

    return {
        "regime": "trending" if is_trending else "choppy",
        "adx": round(current_adx, 1),
        "can_trade": is_trending,
    }


# ══════════════════════════════════════════════════════════════════════════════
# SCORE DE CONFIANCE
# ══════════════════════════════════════════════════════════════════════════════

def calculate_confidence(
    direction: str,
    st_aligned: bool,
    ema_aligned: bool,
    pullback_valid: bool,
    adx_trending: bool,
    volume_spike: bool = False,
    macro_filter: bool = True,
) -> dict:
    """
    Score de confiance du signal (0-5).
    Chaque condition validée = +1 point.
    """
    score = 0
    details = []

    if st_aligned:
        score += 1
        details.append("SuperTrend OK")
    else:
        details.append("SuperTrend KO")

    if ema_aligned:
        score += 1
        details.append("EMA OK")
    else:
        details.append("EMA KO")

    if pullback_valid:
        score += 1
        details.append("Pullback OK")
    else:
        details.append("Pullback KO")

    if adx_trending:
        score += 1
        details.append("ADX trending")
    else:
        details.append("ADX choppy")

    if macro_filter:
        score += 1
        details.append("Macro OK")
    else:
        details.append("Macro KO")

    stars = "\u2B50" * score + "\u2606" * (5 - score)

    return {
        "score": score,
        "max": 5,
        "stars": stars,
        "details": details,
        "strong": score >= 4,
    }
