#!/bin/bash
# Arrêt forcé de Manga Translator Studio (normalement inutile : fermer la fenêtre suffit)
curl -s -m 2 -X POST http://127.0.0.1:8000/api/system/shutdown >/dev/null 2>&1
sleep 1
pkill -f "app/launcher.py" 2>/dev/null
pkill -f "uvicorn server:app" 2>/dev/null
echo "Manga Translator Studio est arrêté."
