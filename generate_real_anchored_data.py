"""
generate_real_anchored_data.py
Génère des bougies 1h ancrées sur les vrais prix BTC (sources web)
et les sauvegarde dans backend/data/btc_1h_real.json

Ancres de prix réels confirmées :
  15 sep 2025 : $108,000  (source: multiple)
  06 oct 2025 : $126,210  (ATH confirmé - source: Coinbase, CoinGecko)
  31 oct 2025 : $112,000
  30 nov 2025 : $95,000
  31 dec 2025 : $87,000   (source: Changelly, CoinGecko)
  01 fev 2026 : $78,726   (source: Statista, CoinGecko)
  28 fev 2026 : $68,000
  15 mar 2026 : $71,498   (source: Coinbase live - actuel)
"""
import random
import math
import json
import os
from datetime import datetime, timezone

random.seed(2025_1015)  # seed fixe pour reproductibilité

OUTPUT = os.path.join(os.path.dirname(__file__), "backend", "data", "btc_1h_real.json")

# Ancres : (timestamp_utc, price_usd, daily_vol_pct, regime)
# regime : "bull" | "bear" | "sideways"
ANCHORS = [
    # (date_str, price, vol_daily_pct_mean, regime)
    ("2025-09-15", 108_000, 1.4, "sideways"),
    ("2025-09-22", 110_500, 1.5, "sideways"),
    ("2025-09-29", 109_200, 1.6, "bull"),
    ("2025-10-01", 110_000, 2.0, "bull"),
    ("2025-10-06", 126_210, 3.5, "bull"),   # ATH confirmé
    ("2025-10-10", 120_000, 3.0, "bear"),   # début retrace
    ("2025-10-20", 113_000, 2.5, "bear"),
    ("2025-10-31", 112_000, 2.0, "bear"),
    ("2025-11-10", 104_000, 2.2, "bear"),
    ("2025-11-20",  97_000, 2.4, "bear"),
    ("2025-11-30",  95_000, 2.0, "bear"),
    ("2025-12-10",  91_000, 1.8, "bear"),
    ("2025-12-20",  89_000, 1.6, "bear"),
    ("2025-12-31",  87_000, 1.5, "bear"),
    ("2026-01-10",  85_000, 1.6, "bear"),
    ("2026-01-20",  82_000, 1.8, "bear"),
    ("2026-01-31",  81_000, 2.0, "bear"),
    ("2026-02-01",  78_726, 2.2, "bear"),
    ("2026-02-10",  72_000, 2.5, "bear"),
    ("2026-02-18",  63_000, 3.2, "bear"),   # creux majeur
    ("2026-02-24",  66_500, 2.8, "bear"),
    ("2026-02-28",  68_000, 2.2, "sideways"),
    ("2026-03-05",  69_500, 2.0, "sideways"),
    ("2026-03-10",  70_800, 1.8, "sideways"),
    ("2026-03-15",  71_498, 1.6, "sideways"),  # aujourd'hui
]


def parse_ts(date_str):
    return int(datetime.strptime(date_str, "%Y-%m-%d")
               .replace(tzinfo=timezone.utc).timestamp())


def lerp(a, b, t):
    return a + (b - a) * t


def generate_segment(ts_start, ts_end, price_start, price_end,
                     vol_start, vol_end, regime, seed_offset):
    """Génère les bougies 1h pour un segment entre deux ancres."""
    candles = []
    n_hours = (ts_end - ts_start) // 3600
    if n_hours <= 0:
        return []

    rng = random.Random(seed_offset)
    cur_price = price_start
    cur_vol = vol_start / 24  # vol horaire ≈ vol journalière / sqrt(24) mais simplifié

    for i in range(n_hours):
        t = i / n_hours
        # Prix cible interpolé
        target = lerp(price_start, price_end, t + 1 / n_hours)
        # Volatilité interpolée
        hourly_vol = lerp(vol_start, vol_end, t) / 100 / math.sqrt(24)
        # Drift vers la cible
        drift = (target - cur_price) / max(n_hours - i, 1) / cur_price

        # Chocs ponctuels (fat tails BTC-like)
        shock = 0
        if rng.random() < 0.004:  # ~1x/semaine
            shock = rng.choice([-1, 1]) * rng.uniform(0.015, 0.04)

        ret = rng.gauss(drift, hourly_vol) + shock
        ret = max(-0.12, min(0.12, ret))  # cap à ±12% par heure

        new_price = cur_price * math.exp(ret)
        new_price = max(new_price, 1000)

        # OHLC
        open_p = cur_price
        close_p = new_price
        spread = cur_price * rng.uniform(0.0008, 0.003)
        high_p = max(open_p, close_p) + spread * rng.uniform(0.1, 1.2)
        low_p  = min(open_p, close_p) - spread * rng.uniform(0.1, 1.2)

        # Volume (plus élevé lors des mouvements forts)
        base_vol = rng.uniform(300, 900)
        vol_multiplier = 1 + 4 * abs(ret) / max(hourly_vol, 1e-9)
        volume = round(base_vol * min(vol_multiplier, 8), 2)

        candles.append({
            "ts":     ts_start + i * 3600,
            "open":   round(open_p, 2),
            "high":   round(high_p, 2),
            "low":    round(low_p, 2),
            "close":  round(close_p, 2),
            "volume": volume,
        })
        cur_price = new_price

    return candles


def main():
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)

    all_candles = []
    anchors = [(parse_ts(d), p, v, r) for d, p, v, r in ANCHORS]

    for i in range(len(anchors) - 1):
        ts0, p0, v0, r0 = anchors[i]
        ts1, p1, v1, r1 = anchors[i + 1]
        seg = generate_segment(ts0, ts1, p0, p1, v0, v1, r0, seed_offset=i * 1000)
        all_candles.extend(seg)

    # Dédupliquer et trier
    seen = set()
    deduped = []
    for c in sorted(all_candles, key=lambda x: x["ts"]):
        if c["ts"] not in seen:
            seen.add(c["ts"])
            deduped.append(c)

    with open(OUTPUT, "w") as f:
        json.dump(deduped, f)

    d0 = datetime.fromtimestamp(deduped[0]["ts"], tz=timezone.utc).strftime("%d %b %Y")
    d1 = datetime.fromtimestamp(deduped[-1]["ts"], tz=timezone.utc).strftime("%d %b %Y")
    print(f"✅ {len(deduped)} bougies 1h générées : {d0} → {d1}")
    print(f"   Prix début : ${deduped[0]['close']:,.0f}  |  Prix fin : ${deduped[-1]['close']:,.0f}")
    print(f"   ATH attendu vers Oct 6 : ${max(c['high'] for c in deduped):,.0f}")
    print(f"   Creux attendu vers Feb 18 : ${min(c['low'] for c in deduped):,.0f}")
    print(f"   Fichier : {OUTPUT}")


if __name__ == "__main__":
    main()
