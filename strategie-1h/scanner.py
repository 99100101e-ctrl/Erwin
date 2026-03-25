"""
Erwin Strategy 1H — Scanner en boucle avec alertes Telegram.

Fonctionnalites :
  - Scan toutes les heures, detecte entrees/sorties, notifie par Telegram
  - Commande /status : etat complet de la strategie + conditions remplies
  - Resume quotidien automatique a 22h (heure Paris)

Usage :
  export TELEGRAM_TOKEN="123456:ABC..."
  export TELEGRAM_CHAT_ID="987654321"
  python scanner.py
"""

import time
from datetime import datetime, timezone, timedelta

from signals.data_feed import fetch_ohlcv
from signals.strategy import generate_signals, get_latest_signal
from signals import config as cfg
from signals.telegram_notifier import (
    notify_entry, notify_exit, notify_status, notify_daily_summary,
    send_telegram, get_telegram_updates,
)

# Fuseau horaire Paris (UTC+1 / UTC+2 en ete)
TZ_PARIS = timezone(timedelta(hours=1))


class PositionTracker:
    """Suit la position ouverte pour detecter les sorties SL/TP."""

    def __init__(self):
        self.active = False
        self.direction = None
        self.entry_price = None
        self.sl = None
        self.tp = None

    def open(self, signal: str, entry_price: float, sl, tp):
        self.active = True
        self.direction = signal
        self.entry_price = entry_price
        self.sl = float(sl) if sl else None
        self.tp = float(tp) if tp else None

    def check_exit(self, high: float, low: float, close: float):
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


class DailyStats:
    """Compteur de statistiques journalieres."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.date = datetime.now(TZ_PARIS).date()
        self.nb_long = 0
        self.nb_short = 0
        self.nb_entries = 0
        self.nb_exits = 0
        self.trades = []

    def check_new_day(self):
        """Reset les stats si on change de jour."""
        today = datetime.now(TZ_PARIS).date()
        if today != self.date:
            self.reset()

    def record_signal(self, signal: str):
        if signal == "LONG":
            self.nb_long += 1
        elif signal == "SHORT":
            self.nb_short += 1

    def record_entry(self):
        self.nb_entries += 1

    def record_exit(self, direction: str, entry_price: float, exit_price: float, reason: str):
        self.nb_exits += 1
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100
        if direction == "SHORT":
            pnl_pct = -pnl_pct
        self.trades.append({
            "direction": direction,
            "entry": entry_price,
            "exit": exit_price,
            "pnl_pct": pnl_pct,
            "reason": reason,
        })

    def to_dict(self):
        return {
            "nb_long": self.nb_long,
            "nb_short": self.nb_short,
            "nb_entries": self.nb_entries,
            "nb_exits": self.nb_exits,
            "trades": self.trades,
        }


def handle_telegram_commands(tracker, update_offset):
    """Verifie si l'utilisateur a envoye /status sur Telegram."""
    updates = get_telegram_updates(offset=update_offset)

    new_offset = update_offset
    for update in updates:
        new_offset = update["update_id"] + 1
        msg = update.get("message", {})
        text = msg.get("text", "").strip().lower()
        chat_id = str(msg.get("chat", {}).get("id", ""))

        # Verifier que le message vient du bon chat
        if chat_id != cfg.TELEGRAM_CHAT_ID:
            continue

        if text.startswith("/status"):
            try:
                df = fetch_ohlcv(limit=300)
                df = generate_signals(df)
                result = get_latest_signal(df)
                notify_status(result, tracker)
                print(f"  [CMD] /status envoye")
            except Exception as e:
                send_telegram(f"\u274C Erreur /status : {e}")
                print(f"  [CMD] Erreur /status : {e}")

    return new_offset


