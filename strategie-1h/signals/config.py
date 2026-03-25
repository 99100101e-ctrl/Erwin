"""
Configuration de la strategie Erwin 1H
Reproduction fidele des parametres du script Pine TradingView
"""

# ═══════════════════════════════════════════════════════════════
#  PARAMETRES ICHIMOKU
# ═══════════════════════════════════════════════════════════════
KIJUN_LEN = 26
TENKAN_LEN = 9
DISPLACEMENT = 26

# ═══════════════════════════════════════════════════════════════
#  DETECTION FLAT / RANGE
# ═══════════════════════════════════════════════════════════════
# Options: "ADX seul", "Bollinger Width", "ADX + ATR combine"
FLAT_MODE = "ADX seul"

# ADX
ADX_LEN = 14
ADX_TREND = 22    # seuil tendance (>X)
ADX_FLAT = 18     # seuil flat (<X)

# Bollinger Width
BB_LEN = 20
BB_MULT = 2.0
BB_THRESH = 0.05  # flat si < X

# ATR combine
ATR_LEN = 14
ATR_RATIO = 0.8   # flat si ATR < X * moy

# ═══════════════════════════════════════════════════════════════
#  FILTRES SUPPLEMENTAIRES
# ═══════════════════════════════════════════════════════════════
USE_EMA = True
EMA_LEN = 200
USE_RSI = True
RSI_LEN = 14
RSI_OB = 65       # overbought
RSI_OS = 35       # oversold
USE_VOL = True
VOL_LEN = 20

# ═══════════════════════════════════════════════════════════════
#  GESTION DU TRADE
# ═══════════════════════════════════════════════════════════════
USE_PARTIAL = False
EXCLUDE_FLAT = True
USE_SL = True
SL_PCT = 2.0
USE_TRAILING = False
TRAIL_PCT = 1.5
TRAIL_OFFSET = 0.5
USE_TP = True
TP_PCT = 4.0

# ═══════════════════════════════════════════════════════════════
#  API / DATA SOURCE
# ═══════════════════════════════════════════════════════════════
SYMBOL = "BTCUSDT"
TIMEFRAME = "1h"
EXCHANGE = "binance"
