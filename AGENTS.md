# Manga Translator Studio (Web UI & Cloud Vision)

Application moderne de traduction de mangas avec interface Web interactive, visualiseur de pages en direct et moteur 100% Cloud Vision (zéro modèle local).

---

## 1. Fonctionnalités Clés

- **Interface Web Moderne (Zéro Ligne de Commande)** :
  - Glisser-déposer d'archives **CBZ, CBR, RAR, ZIP, Dossiers ou Images**.
  - **Liseuse / Comparateur intégré** : Visualisation Avant / Après en temps réel (split-view ou slider).
  - Navigation fluide par miniatures avec badges d'état (`En attente`, `En cours ⚡`, `Traduit ✓`).
  - Lecture des pages traduites au fur et à mesure sans attendre la fin du chapitre.
  - Téléchargement direct en un clic du manga traduit au format d'origine.
- **Support Universel des APIs & Modèles** :
  - **Google Gemini** (1500 requêtes gratuites/jour via Google AI Studio).
  - **OpenRouter** (modèles gratuits ou payants : Nemotron-VL, Gemma-4, etc.).
  - **Groq** (raffinement ultra-rapide du français parlé).
  - **Endpoint Personnalisé (OpenAI-compatible)** : renseignez n'importe quel Base URL, Clé et nom de modèle.
- **Personnalisation Typographique & Style** :
  - Choix des langues source et cible (Japonais, Français, Anglais, Coréen, Chinois...).
  - Dimensionnement : auto-fit adaptatif à la bulle ou taille fixe en pixels.
  - Style de police (Anime Manga Bold, Comic, Sans-serif, Serif).
  - Forme du masque de bulle (arrondi doux, ellipse, rectangle, transparent).
- **Zéro Modèle Local & Empreinte Minimale** :
  - Consommation mémoire < 50 Mo de RAM.
  - Aucun risque de faire figer ou planter la machine.

---

## 2. Lancement en 1 Clic

### Depuis le Bureau (Raccourci Desktop) :
Double-cliquez simplement sur l'icône **Manga Translator Studio** sur votre Bureau.

### Ou depuis le script :
```bash
./lancer_manga_translator.sh
```
*Le script démarre le serveur local et ouvre automatiquement l'interface dans votre navigateur à l'adresse `http://localhost:8000`.*
