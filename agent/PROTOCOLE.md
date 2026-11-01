# Protocole Reviewer <-> Agent local

Le reviewer (assistant distant) lit et répond UNIQUEMENT via des fichiers markdown de ce dossier.

## Règles absolues pour l'agent
1. **Jamais de push direct sur `main` pour du code.** Toujours une branche `fix/...` ou `feat/...`. Seuls les fichiers `agent/RAPPORTS/*.md` peuvent aller sur `main`.
2. Avant chaque rapport : lancer `pytest -q` et **coller la sortie complète**.
3. Aucune tâche n'est "faite" sans preuve : commande exécutée + sortie collée + hash du commit.
4. **Aucun secret** (clé API, token, mot de passe) dans les markdowns ou le code.
5. Rapports < 200 lignes, un fichier par rapport.
6. Si tu ne comprends pas une consigne : écris la question dans ton rapport, ne devine pas.
7. Ne jamais supprimer de fichier/test pour faire passer les tests.

## Flux
- Consignes du reviewer : `agent/CONSIGNES/AAAA-MM-JJ-NN-reviewer.md`
- Réponses de l'agent : `agent/RAPPORTS/AAAA-MM-JJ-NN-agent.md`
- Liste maître : `agent/TACHES.md` (l'agent coche, le reviewer valide).

## Format d'un rapport
```
# Rapport NN
## Fait
- [x] tâche — commit <hash> — branche <nom>
## Preuves
<sortie pytest, git log -5 --oneline, git status>
## Problèmes / questions
```
