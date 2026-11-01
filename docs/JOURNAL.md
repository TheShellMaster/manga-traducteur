# Journal — audit du pipeline de traduction

## 1er novembre 2026 — audit rapide

### Constats vérifiés
- La racine contient `server.py`, `app/pipeline.py` et `app/cloud_vision.py`. Le dépôt n’a pas de `translate.py` à la racine; l’implémentation active semble organisée sous `app/`.
- La récupération des contenus sources via l’interface GitHub n’a pas permis d’inspecter leur texte dans cet environnement. Il est donc impossible d’établir si le serveur contient un mock, si le pipeline consomme un JSON de coordonnées, ou si les clés sont exposées.
- Un module candidat `app/bubble_detector.py` a été ajouté sur la branche `fix/pipeline-traduction`. Il propose contours OpenCV et OCR Tesseract facultatifs avec fallback pleine page; le branchement effectif dans le pipeline n’a pas été réalisé.

### État
- **Corrigé / livré en branche** : base d’un détecteur heuristique réutilisable.
- **Non corrigé** : intégration image par image et appel LLM par bulle; retry/timeout; audit et correction du mock; vérification complète des secrets et du `.gitignore`; documentation d’usage réel.

### À faire
- Relire les contenus de `app/pipeline.py`, `app/cloud_vision.py`, `server.py`, `requirements.txt`, `.gitignore` et `README.md` dans une session ayant accès au texte des pièces jointes GitHub.
- Intégrer et tester le détecteur dans le flux de traduction sans casser l’API actuelle.
- Faire l’audit de sécurité des clés et ajouter des timeouts/retry mesurés.
- Finaliser la documentation et valider la syntaxe ainsi que les tests dans le dépôt.
- **Lecteur manga intégré** : état non vérifié; à auditer.
- **Site vitrine** : état non vérifié; à auditer.
- **Timeouts des longues sessions** : correctif non appliqué; à traiter après validation du nouveau comportement séquentiel.

Ce journal distingue explicitement les éléments observés des tâches encore non vérifiées.