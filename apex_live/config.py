"""
apex_live/config.py — Configuration APEX Bot Live

ÉTAPES DE DÉMARRAGE :
  1. Remplis API_KEY et API_SECRET avec tes clés Binance Futures
  2. Laisse PAPER_TRADING = True pour tester sans argent réel
  3. Lance : python apex_live/apex_live.py
  4. Quand tu es satisfait des résultats paper → passe PAPER_TRADING = False
"""

# ── Binance API ────────────────────────────────────────────────────────────────
# Crée tes clés sur https://www.binance.com/fr/my/settings/api-management
# Active UNIQUEMENT "Futures" (pas de retrait)
API_KEY    = ""       # ← ta clé API
API_SECRET = ""       # ← ton secret API

# ── Paire et levier ────────────────────────────────────────────────────────────
SYMBOL   = "BTCUSDT"
LEVERAGE = 1         # 1 = pas de levier (recommandé pour démarrer)

# ── Taille de position ─────────────────────────────────────────────────────────
TRADE_SIZE_USDT = 2000.0   # Montant par trade en USDT (même que le backtest)

# ── Mode ───────────────────────────────────────────────────────────────────────
PAPER_TRADING = True       # True = simulation pure | False = ordres réels

# ── Paramètres APEX v2 (validés en backtest — NE PAS MODIFIER sans re-backtester)
BOS_LB     = 20    # Break of Structure lookback
EXT_ATR    = 7.0   # Filtre extension EMA50 (× ATR)
SCORE_BUY  = 2     # Score min BUY  (sur 6 confirmateurs)
SCORE_SELL = 3     # Score min SELL (sur 5 confirmateurs)
ADX_BUY    = 25    # ADX minimum pour BUY
ADX_SELL   = 20    # ADX minimum pour SELL
COOLDOWN_H = 3     # Heures de cooldown entre deux signaux
SL_MULT    = 2.0   # Multiplicateur ATR pour le Stop Loss

# ── Niveaux de sortie ──────────────────────────────────────────────────────────
TP1_R     = 1.2   # TP1 (× R) → ferme 40% de la position, SL → Breakeven
TP2_R     = 2.5   # TP2 (× R) → ferme 35%
TP3_R     = 5.0   # TP3 (× R) → ferme les 25% restants
TIMEOUT_H = 96    # Ferme la position après N heures si ni SL ni TP atteints

# ── Notifications Telegram (optionnel) ────────────────────────────────────────
# Crée un bot Telegram : @BotFather → /newbot → récupère le token
# Trouve ton chat_id : envoie un message au bot puis appelle
# https://api.telegram.org/bot<TOKEN>/getUpdates
TELEGRAM_TOKEN   = ""   # ex : "7123456789:AAGx..."
TELEGRAM_CHAT_ID = ""   # ex : "123456789"

# ── Fichiers ───────────────────────────────────────────────────────────────────
STATE_FILE = "apex_live/state.json"
LOG_FILE   = "apex_live/trades.jsonl"
