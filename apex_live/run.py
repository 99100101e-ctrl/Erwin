"""
apex_live/run.py — Lance le bot APEX + dashboard en un seul fichier

Usage :
  python apex_live/run.py

Ouvre ensuite http://localhost:8080 dans ton navigateur.
Ctrl+C pour tout arrêter.
"""

import sys, os, threading, time

# Ajoute apex_live/ au path pour les imports internes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Vérification dépendance ───────────────────────────────────────────────────
try:
    import requests
except ImportError:
    print("ERREUR : installe requests → pip install requests")
    sys.exit(1)

# ── Dashboard dans un thread séparé ──────────────────────────────────────────
def _start_dashboard():
    from http.server import HTTPServer
    import dashboard as dash
    print("Dashboard : http://localhost:8080")
    HTTPServer(("", dash.PORT), dash.Handler).serve_forever()

t = threading.Thread(target=_start_dashboard, daemon=True)
t.start()
time.sleep(0.5)   # laisse le serveur démarrer

# ── Bot dans le thread principal ─────────────────────────────────────────────
import apex_live as bot
bot.main()
