#!/bin/bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

echo "=========================================================="
echo " 📖 Manga Translator Studio"
echo " Zéro Modèle Local • 100% Cloud Vision • Port 8000"
echo "=========================================================="

# 1. Activation de l'environnement virtuel
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# 2. Si un affichage graphique est disponible, lancer l'application native
# Elle apparaît directement dans la barre des tâches / dock des applications actives de l'OS
if ([ -n "$DISPLAY" ] || [ -n "$WAYLAND_DISPLAY" ]) && [ "$1" != "--cli" ]; then
    echo "==> Lancement de l'application bureau (présente dans la barre des tâches active)..."
    exec python3 app/desktop_app.py
fi

# 3. Repli en mode serveur pur / CLI
echo "==> Démarrage du serveur uvicorn sur http://localhost:8000..."
echo "==> Appuyez sur Ctrl+C ou utilisez ./arreter_manga_translator.sh pour arrêter."
(sleep 1.5 && (xdg-open http://localhost:8000 2>/dev/null || sensible-browser http://localhost:8000 2>/dev/null || true)) &
exec uvicorn server:app --host 127.0.0.1 --port 8000
