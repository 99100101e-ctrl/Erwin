"""
Erwin Strategy 1H — Scanner en boucle avec alertes Telegram.

Lance un scan toutes les heures (configurable).
Detecte les entrees ET les sorties (SL/TP touches) et notifie par Telegram.

Usage :
  export TELEGRAM_TOKEN="123456:ABC..."
  export TELEGRAM_CHAT_ID="987654321"
  python scanner.py
"""

import time
import json
from datetime import datetime, timezone

from signals.data_feed import fetch_ohlcv
from signals.strategy import generate_signals, get_latest_signal
from signals import config as cfg
from signals.telegram_notifier import (
    notify_entry, notify_exit, send_telegram
)


class PositionTracker:
    """Suit la position ouverte pour detecter les sorties SL/TP."""

    def __init__(self):
        self.active = False
        self.direction = None   # "LONG" ou "SHORT"
        self.entry_price = None
        self.sl = None
        self.tp = None

    def open(self, signal: str, entry_price: float, sl, tp):
        self.active = True
        self.direction = signal
        self.entry_price = entry_price
        self.sl = float(sl) if sl else None
        self.tp = float(tp) if tp else None

    def check_exit(self, high: float, low: float, close: float) -> str | None:
        """Verifie si SL ou TP est touche. Retourne la raison ou None."""
        if not self.active:
            return None

        if self.direction == "LONG":
            if self.sl and low <= self.sl:
                return f"Stop-Loss touche ({self.sl:.2f})"
            if self.tp and high >= self.tp:
                return f"Take-Profit atteint ({self.tp:.2f})"
        elif self.direction == "SHORT":
            if self.sl and high >= self.sl:
                return f"Stop-Loss touche ({self.sl:.2f})"
            if self.tp and low <= self.tp:
                return f"Take-Profit atteint ({self.tp:.2f})"

        return None

    def close(self):
        direction = self.direction
        entry = self.entry_price
        self.active = False
        self.direction = None
        self.entry_price = None
        self.sl = None
        self.tp = None
        return direction, entry


def run_scanner():
    """Boucle principale du scanner."""
    tracker = PositionTracker()

    # Message de demarrage
    start_msg = (
        "\U0001F680 <b>Erwin Strategy 1H — Scanner demarre</b>\n"
        f"Paire : {cfg.SYMBOL}\n"
        f"Timeframe : {cfg.TIMEFRAME}\n"
        f"Scan toutes les {cfg.SCAN_INTERVAL}s\n"
        f"SL : {cfg.SL_PCT}% | TP : {cfg.TP_PCT}%\n"
        f"Mode flat : {cfg.FLAT_MODE}"
    )
    send_telegram(start_msg)
    print(start_msg.replace("<b>", "").replace("</b>", ""))

    while True:
        try:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            print(f"\n[{now}] Scan en cours...")

            df = fetch_ohlcv(limit=300)
            df = generate_signals(df)
            result = get_latest_signal(df)

            last_row = df.iloc[-1]

            # ── Verifier sortie de position ──────────────────
            if tracker.active:
                exit_reason = tracker.check_exit(
                    high=last_row["high"],
                    low=last_row["low"],
                    close=last_row["close"],
                )
                if exit_reason:
                    direction, entry_price = tracker.close()
                    notify_exit(
                        direction=direction,
                        close_price=last_row["close"],
                        reason=exit_reason,
                        entry_price=entry_price,
                    )
                    print(f"  >> SORTIE {direction} : {exit_reason}")

                # Si signal inverse, fermer position actuelle
                if result["signal"] and result["signal"] != tracker.direction:
                    direction, entry_price = tracker.close()
                    notify_exit(
                        direction=direction,
                        close_price=last_row["close"],
                        reason=f"Signal inverse ({result['signal']})",
                        entry_price=entry_price,
                    )
                    print(f"  >> SORTIE {direction} : signal inverse")

            # ── Verifier entree en position ──────────────────
            if result["signal"] and not tracker.active:
                notify_entry(result)
                tracker.open(
                    signal=result["signal"],
                    entry_price=result["close"],
                    sl=result["sl"],
                    tp=result["tp"],
                )
                print(f"  >> ENTREE {result['signal']} @ {result['close']:.2f}")
                print(f"     SL: {result['sl']}  |  TP: {result['tp']}")
            elif not result["signal"]:
                print(f"  Pas de signal | {result['market_state']} | Score: {result['score_bull']}/9")

            if tracker.active:
                print(f"  Position ouverte: {tracker.direction} @ {tracker.entry_price:.2f}")

        except Exception as e:
            error_msg = f"\U0000274C <b>Erreur scanner :</b> {e}"
            send_telegram(error_msg)
            print(f"  ERREUR : {e}")

        print(f"  Prochain scan dans {cfg.SCAN_INTERVAL}s...")
        time.sleep(cfg.SCAN_INTERVAL)


if __name__ == "__main__":
    run_scanner()
