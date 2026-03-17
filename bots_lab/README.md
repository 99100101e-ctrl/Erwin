# bots_lab — Exploration de nouveaux bots

Dossier dédié aux expérimentations de stratégies alternatives.

## Bot de référence (à battre)
**v7 — EMA100d + ADX>=25 + HeuresFR + SL×2.0 + Cooldown 2h**
- N=51 | WR 66.7% | Sharpe +2.25 | MDD -6.4% | +621€ / 2 ans

## Structure
Chaque fichier = une stratégie indépendante.
Tous importent les données via : `sys.path.insert(0, "../backend")`

```python
from bt_common import load_real_candles, TRADE_SIZE
from backtest_2ans import precompute_full, stats, section, row, HDR
from backtest_v2 import enrich_signals
from backtest_v6 import enrich_v6
```

## Fichiers
| Fichier | Stratégie |
|---------|-----------|
| _(à créer)_ | _(tes idées ici)_ |
