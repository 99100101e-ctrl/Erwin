"""
Telegram Alert Bot — Reçoit les webhooks TradingView et forwarde sur Telegram.

Setup :
  1. Créer un bot via @BotFather sur Telegram → copier le token
  2. Parler à @userinfobot pour obtenir ton chat_id
  3. Copier .env.example → .env et remplir les valeurs
  4. pip install -r requirements.txt
  5. python bot.py
  6. Dans TradingView : webhook URL = http://<ton-serveur>:5000/webhook
"""

import os
import logging
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

# ── Config ──
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
PORT = int(os.environ.get("PORT", 5000))
SECRET = os.environ.get("WEBHOOK_SECRET", "")  # optionnel, sécurise le webhook

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

# ── App ──
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


def send_telegram(text: str) -> bool:
    """Envoie un message sur Telegram."""
    resp = requests.post(TELEGRAM_API, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }, timeout=10)
    if resp.ok:
        logging.info("Message envoyé sur Telegram")
    else:
        logging.error("Erreur Telegram: %s", resp.text)
    return resp.ok


@app.route("/webhook", methods=["POST"])
def webhook():
    """Reçoit le webhook de TradingView et forwarde sur Telegram."""
    # Vérification du secret (optionnel)
    if SECRET:
        token = request.headers.get("X-Webhook-Secret", "")
        if token != SECRET:
            return jsonify({"error": "unauthorized"}), 401

    # TradingView envoie du texte brut ou du JSON
    if request.is_json:
        data = request.get_json()
        message = data.get("message", str(data))
    else:
        message = request.get_data(as_text=True)

    if not message:
        return jsonify({"error": "empty message"}), 400

    logging.info("Alerte reçue: %s", message[:100])
    send_telegram(message)

    return jsonify({"status": "ok"}), 200


@app.route("/health", methods=["GET"])
def health():
    """Health check pour les services d'hébergement."""
    return jsonify({"status": "running"}), 200


if __name__ == "__main__":
    logging.info("Bot démarré sur le port %d", PORT)
    app.run(host="0.0.0.0", port=PORT)
