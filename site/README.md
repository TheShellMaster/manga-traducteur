# Site public

Vitrine et lecteur. Le studio technique (`server.py`, clés, fournisseurs) ne doit pas être exposé aux visiteurs.

- `public/index.html` : présentation, animations lentes, lecteur de démo.
- `sequential_guard.py` : une page à la fois, pause si quota gratuit (429).

Ne pas fusionner les branches `fix/bugs-audit` et `fix/security-and-cache` : leurs commits ont tronqué des fichiers.
