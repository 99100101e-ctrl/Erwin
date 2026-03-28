"""
Erwin Strategy — Scanner Multi-Timeframe (1H + 15M).

Fonctionnalites :
  - Scan 1H toutes les heures, 15M toutes les 15 minutes
  - Detecte entrees/sorties, notifie par Telegram
  - Commande /status : etat complet des 2 strategies
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


def scan_strategy(strat_key: str, strat_cfg: dict, tracker: PositionTracker, daily_stats: DailyStats):
    """Execute un scan pour une strategie donnee (1h ou 15m)."""
    label = strat_cfg["label"]
    tf = strat_cfg["timeframe"]
    sl_pct = strat_cfg["sl_pct"]
    tp_pct = strat_cfg["tp_pct"]

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n[{now_str}] Scan {label} en cours...")

    df = fetch_ohlcv(timeframe=tf, limit=300)
    df = generate_signals(df, sl_pct=sl_pct, tp_pct=tp_pct)
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
                label=label,
            )
            print(f"  [{label}] >> SORTIE {direction} : {exit_reason}")

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
                label=label,
            )
            print(f"  [{label}] >> SORTIE {direction} : signal inverse")

    # ── Verifier entree en position ──────────────
    if result["signal"] and not tracker.active:
        daily_stats.record_entry()
        notify_entry(result, label=label, sl_pct=sl_pct, tp_pct=tp_pct, timeframe=tf)
        tracker.open(
            signal=result["signal"],
            entry_price=result["close"],
            sl=result["sl"],
            tp=result["tp"],
        )
        print(f"  [{label}] >> ENTREE {result['signal']} @ {result['close']:.2f}")
        print(f"     SL: {result['sl']}  |  TP: {result['tp']}")
    elif not result["signal"]:
        print(f"  [{label}] Pas de signal | {result['market_state']} | Score: {result['score_bull']}/9")

    if tracker.active:
        print(f"  [{label}] Position ouverte: {tracker.direction} @ {tracker.entry_price:.2f}")


def handle_telegram_commands(trackers: dict, update_offset):
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
                for strat_key, strat_cfg in cfg.STRATEGIES.items():
                    label = strat_cfg["label"]
                    tf = strat_cfg["timeframe"]
                    sl_pct = strat_cfg["sl_pct"]
                    tp_pct = strat_cfg["tp_pct"]
                    df = fetch_ohlcv(timeframe=tf, limit=300)
                    df = generate_signals(df, sl_pct=sl_pct, tp_pct=tp_pct)
                    result = get_latest_signal(df)
                    notify_status(result, trackers.get(strat_key), label=label, timeframe=tf)
                print(f"  [CMD] /status envoye pour toutes les strategies")
            except Exception as e:
                send_telegram(f"\u274C Erreur /status : {e}")
                print(f"  [CMD] Erreur /status : {e}")

    return new_offset


def check_daily_summary(last_summary_date, daily_stats_all: dict):
    """Envoie le resume quotidien a 22h Paris pour chaque strategie."""
    now_paris = datetime.now(TZ_PARIS)
    today = now_paris.date()

    # Envoyer a 22h si pas deja fait aujourd'hui
    if now_paris.hour >= 22 and last_summary_date != today:
        try:
            for strat_key, strat_cfg in cfg.STRATEGIES.items():
                label = strat_cfg["label"]
                tf = strat_cfg["timeframe"]
                sl_pct = strat_cfg["sl_pct"]
                tp_pct = strat_cfg["tp_pct"]
                df = fetch_ohlcv(timeframe=tf, limit=300)
                df = generate_signals(df, sl_pct=sl_pct, tp_pct=tp_pct)
                result = get_latest_signal(df)
                stats = daily_stats_all[strat_key]
                notify_daily_summary(result, stats.to_dict(), label=label)
            print(f"  [DAILY] Resume 22h envoye pour toutes les strategies")
            return today
        except Exception as e:
            send_telegram(f"\u274C Erreur resume quotidien : {e}")
            print(f"  [DAILY] Erreur : {e}")

    return last_summary_date


def run_scanner():
    """Boucle principale du scanner multi-timeframe."""
    # Un tracker et des stats par strategie
    trackers = {}
    daily_stats_all = {}
    last_scan_times = {}

    for key in cfg.STRATEGIES:
        trackers[key] = PositionTracker()
        daily_stats_all[key] = DailyStats()
        last_scan_times[key] = 0

    update_offset = None
    last_summary_date = None

    # Consommer les anciens messages Telegram au demarrage
    old_updates = get_telegram_updates()
    if old_updates:
        update_offset = old_updates[-1]["update_id"] + 1

    # Message de demarrage
    strat_lines = []
    for key, sc in cfg.STRATEGIES.items():
        strat_lines.append(f"  • {sc['label']} — scan {sc['scan_interval']}s — SL {sc['sl_pct']}% / TP {sc['tp_pct']}%")

    start_msg = (
        "\U0001F680 <b>Erwin Strategy — Scanner Multi-TF demarre</b>\n"
        f"Paire : {cfg.SYMBOL}\n"
        f"Mode flat : {cfg.FLAT_MODE}\n\n"
        f"<b>Strategies actives :</b>\n"
        + "\n".join(strat_lines) + "\n\n"
        f"Commande : /status"
    )
    send_telegram(start_msg)
    print(start_msg.replace("<b>", "").replace("</b>", ""))

    poll_interval = 30  # polling Telegram toutes les 30s

    while True:
        try:
            now_ts = time.time()

            # ── Polling commandes Telegram (toutes les 30s) ──
            update_offset = handle_telegram_commands(trackers, update_offset)

            # ── Reset stats si nouveau jour ──────────────────
            for stats in daily_stats_all.values():
                stats.check_new_day()

            # ── Resume quotidien 22h ─────────────────────────
            last_summary_date = check_daily_summary(last_summary_date, daily_stats_all)

            # ── Scan chaque strategie selon son intervalle ────
            for strat_key, strat_cfg in cfg.STRATEGIES.items():
                interval = strat_cfg["scan_interval"]
                if now_ts - last_scan_times[strat_key] >= interval:
                    last_scan_times[strat_key] = now_ts
                    try:
                        scan_strategy(
                            strat_key, strat_cfg,
                            trackers[strat_key],
                            daily_stats_all[strat_key],
                        )
                    except Exception as e:
                        label = strat_cfg["label"]
                        error_msg = f"\u274C <b>Erreur scanner {label} :</b> {e}"
                        send_telegram(error_msg)
                        print(f"  [{label}] ERREUR : {e}")

        except Exception as e:
            error_msg = f"\u274C <b>Erreur scanner :</b> {e}"
            send_telegram(error_msg)
            print(f"  ERREUR : {e}")

        time.sleep(poll_interval)


if __name__ == "__main__":
    run_scanner()
