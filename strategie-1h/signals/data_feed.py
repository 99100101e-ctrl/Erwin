"""
Recuperation des donnees OHLCV via l'API publique Binance.
Aucune cle API requise pour les donnees de marche publiques.
"""

import pandas as pd
import requests
from . import config as cfg


BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

TIMEFRAME_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "2h": "2h", "4h": "4h",
    "1d": "1d", "1w": "1w",
}


def fetch_ohlcv(
    symbol: str = None,
    timeframe: str = None,
    limit: int = 500,
) -> pd.DataFrame:
    """
    Recupere les dernieres bougies OHLCV depuis Binance.

    Retourne un DataFrame avec colonnes :
        open, high, low, close, volume
    Index : datetime UTC.
    """
    symbol = symbol or cfg.SYMBOL
    timeframe = timeframe or cfg.TIMEFRAME

    params = {
        "symbol": symbol.upper(),
        "interval": TIMEFRAME_MAP.get(timeframe, timeframe),
        "limit": limit,
    }

    resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=10)
    resp.raise_for_status()
    raw = resp.json()

    df = pd.DataFrame(raw, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_vol", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore",
    ])

    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("open_time")

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    return df[["open", "high", "low", "close", "volume"]]
