# AGENT_COMM — Canal de communication Agent local ↔ Claude (GitHub)

**Dernière mise à jour par :** Claude — 2026-11-01

## Comment ça marche

1. Tu (agent local) lis la **Section 1 — Tâches**. Tu exécutes **une seule tâche à la fois**.
2. Après chaque tâche, tu écris un rapport dans la **Section 2 — Journal** (copie le modèle), puis tu commits et push sur `main`.
3. Claude lit ton rapport et répond dans le Journal, sous ton entrée, avec validation ou corrections.
4. **Jamais** de push direct de code sur `main` sans que Claude ait validé. Pour le code : branche + PR.

## Règles non négociables

- Une tâche à la fois. Pas deux.
- Copier-coller les commandes exactement. Ne rien improviser.
- Si une commande échoue : **STOP**, coller la sortie d'erreur complète dans le Journal, attendre les instructions de Claude.
- Ne jamais modifier `server.py` sans tâche explicite dans ce fichier.
- Ne jamais utiliser `git push --force`.
- Ne jamais commit de fichier `.env` ou de clé API.

---

## Section 1 — Tâches (dans l'ordre, du plus urgent au moins urgent)

### TÂCHE 0 — Diagnostic de l'état de `main` (URGENT — avant toute autre chose)

Le propriétaire signale que `main` a été endommagé. On doit mesurer les dégâts.

```bash
cd <dossier-du-projet>
git checkout main
git pull origin main
git log --oneline -15
python -m pytest tests/ -x 2>&1 | tail -30
python -c "import server" 2>&1 | tail -10
```

**Critère de réussite :** rapporter dans le Journal (a) la liste des 15 derniers commits, (b) le résultat des tests (combien passent / échouent), (c) si `import server` fonctionne. **Ne rien réparer toi-même.** Claude décide de la stratégie (revert, fix, etc.) après lecture.

### TÂCHE 1 — Vérifier que rien de sensible n'est commité

```bash
git ls-files | grep -E "\.env$|\.env\.|secrets|credentials" || echo "OK: aucun secret versionné"
git log --all --oneline -- .env || echo "OK: .env jamais commité"
```

**Critère de réussite :** les deux lignes affichent `OK`. Sinon, rapporter les noms de fichiers trouvés et attendre les instructions.

### TÂCHE 2 — Créer la branche de travail des corrections

```bash
git checkout -b fix/stabilisation
git push -u origin fix/stabilisation
```

**Critère de réussite :** la branche `fix/stabilisation` existe sur GitHub. Rapporter dans le Journal. Les corrections de code viendront ensuite, fichier par fichier, sur cette branche.

### TÂCHES SUIVANTES

Elles seront ajoutées ici par Claude après lecture du rapport des Tâches 0–2. Chaque correction (traduction séquentielle, sécurité, sessions, admin) fera l'objet d'une tâche dédiée avec diff exact à appliquer.

---

## Section 2 — Journal d'échange

### Modèle de rapport (à copier-coller pour chaque tâche)

```
#### [Agent] Tâche N — AAAA-MM-JJ HH:MM
- Commande exécutée : <commande>
- Résultat : <sortie complète ou résumé fidèle>
- Critère de réussite atteint : OUI / NON
- Blocage éventuel : <erreur complète si échec>
```

---

#### [Claude] 2026-11-01 — Ouverture du canal

Bienvenue. Le repo est `TheShellMaster/manga-traducteur`. Commence par la Tâche 0 : je dois connaître l'état exact de `main` (derniers commits, état des tests, import du serveur) avant de prescrire la moindre correction. Ne répare rien toi-même à ce stade. J'attends ton premier rapport.

Contexte des problèmes connus à traiter ensuite (pour information, pas encore à faire) :
1. Traduction : le pipeline doit traiter les pages **séquentiellement** (une à la fois, dans l'ordre), avec gestion des quotas des API gratuites.
2. Sécurité : clés API, sessions, exposition du backend et de `/docs` à verrouiller.
3. Le propriétaire veut à terme : site vitrine avec animations 3D, lecteur de manga intégré, backend invisible pour les visiteurs.
