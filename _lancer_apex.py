#!/usr/bin/env python3
"""
_lancer_apex.py — Lanceur APEX Bot v2

Lance automatiquement :
  1. Vérifie Python 3.8+
  2. Installe 'requests' si absent
  3. Démarre le dashboard  → http://localhost:8080
  4. Ouvre le navigateur   → http://localhost:8080
  5. Démarre le bot APEX dans le thread principal

Usage :
  python _lancer_apex.py          (Linux / Mac)
  double-clic sur _lancer_apex.bat (Windows)

Ctrl+C pour tout arrêter.
"""

import sys
import os
import subprocess
import threading
import time

# ── 1. Version Python ─────────────────────────────────────────────────────────
if sys.version_info < (3, 8):
    print("ERREUR : Python 3.8+ requis.")
    print(f"  Version actuelle : {sys.version}")
    input("Appuie sur Entrée pour quitter...")
    sys.exit(1)

# ── 2. Répertoire racine (là où se trouvent apex_live/, backend/, etc.) ───────
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "apex_live"))

# ── 3. Installation automatique des dépendances ───────────────────────────────
REQUIRED = ["requests"]

def ensure(package):
    try:
        __import__(package)
        return True
    except ImportError:
        pass
    print(f"  → Installation de '{package}'...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", package, "--quiet"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"\nERREUR : impossible d'installer '{package}'.")
        print(result.stderr.strip())
        return False
    try:
        __import__(package)
        print(f"  → '{package}' installé.")
        return True
    except ImportError:
        print(f"\nERREUR : '{package}' toujours introuvable après installation.")
        return False

print()
print("=" * 55)
print("  APEX Bot v2 — Vérification des dépendances...")
print("=" * 55)
all_ok = all(ensure(pkg) for pkg in REQUIRED)
if not all_ok:
    input("\nAppuie sur Entrée pour quitter...")
    sys.exit(1)

# ── 4. Vérifier que le port 8080 est libre ────────────────────────────────────
import socket

def port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) != 0

DASH_PORT = 8080
if not port_free(DASH_PORT):
    print(f"\nATTENTION : le port {DASH_PORT} est déjà utilisé.")
    print(f"  Ouvre http://localhost:{DASH_PORT} — le bot tourne peut-être déjà.")
    ans = input("  Continuer quand même ? (o/n) : ").strip().lower()
    if ans not in ("o", "oui", "y", "yes", ""):
        sys.exit(0)

# ── 5. Démarrage du dashboard ─────────────────────────────────────────────────
def _start_dashboard():
    try:
        from http.server import HTTPServer
        import dashboard as dash
        HTTPServer(("", dash.PORT), dash.Handler).serve_forever()
    except OSError as e:
        print(f"\nERREUR dashboard : {e}")
        print("  Vérifie que le port 8080 n'est pas déjà utilisé.")

t = threading.Thread(target=_start_dashboard, daemon=True)
t.start()
time.sleep(0.8)  # laisser le serveur démarrer

# ── 6. Ouvrir le navigateur ───────────────────────────────────────────────────
try:
    import webbrowser
    webbrowser.open(f"http://localhost:{DASH_PORT}")
except Exception:
    pass  # Pas bloquant si le navigateur ne peut pas s'ouvrir

# ── 7. Démarrage du bot ───────────────────────────────────────────────────────
print()
print("=" * 55)
print("  APEX Bot v2 — BTC/USDT")
print(f"  Dashboard  : http://localhost:{DASH_PORT}")
print("  Ctrl+C     : arrêter le bot et le dashboard")
print("=" * 55)
print()

try:
    import apex_live as bot
    bot.main()
except KeyboardInterrupt:
    print("\nArrêt demandé. À bientôt.")
    sys.exit(0)
