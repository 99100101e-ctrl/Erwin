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
    """Envoie le status enrichi : prix live, PnL flottant, position."""
    state = ScannerState.load()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # Fetch prix BTC live
    try:
        resp = requests.get("https://api.binance.com/api/v3/ticker/price",
                            params={"symbol": "BTCUSDT"}, timeout=10)
        btc_price = float(resp.json()["price"])
    except Exception:
        btc_price = 0

    if state.position == "FLAT":
        pos_block = (
            "\U0001F7E1 Position: <b>FLAT</b> (en attente)\n"
            f"\U0001F4B2 BTC: <code>${btc_price:,.2f}</code>"
        )
    elif state.position == "LONG":
        if btc_price > 0 and state.entry_price > 0:
            pnl_pct = (btc_price - state.entry_price) / state.entry_price * 100
            pnl_emoji = "\U0001F7E2" if pnl_pct >= 0 else "\U0001F534"
            sl_dist = (btc_price - state.trail_long) / btc_price * 100 if state.trail_long > 0 else 0
            pos_block = (
                f"\U0001F7E2 Position: <b>LONG</b> @ <code>${state.entry_price:,.2f}</code>\n"
                f"\U0001F4B2 Prix: <code>${btc_price:,.2f}</code>\n"
                f"{pnl_emoji} PnL: <code>{pnl_pct:+.2f}%</code>\n"
                f"\U0001F6E1 Trail: <code>${state.trail_long:,.2f}</code> ({sl_dist:.1f}% du prix)"
            )
        else:
            pos_block = f"\U0001F7E2 Position: <b>LONG</b> @ <code>${state.entry_price:,.2f}</code>"
    else:  # SHORT
        if btc_price > 0 and state.entry_price > 0:
            pnl_pct = (state.entry_price - btc_price) / state.entry_price * 100
            pnl_emoji = "\U0001F7E2" if pnl_pct >= 0 else "\U0001F534"
            pos_block = (
                f"\U0001F534 Position: <b>SHORT</b> @ <code>${state.entry_price:,.2f}</code>\n"
                f"\U0001F4B2 Prix: <code>${btc_price:,.2f}</code>\n"
                f"{pnl_emoji} PnL: <code>{pnl_pct:+.2f}%</code>\n"
                f"\U0001F4CA Bars: {state.short_bars_in}"
            )
        else:
            pos_block = f"\U0001F534 Position: <b>SHORT</b> @ <code>${state.entry_price:,.2f}</code>"

    text = (
        "\U0001F4CA <b>Phantom Edge V11 \u2014 Status</b>\n"
        f"\n"
        f"{pos_block}\n"
        f"\n"
        f"\U0001F4C8 Signaux aujourd'hui: {state.day_trades}/3\n"
        f"\U0000231A {now} UTC\n"
        f"\n"
        f"\u2705 Scanner actif \u2014 scan toutes les 5 min"
    )
    try:
        requests.post(f"{TELEGRAM_API}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }, timeout=10)
    except Exception as e:
        logging.error("Erreur envoi status: %s", e)


def send_help_reply(chat_id: str):
    """Envoie le memo des commandes disponibles."""
    text = (
        "\U0001F4D6 <b>Commandes disponibles</b>\n"
        "\n"
        "/status \u2014 Position actuelle, prix BTC live, PnL flottant\n"
        "/help \u2014 Ce memo\n"
        "\n"
        "\U0001F514 <b>Alertes automatiques</b>\n"
        "\n"
        "\U0001F7E2\U0001F534 Signal LONG/SHORT avec score de confiance\n"
        "\U0001F504 SuperTrend flip (4H + Daily)\n"
        "\U0001F4CA Position update (toutes les 1h)\n"
        "\U0001F6A8 Alerte SL proche (&lt;1.5%)\n"
        "\U0001F389 Alerte TP proche (&lt;2%)\n"
        "\u2705\u274C Fermeture position (SL/trail/BE/time stop)\n"
        "\U0001F49A Heartbeat (toutes les 4h, 6h-23h)\n"
        "\U0001F4C5 Resume du jour (21h UTC)\n"
        "\U0001F6A8 Erreurs / connexion perdue\n"
        "\n"
        "\U0001F4A1 <i>Les alertes sont envoyees automatiquement, "
        "pas besoin de les demander.</i>"
    )
    try:
        requests.post(f"{TELEGRAM_API}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }, timeout=10)
    except Exception as e:
        logging.error("Erreur envoi help: %s", e)


def register_telegram_commands():
    """Enregistre le menu de commandes dans Telegram (bouton / du clavier)."""
    commands = [
        {"command": "status", "description": "Position, prix BTC, PnL flottant"},
        {"command": "help", "description": "Liste des commandes et alertes"},
    ]
    try:
        resp = requests.post(f"{TELEGRAM_API}/setMyCommands",
                             json={"commands": commands}, timeout=10)
        if resp.ok:
            logging.info("Menu Telegram enregistre (%d commandes)", len(commands))
        else:
            logging.warning("setMyCommands failed: %s", resp.text)
    except Exception as e:
        logging.warning("Erreur enregistrement commandes: %s", e)


def poll_telegram_commands():
    """Poll les messages Telegram pour repondre aux commandes."""
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
                    elif text == "/help":
                        send_help_reply(chat_id)
        except Exception as e:
            logging.warning("Poll Telegram error: %s", e)
            time.sleep(10)


def start_scanner():
    """Lance le scanner dans un thread daemon."""
    logging.info("Lancement du scanner V11 en arriere-plan...")
    scanner_main()


# Enregistrer le menu de commandes + lancer scanner + polling
register_telegram_commands()

scanner_thread = threading.Thread(target=start_scanner, daemon=True)
scanner_thread.start()

telegram_thread = threading.Thread(target=poll_telegram_commands, daemon=True)
telegram_thread.start()
