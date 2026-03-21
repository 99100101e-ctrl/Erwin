"""
Render.com Wrapper — Lance le scanner V11 en arrière-plan
+ serveur Flask pour le health check (obligatoire sur Render free tier).

Render free tier coupe les services inactifs après 15 min.
→ Utiliser https://cron-job.org pour pinger /health toutes les 10 min.

Deploy sur Render :
  1. Créer un "Web Service" sur render.com
  2. Connecter le repo GitHub
  3. Root Directory : telegram-bot
  4. Build Command : pip install -r requirements.txt
  5. Start Command : gunicorn render_app:app --bind 0.0.0.0:$PORT
  6. Ajouter les variables d'environnement :
     - TELEGRAM_TOKEN
     - TELEGRAM_CHAT_ID
  7. Sur https://cron-job.org, créer un job qui ping
     https://<ton-app>.onrender.com/health toutes les 10 min
"""

import os
import time
import threading
import logging
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify

# Import du scanner V11 (identique au Pine Script Phantom Edge V11 — Unified)
from btc_scanner import main as scanner_main, ScannerState, STATE_FILE

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


@app.route("/health", methods=["GET"])
def health():
    """Health check pour Render + status de la position."""
    state = ScannerState.load()
    return jsonify({
        "status": "running",
        "scanner": "Phantom Edge V11",
        "position": state.position,
        "entry_price": state.entry_price,
        "day_trades": state.day_trades,
        "utc_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }), 200


@app.route("/", methods=["GET"])
def index():
    """Page d'accueil simple."""
    return jsonify({
        "name": "Phantom Edge V11 Scanner",
        "endpoints": {
            "/health": "Status du scanner",
            "/position": "Position actuelle",
        },
    }), 200


@app.route("/position", methods=["GET"])
def position():
    """Détail de la position en cours."""
    state = ScannerState.load()
    if state.position == "FLAT":
        return jsonify({
            "position": "FLAT",
            "day_trades": f"{state.day_trades}/3",
        }), 200

    info = {
        "position": state.position,
        "entry_price": state.entry_price,
        "entry_time": state.entry_time,
        "day_trades": f"{state.day_trades}/3",
    }
    if state.position == "LONG":
        info["trailing_stop"] = state.trail_long
    else:
        info["short_bars_in"] = state.short_bars_in
        info["short_be_reached"] = state.short_be_reached
    return jsonify(info), 200


def send_status_reply(chat_id: str):
    """Envoie le status actuel du scanner via Telegram."""
    state = ScannerState.load()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if state.position == "FLAT":
        pos_info = "FLAT (en attente de signal)"
    elif state.position == "LONG":
        pnl = f" | Trail: {state.trail_long:,.0f}" if state.trail_long else ""
        pos_info = f"LONG @ {state.entry_price:,.2f}{pnl}"
    else:
        pos_info = f"SHORT @ {state.entry_price:,.2f} | Bars: {state.short_bars_in}"

    text = (
        "\U0001F4CA <b>Phantom Edge V11 — Status</b>\n"
        f"\n"
        f"\U0001F534 Position: {pos_info}\n"
        f"\U0001F4C8 Trades aujourd'hui: {state.day_trades}/3\n"
        f"\U0000231A {now} UTC\n"
        f"\n"
        f"\u2705 Scanner actif — scan toutes les 5 min"
    )
    try:
        requests.post(f"{TELEGRAM_API}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }, timeout=10)
    except Exception as e:
        logging.error("Erreur envoi status: %s", e)


def poll_telegram_commands():
    """Poll les messages Telegram pour répondre aux commandes /status."""
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
                    text = msg.get("text", "")
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    if text in ("/status", "/start"):
                        send_status_reply(chat_id)
        except Exception as e:
            logging.warning("Poll Telegram error: %s", e)
            time.sleep(10)


def start_scanner():
    """Lance le scanner dans un thread daemon."""
    logging.info("Lancement du scanner V11 en arriere-plan...")
    scanner_main()


# Lancer le scanner + polling Telegram au démarrage
scanner_thread = threading.Thread(target=start_scanner, daemon=True)
scanner_thread.start()

telegram_thread = threading.Thread(target=poll_telegram_commands, daemon=True)
telegram_thread.start()
