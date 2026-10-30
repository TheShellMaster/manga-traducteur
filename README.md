# 📖 Manga Translator Studio (100% Cloud Vision & Scanlation Pro)

Application Web moderne de traduction automatique de mangas, manhwas et comics, conçue pour fonctionner avec **zéro modèle lourd local** (`< 50 Mo` de RAM au repos, aucun GPU requis). Toute la puissance d'analyse visuelle (OCR, détection de bulles et traduction contextuelle) est déléguée aux APIs Cloud gratuites ou personnalisées, avec traitement **multithread parallèle (jusqu'à 3 pages en simultané)**.

---

## ✨ Fonctionnalités Principales

### 1. 🖼️ Formats Universels & Restitution au Format Exact
- **Archives complètes** : `.cbz`, `.cbr`, `.rar`, `.zip`.
- **Dossiers complets** : Import par glisser-déposer de dossiers entiers de chapitres (`webkitdirectory`).
- **Planches isolées** : `.png`, `.jpg`, `.jpeg`, `.webp`.
- **Export fidèle** : Le manga traduit est recompressé automatiquement dans le **même format d'origine** (ou téléchargé en un clic au format CBZ standard pour liseuses).

### 2. 👁️ 4 Modes de Visualisation & Liseuse Intégrée
1. **Comparateur Côte à Côte (Split-View)** : Planche originale à gauche, planche traduite à droite.
2. **Liseuse Seule** : Lecture plein écran de la version traduite avec bascule instantanée.
3. **Slider Interactif Avant / Après** : Curseur glissable superposant l'original et la version traduite en temps réel.
4. **Mode Webtoon (Défilement Continu)** : Lecture verticale sans coupure de tout le chapitre, particulièrement adaptée aux manhwas et webtoons.
- **Sens de lecture Manga (RTL)** : Bascule instantanée entre le sens japonais (Droite ➜ Gauche) et occidental (Gauche ➜ Droite).

### 3. 🎨 Qualité « Scanlation Pro » & Typographie Manga
- **Masquage Intelligent des Bulles (`smart`)** :
  - **Préservation des contours de bulles** : Analyse d'histogramme en C (`Pillow`) et détection des composantes connexes au bord pour effacer uniquement les kanjis/textes internes sans jamais effacer le contour noir de la bulle.
  - **Détection automatique Fond Sombre / Clair** : Les cartouches de narration sombres sont préservées et composées en texte blanc avec contour de sécurité.
- **Typographie en Losange (Diamond Word-Wrap)** :
  - Programmation dynamique équilibrant les lignes de texte pour épouser la forme ovale naturelle des bulles de manga et éliminer les mots orphelins.
  - Typographie française soignée (espaces insécables automatiques avant `!`, `?`, `:`, `;` et dans `« … »`).
- **Éditeur de Bulles en Direct (< 50 ms)** :
  - Panneau latéral **« 💬 Bulles »** permettant d'ajuster ou réécrire n'importe quelle réplique en direct sans relancer l'API.

### 4. ⚡ Vitesse & Ergonomie
- **Traduction Parallèle Multi-Pages** : Traitement de 2 à 3 pages en simultané, divisant le temps d'attente total par ~2.5x.
- **Flux LLM en Direct** : Visualisation en temps réel des répliques traduites au fur et à mesure que l'IA les analyse.
- **Résilience au Rechargement (F5)** : Si vous actualisez votre navigateur pendant ou après une traduction, votre session et votre progression sont immédiatement restaurées via `localStorage`.
- **Historique Persistant des Mangas** : Retrouvez tous vos chapitres traduits dans le panneau **« 📜 Historique »** pour les relire ou les télécharger à tout moment.

---

## 🔑 Guide d'Obtention des Clés d'API 100% Gratuites (Sans Carte Bancaire)

Manga Translator Studio n'a besoin d'aucune configuration manuelle complexe : **vous n'avez aucun nom de modèle ni aucune URL à copier**. Collez simplement votre clé dans l'application, et la liste déroulante affiche automatiquement les vrais modèles autorisés.

