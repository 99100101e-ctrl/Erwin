"""
Alert Manager — Systeme d'alertes temps reel pour Phantom Edge V14.

Fonctionnalites :
  - Heartbeat periodique ("bot actif, dernier scan il y a Xmin")
  - Alertes d'erreur (crash, deconnexion exchange, signal rate)
  - Alerte drawdown (equity -X% depuis le pic)
  - Position live (PnL flottant, distance SL/trail)
  - SuperTrend flip notifications
"""

import time
import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION ALERTES
# ══════════════════════════════════════════════════════════════════════════════

class AlertConfig:
    """Parametres du systeme d'alertes."""

    def __init__(
        self,
        # Heartbeat
        heartbeat_interval_hours: float = 4.0,   # Envoyer un heartbeat toutes les X heures

        # Drawdown
        drawdown_warn_pct: float = 5.0,           # Alerte si equity -X% depuis le pic
        drawdown_critical_pct: float = 10.0,       # Alerte critique

        # Erreurs
        max_consecutive_errors: int = 3,           # Alerte apres X erreurs d'affilee
        error_cooldown_seconds: int = 300,         # Pas de spam: 1 alerte erreur / 5 min

        # Position live
        position_update_hours: float = 2.0,        # Update position toutes les X heures
    ):
        self.heartbeat_interval_hours = heartbeat_interval_hours
        self.drawdown_warn_pct = drawdown_warn_pct
        self.drawdown_critical_pct = drawdown_critical_pct
        self.max_consecutive_errors = max_consecutive_errors
        self.error_cooldown_seconds = error_cooldown_seconds
        self.position_update_hours = position_update_hours


DEFAULT_ALERT_CONFIG = AlertConfig()


# ══════════════════════════════════════════════════════════════════════════════
# ALERT MANAGER
# ══════════════════════════════════════════════════════════════════════════════

