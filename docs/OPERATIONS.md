# Exploitation, configuration et limites

Ce guide décrit le dépôt tel qu'il fonctionne, sans supposer qu'il s'agit d'un service multi-utilisateur.

## Stack et architecture

- **Interface** : HTML/CSS/JavaScript natifs dans `web/templates/index.html` et `web/static/`. Le studio offre import de chapitre/dossier, suivi des pages, lecteur original/traduit et curseur de comparaison, retouche de bulles, bibliothèque et guide.
- **API locale** : FastAPI (`server.py`), servi par Uvicorn. Les sessions d'exécution et leurs tâches sont en mémoire du processus; un redémarrage les invalide. Les sorties, caches et fichiers temporaires sont dans `data/` (ou `MTS_HOME`).
- **Pipeline** : `app/archives.py` extrait et reconditionne; `app/cloud_vision.py` appelle les modèles vision configurés; `app/typesetter.py` nettoie et redessine les bulles; `app/groq_refine.py` fournit un raffinement facultatif; `app/pipeline.py` est le chemin CLI.
- **Dépendances** : Python 3.10+ et versions Python listées dans `requirements.txt`; traitement d'images Pillow, FastAPI/Uvicorn et multipart. Les formats RAR/CBR dépendent aussi des outils d'archives installés dans le système.
- **Tests** : pytest, TestClient/httpx et archives/images synthétiques dans `tests/`; aucun appel fournisseur ne doit être requis pour les tests unitaires.

## Installation locale

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env       # facultatif; supprimer les valeurs d'exemple avant tout usage
python server.py
```

Le script `lancer_manga_translator.sh` est aussi disponible. Vérifier son contenu et ses dépendances système sur la plateforme visée. Le serveur local est destiné à être consulté sur la même machine (`http://127.0.0.1:8000`). Les variables acceptées et fournisseurs/modèles préconfigurés sont dans `app/config.py`; les noms et la disponibilité des modèles changent selon les fournisseurs.

## Configuration et secrets

- Dans l'interface, saisir une clé fournisseur dans les paramètres. `/api/settings` ne renvoie pas la valeur des clés, seulement leur état configuré. Les paramètres enregistrés sont écrits dans le fichier `.env` du répertoire utilisateur (`MTS_HOME`, ou répertoire du projet en développement) avec permissions POSIX 0600 et remplacement atomique.
- `.env` est ignoré par Git; ne jamais mettre de clé dans un commit, issue, capture, journal ou URL. `.env.example` ne contient que des exemples et n'est pas un fichier de secrets prêt à l'emploi.
- Un endpoint compatible OpenAI personnalisé permet aussi une URL locale ou gérée par l'utilisateur. Ne le configurer qu'avec une destination de confiance.
- Les clés saisies dans une requête de traduction sont en mémoire le temps de cette requête. Utiliser des fournisseurs directs réduit les intermédiaires mais ne modifie pas leurs politiques de conservation.

## Pipeline de traduction

1. L'upload crée un identifiant de session et extrait une archive ou prépare l'image/dossier.
2. Le traitement OCR/traduction et le rendu s'exécutent en tâche d'arrière-plan; chaque page met à jour son état. Les pages sont maintenant soumises **séquentiellement dans l'ordre de l'archive**, pour que le contexte des pages précédentes soit déterministe et que les quotas ne soient pas consommés par des appels parallèles. Le paramètre API historique `concurrency` reste accepté dans la plage 1–3 pour compatibilité, mais n'active plus de parallélisme.
3. Une page en erreur laisse l'original disponible; l'archive de sortie est reconditionnée quand c'est possible. Une interruption du processus perd l'état mémoire de session.
4. Le lecteur permet de vérifier l'original et le rendu; corriger les bulles détectées reste nécessaire pour les cas ambigus.

Il ne s'agit pas d'une traduction certifiée ni d'un éditeur de scanlation entièrement automatique. OCR, segmentation des bulles, nettoyage, typographie et terminologie peuvent nécessiter une révision humaine. La qualité varie selon le modèle et la langue.

## Lancement Docker

`docker compose up --build` expose le service sur `127.0.0.1:8000` et monte `./data` dans le conteneur. Le Dockerfile écoute sur toutes les interfaces **dans le conteneur**; conserver le binding loopback indiqué dans Compose pour usage mono-utilisateur. L'image déclare une limite indicative de 1,5 CPU/1 Gio mémoire via Compose; le traitement Pillow et les archives peuvent demander davantage. Le volume persistant contient chapitres, pages, sorties, cache et historique: protéger, sauvegarder et purger ce répertoire selon le besoin.

### Déploiement réseau

Le projet n'a pas de comptes, sessions utilisateur authentifiées, isolation de données par compte, quotas d'upload globaux ni modèle de permissions multi-tenant. Les sessions d'application ne sont pas une authentification. **Ne pas exposer directement ce serveur sur Internet ou à un réseau non fiable.** Pour une expérimentation distante, mettre un VPN ou un proxy d'accès authentifié devant le service, appliquer TLS, limites de taille/durée et quotas, isoler stockage et processus par utilisateur, contrôler les destinations réseau personnalisées et auditer les contrôles d'accès avant l'ouverture publique. CORS/contrôle d'origine seul n'est pas une authentification.

## Coûts, quotas et données

Le dépôt ne fixe ni ne garantit un tarif ou quota gratuit. Les tarifs, modèles autorisés, restrictions d'usage, quotas par minute/jour, régions et règles de conservation varient par fournisseur, compte et date; consulter leurs pages officielles avant usage. Chaque page envoyée peut consommer une requête/modèle et du volume image; les retries/fallbacks et les clés ayant un quota épuisé peuvent produire des coûts inattendus. Commencer par un petit chapitre, choisir un modèle et fournisseur adaptés, surveiller le tableau de bord fournisseur et fixer des limites côté compte. Le séquencement réduit les requêtes simultanées mais ne réduit pas nécessairement le nombre total de pages.

Les images et textes sont transmis au fournisseur sélectionné pour l'inférence. Ne traduire que du contenu que l'on est autorisé à traiter; considérer les images source, fichiers traduits, caches et historique comme des données sensibles. La durée de conservation dépend de la configuration et du nettoyage local; aucune purge automatique complète n'est garantie.

## Vérification

```sh
PYTHONPATH=. python -m pytest -q tests/
```

Les tests utilisent des données synthétiques et des appels simulés; ils vérifient le comportement logiciel, pas la disponibilité réelle des fournisseurs, l'exactitude linguistique, ni le coût d'un chapitre réel.
