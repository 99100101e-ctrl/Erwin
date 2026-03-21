"""
Trade Tracker — Journalise chaque trade en CSV et calcule les stats en temps réel.

Fonctionnalités :
  - Log chaque entrée/sortie dans trades.csv
  - Calcul win rate, profit factor, max drawdown, Sharpe simplifié
  - Résumé P&L quotidien
  - Commande /stats pour Telegram
"""

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

STATE_DIR = Path(__file__).parent
TRADES_CSV = STATE_DIR / "trades.csv"
EQUITY_FILE = STATE_DIR / "equity_state.json"

CSV_HEADERS = [
    "id", "direction", "timeframe", "entry_price", "exit_price",
    "sl", "tp", "entry_time", "exit_time", "exit_reason",
    "pnl_pct", "pnl_usd", "equity_after", "risk_pct",
]

log = logging.getLogger(__name__)


def _ensure_csv():
    """Crée le fichier CSV avec les headers s'il n'existe pas."""
    if not TRADES_CSV.exists():
        with open(TRADES_CSV, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)


def _next_trade_id() -> int:
    """Retourne le prochain ID de trade."""
    _ensure_csv()
    count = 0
    with open(TRADES_CSV, "r") as f:
        reader = csv.reader(f)
        next(reader, None)  # skip header
        for _ in reader:
            count += 1
    return count + 1


def log_entry(direction: str, timeframe: str, entry_price: float,
              sl: float, tp: float, risk_pct: float, equity: float) -> int:
    """Log l'ouverture d'un trade. Retourne le trade ID."""
    _ensure_csv()
    trade_id = _next_trade_id()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    with open(TRADES_CSV, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            trade_id, direction, timeframe, f"{entry_price:.2f}", "",
            f"{sl:.2f}", f"{tp:.2f}" if tp > 0 else "ST Flip",
            now, "", "", "", "", f"{equity:.2f}", f"{risk_pct:.1f}",
        ])

    log.info("Trade #%d ouvert: %s @ %.2f", trade_id, direction, entry_price)
    return trade_id


def log_exit(trade_id: int, exit_price: float, exit_reason: str,
             pnl_pct: float, pnl_usd: float, equity_after: float):
    """Met à jour le trade avec les infos de sortie."""
    _ensure_csv()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    rows = []
    with open(TRADES_CSV, "r") as f:
        reader = csv.reader(f)
        rows = list(reader)

    for row in rows[1:]:  # skip header
        if row[0] == str(trade_id):
            row[4] = f"{exit_price:.2f}"       # exit_price
            row[8] = now                        # exit_time
            row[9] = exit_reason                # exit_reason
            row[10] = f"{pnl_pct:.2f}"         # pnl_pct
            row[11] = f"{pnl_usd:.2f}"         # pnl_usd
            row[12] = f"{equity_after:.2f}"    # equity_after
            break

    with open(TRADES_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)

    log.info("Trade #%d fermé: %s | PnL: %+.2f%%", trade_id, exit_reason, pnl_pct)


