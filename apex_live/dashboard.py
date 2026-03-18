"""
apex_live/dashboard.py — Dashboard web APEX Bot (http://localhost:8080)
Aucune dépendance externe. Lance dans un second terminal :
  python apex_live/dashboard.py
"""

import json, os, time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

STATE_FILE  = "apex_live/state.json"
LOG_FILE    = "apex_live/trades.jsonl"
BOT_LOG     = "apex_live/apex_live.log"
PORT        = 8080


def _read_state():
    if not os.path.exists(STATE_FILE):
        return None
    with open(STATE_FILE, "r") as f:
        return json.load(f)


def _read_trades(n=10):
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE, "r") as f:
        lines = f.read().strip().splitlines()
    trades = []
    for line in reversed(lines[-n:]):
        try:
            trades.append(json.loads(line))
        except Exception:
            pass
    return list(reversed(trades))


def _read_log(n=30):
    if not os.path.exists(BOT_LOG):
        return []
    with open(BOT_LOG, "r", encoding="utf-8", errors="replace") as f:
        lines = f.read().strip().splitlines()
    return lines[-n:]


def _bot_running():
    """Vérifie si le log a été modifié dans les 3 dernières minutes."""
    if not os.path.exists(BOT_LOG):
        return False
    return (time.time() - os.path.getmtime(BOT_LOG)) < 180


def _fmt_ts(ts):
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _pnl_color(val):
    if val is None:
        return "#888"
    return "#00e676" if val >= 0 else "#ff5252"


