"""
Notifications Telegram pour les signaux Erwin Strategy 1H.
Envoie des alertes formatees pour chaque entree (LONG/SHORT)
avec les niveaux SL, TP et le dashboard du marche.
Supporte la commande /status et le resume quotidien.
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


def format_conditions(conditions: list) -> str:
    """Formate la liste des conditions remplies / non remplies."""
    lines = []
    for c in conditions:
        icon = "\u2705" if c["ok"] else "\u274C"
        lines.append(f"{icon} {c['nom']}")
    return "\n".join(lines)


def format_entry_alert(result: dict) -> str:
    """Formate un message d'alerte d'entree en position."""
    sig = result["signal"]
    emoji = "\U0001F7E2" if sig == "LONG" else "\U0001F534"
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
        f"<b>--- Conditions ({result['score_bull']}/9) ---</b>",
        format_conditions(result["conditions"]),
        f"",
        f"<b>Marche :</b> {result['market_state']}",
        f"",
        f"<i>Erwin Strategy 1H — {result['timestamp']}</i>",
    ]

    return "\n".join(lines)


def format_exit_alert(direction: str, close_price: float, reason: str, entry_price: float = None) -> str:
    """Formate un message d'alerte de sortie de position."""
    emoji = "\U000026A0"

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
        pnl_emoji = "\u2705" if pnl_pct > 0 else "\u274C"
        lines.append(f"{pnl_emoji} <b>P&L :</b> {pnl_pct:+.2f}%")

    lines += [
        f"",
        f"<i>Erwin Strategy 1H</i>",
    ]

    return "\n".join(lines)


def format_status(result: dict, tracker=None) -> str:
    """Formate le message /status avec toutes les infos de la strategie."""
    lines = [
        f"\U0001F4CA <b>ERWIN STRATEGY 1H — STATUS</b>",
        f"",
        f"<b>Paire :</b> {cfg.SYMBOL}",
        f"<b>Timeframe :</b> {cfg.TIMEFRAME}",
        f"<b>Prix :</b> {result['close']:.2f}",
        f"<b>Marche :</b> {result['market_state']}",
        f"",
    ]

    # Position en cours
    if tracker and tracker.active:
        pnl_pct = ((result['close'] - tracker.entry_price) / tracker.entry_price) * 100
        if tracker.direction == "SHORT":
            pnl_pct = -pnl_pct
        pnl_emoji = "\u2705" if pnl_pct > 0 else "\u274C"
        lines += [
            f"\U0001F4B0 <b>Position ouverte : {tracker.direction}</b>",
            f"  Entree : {tracker.entry_price:.2f}",
            f"  SL : {tracker.sl:.2f}" if tracker.sl else "",
            f"  TP : {tracker.tp:.2f}" if tracker.tp else "",
            f"  {pnl_emoji} P&L latent : {pnl_pct:+.2f}%",
            f"",
        ]
    else:
        lines += [
            f"\U0001F4AD <b>Aucune position ouverte</b>",
            f"",
        ]

    # Conditions detaillees
    lines += [
        f"<b>--- Conditions LONG ({result['score_bull']}/9) ---</b>",
        format_conditions(result["conditions"]),
        f"",
        f"<b>--- Indicateurs ---</b>",
        f"ADX : {result['adx']}",
        f"RSI : {result['rsi']}",
        f"ATR : {result['atr']}",
        f"BB Width : {result['bb_width']}%",
        f"Kijun : {result['kijun']} | Tenkan : {result['tenkan']}",
        f"EMA200 : {result['ema200']}",
        f"",
        f"<i>{result['timestamp']}</i>",
    ]

    return "\n".join([l for l in lines if l is not None])


def format_daily_summary(result: dict, daily_stats: dict) -> str:
    """Formate le resume quotidien de 22h."""
    lines = [
        f"\U0001F319 <b>RESUME JOURNALIER — ERWIN 1H</b>",
        f"",
        f"<b>Paire :</b> {cfg.SYMBOL}",
        f"<b>Prix actuel :</b> {result['close']:.2f}",
        f"<b>Marche :</b> {result['market_state']}",
        f"",
        f"<b>--- Activite du jour ---</b>",
        f"Signaux LONG : {daily_stats['nb_long']}",
        f"Signaux SHORT : {daily_stats['nb_short']}",
        f"Entrees : {daily_stats['nb_entries']}",
        f"Sorties : {daily_stats['nb_exits']}",
    ]

    if daily_stats["trades"]:
        lines.append(f"")
        lines.append(f"<b>--- Trades du jour ---</b>")
        for t in daily_stats["trades"]:
            pnl_emoji = "\u2705" if t["pnl_pct"] > 0 else "\u274C"
            lines.append(
                f"{pnl_emoji} {t['direction']} @ {t['entry']:.2f} → {t['exit']:.2f} ({t['pnl_pct']:+.2f}%) — {t['reason']}"
            )

    total_pnl = sum(t["pnl_pct"] for t in daily_stats["trades"]) if daily_stats["trades"] else 0
    lines += [
        f"",
        f"<b>P&L total du jour : {total_pnl:+.2f}%</b>",
        f"",
        f"<b>--- Conditions actuelles ({result['score_bull']}/9) ---</b>",
        format_conditions(result["conditions"]),
        f"",
        f"<i>Erwin Strategy 1H — Resume 22h</i>",
    ]

    return "\n".join(lines)


def notify_entry(result: dict) -> bool:
    msg = format_entry_alert(result)
    return send_telegram(msg)


def notify_exit(direction: str, close_price: float, reason: str, entry_price: float = None) -> bool:
    msg = format_exit_alert(direction, close_price, reason, entry_price)
    return send_telegram(msg)


def notify_status(result: dict, tracker=None) -> bool:
    msg = format_status(result, tracker)
    return send_telegram(msg)


def notify_daily_summary(result: dict, daily_stats: dict) -> bool:
    msg = format_daily_summary(result, daily_stats)
    return send_telegram(msg)


def get_telegram_updates(offset: int = None) -> list:
    """Recupere les messages envoyes au bot (pour detecter /status)."""
    if not cfg.TELEGRAM_TOKEN:
        return []

    url = f"https://api.telegram.org/bot{cfg.TELEGRAM_TOKEN}/getUpdates"
    params = {"timeout": 1}
    if offset:
        params["offset"] = offset

    try:
        resp = requests.get(url, params=params, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return data.get("result", [])
    except requests.RequestException:
        return []
