"""
Notifications Telegram pour les signaux Erwin Strategy 1H.
Envoie des alertes formatees pour chaque entree (LONG/SHORT)
avec les niveaux SL, TP et le dashboard du marche.
"""

import requests
from . import config as cfg


def send_telegram(message: str) -> bool:
    """Envoie un message Telegram. Retourne True si succes."""
    if not cfg.TELEGRAM_TOKEN or not cfg.TELEGRAM_CHAT_ID:
        print("[TELEGRAM] Token ou Chat ID manquant — message non envoye.")
        return False

    url = f"https://api.telegram.org/bot{cfg.TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": cfg.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"[TELEGRAM] Erreur envoi : {e}")
        return False


def format_entry_alert(result: dict) -> str:
    """Formate un message d'alerte d'entree en position."""
    sig = result["signal"]
    emoji = "\U0001F7E2" if sig == "LONG" else "\U0001F534"  # green / red circle
    direction = "ACHAT (LONG)" if sig == "LONG" else "VENTE (SHORT)"

    lines = [
        f"{emoji} <b>SIGNAL {direction}</b>",
        f"",
        f"<b>Paire :</b> {cfg.SYMBOL}",
        f"<b>Timeframe :</b> {cfg.TIMEFRAME}",
        f"<b>Prix :</b> {result['close']:.2f}",
        f"<b>Type :</b> {result['signal_type']}",
        f"",
    ]

    if result.get("sl"):
        sl_val = float(result["sl"])
        lines.append(f"\U0001F6D1 <b>Stop-Loss :</b> {sl_val:.2f} (-{cfg.SL_PCT}%)")
    if result.get("tp"):
        tp_val = float(result["tp"])
        lines.append(f"\U0001F3AF <b>Take-Profit :</b> {tp_val:.2f} (+{cfg.TP_PCT}%)")

    lines += [
        f"",
        f"<b>--- Dashboard ---</b>",
        f"Marche : {result['market_state']}",
        f"Score Bull : {result['score_bull']} / 9",
        f"ADX : {result['adx']} | RSI : {result['rsi']}",
        f"Kijun : {result['kijun']} | Tenkan : {result['tenkan']}",
        f"EMA200 : {result['ema200']}",
        f"",
        f"<i>Erwin Strategy 1H — {result['timestamp']}</i>",
    ]

    return "\n".join(lines)


def format_exit_alert(direction: str, close_price: float, reason: str, entry_price: float = None) -> str:
    """Formate un message d'alerte de sortie de position."""
    emoji = "\U000026A0"  # warning sign

    lines = [
        f"{emoji} <b>SORTIE DE POSITION</b>",
        f"",
        f"<b>Paire :</b> {cfg.SYMBOL}",
        f"<b>Direction :</b> {direction}",
        f"<b>Prix de sortie :</b> {close_price:.2f}",
        f"<b>Raison :</b> {reason}",
    ]

    if entry_price:
        pnl_pct = ((close_price - entry_price) / entry_price) * 100
        if direction == "SHORT":
            pnl_pct = -pnl_pct
        pnl_emoji = "\U00002705" if pnl_pct > 0 else "\U0000274C"
        lines.append(f"{pnl_emoji} <b>P&L :</b> {pnl_pct:+.2f}%")

    lines += [
        f"",
        f"<i>Erwin Strategy 1H</i>",
    ]

    return "\n".join(lines)


def notify_entry(result: dict) -> bool:
    """Envoie une alerte Telegram pour une entree en position."""
    msg = format_entry_alert(result)
    return send_telegram(msg)


def notify_exit(direction: str, close_price: float, reason: str, entry_price: float = None) -> bool:
    """Envoie une alerte Telegram pour une sortie de position."""
    msg = format_exit_alert(direction, close_price, reason, entry_price)
    return send_telegram(msg)
