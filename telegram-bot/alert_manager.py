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
