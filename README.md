# BTC Trading Advisor — Stratégie E

Conseiller de trading BTC en temps réel avec analyse technique avancée.

## Installation

### Prérequis
- [Python 3.10+](https://www.python.org/downloads/) — cocher **"Add Python to PATH"**
- [Node.js LTS](https://nodejs.org/) (v18 ou supérieur)
- Git

### Cloner le projet

```powershell
git clone --branch claude/bitcoin-trading-advisor-Uj9A1 --single-branch https://github.com/99100101e-ctrl/Erwin D:\BTC-strategieE
```

### Démarrer le programme

Double-cliquer sur `D:\BTC-strategieE\start.bat`

> La première fois : le script installe automatiquement toutes les dépendances (~2 min).

---

## Fonctionnalités

- **Prix BTC en direct** (Binance WebSocket, fallback synthétique si bloqué)
- **Score de signal 0–100** basé sur 10 conditions techniques
- **Multi-timeframe** : 15m, 1h, 4h, 1j
- **Titan Sniper** : MSB/CHoCH, CVD Absorption, Divergences RSI
- **Gestion du risque — Stratégie E** (optimisée par backtest 6 mois) :
  - SL = 1.8×ATR
  - TP1 = 1.0×R (40% de la position — rapide)
  - TP2 = 2.5×R (35%)
  - TP3 = 5.0×R (25% — laisse courir)
  - ⚡ Breakeven automatique dès TP1 atteint
- **Session de trading** : London / New York / Asia
- **Fear & Greed Index**
- **Backtest 6 mois** comparatif (6 stratégies)

---

## Résultats du backtest (Stratégie E vs baseline)

| Métrique | Baseline | Stratégie E |
|---|---|---|
| Win rate | 46.2% | **54.5%** |
| Sharpe | +1.47 | **+1.93** |
| Net P&L (1000€/trade) | +311€ | **+383€** |
| Max Drawdown | -8.8% | **-5.9%** |
| SL touchés | 62% | **35%** |

---

## Structure

```
D:\BTC-strategieE\
├── start.bat              ← Lanceur Windows (double-clic)
├── backend\
│   ├── main.py            ← FastAPI (port 8000)
│   ├── signal_engine.py   ← Moteur de signaux + Stratégie E
│   ├── indicators.py      ← RSI, MACD, BB, ADX, EMA, Stoch...
│   ├── backtest.py        ← Backtest 6 mois (6 stratégies)
│   └── requirements.txt
└── frontend\
    ├── src\
    │   ├── App.js
    │   ├── components\
    │   │   ├── LiveTab.js
    │   │   ├── ChartTab.js
    │   │   └── HistoryTab.js
    │   └── hooks\
    │       └── useWebSocket.js
    └── package.json
```

---

## Accès

| Service | URL |
|---|---|
| Application | http://localhost:3000 |
| API Backend | http://localhost:8000 |
| Documentation API | http://localhost:8000/docs |

---

## Lancer le backtest

```powershell
cd D:\BTC-strategieE\backend
.venv\Scripts\activate
python backtest.py
```

## Arrêter le programme

Fermer les deux fenêtres noires intitulées **"BTC Advisor — Backend"** et **"BTC Advisor — Frontend"**.
