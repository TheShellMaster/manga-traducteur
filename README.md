# Manga Translator Studio

Studio local pour préparer et relire la traduction de mangas, manhwas et comics. L'application combine un lecteur de pages, un pipeline OCR/traduction par fournisseur de vision configurable, un rendu des bulles et une bibliothèque de sorties. Elle s'adresse d'abord à un usage personnel sur la machine où elle est installée.

## Parcours

1. Importer un CBZ/CBR/ZIP/RAR, une image ou un dossier de pages.
2. Configurer une clé auprès d'un fournisseur vision pris en charge, choisir les langues et lancer la traduction.
3. Suivre le traitement page par page, comparer original et rendu, puis corriger si besoin les textes détectés.
4. Télécharger et relire l'archive produite.

Le lecteur inclut les vues originale/traduite, comparaison par slider, navigation de page, aperçu des bulles et lecture de chapitre. La qualité de l'OCR et de la traduction n'est pas garantie: une relecture humaine est recommandée.

## Démarrage rapide

Python 3.10 ou supérieur est recommandé. Installer aussi les outils d'archives nécessaires aux fichiers RAR/CBR sur votre système.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python server.py
```

Ouvrir ensuite `http://127.0.0.1:8000`. Le lanceur `lancer_manga_translator.sh` est également fourni. Pour conteneur local: `docker compose up --build`; Compose publie volontairement le port uniquement sur loopback.

## Fournisseurs et configuration

Le code inclut des profils Gemini, OpenRouter, OpenAI, Groq, Mistral, NVIDIA et endpoint compatible OpenAI. Vérifier dans `app/config.py` et chez le fournisseur que le nom du modèle et les capacités sont toujours disponibles. Configurer la clé depuis Paramètres; l'API de lecture des réglages n'en renvoie que l'état de configuration. Les réglages locaux sont conservés dans `.env` sous `MTS_HOME` (ou le dossier du projet en développement) avec permissions POSIX privées. Ne jamais committer `.env` ni communiquer de clé.

Les fournisseurs peuvent facturer les requêtes et appliquer leurs propres limites; aucun quota gratuit ou coût n'est garanti. Les pages sont traitées dans l'ordre, une à la fois afin d'assurer une propagation stable du contexte et limiter les appels simultanés. Consultez [Exploitation, sécurité et limites](docs/OPERATIONS.md) pour l'installation détaillée, Docker, secrets, données, quotas, sécurité et dépannage.

## Tests

```sh
PYTHONPATH=. python -m pytest -q tests/
```

Les tests automatisés utilisent des images/archives synthétiques et des fournisseurs simulés; ils ne valident pas la qualité des traductions ni les API réelles.

## Sécurité et limites

Cette version ne fournit pas de comptes ni d'isolation multi-utilisateur. Ne pas exposer directement le serveur à Internet ou à un réseau non fiable. Pour les détails de déploiement et les limites de sécurité, consulter le guide d'exploitation.

Licence MIT; voir `LICENSE`.
