"""
fetch_btc_data.py
-----------------
Lance ce script sur ta machine Windows AVANT de faire git pull.
Il télécharge les vraies bougies BTCUSDT 1h depuis Binance (6 derniers mois)
et les sauvegarde dans backend/data/btc_1h_real.json

Usage :
    python fetch_btc_data.py
"""

import urllib.request
import json
import time
import os
from datetime import datetime, timezone, timedelta

SYMBOL   = "BTCUSDT"
INTERVAL = "1h"
LIMIT    = 1000  # max Binance
OUTPUT   = os.path.join(os.path.dirname(__file__), "backend", "data", "btc_1h_real.json")

# 6 mois en arrière depuis aujourd'hui
end_ms   = int(datetime.now(timezone.utc).timestamp() * 1000)
start_ms = int((datetime.now(timezone.utc) - timedelta(days=183)).timestamp() * 1000)

def fetch_klines(start, end):
    url = (
        f"https://api.binance.com/api/v3/klines"
        f"?symbol={SYMBOL}&interval={INTERVAL}&limit={LIMIT}"
        f"&startTime={start}&endTime={end}"
    )
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read())

def main():
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    all_candles = []
    cur = start_ms
    print(f"Téléchargement BTCUSDT 1h de {datetime.fromtimestamp(start_ms/1000, tz=timezone.utc).date()} "
          f"à {datetime.fromtimestamp(end_ms/1000, tz=timezone.utc).date()}...")

    while cur < end_ms:
        try:
            klines = fetch_klines(cur, end_ms)
        except Exception as e:
            print(f"  Erreur : {e} — nouvelle tentative dans 5s")
            time.sleep(5)
            continue

        if not klines:
            break

        for k in klines:
            all_candles.append({
                "ts":     int(k[0]) // 1000,   # secondes
                "open":   float(k[1]),
                "high":   float(k[2]),
                "low":    float(k[3]),
                "close":  float(k[4]),
                "volume": float(k[5]),
            })

        last_ts = int(klines[-1][0])
        print(f"  → {len(all_candles)} bougies | dernier : {datetime.fromtimestamp(last_ts/1000, tz=timezone.utc)}")

        if len(klines) < LIMIT:
            break
        cur = last_ts + 3600000  # +1h en ms
        time.sleep(0.3)  # respecter le rate limit Binance

    # Dédupliquer et trier
    seen = set()
    deduped = []
    for c in sorted(all_candles, key=lambda x: x["ts"]):
        if c["ts"] not in seen:
            seen.add(c["ts"])
            deduped.append(c)

    with open(OUTPUT, "w") as f:
        json.dump(deduped, f)

    print(f"\n✅ {len(deduped)} bougies sauvegardées dans {OUTPUT}")
    print(f"   Période : {datetime.fromtimestamp(deduped[0]['ts'], tz=timezone.utc).date()} "
          f"→ {datetime.fromtimestamp(deduped[-1]['ts'], tz=timezone.utc).date()}")
    print(f"\nFais maintenant : git add backend/data/btc_1h_real.json && git push")

if __name__ == "__main__":
    main()
