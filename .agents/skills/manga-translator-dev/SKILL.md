---
name: manga-translator-dev
description: >-
  Use this skill whenever developing, modifying, debugging, or verifying the Manga Translator Studio codebase (server.py, app/*, web/*, tests/*).
---

# Manga Translator Studio — Dev & Verification Runbook

## 1. Architecture du Projet (15 lignes max)
```text
server.py                  # FastAPI backend: /api/upload, /api/upload_folder, /api/translate/start, /api/status, /api/image, /api/download
app/launcher.py            # Lanceur monoprocessus (pywebview ou navigateur + watchdog heartbeat auto-exit)
app/config.py              # .env loader/saver, constantes, presets providers, polices embarquées app/fonts/
app/archives.py            # ArchiveHandler: extract & pack pour CBZ/ZIP, CBR/RAR (unrar/7z), folder, image
app/cloud_vision.py        # CloudVisionClient: détection bulles + traduction via Gemini, OpenRouter, Anthropic, Custom
app/groq_refine.py         # Raffinement optionnel du texte traduit via Groq API
app/typesetter.py          # Inpainting doux (smart/rounded/ellipse) & typographie (mask_only=True pour clean stage)
app/fonts/                 # Polices TrueType locales embarquées (DejaVuSans, LiberationSans)
web/templates/index.html   # Interface Web moderne et épurée (drop-zone, studio, liseuse, bibliothèque, paramètres)
web/static/css/style.css   # Feuille de style minimale et moderne (thème sombre, responsive mobile/desktop)
web/static/js/app.js       # Logique frontend centralisée (state, navigation, upload, drag&drop, studio)
tests/test_suite.py        # Suite de tests pytest (41 tests automatisés)
LESSONS.md                 # Journal des erreurs rencontrées et correctifs appliqués
```

## 2. Règles Strictes & Invariants
1. **Discipline de Simplification & Monoprocessus (The Opus Standard)** : *Priorité absolue à la compacité et à la robustesse native. Ne jamais ajouter un deuxième processus (tray, helper) ou des scripts injecteurs de DOM quand un mécanisme passif standard (Heartbeat HTTP, CSS pur, événement de cycle de vie) résout le problème avec dix fois moins de code.*
2. **Protection Anti-Régression sur Refonte Radicale (Zero Feature Dropped)** : *Toute simplification ou réécriture du code (notamment en contexte de contrainte de tokens) doit obligatoirement préserver la parité fonctionnelle. Les éléments clés (statut des APIs, choix direct du modèle, support du mode automatique zéro configuration) ne doivent JAMAIS être sacrifiés sous prétexte d'alléger le code.*
3. **Cycle Strict « Développer ➔ Tester ➔ Vérifier ➔ Améliorer »** : *Chaque amélioration suit 4 étapes : 1) Développer (code minimal, typé) 2) Tester (pytest & node --check) 3) Vérifier (Playwright DOM & screenshot) 4) Améliorer (mesure de latence, purge du code inutile, persistance dans LESSONS.md).*
4. **Preuve obligatoire** : *Ne jamais annoncer "terminé" sans sortie de test collée.*
5. **Validation Visuelle Obligatoire (No Blind UI Validation)** : *Aucune modification CSS/JS ne peut être déclarée terminée sans une capture d'écran Playwright réelle (`browser_take_screenshot`) et une inspection des dimensions calculées (`getBoundingClientRect()`).*
6. **Découverte et validation des modèles IA** : *Les noms de modèles IA doivent être uniquement découverts via l'endpoint `/models` (ou `/v1/models`) du fournisseur et validés par un appel d'inférence réel avant d'être inscrits dans la configuration.*
7. **Zéro modèle local** : Aucune dépendance d'inférence locale lourde (`torch`, `tesseract`, `onnxruntime`). Empreinte RAM cible < 50 Mo hors pic.
8. **Journalisation continue** : Relire `LESSONS.md` avant chaque tâche et y ajouter `[date] erreur -> cause -> correction` à chaque bug rencontré.
9. **Modèle Unique Autonome & Raffineur Opt-In** : Un modèle Vision multimodal moderne (Gemma 4, Qwen, Nemotron, GPT-4o) traduit directement en une seule passe. Ne jamais forcer un pipeline à deux modèles par défaut. Tout second passage stylistique est strictement optionnel (`REFINER_ENABLED=false` par défaut).
10. **Traduction Manga Idiomatique & Registres (Zéro Calque)** : Proscrire la traduction mot-à-mot. Reformuler avec le naturel d'un locuteur natif, adapter les idiomes et blagues, privilégier la concision pour le lettrage des bulles, et supporter les 3 registres de langage (`standard`, `familier`, `soutenu`).
11. **Hygiène du Workspace & Zéro Résidu** : Les suites de tests et scripts doivent nettoyer immédiatement leurs archives temporaires. Aucun dossier orphelin, aucun fichier doublon à la racine et aucun raccourci non sollicité sur le Bureau.

## 3. Checklist de Vérification Obligatoire (avant toute validation)
Exécuter systématiquement ces 5 vérifications dans l'ordre :
1. **Syntaxe JS** : `node --check web/static/js/app.js`
2. **Import Backend** : `./venv/bin/python -c "from server import app; print('Import OK')"`
3. **Tests Unitaires & API** : `./venv/bin/pytest tests/ -q`
4. **Test HTTP Réel** : Vérifier que le serveur répond sur `http://localhost:8000` via `curl`.
5. **Validation Visuelle Playwright** : Charger l'interface dans Playwright, vérifier l'absence d'erreurs console, inspecter les dimensions DOM clés et capturer les captures d'écran réelles (thèmes sombre et clair, modales).
