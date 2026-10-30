#!/bin/bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

echo "=========================================================="
echo " 📖 Manga Translator Studio (Web UI)"
echo " Zéro Modèle Local • 100% Cloud Vision • Port 8000"
echo "=========================================================="

# 1. If server is already running on port 8000, simply open the browser and exit
if curl -s -m 2 http://127.0.0.1:8000/ >/dev/null 2>&1; then
    echo "==> Le serveur est déjà actif sur http://localhost:8000 !"
    echo "==> Ouverture de l'interface dans votre navigateur..."
    xdg-open http://localhost:8000 2>/dev/null || sensible-browser http://localhost:8000 2>/dev/null || true
    exit 0
fi

# 2. Activate venv
if [ -d "venv" ]; then
    echo "==> Activation de l'environnement virtuel..."
    source venv/bin/activate
fi

# 3. Launch System Tray icon in background if graphical desktop is available
if [ -n "$DISPLAY" ] || [ -n "$WAYLAND_DISPLAY" ]; then
    if ! pgrep -f "app/tray.py" >/dev/null 2>&1; then
        echo "==> Lancement de l'icône dans la barre des tâches..."
        python app/tray.py >/dev/null 2>&1 &
    fi
fi

# 4. Open browser after 1.5s
(sleep 1.5 && (xdg-open http://localhost:8000 2>/dev/null || sensible-browser http://localhost:8000 2>/dev/null || true)) &

# 4. Launch FastAPI server
echo "==> Démarrage du serveur web sur http://localhost:8000..."
exec uvicorn server:app --host 127.0.0.1 --port 8000
