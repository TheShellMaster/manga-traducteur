#!/bin/bash
# Manga Translator Studio - lancement
# Fermer la fenêtre (ou cliquer sur "Quitter") arrête complètement l'application.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"
[ -d venv ] && source venv/bin/activate
exec python3 app/launcher.py "$@"
