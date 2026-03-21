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
import threading
import logging
from datetime import datetime, timezone

from flask import Flask, jsonify

# Import du scanner V11 (identique au Pine Script Phantom Edge V11 — Unified)
from btc_scanner import main as scanner_main, ScannerState, STATE_FILE

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


def start_scanner():
    """Lance le scanner dans un thread daemon."""
    logging.info("Lancement du scanner V11 en arriere-plan...")
    scanner_main()


# Lancer le scanner au démarrage de l'app
scanner_thread = threading.Thread(target=start_scanner, daemon=True)
scanner_thread.start()
