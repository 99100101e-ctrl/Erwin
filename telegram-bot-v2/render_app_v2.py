"""
Render.com Wrapper V2 — Lance le scanner V14 en arrière-plan
+ serveur Flask pour health check + commandes Telegram enrichies.

Commandes Telegram :
  /status  — Position actuelle
  /stats   — Statistiques complètes
  /equity  — Equity + drawdown
  /resume  — Reprendre après circuit breaker
  /daily   — Résumé du jour

⚠️  Branche de développement — ne tourne PAS sur Render pour l'instant.
"""

import os
import time
import threading
import logging
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify

from btc_scanner_v14 import main as scanner_main, ScannerState, STATE_FILE, INITIAL_EQUITY
from trade_tracker import compute_stats, format_stats_telegram, format_daily_summary
from risk_manager import RiskConfig, CircuitBreaker
from alert_manager import AlertManager, AlertConfig, format_live_status

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


@app.route("/health", methods=["GET"])
def health():
    state = ScannerState.load()
    stats = compute_stats()
    return jsonify({
        "status": "running",
        "scanner": "Phantom Edge V14",
        "position": state.position,
        "entry_price": state.entry_price,
        "equity": state.equity,
        "day_trades": state.day_trades,
        "total_trades": stats.get("total_trades", 0),
        "win_rate": stats.get("win_rate", 0),
        "utc_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }), 200


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "name": "Phantom Edge V14 Scanner",
        "version": "2.0",
        "endpoints": {
            "/health": "Status + stats",
            "/position": "Position actuelle",
            "/stats": "Statistiques completes",
        },
    }), 200


@app.route("/position", methods=["GET"])
def position():
    state = ScannerState.load()
    if state.position == "FLAT":
        return jsonify({
            "position": "FLAT",
            "equity": state.equity,
            "day_trades": f"{state.day_trades}/3",
        }), 200

    info = {
        "position": state.position,
        "entry_price": state.entry_price,
        "entry_time": state.entry_time,
        "position_size_usd": state.position_size_usd,
        "risk_pct": state.risk_pct,
        "equity": state.equity,
        "day_trades": f"{state.day_trades}/3",
    }
    if state.position == "LONG":
        info["trailing_stop"] = state.trail_long
    else:
        info["short_sl"] = state.short_sl
    return jsonify(info), 200


@app.route("/stats", methods=["GET"])
def stats_endpoint():
    return jsonify(compute_stats()), 200


# ── Telegram Commands ──

def send_reply(chat_id: str, text: str):
    try:
        requests.post(f"{TELEGRAM_API}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }, timeout=10)
    except Exception as e:
        logging.error("Erreur envoi reply: %s", e)


def handle_status(chat_id: str):
    state = ScannerState.load()

    # Fetch prix BTC actuel pour PnL flottant
    try:
        resp = requests.get("https://api.binance.com/api/v3/ticker/price",
                            params={"symbol": "BTCUSDT"}, timeout=10)
        current_price = float(resp.json()["price"])
    except Exception:
        current_price = state.entry_price if state.entry_price > 0 else 0

    # Peak equity pour drawdown
    peak_equity = state.circuit_breaker.get("peak_equity", state.equity)

    # Reconstruire l'AlertManager a partir du state
    alert_mgr = AlertManager(config=AlertConfig())
    if state.alert_state:
        alert_mgr.load_from_dict(state.alert_state)

    text = format_live_status(state, current_price, peak_equity, alert_mgr)
    send_reply(chat_id, text)


def handle_stats(chat_id: str):
    text = format_stats_telegram()
    send_reply(chat_id, text)


def handle_equity(chat_id: str):
    state = ScannerState.load()
    stats = compute_stats()

    pnl = state.equity - INITIAL_EQUITY
    pnl_pct = pnl / INITIAL_EQUITY * 100
    dd = stats.get("max_drawdown_pct", 0)

    text = (
        "\U0001F4B5 <b>Equity Report</b>\n"
        f"\n"
        f"Capital initial: <code>${INITIAL_EQUITY:,.2f}</code>\n"
        f"Equity actuelle: <code>${state.equity:,.2f}</code>\n"
        f"P&L: <code>${pnl:+,.2f}</code> ({pnl_pct:+.2f}%)\n"
        f"Max Drawdown: {dd:.2f}%\n"
        f"\n"
        f"Trades: {stats.get('total_trades', 0)} | "
        f"Win Rate: {stats.get('win_rate', 0):.1f}%"
    )
    send_reply(chat_id, text)


def handle_resume(chat_id: str):
    state = ScannerState.load()
    if state.circuit_breaker.get("is_paused"):
        state.circuit_breaker["is_paused"] = False
        state.circuit_breaker["pause_reason"] = ""
        state.circuit_breaker["consecutive_losses"] = 0
        state.save()
        send_reply(chat_id, "\u2705 Circuit breaker d\u00e9sactiv\u00e9. Trading repris.")
    else:
        send_reply(chat_id, "\u2139\ufe0f Le circuit breaker n'est pas actif.")


def handle_daily(chat_id: str):
    text = format_daily_summary()
    send_reply(chat_id, text)


COMMANDS = {
    "/status": handle_status,
    "/start": handle_status,
    "/stats": handle_stats,
    "/equity": handle_equity,
    "/resume": handle_resume,
    "/daily": handle_daily,
}


def poll_telegram_commands():
    last_update_id = 0
    while True:
        try:
            resp = requests.get(f"{TELEGRAM_API}/getUpdates", params={
                "offset": last_update_id + 1,
                "timeout": 30,
            }, timeout=35)
            if resp.ok:
                for update in resp.json().get("result", []):
                    last_update_id = update["update_id"]
                    msg = update.get("message", {})
                    text = msg.get("text", "").strip()
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    handler = COMMANDS.get(text)
                    if handler:
                        handler(chat_id)
        except Exception as e:
            logging.warning("Poll Telegram error: %s", e)
            time.sleep(10)


def start_scanner():
    logging.info("Lancement du scanner V14 en arriere-plan...")
    scanner_main()


scanner_thread = threading.Thread(target=start_scanner, daemon=True)
scanner_thread.start()

telegram_thread = threading.Thread(target=poll_telegram_commands, daemon=True)
telegram_thread.start()
