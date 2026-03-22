"""
Alert Manager (simplifie) — Alertes temps reel pour trading manuel.

- Heartbeat toutes les 4h
- SuperTrend flip (4H + Daily)
- Alertes erreur (connexion perdue, erreurs consecutives)
"""

import time
import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

# Intervalle heartbeat en secondes (4 heures)
HEARTBEAT_INTERVAL = 4 * 3600

# Alerte erreur apres X erreurs consecutives
MAX_CONSECUTIVE_ERRORS = 3
ERROR_COOLDOWN = 300  # 5 min entre alertes erreur


class AlertManager:
    """Alertes non-trading : heartbeat, ST flip, erreurs."""

    def __init__(self, send_fn=None):
        self.send = send_fn or (lambda text: log.info("ALERT: %s", text))

        # Heartbeat
        self.last_heartbeat: float = 0.0
        self.last_scan_time: float = 0.0
        self.scan_count: int = 0
        self.bot_start_time: float = time.time()

        # Erreurs
        self.consecutive_errors: int = 0
        self.last_error_alert: float = 0.0
        self.total_errors: int = 0

        # SuperTrend tracking
        self.last_st_dir_4h: Optional[float] = None
        self.last_st_dir_1d: Optional[float] = None

        # Position updates
        self.last_position_update: float = 0.0
        self.last_sl_proximity_alert: float = 0.0
        self.last_tp_proximity_alert: float = 0.0

    # ── Heartbeat ──

    def record_scan(self):
        """Appeler apres chaque scan reussi."""
        self.last_scan_time = time.time()
        self.scan_count += 1
        self.consecutive_errors = 0

    def check_heartbeat(self, position: str, day_trades: int):
        """Envoie un heartbeat si l'intervalle est ecoule (pas entre 23h-6h UTC)."""
        now = time.time()
        if now - self.last_heartbeat < HEARTBEAT_INTERVAL:
            return

        # Pas de heartbeat la nuit (23h-6h UTC)
        current_hour = datetime.now(timezone.utc).hour
        if current_hour >= 23 or current_hour < 6:
            return

        self.last_heartbeat = now
        uptime = self._format_duration(now - self.bot_start_time)
        last_scan = self._format_duration(now - self.last_scan_time) if self.last_scan_time > 0 else "jamais"

        pos_str = position if position == "FLAT" else f"{position} ouvert"
        error_str = ""
        if self.total_errors > 0:
            error_str = f"\n\u26A0 Erreurs totales: {self.total_errors}"

        text = (
            "\U0001F49A <b>Heartbeat</b> \u2014 Bot actif\n"
            "\n"
            f"\u23F1 Uptime: {uptime}\n"
            f"\U0001F50D Dernier scan: il y a {last_scan}\n"
            f"\U0001F4CA Scans effectues: {self.scan_count}\n"
            f"\U0001F534 Position: {pos_str}\n"
            f"\U0001F4C8 Trades aujourd'hui: {day_trades}/3"
            f"{error_str}\n"
            "\n"
            "\u2705 Tout fonctionne normalement\n"
            f"\U0000231A {datetime.now(timezone.utc).strftime('%H:%M')} UTC"
        )
        self.send(text)
        log.info("Heartbeat envoye (uptime: %s, scans: %d)", uptime, self.scan_count)

    # ── Erreurs ──

    def record_error(self, error_type: str, error_msg: str):
        """Envoie une alerte si trop d'erreurs consecutives."""
        self.consecutive_errors += 1
        self.total_errors += 1
        now = time.time()

        if now - self.last_error_alert < ERROR_COOLDOWN:
            return

        if self.consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            self.last_error_alert = now
            text = (
                "\U0001F6A8 <b>ALERTE ERREUR</b>\n"
                "\n"
                f"\u274C {self.consecutive_errors} erreurs consecutives\n"
                f"\U0001F4CB Derniere: <code>{error_msg[:200]}</code>\n"
                f"\U0001F4A5 Type: {error_type}\n"
                "\n"
                "Le bot continue de tourner mais quelque chose ne va pas.\n"
                f"\U0000231A {datetime.now(timezone.utc).strftime('%H:%M')} UTC"
            )
            self.send(text)

    def alert_connection_lost(self, error_msg: str):
        """Alerte connexion Binance perdue."""
        now = time.time()
        if now - self.last_error_alert < ERROR_COOLDOWN:
            return

        self.last_error_alert = now
        text = (
            "\U0001F6A8 <b>CONNEXION PERDUE</b>\n"
            "\n"
            f"\U0001F4E1 Exchange: Binance\n"
            f"\u274C Erreur: <code>{error_msg[:200]}</code>\n"
            "\n"
            "Le bot va retenter dans 30s.\n"
            f"\U0000231A {datetime.now(timezone.utc).strftime('%H:%M')} UTC"
        )
        self.send(text)

    # ── Position update (toutes les heures) ──

    POSITION_UPDATE_INTERVAL = 3600  # 1h

    def check_position_update(self, position: str, entry_price: float,
                              cur_price: float, trail_stop: float,
                              tp: float, entry_time: str):
        """Envoie un update PnL toutes les heures si en position."""
        if position == "FLAT" or entry_price <= 0 or cur_price <= 0:
            return

        now = time.time()
        if now - self.last_position_update < self.POSITION_UPDATE_INTERVAL:
            return

        # Pas la nuit
        current_hour = datetime.now(timezone.utc).hour
        if current_hour >= 23 or current_hour < 6:
            return

        self.last_position_update = now

        if position == "LONG":
            pnl_pct = (cur_price - entry_price) / entry_price * 100
            sl_dist = (cur_price - trail_stop) / cur_price * 100 if trail_stop > 0 else 0
            tp_dist = (tp - cur_price) / cur_price * 100 if tp > 0 else 0
        else:  # SHORT
            pnl_pct = (entry_price - cur_price) / entry_price * 100
            sl_dist = 0  # short n'a pas de SL fixe
            tp_dist = 0

        pnl_emoji = "\U0001F7E2" if pnl_pct >= 0 else "\U0001F534"

        lines = [
            f"\U0001F4CA <b>Position Update</b> \u2014 {position}",
            "",
            f"{pnl_emoji} PnL: <code>{pnl_pct:+.2f}%</code>",
            f"\U0001F4B2 Prix: <code>${cur_price:,.2f}</code>",
            f"\U0001F4CD Entree: <code>${entry_price:,.2f}</code>",
        ]

        if position == "LONG":
            if trail_stop > 0:
                lines.append(f"\U0001F6E1 Trail SL: <code>${trail_stop:,.2f}</code> ({sl_dist:.1f}%)")
            if tp > 0:
                lines.append(f"\U0001F3AF TP: <code>${tp:,.2f}</code> ({tp_dist:+.1f}%)")

        lines.append(f"\n\U0000231A {datetime.now(timezone.utc).strftime('%H:%M')} UTC")

        self.send("\n".join(lines))
        log.info("Position update: %s PnL=%.2f%%", position, pnl_pct)

    # ── Alerte proximite SL / TP ──

    SL_PROXIMITY_PCT = 1.5   # alerte si prix a moins de 1.5% du SL
    TP_PROXIMITY_PCT = 2.0   # alerte si prix a moins de 2% du TP
    PROXIMITY_COOLDOWN = 1800  # 30 min entre alertes proximite

    def check_sl_tp_proximity(self, position: str, entry_price: float,
                              cur_price: float, trail_stop: float, tp: float):
        """Alerte quand le prix approche du SL ou du TP."""
        if position == "FLAT" or cur_price <= 0:
            return

        now = time.time()

        # ── Proximite SL (LONG seulement, car short n'a pas de SL fixe) ──
        if position == "LONG" and trail_stop > 0:
            sl_dist_pct = (cur_price - trail_stop) / cur_price * 100
            if sl_dist_pct <= self.SL_PROXIMITY_PCT and sl_dist_pct > 0:
                if now - self.last_sl_proximity_alert > self.PROXIMITY_COOLDOWN:
                    self.last_sl_proximity_alert = now
                    pnl_pct = (cur_price - entry_price) / entry_price * 100
                    self.send(
                        "\U0001F6A8 <b>ATTENTION \u2014 SL proche!</b>\n"
                        "\n"
                        f"\U0001F534 Prix: <code>${cur_price:,.2f}</code>\n"
                        f"\U0001F6E1 Trail SL: <code>${trail_stop:,.2f}</code>\n"
                        f"\U0001F4CF Distance: <code>{sl_dist_pct:.2f}%</code>\n"
                        f"\U0001F4CA PnL actuel: <code>{pnl_pct:+.2f}%</code>\n"
                        f"\n\U0000231A {datetime.now(timezone.utc).strftime('%H:%M')} UTC"
                    )
                    log.info("SL proximity alert: %.2f%% du SL", sl_dist_pct)

        # ── Proximite TP (LONG seulement) ──
        if position == "LONG" and tp > 0:
            tp_dist_pct = (tp - cur_price) / cur_price * 100
            if tp_dist_pct <= self.TP_PROXIMITY_PCT and tp_dist_pct > 0:
                if now - self.last_tp_proximity_alert > self.PROXIMITY_COOLDOWN:
                    self.last_tp_proximity_alert = now
                    pnl_pct = (cur_price - entry_price) / entry_price * 100
                    self.send(
                        "\U0001F389 <b>TP presque atteint!</b>\n"
                        "\n"
                        f"\U0001F7E2 Prix: <code>${cur_price:,.2f}</code>\n"
                        f"\U0001F3AF TP: <code>${tp:,.2f}</code>\n"
                        f"\U0001F4CF Distance: <code>{tp_dist_pct:.2f}%</code>\n"
                        f"\U0001F4CA PnL actuel: <code>{pnl_pct:+.2f}%</code>\n"
                        f"\n\U0000231A {datetime.now(timezone.utc).strftime('%H:%M')} UTC"
                    )
                    log.info("TP proximity alert: %.2f%% du TP", tp_dist_pct)

    # ── SuperTrend flip ──

    def check_supertrend_flip(self, st_dir_4h: float, st_dir_1d: float, position: str):
        """Detecte un flip SuperTrend et notifie."""
        # 4H flip
        if self.last_st_dir_4h is not None and st_dir_4h != self.last_st_dir_4h:
            new_trend = "BULL \u25B2" if st_dir_4h < 0 else "BEAR \u25BC"
            emoji = "\U0001F7E2" if st_dir_4h < 0 else "\U0001F534"
            pos_note = ""
            if position != "FLAT":
                pos_note = f"\n\U0001F4CB Position {position} en cours"

            text = (
                f"{emoji} <b>ST FLIP {new_trend}</b> (4H)\n"
                "\n"
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
                "\n"
                f"SuperTrend Daily a change de direction."
                f"{pos_note}\n"
                f"\U0000231A {datetime.now(timezone.utc).strftime('%H:%M')} UTC"
            )
            self.send(text)
            log.info("SuperTrend Daily flip: %s", new_trend)

        self.last_st_dir_4h = st_dir_4h
        self.last_st_dir_1d = st_dir_1d

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