class AlertManager:
    """Gere toutes les alertes non-trading (heartbeat, erreurs, drawdown, position live)."""

    def __init__(self, config: AlertConfig = None, send_fn=None):
        """
        Args:
            config: AlertConfig (utilise DEFAULT_ALERT_CONFIG par defaut)
            send_fn: Fonction pour envoyer un message Telegram (signature: send_fn(text: str) -> bool)
        """
        self.config = config or DEFAULT_ALERT_CONFIG
        self.send = send_fn or (lambda text: log.info("ALERT (no sender): %s", text))

        # Heartbeat state
        self.last_heartbeat: float = 0.0
        self.last_scan_time: float = 0.0
        self.scan_count: int = 0
        self.bot_start_time: float = time.time()

        # Error tracking
        self.consecutive_errors: int = 0
        self.last_error_alert: float = 0.0
        self.total_errors: int = 0
        self.last_error_msg: str = ""

        # Drawdown tracking
        self.drawdown_warned: bool = False
        self.drawdown_critical_sent: bool = False
        self.last_drawdown_pct: float = 0.0

        # Position update
        self.last_position_update: float = 0.0

        # SuperTrend tracking
        self.last_st_dir_4h: Optional[float] = None
        self.last_st_dir_1d: Optional[float] = None

    # ── Heartbeat ──

    def record_scan(self):
        """Appeler apres chaque scan reussi."""
        self.last_scan_time = time.time()
        self.scan_count += 1
        self.consecutive_errors = 0  # Reset erreurs apres un scan OK

    def check_heartbeat(self, position: str, equity: float, day_trades: int):
        """Envoie un heartbeat si l'intervalle est ecoule."""
        now = time.time()
        interval_sec = self.config.heartbeat_interval_hours * 3600

        if now - self.last_heartbeat < interval_sec:
            return

        self.last_heartbeat = now
        uptime = self._format_duration(now - self.bot_start_time)
        last_scan_ago = self._format_duration(now - self.last_scan_time) if self.last_scan_time > 0 else "jamais"

        pos_str = position if position == "FLAT" else f"{position} ouvert"
        error_str = ""
        if self.total_errors > 0:
            error_str = f"\n\u26A0 Erreurs totales: {self.total_errors}"

        text = (
            "\U0001F49A <b>Heartbeat</b> \u2014 Bot actif\n"
            "\n"
            f"\u23F1 Uptime: {uptime}\n"
            f"\U0001F50D Dernier scan: il y a {last_scan_ago}\n"
            f"\U0001F4CA Scans effectues: {self.scan_count}\n"
            f"\U0001F534 Position: {pos_str}\n"
            f"\U0001F4B5 Equity: <code>${equity:,.2f}</code>\n"
            f"\U0001F4C8 Trades aujourd'hui: {day_trades}/3"
            f"{error_str}\n"
            f"\n"
            f"\u2705 Tout fonctionne normalement\n"
            f"\U0000231A {datetime.now(timezone.utc).strftime('%H:%M')} UTC"
        )
        self.send(text)
        log.info("Heartbeat envoye (uptime: %s, scans: %d)", uptime, self.scan_count)

    # ── Alertes d'erreur ──

    def record_error(self, error_type: str, error_msg: str):
        """
        Appeler quand une erreur survient.
        Envoie une alerte Telegram si le seuil est atteint.
        """
        self.consecutive_errors += 1
        self.total_errors += 1
        self.last_error_msg = f"{error_type}: {error_msg}"
        now = time.time()

        # Anti-spam: pas d'alerte si la derniere est recente
        if now - self.last_error_alert < self.config.error_cooldown_seconds:
            log.warning("Erreur #%d (alerte en cooldown): %s", self.consecutive_errors, self.last_error_msg)
            return

        if self.consecutive_errors >= self.config.max_consecutive_errors:
            self.last_error_alert = now
            text = (
                "\U0001F6A8 <b>ALERTE ERREUR</b>\n"
                "\n"
                f"\u274C {self.consecutive_errors} erreurs consecutives\n"
                f"\U0001F4CB Derniere: <code>{error_msg[:200]}</code>\n"
                f"\U0001F4A5 Type: {error_type}\n"
                f"\n"
                f"Le bot continue de tourner mais quelque chose ne va pas.\n"
                f"Verifiez les logs.\n"
                f"\U0000231A {datetime.now(timezone.utc).strftime('%H:%M')} UTC"
            )
            self.send(text)
            log.error("Alerte erreur envoyee: %d erreurs consecutives", self.consecutive_errors)

    def alert_connection_lost(self, exchange: str, error_msg: str):
        """Alerte specifique: connexion a l'exchange perdue."""
        now = time.time()
        if now - self.last_error_alert < self.config.error_cooldown_seconds:
            return

        self.last_error_alert = now
        text = (
            "\U0001F6A8 <b>CONNEXION PERDUE</b>\n"
            "\n"
            f"\U0001F4E1 Exchange: {exchange}\n"
            f"\u274C Erreur: <code>{error_msg[:200]}</code>\n"
            "\n"
            "Le bot va retenter dans 30s.\n"
            f"\U0000231A {datetime.now(timezone.utc).strftime('%H:%M')} UTC"
        )
        self.send(text)
        log.error("Connexion perdue: %s - %s", exchange, error_msg)

    def alert_signal_missed(self, direction: str, reason: str):
        """Alerte quand un signal est detecte mais non pris."""
        text = (
            "\u26A0 <b>Signal non pris</b>\n"
            "\n"
            f"\U0001F4CD Direction: {direction}\n"
            f"\U0001F4CB Raison: {reason}\n"
            f"\U0000231A {datetime.now(timezone.utc).strftime('%H:%M')} UTC"
        )
        self.send(text)
        log.info("Signal %s non pris: %s", direction, reason)

    # ── Drawdown alerts ──

    def check_drawdown(self, current_equity: float, peak_equity: float):
        """Verifie le drawdown et envoie une alerte si necessaire."""
        if peak_equity <= 0:
            return

        drawdown_pct = (peak_equity - current_equity) / peak_equity * 100
        self.last_drawdown_pct = drawdown_pct

        # Alerte critique
        if drawdown_pct >= self.config.drawdown_critical_pct and not self.drawdown_critical_sent:
            self.drawdown_critical_sent = True
            text = (
                "\U0001F534\U0001F534\U0001F534 <b>DRAWDOWN CRITIQUE</b>\n"
                "\n"
                f"\U0001F4C9 Equity: <code>${current_equity:,.2f}</code>\n"
                f"\U0001F4C8 Pic: <code>${peak_equity:,.2f}</code>\n"
                f"\U0001F6A8 Drawdown: <b>{drawdown_pct:.1f}%</b>\n"
                "\n"
                "Le circuit breaker devrait se declencher.\n"
                "Considerez une intervention manuelle.\n"
                f"\U0000231A {datetime.now(timezone.utc).strftime('%H:%M')} UTC"
            )
            self.send(text)
            log.warning("DRAWDOWN CRITIQUE: %.1f%%", drawdown_pct)

        # Alerte warning
        elif drawdown_pct >= self.config.drawdown_warn_pct and not self.drawdown_warned:
            self.drawdown_warned = True
            text = (
                "\u26A0 <b>DRAWDOWN ALERT</b>\n"
                "\n"
                f"\U0001F4C9 Equity: <code>${current_equity:,.2f}</code>\n"
                f"\U0001F4C8 Pic: <code>${peak_equity:,.2f}</code>\n"
                f"\U0001F4CA Drawdown: <b>{drawdown_pct:.1f}%</b>\n"
                "\n"
                f"Equity en baisse de {drawdown_pct:.1f}% depuis le pic \u2014 attention\n"
                f"\U0000231A {datetime.now(timezone.utc).strftime('%H:%M')} UTC"
            )
            self.send(text)
            log.warning("Drawdown warning: %.1f%%", drawdown_pct)

        # Reset si le drawdown diminue (equity remonte)
        elif drawdown_pct < self.config.drawdown_warn_pct:
            if self.drawdown_warned:
                log.info("Drawdown revenu sous %.1f%% — warning reset", self.config.drawdown_warn_pct)
            self.drawdown_warned = False
            self.drawdown_critical_sent = False

    # ── Position live update ──

    def check_position_update(self, position: str, entry_price: float,
                               current_price: float, equity: float,
                               trail_stop: float = 0, short_sl: float = 0,
                               position_size_usd: float = 0):
        """Envoie un update de position si l'intervalle est ecoule."""
        if position == "FLAT":
            return

        now = time.time()
        interval_sec = self.config.position_update_hours * 3600
        if now - self.last_position_update < interval_sec:
            return

        self.last_position_update = now

        if position == "LONG":
            pnl_pct = (current_price - entry_price) / entry_price * 100
            pnl_usd = position_size_usd * pnl_pct / 100
            sl_price = trail_stop
            sl_distance_pct = (current_price - sl_price) / current_price * 100 if sl_price > 0 else 0
            sl_label = "Trail Stop"
        else:
            pnl_pct = (entry_price - current_price) / entry_price * 100
            pnl_usd = position_size_usd * pnl_pct / 100
            sl_price = short_sl
            sl_distance_pct = (sl_price - current_price) / current_price * 100 if sl_price > 0 else 0
            sl_label = "Stop Loss"

        pnl_emoji = "\U0001F7E2" if pnl_pct >= 0 else "\U0001F534"

        text = (
            f"\U0001F4CB <b>Position {position}</b> \u2014 Update\n"
            f"\n"
            f"\U0001F4CD Entree: <code>${entry_price:,.2f}</code>\n"
            f"\U0001F4B2 Prix actuel: <code>${current_price:,.2f}</code>\n"
            f"{pnl_emoji} PnL flottant: <code>{pnl_pct:+.2f}%</code> (${pnl_usd:+,.2f})\n"
            f"\n"
            f"\U0001F6E1 {sl_label}: <code>${sl_price:,.2f}</code>\n"
            f"\U0001F4CF Distance SL: {sl_distance_pct:.2f}%\n"
            f"\U0001F4B5 Equity: <code>${equity:,.2f}</code>\n"
            f"\U0000231A {datetime.now(timezone.utc).strftime('%H:%M')} UTC"
        )
        self.send(text)
        log.info("Position update: %s PnL %.2f%%", position, pnl_pct)

    # ── SuperTrend flip ──

    def check_supertrend_flip(self, st_dir_4h: float, st_dir_1d: float,
                                position: str):
        """Detecte un flip SuperTrend et notifie (meme sans position)."""
        # 4H flip
        if self.last_st_dir_4h is not None and st_dir_4h != self.last_st_dir_4h:
            new_trend = "BULL \u25B2" if st_dir_4h < 0 else "BEAR \u25BC"
            emoji = "\U0001F7E2" if st_dir_4h < 0 else "\U0001F534"
            pos_note = ""
            if position != "FLAT":
                pos_note = f"\n\U0001F4CB Position {position} en cours"

            text = (
                f"{emoji} <b>ST FLIP {new_trend}</b> (4H)\n"
                f"\n"
                f"SuperTrend 4H a change de direction."
                f"{pos_note}\n"
                f"\U0000231A {datetime.now(timezone.utc).strftime('%H:%M')} UTC"
            )
            self.send(text)
            log.info("SuperTrend 4H flip: %s", new_trend)

        # Daily flip
        if self.last_st_dir_1d is not None and st_dir_1d != self.last_st_dir_1d:
            new_trend = "BULL \u25B2" if st_dir_1d < 0 else "BEAR \u25BC"
            emoji = "\U0001F7E2" if st_dir_1d < 0 else "\U0001F534"
            pos_note = ""
            if position != "FLAT":
                pos_note = f"\n\U0001F4CB Position {position} en cours"

            text = (
                f"{emoji} <b>ST FLIP {new_trend}</b> (Daily)\n"
                f"\n"
                f"SuperTrend Daily a change de direction."
                f"{pos_note}\n"
                f"\U0000231A {datetime.now(timezone.utc).strftime('%H:%M')} UTC"
            )
            self.send(text)
            log.info("SuperTrend Daily flip: %s", new_trend)

        self.last_st_dir_4h = st_dir_4h
        self.last_st_dir_1d = st_dir_1d

    # ── Serialisation ──

    def to_dict(self) -> dict:
        return {
            "last_heartbeat": self.last_heartbeat,
            "last_scan_time": self.last_scan_time,
            "scan_count": self.scan_count,
            "bot_start_time": self.bot_start_time,
            "consecutive_errors": self.consecutive_errors,
            "total_errors": self.total_errors,
            "last_error_alert": self.last_error_alert,
            "last_error_msg": self.last_error_msg,
            "drawdown_warned": self.drawdown_warned,
            "drawdown_critical_sent": self.drawdown_critical_sent,
            "last_position_update": self.last_position_update,
            "last_st_dir_4h": self.last_st_dir_4h,
            "last_st_dir_1d": self.last_st_dir_1d,
        }

    def load_from_dict(self, data: dict):
        for key, val in data.items():
            if hasattr(self, key):
                setattr(self, key, val)

    # ── Utils ──

    @staticmethod
    def _format_duration(seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds / 60)}min"
        elif seconds < 86400:
            h = int(seconds / 3600)
            m = int((seconds % 3600) / 60)
            return f"{h}h{m:02d}min"
        else:
            d = int(seconds / 86400)
            h = int((seconds % 86400) / 3600)
            return f"{d}j {h}h"


