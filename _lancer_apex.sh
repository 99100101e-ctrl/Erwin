#!/bin/bash
# _lancer_apex.sh — Lance le bot APEX v2 sous Linux / Mac
# Usage : bash _lancer_apex.sh

cd "$(dirname "$0")"

# Chercher python3 ou python
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo "ERREUR : Python introuvable. Installe Python 3.8+."
    exit 1
fi

$PYTHON _lancer_apex.py
