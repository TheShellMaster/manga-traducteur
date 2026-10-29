#!/bin/bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

echo "=========================================================="
echo " 📖 Manga Translator Studio (Web UI)"
echo " Zéro Modèle Local • 100% Cloud Vision • Port 8000"
echo "=========================================================="

# 1. Activate venv if it exists
if [ -d "venv" ]; then
    echo "==> Activation de l'environnement virtuel..."
    source venv/bin/activate
fi

# 2. Check and install requirements quietly
echo "==> Vérification des dépendances..."
pip install -r requirements.txt -q

# 3. Open browser in background
(sleep 2 && (xdg-open http://localhost:8000 2>/dev/null || sensible-browser http://localhost:8000 2>/dev/null || open http://localhost:8000 2>/dev/null)) &

# 4. Launch FastAPI server
echo "==> Démarrage du serveur web sur http://localhost:8000..."
exec uvicorn server:app --host 0.0.0.0 --port 8000 --reload