### 1. Google Gemini (Recommandé - Vision Haute Fidélité)
Google offre un quota gratuit extrêmement généreux sur ses meilleurs modèles Vision.
- **Site officiel** : [Google AI Studio](https://aistudio.google.com/)
- **Quota gratuit** : **1 500 requêtes gratuites par jour** (largement de quoi traduire 50 à 75 chapitres complets par jour).
- **Étapes pas-à-pas** :
  1. Rendez-vous sur [aistudio.google.com](https://aistudio.google.com/) et connectez-vous avec votre compte Google.
  2. Cliquez sur le bouton bleu **« Get API key »** (en haut à gauche).
  3. Cliquez sur **« Create API key »** (dans un nouveau projet ou un projet existant).
  4. Copiez votre clé d'API (commençant par `AIzaSy...`).
  5. Dans Manga Translator Studio, ouvrez **⚙️ Paramètres & APIs**, choisissez **Google Gemini**, collez votre clé et cliquez sur Enregistrer. Les modèles `gemini-2.5-flash` et `gemini-1.5-flash` sont automatiquement prêts !

### 2. Groq (Recommandé - Raffinement Instantané du Français)
Groq utilise des processeurs LPU ultra-rapides capables de polir vos dialogues en français naturel en moins de 300 millisecondes.
- **Site officiel** : [Groq Console](https://console.groq.com/)
- **Quota gratuit** : Gratuit pour un usage quotidien personnel.
- **Étapes pas-à-pas** :
  1. Créez un compte sur [console.groq.com](https://console.groq.com/).
  2. Rendez-vous dans l'onglet **« API Keys »** dans le menu de gauche.
  3. Cliquez sur **« Create API Key »**, donnez-lui un nom (ex: `manga-traducteur`) et copiez la clé `gsk_...`.
  4. Collez cette clé dans la case **Clé d'API Groq** des Paramètres de l'application.

### 3. OpenRouter (Multi-Fournisseurs & Modèles Vision Gratuits)
OpenRouter permet d'accéder à des dizaines de modèles Vision sans installer quoi que ce soit.
- **Site officiel** : [OpenRouter.ai](https://openrouter.ai/)
- **Étapes pas-à-pas** :
  1. Créez un compte gratuit sur [openrouter.ai](https://openrouter.ai/).
  2. Cliquez sur votre profil ➜ **« Keys »** ➜ **« Create a Key »**.
  3. Copiez la clé (`sk-or-v1-...`).
  4. Dans Manga Translator Studio, sélectionnez **OpenRouter** et collez votre clé : l'application charge en direct tous les modèles Vision gratuits signalés par `✨ (Gratuit)` (ex: `nvidia/nemotron-3.5-super-vl:free`).

---

## 💻 Guide d'Installation selon votre Système

### Prérequis
- **Python 3.10 ou supérieur** (Python 3.11, 3.12 ou 3.14 recommandés).
- Utilitaires d'archives pour ouvrir les fichiers `.cbr` et `.rar`.

### 1. Ubuntu / Debian / Linux Mint
Ouvrez votre terminal et exécutez :
```bash
sudo apt update && sudo apt install -y python3-venv python3-pip unrar p7zip-full fonts-dejavu-core
```

### 2. Fedora / Red Hat / RHEL
```bash
sudo dnf install -y python3 python3-pip unrar p7zip dejavu-sans-fonts
```

### 3. Arch Linux / Manjaro
```bash
sudo pacman -S --needed python python-pip unrar p7zip ttf-dejavu
```

### 4. macOS (via Homebrew)
```bash
brew install python unrar p7zip
```

### 5. Windows (via WSL2 Ubuntu)
Installez WSL2 puis suivez les instructions Ubuntu ci-dessus.

---

## 📦 Installation & Démarrage du Projet

1. **Cloner le dépôt ou accéder au dossier** :
   ```bash
   cd traducteur
   ```

2. **Créer l'environnement virtuel Python** :
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Installer les dépendances requises** :
   ```bash
   pip install -r requirements.txt
   ```

---

## 🚀 Lancement en 1 Clic

### Option A : Depuis le Bureau (Raccourci Desktop)
Double-cliquez simplement sur l'icône **Manga Translator Studio** présente sur votre Bureau.

### Option B : Depuis le Terminal
```bash
./lancer_manga_translator.sh
```
*Le script vérifie automatiquement l'environnement, démarre le serveur local et ouvre votre navigateur Web à l'adresse `http://localhost:8000`.*

---

## ⌨️ Raccourcis Clavier & Astuces

| Raccourci | Action |
| :---: | :--- |
| `←` / `→` | **Page précédente / Page suivante** (s'inverse automatiquement en mode RTL Manga) |
| `1` | Mode **Comparateur Côte à Côte** |
| `2` | Mode **Liseuse Seule** |
| `3` | Mode **Slider Interactif** Avant / Après |
| `4` | Mode **Webtoon** (défilement vertical sans interruption) |
| `R` | Basculer entre sens de lecture **Japonais RTL** (`🇯🇵 ←`) et **Occidental LTR** (`🌍 →`) |
| `F` | Activer / Quitter le **Plein Écran** |
| `Ctrl` + `Molette` | **Zoom fluide** sur la planche affichée (`50%` à `250%`) |
| **Clic sur une bulle** | Ouvre l'éditeur latéral pour retoucher le texte français en direct (< 50 ms) |
| **F5 (Actualiser)** | Restauration automatique et transparente de votre session sans perte de données |

---

## 🧪 Tests Automatisés

Le projet comprend une suite complète de **35 tests unitaires et d'intégration** (vérifiant la détection de bulles, le parseur JSON robuste, la calibration du masque anti-aplat noir, la résilience aux coupures d'API et la parallélisation) :

```bash
./venv/bin/pytest tests/ -q
```

---

## 📄 Licence

Distribué sous licence **MIT**. Développé pour la communauté scanlation et les amateurs de manga.
