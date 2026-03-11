#!/usr/bin/env bash
# BTC Trading Advisor — single-command launcher
# Usage: ./start.sh
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

echo ""
echo "============================================================"
echo "  BTC Trading Advisor — Starting..."
echo "============================================================"

# ---------- Backend ----------
echo ""
echo "[1/3] Setting up Python backend..."
cd "$BACKEND"

if [ ! -d ".venv" ]; then
  echo "  Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate

# Install / upgrade deps quietly
pip install -q -r requirements.txt

echo "  Backend ready."

# ---------- Frontend ----------
echo ""
echo "[2/3] Setting up React frontend..."
cd "$FRONTEND"

if [ ! -d "node_modules" ]; then
  echo "  Installing npm packages (first run, may take a minute)..."
  npm install --silent
fi

echo "  Frontend ready."

# ---------- Launch ----------
echo ""
echo "[3/3] Launching services..."
echo ""
echo "  Backend  → http://localhost:8000"
echo "  Frontend → http://localhost:3000"
echo "  API docs → http://localhost:8000/docs"
echo ""
echo "  Press Ctrl+C to stop both services."
echo "============================================================"
echo ""

# Start backend in background
cd "$BACKEND"
source .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --log-level info &
BACKEND_PID=$!

# Give backend a moment to bind
sleep 1

# Start frontend (blocks; Ctrl+C will kill it and the trap below cleans up)
cd "$FRONTEND"
BROWSER=none npm start &
FRONTEND_PID=$!

# Open browser after a short delay
(sleep 4 && (xdg-open http://localhost:3000 2>/dev/null || open http://localhost:3000 2>/dev/null || true)) &

# Clean shutdown on Ctrl+C
trap 'echo ""; echo "Stopping..."; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; wait; echo "Done."; exit 0' INT TERM

# Wait for both to finish (or Ctrl+C)
wait $BACKEND_PID $FRONTEND_PID