def render_html():
    state  = _read_state()
    trades = _read_trades(15)
    logs   = _read_log(40)
    running = _bot_running()

    stats   = state["stats"] if state else {"n": 0, "wins": 0, "pnl_eur": 0.0}
    pos     = state["position"] if state else None
    wr      = (stats["wins"] / stats["n"] * 100) if stats["n"] > 0 else 0.0
    pos_active = pos and pos.get("active")

    # ── Statut bot ─────────────────────────────────────────────
    status_color = "#00e676" if running else "#ff5252"
    status_txt   = "EN LIGNE" if running else "HORS LIGNE"

    # ── Position ───────────────────────────────────────────────
    if pos_active:
        direction = pos["direction"]
        dir_color = "#00e676" if direction == "BUY" else "#ff5252"
        entry_ts  = _fmt_ts(pos.get("entry_time"))
        elapsed_h = (time.time() - pos["entry_time"]) / 3600 if pos.get("entry_time") else 0
        pos_html = f"""
        <div class="card pos-card">
          <h2>Position ouverte</h2>
          <div class="pos-dir" style="color:{dir_color}">{'▲' if direction=='BUY' else '▼'} {direction}</div>
          <table class="info-table">
            <tr><td>Entrée</td><td>{pos['entry_price']:,.1f} $</td></tr>
            <tr><td>SL</td><td style="color:#ff5252">{pos['sl_price']:,.1f} $</td></tr>
            <tr><td>TP1</td><td style="color:#ffab40">{pos['tp1_price']:,.1f} $
              {'<span class="badge ok">OK</span>' if pos.get("tp1_done") else ''}</td></tr>
            <tr><td>TP2</td><td style="color:#69f0ae">{pos['tp2_price']:,.1f} $
              {'<span class="badge ok">OK</span>' if pos.get("tp2_done") else ''}</td></tr>
            <tr><td>TP3</td><td style="color:#00e676">{pos['tp3_price']:,.1f} $</td></tr>
            <tr><td>Ouvert</td><td>{entry_ts} ({elapsed_h:.1f}h)</td></tr>
          </table>
        </div>"""
    else:
        pos_html = """
        <div class="card pos-card neutral">
          <h2>Position</h2>
          <div class="pos-dir" style="color:#888">— Aucune position —</div>
          <p style="color:#666;margin-top:12px">En attente de signal APEX v2</p>
        </div>"""

    # ── Historique trades ──────────────────────────────────────
    if trades:
        rows = ""
        for t in trades:
            pnl = t.get("pnl_eur", 0)
            pct = t.get("pnl_pct", 0)
            col = "#00e676" if pnl >= 0 else "#ff5252"
            icon = "✓" if pnl >= 0 else "✗"
            tps  = f"{'TP1 ' if t.get('tp1') else ''}{'TP2' if t.get('tp2') else ''}".strip() or "—"
            rows += f"""<tr>
              <td style="color:{col}">{icon}</td>
              <td>{_fmt_ts(t.get('ts'))}</td>
              <td>{t.get('direction','')}</td>
              <td>{t.get('entry',0):,.0f}</td>
              <td>{t.get('exit',0):,.0f}</td>
              <td>{t.get('reason','')}</td>
              <td>{tps}</td>
              <td style="color:{col}">{pct:+.2f}%</td>
              <td style="color:{col}">{pnl:+.0f}€</td>
            </tr>"""
        trades_html = f"""
        <table class="trades-table">
          <thead><tr>
            <th></th><th>Date</th><th>Dir.</th><th>Entrée</th><th>Sortie</th>
            <th>Raison</th><th>TPs</th><th>PnL %</th><th>PnL €</th>
          </tr></thead>
          <tbody>{rows}</tbody>
        </table>"""
    else:
        trades_html = "<p style='color:#666;text-align:center;padding:20px'>Aucun trade enregistré</p>"

    # ── Log console ────────────────────────────────────────────
    log_lines = ""
    for line in logs:
        if "[ERROR]" in line:
            col = "#ff5252"
        elif "SIGNAL" in line or "TP" in line or "SL" in line or "CLOTURE" in line or "ENTREE" in line:
            col = "#ffab40"
        elif "Pas de signal" in line:
            col = "#555"
        else:
            col = "#aaa"
        import html
        log_lines += f'<div style="color:{col}">{html.escape(line)}</div>'

    # ── HTML complet ───────────────────────────────────────────
    pnl_color = _pnl_color(stats["pnl_eur"])
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>APEX Bot Dashboard</title>
<style>
  * {{ box-sizing:border-box; margin:0; padding:0 }}
  body {{ background:#0d0d0d; color:#e0e0e0; font-family:'Segoe UI',monospace; padding:16px }}
  h1 {{ font-size:1.4rem; margin-bottom:16px; color:#fff }}
  h2 {{ font-size:0.95rem; color:#888; margin-bottom:12px; text-transform:uppercase; letter-spacing:1px }}
  .header {{ display:flex; align-items:center; gap:16px; margin-bottom:20px }}
  .status-dot {{ width:10px; height:10px; border-radius:50%; background:{status_color}; display:inline-block }}
  .status-txt {{ color:{status_color}; font-size:0.85rem; font-weight:bold }}
  .grid {{ display:grid; grid-template-columns:280px 1fr; gap:16px; margin-bottom:16px }}
  .card {{ background:#1a1a1a; border:1px solid #2a2a2a; border-radius:8px; padding:16px }}
  .stats-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:16px }}
  .stat {{ background:#1a1a1a; border:1px solid #2a2a2a; border-radius:8px; padding:12px; text-align:center }}
  .stat-val {{ font-size:1.6rem; font-weight:bold; margin-bottom:2px }}
  .stat-lbl {{ font-size:0.75rem; color:#666 }}
  .pos-dir {{ font-size:2rem; font-weight:bold; text-align:center; padding:12px 0 }}
  .info-table {{ width:100%; border-collapse:collapse; font-size:0.88rem }}
  .info-table td {{ padding:5px 4px; border-bottom:1px solid #222 }}
  .info-table td:first-child {{ color:#666; width:55px }}
  .badge {{ display:inline-block; background:#1b5e20; color:#69f0ae; border-radius:3px;
            padding:1px 5px; font-size:0.7rem; margin-left:6px }}
  .neutral {{ opacity:0.6 }}
  .trades-table {{ width:100%; border-collapse:collapse; font-size:0.82rem }}
  .trades-table th {{ color:#555; font-weight:normal; padding:6px 8px;
                      text-align:left; border-bottom:1px solid #2a2a2a }}
  .trades-table td {{ padding:6px 8px; border-bottom:1px solid #1e1e1e }}
  .log-box {{ background:#111; border:1px solid #2a2a2a; border-radius:8px; padding:12px;
              font-size:0.75rem; line-height:1.6; height:220px; overflow-y:auto;
              font-family:monospace }}
  .refresh-note {{ color:#444; font-size:0.72rem; text-align:right; margin-top:8px }}
</style>
</head>
<body>
<div class="header">
  <h1>APEX Bot v2 — BTCUSDT</h1>
  <span class="status-dot"></span>
  <span class="status-txt">{status_txt}</span>
</div>

<div class="stats-grid">
  <div class="stat">
    <div class="stat-val" style="color:{pnl_color}">{stats['pnl_eur']:+.0f}€</div>
    <div class="stat-lbl">P&amp;L total</div>
  </div>
  <div class="stat">
    <div class="stat-val" style="color:#64b5f6">{wr:.0f}%</div>
    <div class="stat-lbl">Win Rate ({stats['wins']}/{stats['n']} trades)</div>
  </div>
</div>

<div class="grid">
  {pos_html}
  <div class="card">
    <h2>Derniers trades</h2>
    {trades_html}
  </div>
</div>

<div class="card">
  <h2>Log en direct</h2>
  <div class="log-box">{log_lines}</div>
</div>

<p class="refresh-note">Actualisation automatique toutes les 30 secondes</p>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        content = render_html().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *args):
        pass  # Silence les logs HTTP


if __name__ == "__main__":
    print(f"Dashboard APEX : http://localhost:{PORT}")
    print("Ctrl+C pour arreter")
    HTTPServer(("", PORT), Handler).serve_forever()