# ══════════════════════════════════════════════════════════════════════════════
# FORMAT HELPERS (pour /status enrichi)
# ══════════════════════════════════════════════════════════════════════════════

def format_live_status(state, current_price: float, peak_equity: float,
                       alert_mgr: AlertManager) -> str:
    """
    Formate un /status enrichi avec PnL flottant, drawdown, et sante du bot.

    Args:
        state: ScannerState instance
        current_price: prix BTC actuel
        peak_equity: equity pic pour calcul drawdown
        alert_mgr: AlertManager instance
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # ── Sante du bot ──
    uptime = alert_mgr._format_duration(time.time() - alert_mgr.bot_start_time)
    last_scan = alert_mgr._format_duration(time.time() - alert_mgr.last_scan_time) if alert_mgr.last_scan_time > 0 else "jamais"
    health_emoji = "\u2705" if alert_mgr.consecutive_errors == 0 else "\u26A0"

    # ── Circuit breaker ──
    cb_info = ""
    if state.circuit_breaker.get("is_paused"):
        cb_info = f"\n\U0001F6A8 <b>PAUSE</b>: {state.circuit_breaker.get('pause_reason', '')}\n"

    # ── Position ──
    if state.position == "FLAT":
        pos_block = (
            "\U0001F7E1 Position: <b>FLAT</b> (en attente)\n"
            f"\U0001F4B2 BTC: <code>${current_price:,.2f}</code>"
        )
    elif state.position == "LONG":
        pnl_pct = (current_price - state.entry_price) / state.entry_price * 100
        pnl_usd = state.position_size_usd * pnl_pct / 100
        pnl_emoji = "\U0001F7E2" if pnl_pct >= 0 else "\U0001F534"
        sl_dist = (current_price - state.trail_long) / current_price * 100 if state.trail_long > 0 else 0

        pos_block = (
            f"\U0001F7E2 Position: <b>LONG</b> @ <code>${state.entry_price:,.2f}</code>\n"
            f"\U0001F4B2 Prix: <code>${current_price:,.2f}</code>\n"
            f"{pnl_emoji} PnL: <code>{pnl_pct:+.2f}%</code> (${pnl_usd:+,.2f})\n"
            f"\U0001F6E1 Trail: <code>${state.trail_long:,.2f}</code> ({sl_dist:.1f}% du prix)\n"
            f"\U0001F4B0 Taille: ${state.position_size_usd:,.0f}"
        )
    else:  # SHORT
        pnl_pct = (state.entry_price - current_price) / state.entry_price * 100
        pnl_usd = state.position_size_usd * pnl_pct / 100
        pnl_emoji = "\U0001F7E2" if pnl_pct >= 0 else "\U0001F534"
        sl_dist = (state.short_sl - current_price) / current_price * 100 if state.short_sl > 0 else 0

        pos_block = (
            f"\U0001F534 Position: <b>SHORT</b> @ <code>${state.entry_price:,.2f}</code>\n"
            f"\U0001F4B2 Prix: <code>${current_price:,.2f}</code>\n"
            f"{pnl_emoji} PnL: <code>{pnl_pct:+.2f}%</code> (${pnl_usd:+,.2f})\n"
            f"\U0001F6D1 SL: <code>${state.short_sl:,.2f}</code> ({sl_dist:.1f}% du prix)\n"
            f"\U0001F4B0 Taille: ${state.position_size_usd:,.0f}"
        )

    # ── Equity & drawdown ──
    drawdown_pct = (peak_equity - state.equity) / peak_equity * 100 if peak_equity > 0 else 0
    dd_emoji = "\u2705" if drawdown_pct < 5 else "\u26A0" if drawdown_pct < 10 else "\U0001F534"

    # ── Daily PnL ──
    from trade_tracker import compute_stats
    stats = compute_stats()
    today_pnl = stats.get("today_pnl_usd", 0)
    today_trades = stats.get("today_trades", 0)

    text = (
        f"\U0001F4CA <b>Phantom Edge V14 \u2014 Status</b>\n"
        f"\n"
        f"{pos_block}\n"
        f"{cb_info}"
        f"\n"
        f"\U0001F4B5 Equity: <code>${state.equity:,.2f}</code>\n"
        f"{dd_emoji} Drawdown: {drawdown_pct:.1f}% (pic: ${peak_equity:,.0f})\n"
        f"\U0001F4C5 PnL du jour: <code>${today_pnl:+,.2f}</code> ({today_trades} trades)\n"
        f"\U0001F4C8 Trades: {state.day_trades}/3\n"
        f"\n"
        f"{health_emoji} Bot: actif depuis {uptime}\n"
        f"\U0001F50D Dernier scan: il y a {last_scan}\n"
        f"\U0000231A {now} UTC"
    )
    return text
