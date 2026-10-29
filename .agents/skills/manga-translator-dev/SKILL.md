---
name: manga-translator-dev
description: >-
  Use this skill whenever developing, modifying, debugging, or verifying the Manga Translator Studio codebase (server.py, app/*, web/*, tests/*).
---

# Manga Translator Studio — Dev & Verification Runbook

## 1. Architecture du Projet (15 lignes max)
```text
server.py                  # FastAPI backend: /api/upload, /api/upload_folder, /api/translate/start, /api/status, /api/image, /api/download
app/config.py              # .env loader/saver, constantes, listes de modèles vision découverts & validés
app/archives.py            # ArchiveHandler: extract & pack pour CBZ/ZIP, CBR/RAR (unrar/7z), folder, image
app/cloud_vision.py        # CloudVisionClient: détection bulles + traduction via Gemini, OpenRouter, Anthropic, ou Custom OpenAI
app/groq_refine.py         # Raffinement optionnel du texte traduit via Groq API
app/typesetter.py          # Inpainting doux (rounded/ellipse/rectangle/transparent) & rendu typographique Pillow (auto-fit ou fixe)
app/pipeline.py            # Pipeline séquentiel de bout en bout
web/templates/index.html   # Interface Web Studio (upload fichier/dossier, comparateur, slider, liseuse, modale settings)
web/static/css/style.css   # Thème sombre, animations, slider comparatif, badges, toasts, responsive mobile
web/static/js/app.js       # Logique frontend, drag&drop, polling temps réel, slider interactif, toasts
tests/test_suite.py        # Suite de tests pytest (parser, typesetter, archives, API TestClient, worker mocké)
LESSONS.md                 # Journal des erreurs rencontrées et correctifs appliqués
```

## 2. Règles Strictes & Invariants
1. **Preuve obligatoire** : *Ne jamais annoncer "terminé" sans sortie de test collée.*
2. **Découverte et validation des modèles IA** : *Les noms de modèles IA doivent être uniquement découverts via l'endpoint `/models` (ou `/v1/models`) du fournisseur et validés par un appel d'inférence réel avant d'être inscrits dans la configuration.*
3. **Zéro modèle local** : Aucune dépendance d'inférence locale lourde (`torch`, `tesseract`, `onnxruntime`). Empreinte RAM cible < 50 Mo hors pic.
4. **Journalisation continue** : Relire `LESSONS.md` avant chaque tâche et y ajouter `[date] erreur -> cause -> correction` à chaque bug rencontré.

## 3. Checklist de Vérification Obligatoire (avant toute validation)
Exécuter systématiquement ces 4 vérifications dans l'ordre :
1. **Syntaxe JS** : `node --check web/static/js/app.js`
2. **Import Backend** : `./venv/bin/python -c "from server import app; print('Import OK')"`
3. **Tests Unitaires & API** : `./venv/bin/pytest tests/ -q`
4. **Test HTTP Réel** : Démarrer `uvicorn server:app --port 8000` et vérifier les endpoints avec `curl`.
