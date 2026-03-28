"""
Configuration de la strategie Erwin — Multi-timeframe
Meme logique Ichimoku sur 1H et 15M
"""
import os

# ═══════════════════════════════════════════════════════════════
#  PARAMETRES ICHIMOKU (communs aux 2 timeframes)
# ═══════════════════════════════════════════════════════════════
KIJUN_LEN = 26
TENKAN_LEN = 9
DISPLACEMENT = 26

# ═══════════════════════════════════════════════════════════════
#  DETECTION FLAT / RANGE
# ═══════════════════════════════════════════════════════════════
FLAT_MODE = "ADX seul"
ADX_LEN = 14
ADX_TREND = 22
ADX_FLAT = 18
BB_LEN = 20
BB_MULT = 2.0
BB_THRESH = 0.05
ATR_LEN = 14
ATR_RATIO = 0.8

# ═══════════════════════════════════════════════════════════════
#  FILTRES SUPPLEMENTAIRES
# ═══════════════════════════════════════════════════════════════
USE_EMA = True
EMA_LEN = 200
USE_RSI = True
RSI_LEN = 14
RSI_OB = 65
RSI_OS = 35
USE_VOL = True
VOL_LEN = 20

# ═══════════════════════════════════════════════════════════════
#  GESTION DU TRADE
# ═══════════════════════════════════════════════════════════════
USE_PARTIAL = False
EXCLUDE_FLAT = True
USE_SL = True
USE_TRAILING = False
TRAIL_PCT = 1.5
TRAIL_OFFSET = 0.5
USE_TP = True

# ═══════════════════════════════════════════════════════════════
#  STRATEGIES — config par timeframe
# ═══════════════════════════════════════════════════════════════
SYMBOL = "BTCUSDT"
EXCHANGE = "binance"

# Valeurs par defaut (utilisees par l'ancien code)
TIMEFRAME = "1h"
SL_PCT = 2.0
TP_PCT = 4.0
SCAN_INTERVAL = 3600

STRATEGIES = {
    "1h": {
        "timeframe": "1h",
        "label": "Erwin 1H",
        "scan_interval": 3600,    # toutes les heures
        "sl_pct": 2.0,
        "tp_pct": 4.0,
    },
    "15m": {
        "timeframe": "15m",
        "label": "Erwin 15M",
        "scan_interval": 900,     # toutes les 15 minutes
        "sl_pct": 1.0,
        "tp_pct": 2.0,
    },
}

# ═══════════════════════════════════════════════════════════════
#  TELEGRAM
# ═══════════════════════════════════════════════════════════════
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