def check_daily_summary(last_summary_date, daily_stats):
    """Envoie le resume quotidien a 22h Paris."""
    now_paris = datetime.now(TZ_PARIS)
    today = now_paris.date()

    # Envoyer a 22h si pas deja fait aujourd'hui
    if now_paris.hour >= 22 and last_summary_date != today:
        try:
            df = fetch_ohlcv(limit=300)
            df = generate_signals(df)
            result = get_latest_signal(df)
            notify_daily_summary(result, daily_stats.to_dict())
            print(f"  [DAILY] Resume 22h envoye")
            return today
        except Exception as e:
            send_telegram(f"\u274C Erreur resume quotidien : {e}")
            print(f"  [DAILY] Erreur : {e}")

    return last_summary_date


def run_scanner():
    """Boucle principale du scanner."""
    tracker = PositionTracker()
    daily_stats = DailyStats()
    update_offset = None
    last_summary_date = None

    # Consommer les anciens messages Telegram au demarrage
    old_updates = get_telegram_updates()
    if old_updates:
        update_offset = old_updates[-1]["update_id"] + 1

    # Message de demarrage
    start_msg = (
        "\U0001F680 <b>Erwin Strategy 1H — Scanner demarre</b>\n"
        f"Paire : {cfg.SYMBOL}\n"
        f"Timeframe : {cfg.TIMEFRAME}\n"
        f"Scan toutes les {cfg.SCAN_INTERVAL}s\n"
        f"SL : {cfg.SL_PCT}% | TP : {cfg.TP_PCT}%\n"
        f"Mode flat : {cfg.FLAT_MODE}\n\n"
        f"Commandes : /status /status_1h"
    )
    send_telegram(start_msg)
    print(start_msg.replace("<b>", "").replace("</b>", ""))

    scan_interval_short = 30  # polling Telegram toutes les 30s

    last_scan_time = 0

    while True:
        try:
            now = datetime.now(timezone.utc)
            now_ts = now.timestamp()

            # ── Polling commandes Telegram (toutes les 30s) ──
            update_offset = handle_telegram_commands(tracker, update_offset)

            # ── Reset stats si nouveau jour ──────────────────
            daily_stats.check_new_day()

            # ── Resume quotidien 22h ─────────────────────────
            last_summary_date = check_daily_summary(last_summary_date, daily_stats)

            # ── Scan strategie (toutes les SCAN_INTERVAL sec) ──
            if now_ts - last_scan_time >= cfg.SCAN_INTERVAL:
                last_scan_time = now_ts

                now_str = now.strftime("%Y-%m-%d %H:%M UTC")
                print(f"\n[{now_str}] Scan en cours...")

                df = fetch_ohlcv(limit=300)
                df = generate_signals(df)
                result = get_latest_signal(df)

                last_row = df.iloc[-1]

                # Compter les signaux detectes
                if result["signal"]:
                    daily_stats.record_signal(result["signal"])

                # ── Verifier sortie de position ──────────────
                if tracker.active:
                    exit_reason = tracker.check_exit(
                        high=last_row["high"],
                        low=last_row["low"],
                        close=last_row["close"],
                    )
                    if exit_reason:
                        direction, entry_price = tracker.close()
                        daily_stats.record_exit(direction, entry_price, last_row["close"], exit_reason)
                        notify_exit(
                            direction=direction,
                            close_price=last_row["close"],
                            reason=exit_reason,
                            entry_price=entry_price,
                        )
                        print(f"  >> SORTIE {direction} : {exit_reason}")

                    # Signal inverse
                    if result["signal"] and result["signal"] != tracker.direction:
                        direction, entry_price = tracker.close()
                        reason = f"Signal inverse ({result['signal']})"
                        daily_stats.record_exit(direction, entry_price, last_row["close"], reason)
                        notify_exit(
                            direction=direction,
                            close_price=last_row["close"],
                            reason=reason,
                            entry_price=entry_price,
                        )
                        print(f"  >> SORTIE {direction} : signal inverse")

                # ── Verifier entree en position ──────────────
                if result["signal"] and not tracker.active:
                    daily_stats.record_entry()
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
            error_msg = f"\u274C <b>Erreur scanner :</b> {e}"
            send_telegram(error_msg)
            print(f"  ERREUR : {e}")

        time.sleep(scan_interval_short)


if __name__ == "__main__":
    run_scanner()
