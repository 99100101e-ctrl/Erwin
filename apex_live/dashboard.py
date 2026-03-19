"""
apex_live/dashboard.py — Dashboard web APEX Bot v2 (http://localhost:8080)

v2 — Améliorations :
  • Graphique d'équité SVG (courbe PnL cumulatif trade par trade)
  • Stats enrichies : Sharpe, Max Drawdown, R/R ratio, gain/perte moyens, streak
  • Prix BTC en direct via Binance public API (JavaScript)
  • Actualisation AJAX silencieuse toutes les 15s (sans rechargement de page)

Aucune dépendance externe. Lance :
  python apex_live/dashboard.py
"""

import json, os, time, math, html as _html
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

STATE_FILE   = "apex_live/state.json"
LOG_FILE     = "apex_live/trades.jsonl"
SIGNALS_FILE = "apex_live/signals.jsonl"
BOT_LOG      = "apex_live/apex_live.log"
PORT         = 8080


# ─────────────────────────────────────── Lecture fichiers ────────────────────

def _read_state():
    if not os.path.exists(STATE_FILE):
        return None
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def _read_all_trades():
    """Retourne tous les trades dans l'ordre chronologique."""
    if not os.path.exists(LOG_FILE):
        return []
    trades = []
    with open(LOG_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    trades.append(json.loads(line))
                except Exception:
                    pass
    return trades


def _read_signals(n=50):
    if not os.path.exists(SIGNALS_FILE):
        return []
    with open(SIGNALS_FILE) as f:
        lines = [l.strip() for l in f if l.strip()]
    out = []
    for line in lines[-n:]:
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return list(reversed(out))


def _read_log(n=40):
    if not os.path.exists(BOT_LOG):
        return []
    with open(BOT_LOG, encoding="utf-8", errors="replace") as f:
        lines = f.read().strip().splitlines()
    return lines[-n:]


def _bot_running():
    if not os.path.exists(BOT_LOG):
        return False
    return (time.time() - os.path.getmtime(BOT_LOG)) < 180


def _fmt_ts(ts):
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d/%m %H:%M")


def _pnl_color(val):
    if val is None:
        return "#888"
    return "#00e676" if val >= 0 else "#ff5252"


# ─────────────────────────────────────── Stats avancées ──────────────────────

def _compute_stats(trades):
    """Calcule stats enrichies depuis la liste complète des trades."""
    if not trades:
        return {
            "sharpe": None, "mdd_pct": 0.0, "mdd_eur": 0.0,
            "avg_win": 0.0, "avg_loss": 0.0, "rr": 0.0,
            "streak_cur": 0, "streak_best": 0,
        }

    returns   = [t.get("pnl_pct", 0) / 100 for t in trades]
    wins_eur  = [t["pnl_eur"] for t in trades if t.get("pnl_eur", 0) > 0]
    losses_eur = [t["pnl_eur"] for t in trades if t.get("pnl_eur", 0) < 0]

    # Sharpe (non annualisé, basé sur les trades)
    n = len(returns)
    sharpe = None
    if n >= 2:
        mean_r = sum(returns) / n
        var    = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
        std_r  = math.sqrt(var) if var > 0 else 0
        if std_r > 0:
            sharpe = round(mean_r / std_r * math.sqrt(n), 2)

    # Max Drawdown (sur capital initial 10 000)
    cum, peak, max_dd = 0.0, 0.0, 0.0
    for t in trades:
        cum  += t.get("pnl_eur", 0)
        peak  = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    initial = 10000.0
    mdd_pct = round(max_dd / initial * 100, 1)

    # Gain moyen / perte moyenne / R/R
    avg_win  = round(sum(wins_eur)   / len(wins_eur),  0) if wins_eur  else 0.0
    avg_loss = round(sum(losses_eur) / len(losses_eur), 0) if losses_eur else 0.0
    rr = round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else 0.0

    # Streak actuel (+ wins consécutifs / - pertes consécutives)
    streak_cur = 0
    last_won = None
    for t in reversed(trades):
        won = t.get("pnl_eur", 0) > 0
        if last_won is None:
            last_won   = won
            streak_cur = 1 if won else -1
        elif won == last_won:
            streak_cur += (1 if won else -1)
        else:
            break

    # Meilleur streak gagnant
    best = cur = 0
    for t in trades:
        if t.get("pnl_eur", 0) > 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0

    return {
        "sharpe":      sharpe,
        "mdd_pct":     mdd_pct,
        "mdd_eur":     round(max_dd, 0),
        "avg_win":     avg_win,
        "avg_loss":    avg_loss,
        "rr":          rr,
        "streak_cur":  streak_cur,
        "streak_best": best,
    }


# ─────────────────────────────────────── SVG équité ──────────────────────────

def _equity_svg(trades, width=700, height=130):
    """Génère un SVG de la courbe d'équité cumulée trade par trade."""
    if len(trades) < 2:
        return (
            f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">'
            f'<text x="50%" y="55%" fill="#444" text-anchor="middle" '
            f'font-family="monospace" font-size="13">Pas encore de données</text></svg>'
        )

    cum = 0.0
    series = [0.0]
    for t in trades:
        cum += t.get("pnl_eur", 0)
        series.append(cum)

    min_v = min(series)
    max_v = max(series)
    rng   = max_v - min_v or 1

    pl, pr, pt, pb = 38, 10, 10, 20   # padding left/right/top/bottom
    pw = width  - pl - pr
    ph = height - pt - pb
    n  = len(series)

    def sx(i): return pl + i / (n - 1) * pw
    def sy(v): return pt + (1 - (v - min_v) / rng) * ph

    final_color = "#00e676" if series[-1] >= 0 else "#ff5252"

    # Zone remplie
    area_pts = f"{sx(0):.1f},{pt+ph:.1f}"
    for i, v in enumerate(series):
        area_pts += f" {sx(i):.1f},{sy(v):.1f}"
    area_pts += f" {sx(n-1):.1f},{pt+ph:.1f}"

    # Ligne
    line_pts = " ".join(f"{sx(i):.1f},{sy(v):.1f}" for i, v in enumerate(series))

    # Ligne zéro
    zero_line = ""
    if min_v < 0 < max_v:
        yy = sy(0)
        zero_line = (
            f'<line x1="{pl}" y1="{yy:.1f}" x2="{pl+pw}" y2="{yy:.1f}" '
            f'stroke="#333" stroke-width="1" stroke-dasharray="4,4"/>'
        )

    # Labels Y (min / 0 / max)
    y_labels = ""
    label_vals = sorted({round(min_v, 0), 0.0, round(max_v, 0)})
    for val in label_vals:
        yy = sy(val)
        if pt - 5 <= yy <= pt + ph + 5:
            col = "#00e676" if val > 0 else ("#ff5252" if val < 0 else "#555")
            y_labels += (
                f'<text x="{pl-4}" y="{yy+3:.1f}" fill="{col}" '
                f'font-size="9" text-anchor="end" font-family="monospace">'
                f'{val:+.0f}</text>'
            )

    # Dot + label dernier point
    lx, ly = sx(n - 1), sy(series[-1])
    last_dot = f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3.5" fill="{final_color}"/>'
    last_lbl = (
        f'<text x="{lx - 6:.1f}" y="{max(pt + 10, ly - 5):.1f}" '
        f'fill="{final_color}" font-size="10" text-anchor="end" font-family="monospace">'
        f'{series[-1]:+.0f}€</text>'
    )

    return f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="eg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{final_color}" stop-opacity="0.25"/>
      <stop offset="100%" stop-color="{final_color}" stop-opacity="0.02"/>
    </linearGradient>
  </defs>
  {zero_line}
  <polygon points="{area_pts}" fill="url(#eg)"/>
  <polyline points="{line_pts}" fill="none" stroke="{final_color}" stroke-width="2" stroke-linejoin="round"/>
  {last_dot}
  {y_labels}
  {last_lbl}
</svg>"""


# ─────────────────────────────────────── Fragments HTML ──────────────────────

def _render_position(pos, state):
    if pos and pos.get("active"):
        direction = pos["direction"]
        dir_color = "#00e676" if direction == "BUY" else "#ff5252"
        entry_ts  = _fmt_ts(pos.get("entry_time"))
        elapsed_h = (time.time() - pos["entry_time"]) / 3600 if pos.get("entry_time") else 0
        bal = state.get("paper_balance", 10000) if state else 10000
        return f"""<h2>Position ouverte</h2>
        <div class="pos-dir" style="color:{dir_color}">{'▲' if direction=='BUY' else '▼'} {direction}</div>
        <table class="info-table">
          <tr><td>Entrée</td><td>{pos['entry_price']:,.1f} $</td></tr>
          <tr><td>SL</td><td style="color:#ff5252">{pos['sl_price']:,.1f} $</td></tr>
          <tr><td>TP1</td><td style="color:#ffab40">{pos['tp1_price']:,.1f} $
            {'<span class="badge">✓</span>' if pos.get("tp1_done") else ''}</td></tr>
          <tr><td>TP2</td><td style="color:#69f0ae">{pos['tp2_price']:,.1f} $
            {'<span class="badge">✓</span>' if pos.get("tp2_done") else ''}</td></tr>
          <tr><td>TP3</td><td style="color:#00e676">{pos['tp3_price']:,.1f} $</td></tr>
          <tr><td>Durée</td><td>{elapsed_h:.1f}h · {entry_ts}</td></tr>
          <tr><td>Balance</td><td style="color:#64b5f6">{bal:,.0f} $</td></tr>
        </table>"""
    else:
        bal = state.get("paper_balance", 10000) if state else 10000
        return f"""<h2>Position</h2>
        <div class="pos-dir" style="color:#444">— Aucune —</div>
        <p style="color:#555;font-size:0.85rem;margin-top:8px">En attente de signal APEX v2</p>
        <p style="color:#64b5f6;font-size:0.85rem;margin-top:12px">Balance paper : {bal:,.0f} $</p>"""


def _render_trades(trades):
    if not trades:
        return "<p style='color:#555;text-align:center;padding:20px'>Aucun trade enregistré</p>"
    rows = ""
    for t in trades:
        pnl = t.get("pnl_eur", 0)
        pct = t.get("pnl_pct", 0)
        col = "#00e676" if pnl >= 0 else "#ff5252"
        icon = "✓" if pnl >= 0 else "✗"
        tp_badges = ""
        if t.get("tp1"):
            tp_badges += "<span class='tp-badge tp1'>TP1</span>"
        if t.get("tp2"):
            tp_badges += "<span class='tp-badge tp2'>TP2</span>"
        dir_col = "#00e676" if t.get("direction") == "BUY" else "#ff5252"
        reason_col = {
            "SL": "#ff5252", "TP3": "#00e676",
            "TIMEOUT": "#ffab40", "END": "#666",
        }.get(t.get("reason", ""), "#aaa")
        rows += f"""<tr>
          <td style="color:{col}">{icon}</td>
          <td style="color:#777">{_fmt_ts(t.get('ts'))}</td>
          <td style="color:{dir_col};font-weight:bold">{t.get('direction','')}</td>
          <td>{t.get('entry',0):,.0f}</td>
          <td>{t.get('exit',0):,.0f}</td>
          <td style="color:{reason_col}">{t.get('reason','')}</td>
          <td>{tp_badges}</td>
          <td style="color:{col};font-weight:bold">{pct:+.2f}%</td>
          <td style="color:{col};font-weight:bold">{pnl:+.0f}€</td>
        </tr>"""
    return f"""<table class="trades-table">
      <thead><tr>
        <th></th><th>Date</th><th>Dir.</th><th>Entrée</th><th>Sortie</th>
        <th>Raison</th><th>TPs</th><th>PnL%</th><th>PnL</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


def _render_signals(signals):
    if not signals:
        return "<p style='color:#555;text-align:center;padding:20px'>Aucun signal — le bot écrit ici dès le premier signal détecté</p>"
    rows = ""
    for s in signals:
        d   = s["direction"]
        col = "#00e676" if d == "BUY" else "#ff5252"
        arr = "▲" if d == "BUY" else "▼"
        mode_badge = {
            "SIGNAL_ONLY": "<span class='badge-mode sig'>SIGNAL</span>",
            "PAPER":       "<span class='badge-mode paper'>PAPER</span>",
            "LIVE":        "<span class='badge-mode live'>LIVE</span>",
        }.get(s.get("mode", ""), s.get("mode", ""))
        conf = s.get("confirmateurs", {})
        conf_icons = "".join(
            f'<span title="{_html.escape(str(k))}" '
            f'style="color:{"#00e676" if v else "#2a2a2a"};font-size:0.85rem">●</span>'
            for k, v in conf.items()
        )
        candle_dt = datetime.fromtimestamp(s["candle_ts"], tz=timezone.utc).strftime("%d/%m %H:00")
        rows += f"""<tr>
          <td style="color:{col};font-weight:bold">{arr} {d}</td>
          <td>{candle_dt}</td>
          <td>{mode_badge}</td>
          <td>{s['entry']:,.0f}</td>
          <td style="color:#ff5252">{s['sl']:,.0f}</td>
          <td style="color:#ffab40">{s['tp1']:,.0f}</td>
          <td style="color:#69f0ae">{s['tp2']:,.0f}</td>
          <td style="color:#00e676">{s['tp3']:,.0f}</td>
          <td style="color:#64b5f6">{s['score']}/{s['score_max']}</td>
          <td style="color:#aaa">{s['adx']:.0f}</td>
          <td style="color:#aaa">{s['rsi']:.0f}</td>
          <td style="letter-spacing:2px">{conf_icons}</td>
        </tr>"""
    return f"""<table class="trades-table">
      <thead><tr>
        <th>Direction</th><th>Bougie</th><th>Mode</th>
        <th>Entrée</th><th>SL</th><th>TP1</th><th>TP2</th><th>TP3</th>
        <th>Score</th><th>ADX</th><th>RSI</th><th>Conf.</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


def _render_log(logs):
    lines = ""
    for line in logs:
        if "[ERROR]" in line:
            col = "#ff5252"
        elif any(k in line for k in (
            "SIGNAL", "TP", " SL", "CLOTURE", "ENTREE", "▲", "▼",
            "✅", "❌", "🟡", "🟢", "🏆", "🔴", "▶",
        )):
            col = "#ffab40"
        elif "Pas de signal" in line:
            col = "#3a3a3a"
        else:
            col = "#888"
        lines += f'<div style="color:{col}">{_html.escape(line)}</div>'
    return lines


# ─────────────────────────────────────── Données API ─────────────────────────

def build_api_data():
    """Construit le dictionnaire complet pour le rendu et l'endpoint /api/data."""
    state      = _read_state()
    all_trades = _read_all_trades()
    recent_t   = list(reversed(all_trades[-20:])) if all_trades else []
    signals    = _read_signals(50)
    logs       = _read_log(40)
    running    = _bot_running()

    stats = state["stats"] if state else {"n": 0, "wins": 0, "pnl_eur": 0.0}
    pos   = state["position"] if state else None
    wr    = (stats["wins"] / stats["n"] * 100) if stats["n"] > 0 else 0.0
    adv   = _compute_stats(all_trades)

    return {
        # Statut
        "running":      running,
        "status_color": "#00e676" if running else "#ff5252",
        "status_txt":   "EN LIGNE" if running else "HORS LIGNE",
        # Stats de base
        "pnl_total":    stats["pnl_eur"],
        "pnl_color":    _pnl_color(stats["pnl_eur"]),
        "win_rate":     round(wr, 1),
        "n_trades":     stats["n"],
        "n_wins":       stats["wins"],
        # Stats avancées
        "sharpe":       adv["sharpe"],
        "mdd_pct":      adv["mdd_pct"],
        "mdd_eur":      adv["mdd_eur"],
        "avg_win":      adv["avg_win"],
        "avg_loss":     adv["avg_loss"],
        "rr":           adv["rr"],
        "streak_cur":   adv["streak_cur"],
        "streak_best":  adv["streak_best"],
        # Fragments HTML
        "position_html": _render_position(pos, state),
        "trades_html":   _render_trades(recent_t),
        "signals_html":  _render_signals(signals),
        "log_html":      _render_log(logs),
        "equity_svg":    _equity_svg(all_trades),
        "updated_at":    int(time.time()),
    }


# ─────────────────────────────────────── Page HTML ───────────────────────────

def render_page():
    """Page HTML complète, chargée une fois puis mise à jour par AJAX."""
    d = build_api_data()
    sharpe_txt = f"{d['sharpe']:.2f}" if d["sharpe"] is not None else "—"

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>APEX Bot v2 — Dashboard</title>
<style>
  * {{ box-sizing:border-box; margin:0; padding:0 }}
  body {{ background:#0a0a0a; color:#e0e0e0; font-family:'Segoe UI',monospace; padding:16px }}

  .header {{ display:flex; align-items:center; gap:12px; margin-bottom:20px; flex-wrap:wrap }}
  h1 {{ font-size:1.3rem; color:#fff; letter-spacing:1px }}
  h2 {{ font-size:0.8rem; color:#555; text-transform:uppercase;
        letter-spacing:1px; margin-bottom:12px }}
  .status-dot {{ width:10px; height:10px; border-radius:50%; display:inline-block;
                  transition:background 0.5s }}
  .status-txt {{ font-size:0.8rem; font-weight:bold }}
  .btc-price  {{ margin-left:auto; font-size:1.1rem; color:#fff; font-weight:bold }}
  .last-upd   {{ color:#3a3a3a; font-size:0.72rem }}

  .stats-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(115px,1fr));
                  gap:10px; margin-bottom:16px }}
  .stat {{ background:#141414; border:1px solid #1e1e1e; border-radius:8px;
           padding:12px; text-align:center }}
  .stat-val {{ font-size:1.45rem; font-weight:bold; line-height:1.2 }}
  .stat-lbl {{ font-size:0.68rem; color:#555; margin-top:3px }}

  .equity-card {{ background:#141414; border:1px solid #1e1e1e; border-radius:8px;
                   padding:14px; margin-bottom:16px; overflow:hidden }}

  .main-grid {{ display:grid; grid-template-columns:260px 1fr; gap:16px; margin-bottom:16px }}
  @media (max-width:720px) {{ .main-grid {{ grid-template-columns:1fr }} }}

  .card {{ background:#141414; border:1px solid #1e1e1e; border-radius:8px; padding:14px }}
  .pos-dir {{ font-size:1.8rem; font-weight:bold; text-align:center; padding:10px 0 }}
  .info-table {{ width:100%; border-collapse:collapse; font-size:0.85rem }}
  .info-table td {{ padding:5px 4px; border-bottom:1px solid #1a1a1a }}
  .info-table td:first-child {{ color:#555; width:58px }}
  .badge {{ display:inline-block; background:#1b5e20; color:#69f0ae;
            border-radius:3px; padding:1px 5px; font-size:0.7rem; margin-left:4px }}

  .section-card {{ background:#141414; border:1px solid #1e1e1e; border-radius:8px;
                    padding:14px; margin-bottom:16px }}
  .trades-wrap {{ overflow-x:auto }}
  .trades-table {{ width:100%; border-collapse:collapse; font-size:0.8rem }}
  .trades-table th {{ color:#444; font-weight:normal; padding:5px 8px;
                       text-align:left; border-bottom:1px solid #1e1e1e; white-space:nowrap }}
  .trades-table td {{ padding:5px 8px; border-bottom:1px solid #141414; white-space:nowrap }}
  .tp-badge {{ display:inline-block; border-radius:3px; padding:1px 4px;
                font-size:0.68rem; font-weight:bold; margin-right:2px }}
  .tp-badge.tp1 {{ background:#2a2000; color:#ffab40 }}
  .tp-badge.tp2 {{ background:#002a10; color:#69f0ae }}

  .badge-mode {{ display:inline-block; border-radius:3px; padding:1px 5px;
                  font-size:0.7rem; font-weight:bold }}
  .badge-mode.sig   {{ background:#1a2a3a; color:#64b5f6 }}
  .badge-mode.paper {{ background:#2a2a1a; color:#ffab40 }}
  .badge-mode.live  {{ background:#1a2a1a; color:#00e676 }}

  .log-box {{ background:#0d0d0d; border:1px solid #1a1a1a; border-radius:8px;
               padding:12px; font-size:0.72rem; line-height:1.7; height:200px;
               overflow-y:auto; font-family:monospace }}
</style>
</head>
<body>

<div class="header">
  <h1>APEX Bot v2 — BTC/USDT</h1>
  <span class="status-dot" id="status-dot" style="background:{d['status_color']}"></span>
  <span class="status-txt" id="status-txt" style="color:{d['status_color']}">{d['status_txt']}</span>
  <span class="btc-price">₿ <span id="btc-price">…</span></span>
  <span class="last-upd">mis à jour il y a <span id="upd-sec">0</span>s</span>
</div>

<!-- Stats enrichies -->
<div class="stats-grid">
  <div class="stat">
    <div class="stat-val" id="stat-pnl" style="color:{d['pnl_color']}">{d['pnl_total']:+.0f}€</div>
    <div class="stat-lbl">PnL Total</div>
  </div>
  <div class="stat">
    <div class="stat-val" id="stat-wr" style="color:#64b5f6">{d['win_rate']:.0f}%</div>
    <div class="stat-lbl">Win Rate ({d['n_wins']}/{d['n_trades']})</div>
  </div>
  <div class="stat">
    <div class="stat-val" id="stat-sharpe" style="color:#ce93d8">{sharpe_txt}</div>
    <div class="stat-lbl">Sharpe Ratio</div>
  </div>
  <div class="stat">
    <div class="stat-val" id="stat-mdd" style="color:#ff8a65">-{d['mdd_pct']:.1f}%</div>
    <div class="stat-lbl">Max Drawdown</div>
  </div>
  <div class="stat">
    <div class="stat-val" id="stat-avgwin" style="color:#00e676">+{d['avg_win']:.0f}€</div>
    <div class="stat-lbl">Gain moyen</div>
  </div>
  <div class="stat">
    <div class="stat-val" id="stat-avgloss" style="color:#ff5252">{d['avg_loss']:.0f}€</div>
    <div class="stat-lbl">Perte moy.</div>
  </div>
  <div class="stat">
    <div class="stat-val" id="stat-rr" style="color:#fff">{d['rr']:.2f}</div>
    <div class="stat-lbl">Ratio R/R</div>
  </div>
  <div class="stat">
    <div class="stat-val" id="stat-streak" style="color:#ffab40">{d['streak_best']}</div>
    <div class="stat-lbl">Meilleur streak</div>
  </div>
</div>

<!-- Graphique équité -->
<div class="equity-card">
  <h2>Courbe d'équité — PnL cumulatif (paper)</h2>
  <div id="equity-chart" style="overflow:hidden">{d['equity_svg']}</div>
</div>

<!-- Position + Trades -->
<div class="main-grid">
  <div class="card" id="position-card">{d['position_html']}</div>
  <div class="card">
    <h2>Derniers trades (20)</h2>
    <div class="trades-wrap" id="trades-wrap">{d['trades_html']}</div>
  </div>
</div>

<!-- Signaux -->
<div class="section-card">
  <h2>Journal des signaux</h2>
  <div class="trades-wrap" id="signals-wrap">{d['signals_html']}</div>
</div>

<!-- Log -->
<div class="section-card">
  <h2>Log en direct</h2>
  <div class="log-box" id="log-box">{d['log_html']}</div>
</div>

<script>
// ── Prix BTC live (Binance public API) ───────────────────────────────────────
async function fetchPrice() {{
  try {{
    const r = await fetch('https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT');
    const j = await r.json();
    const p = parseFloat(j.price);
    document.getElementById('btc-price').textContent =
      p.toLocaleString('fr-FR', {{minimumFractionDigits:1, maximumFractionDigits:1}}) + ' $';
  }} catch(e) {{}}
}}
fetchPrice();
setInterval(fetchPrice, 10000);

// ── Mise à jour AJAX toutes les 15s ──────────────────────────────────────────
let lastUpdate = Date.now();

async function updateData() {{
  try {{
    const r = await fetch('/api/data');
    if (!r.ok) return;
    const d = await r.json();

    // Statut bot
    document.getElementById('status-dot').style.background = d.status_color;
    document.getElementById('status-txt').style.color      = d.status_color;
    document.getElementById('status-txt').textContent      = d.status_txt;

    // Stats de base
    const sign = d.pnl_total >= 0 ? '+' : '';
    document.getElementById('stat-pnl').textContent  = sign + Math.round(d.pnl_total) + '€';
    document.getElementById('stat-pnl').style.color  = d.pnl_color;
    document.getElementById('stat-wr').textContent   = d.win_rate.toFixed(0) + '% (' + d.n_wins + '/' + d.n_trades + ')';

    // Stats avancées
    document.getElementById('stat-sharpe').textContent  = d.sharpe !== null ? d.sharpe.toFixed(2) : '—';
    document.getElementById('stat-mdd').textContent     = '-' + d.mdd_pct.toFixed(1) + '%';
    document.getElementById('stat-avgwin').textContent  = '+' + Math.round(d.avg_win) + '€';
    document.getElementById('stat-avgloss').textContent = Math.round(d.avg_loss) + '€';
    document.getElementById('stat-rr').textContent      = d.rr.toFixed(2);
    document.getElementById('stat-streak').textContent  = d.streak_best;

    // Fragments HTML
    document.getElementById('equity-chart').innerHTML  = d.equity_svg;
    document.getElementById('position-card').innerHTML = d.position_html;
    document.getElementById('trades-wrap').innerHTML   = d.trades_html;
    document.getElementById('signals-wrap').innerHTML  = d.signals_html;

    // Log : scroll vers le bas si déjà en bas
    const lb = document.getElementById('log-box');
    const atBottom = lb.scrollHeight - lb.scrollTop <= lb.clientHeight + 30;
    lb.innerHTML = d.log_html;
    if (atBottom) lb.scrollTop = lb.scrollHeight;

    lastUpdate = Date.now();
  }} catch(e) {{
    console.warn('Erreur mise à jour dashboard:', e);
  }}
}}

updateData();
setInterval(updateData, 15000);

// Compteur temps depuis dernière mise à jour
setInterval(() => {{
  document.getElementById('upd-sec').textContent =
    Math.round((Date.now() - lastUpdate) / 1000);
}}, 1000);
</script>
</body>
</html>"""


# ─────────────────────────────────────── Serveur HTTP ────────────────────────

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/data"):
            try:
                data    = build_api_data()
                content = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
            except Exception as e:
                content = json.dumps({"error": str(e)}).encode()
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
        else:
            try:
                content = render_page().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
            except Exception as e:
                content = f"<pre>Erreur: {_html.escape(str(e))}</pre>".encode()
                self.send_response(500)
                self.send_header("Content-Type", "text/html")

        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *args):
        pass  # Silence les logs HTTP


if __name__ == "__main__":
    print(f"Dashboard APEX v2 : http://localhost:{PORT}")
    print(f"Endpoints :")
    print(f"  GET /         → Dashboard complet")
    print(f"  GET /api/data → JSON temps réel (AJAX)")
    print("Ctrl+C pour arrêter")
    HTTPServer(("", PORT), Handler).serve_forever()
