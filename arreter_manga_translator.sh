#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

echo "=========================================================="
echo " 🛑 Arrêt de Manga Translator Studio"
echo "=========================================================="

# 1. Envoi d'un signal propre d'arrêt à l'API HTTP (si active)
if curl -s -m 2 -X POST http://127.0.0.1:8000/api/system/shutdown >/dev/null 2>&1; then
    echo "==> Signal d'extinction envoyé avec succès via l'API."
    sleep 1
fi

# 2. Arrêt des processus uvicorn résiduels
pids=$(pgrep -f "uvicorn server:app" 2>/dev/null || true)
if [ -n "$pids" ]; then
    echo "==> Arrêt du processus serveur ($pids)..."
    kill $pids 2>/dev/null || true
    sleep 0.5
fi

# 3. Arrêt de l'icône de la barre des tâches (si active)
tray_pids=$(pgrep -f "app/tray.py" 2>/dev/null || true)
if [ -n "$tray_pids" ]; then
    echo "==> Arrêt de l'icône de la barre des tâches..."
    kill $tray_pids 2>/dev/null || true
fi

# 4. Notification de bureau Linux
if command -v notify-send >/dev/null 2>&1; then
    notify-send "Manga Translator Studio" "Le serveur local a été arrêté avec succès." -i process-stop 2>/dev/null || true
fi

echo "✓ Manga Translator Studio est complètement arrêté."