def get_closed_trades() -> list[dict]:
    """Retourne tous les trades fermés (avec exit_price renseigné)."""
    _ensure_csv()
    trades = []
    with open(TRADES_CSV, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["exit_price"]:
                trades.append(row)
    return trades


def compute_stats() -> dict:
    """Calcule les statistiques globales de trading."""
    trades = get_closed_trades()

    if not trades:
        return {
            "total_trades": 0,
            "message": "Aucun trade fermé pour le moment.",
        }

    pnls = [float(t["pnl_pct"]) for t in trades]
    pnl_usds = [float(t["pnl_usd"]) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    total = len(pnls)
    win_rate = len(wins) / total * 100 if total > 0 else 0
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    gross_profit = sum(w for w in pnl_usds if w > 0)
    gross_loss = abs(sum(l for l in pnl_usds if l < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Max drawdown (sur equity)
    equities = [float(t["equity_after"]) for t in trades if t["equity_after"]]
    max_dd = 0
    if equities:
        peak = equities[0]
        for eq in equities:
            peak = max(peak, eq)
            dd = (peak - eq) / peak * 100
            max_dd = max(max_dd, dd)

    # Net P&L
    net_pnl_usd = sum(pnl_usds)
    net_pnl_pct = sum(pnls)

    # Streak
    current_streak = 0
    max_win_streak = 0
    max_loss_streak = 0
    streak = 0
    for p in pnls:
        if p > 0:
            streak = streak + 1 if streak > 0 else 1
            max_win_streak = max(max_win_streak, streak)
        else:
            streak = streak - 1 if streak < 0 else -1
            max_loss_streak = max(max_loss_streak, abs(streak))
    current_streak = streak

    # Trades aujourd'hui
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_trades = [t for t in trades if t["exit_time"].startswith(today)]
    today_pnl = sum(float(t["pnl_usd"]) for t in today_trades)

    return {
        "total_trades": total,
        "win_rate": win_rate,
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "profit_factor": profit_factor,
        "net_pnl_usd": net_pnl_usd,
        "net_pnl_pct": net_pnl_pct,
        "max_drawdown_pct": max_dd,
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "current_streak": current_streak,
        "today_trades": len(today_trades),
        "today_pnl_usd": today_pnl,
        "last_equity": equities[-1] if equities else 0,
    }


def format_stats_telegram() -> str:
    """Formate les stats pour un message Telegram."""
    s = compute_stats()

    if s["total_trades"] == 0:
        return "\U0001F4CA <b>Stats</b>\n\nAucun trade ferm\u00e9 pour le moment."

    pf_str = f"{s['profit_factor']:.2f}" if s["profit_factor"] != float("inf") else "\u221e"
    streak_emoji = "\U0001F525" if s["current_streak"] > 0 else "\U0001F9CA"

    return (
        "\U0001F4CA <b>Phantom Edge V14 \u2014 Stats</b>\n"
        "\n"
        f"\U0001F4B0 <b>P&L Net</b>: <code>${s['net_pnl_usd']:+,.2f}</code> ({s['net_pnl_pct']:+.2f}%)\n"
        f"\U0001F3AF <b>Win Rate</b>: {s['win_rate']:.1f}% ({len([t for t in get_closed_trades() if float(t['pnl_pct']) > 0])}/{s['total_trades']})\n"
        f"\U0001F4C8 Avg Win: {s['avg_win_pct']:+.2f}% | Avg Loss: {s['avg_loss_pct']:.2f}%\n"
        f"\U0001F4CA Profit Factor: {pf_str}\n"
        f"\U0001F4C9 Max Drawdown: {s['max_drawdown_pct']:.2f}%\n"
        f"\n"
        f"{streak_emoji} Streak: {s['current_streak']:+d} | "
        f"Best: {s['max_win_streak']}W / {s['max_loss_streak']}L\n"
        f"\U0001F4B5 Equity: <code>${s['last_equity']:,.2f}</code>\n"
        f"\n"
        f"\U0001F4C5 <b>Aujourd'hui</b>: {s['today_trades']} trades | "
        f"<code>${s['today_pnl_usd']:+,.2f}</code>\n"
    )


def format_daily_summary() -> str:
    """Résumé de fin de journée."""
    trades = get_closed_trades()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_trades = [t for t in trades if t["exit_time"].startswith(today)]

    if not today_trades:
        return (
            "\U0001F4C5 <b>R\u00e9sum\u00e9 du jour</b>\n"
            f"\n{today}\nAucun trade aujourd'hui."
        )

    pnls = [float(t["pnl_usd"]) for t in today_trades]
    net = sum(pnls)
    wins = sum(1 for p in pnls if p > 0)
    emoji = "\U00002705" if net >= 0 else "\U0000274C"

    details = []
    for t in today_trades:
        d = "\U0001F7E2" if float(t["pnl_pct"]) > 0 else "\U0001F534"
        details.append(
            f"  {d} {t['direction']} @ {t['entry_price']} \u2192 {t['exit_price']} "
            f"| {float(t['pnl_pct']):+.2f}% (${float(t['pnl_usd']):+,.2f})"
        )

    return (
        f"\U0001F4C5 <b>R\u00e9sum\u00e9 du jour</b> \u2014 {today}\n"
        f"\n"
        f"{emoji} P&L: <code>${net:+,.2f}</code> | {wins}/{len(today_trades)} wins\n"
        f"\n"
        + "\n".join(details)
    )
