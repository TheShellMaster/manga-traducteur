# Liste maître des tâches

L'agent coche `[x]` avec hash de commit. Le reviewer ajoute ✅ après vérification.

## P0 — Intégrité de main
- [ ] Rapport 01 (état des lieux) livré
- [ ] Identifier le dernier commit sain de `main`
- [ ] Restaurer les fichiers tronqués (sur branche `fix/restore-main`)

## P1 — Corrections (après validation P0)
- [ ] Traduction strictement page par page, attente + retry sur HTTP 429
- [ ] Plus de remplacement silencieux par l'original : lister les pages en échec
- [ ] Liste blanche des URL fournisseurs
- [ ] Clé Gemini passée en en-tête, pas dans l'URL
- [ ] Clé de cache = fournisseur + modèle + langue + hash image
- [ ] IDs de session complets (uuid4 / secrets)
- [ ] `/admin` protégé par mot de passe (variable d'environnement)
- [ ] `/docs` et `/openapi.json` désactivés en production
- [ ] Clés par fournisseur en mode auto

## P2 — Produit
- [ ] Lecteur de manga intégré
- [ ] Site vitrine (3D, animations) séparé du backend
- [ ] Aucune info technique exposée côté public
