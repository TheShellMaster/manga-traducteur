# 🎯 MISSION CRITIQUE — Raccordement du détecteur de bulles

## Contexte
Le repo a un `bubble_detector.py` (PR #4, branche `fix/pipeline-traduction`) qui détecte les bulles par contours OpenCV + OCR Tesseract. **Mais il n'est pas câblé dans le pipeline.**

Le `pipeline.py` actuel appelle `CloudVisionClient.detect_and_translate(img)` — c'est un appel API qui fait tout en une fois (détection + traduction). On ne contrôle pas la séquence.

## Objectif
Modifier `app/pipeline.py` pour :
1. **Détecter les bulles localement** avec `bubble_detector.detect_bubbles(img)`
2. **Traduire bulle par bulle** en appelant le LLM pour chaque crop
3. **Ajouter timeout 60s + retry ×3** sur chaque appel LLM
4. **Ne jamais traduire toute la page en un seul prompt** — c'est le bug principal

## Séquence correcte attendue
```
Pour chaque image :
  1. detect_bubbles(img) → liste de {box, text}
  2. Pour chaque bulle :
       a. Crop l'image sur la box
       b. Appeler le LLM avec le crop + contexte page précédente
       c. Timeout 60s, retry ×3 en cas d'échec
       d. Stocker la traduction
  3. render_manga_page(img, blocks) avec les traductions
```

## Fichiers concernés
- `app/pipeline.py` — à modifier
- `app/bubble_detector.py` — déjà prêt (PR #4)
- `app/cloud_vision.py` — à adapter pour traduire une bulle isolée, pas une page entière

## Compromis acceptables
- Si OpenCV absent, fallback sur page entière (déjà géré par `bubble_detector.py`)
- Si Tesseract absent, texte vide + crop envoyé au LLM vision
- Le refiner Groq reste optionnel (OPT-IN)

## ⚠️ ERREUR À NE PAS COMMETTRE
Ne pas modifier `server.py` pour ça. Le raccordement se fait dans `pipeline.py` uniquement.
