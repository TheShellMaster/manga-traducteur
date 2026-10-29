# LESSONS.md — Journal des Erreurs, Découvertes & Correctifs

Ce fichier consigne les erreurs rencontrées, leur cause racine et la règle préventive associée au cours du développement de **Manga Translator Studio**.

---

## 1. HTTP 405 avec `curl -I` sur les routes FastAPI `@app.get`
- **Symptôme** : `curl -I http://127.0.0.1:8000/api/image/...` renvoyait `HTTP/1.1 405 Method Not Allowed`.
- **Cause racine** : `curl -I` envoie une requête `HEAD`. Sur certaines versions de FastAPI/Starlette, `@app.get` ne génère pas automatiquement le handler `HEAD` pour les réponses dynamiques `FileResponse`.
- **Correctif & Règle** : Toujours utiliser `curl -s -o /dev/null -w "%{http_code}"` (requête `GET`) pour vérifier la disponibilité et le type MIME d'un endpoint d'image.

---

## 2. `ConnectionResetError(104)` sur `https://openrouter.ai/api/v1/models`
- **Symptôme** : Un appel Python `requests.get("https://openrouter.ai/api/v1/models")` sans en-tête `User-Agent` explicite ou derrière certains proxys échouait parfois par `Connection reset by peer`.
- **Cause racine** : Filtrage Cloudflare/WAF sur le `User-Agent` par défaut `python-requests/x.y` ou réutilisation de socket.
- **Correctif & Règle** : Toujours inclure `"User-Agent": "Mozilla/5.0"` et un `timeout=20` explicite lors de l'interrogation du catalogue `/api/v1/models`.

---

## 3. Modèles OpenRouter `:free` réservés aux « Agentic Harnesses » (HTTP 403) & Quotas Journaliers (HTTP 429)
- **Symptôme** :
  - `thinkingmachines/inkling:free` et `thinkingmachines/inkling-small:free` figurent dans `/api/v1/models` avec `"image"` dans `input_modalities`, mais renvoient `HTTP 403: This model is currently only available on agentic harnesses`.
  - Les comptes OpenRouter sans crédits payants ont une limite globale de 50 requêtes/jour sur les modèles `:free` (`Rate limit exceeded: free-models-per-day`).
- **Correctif & Règle** :
  - Ne jamais inscrire un modèle dans `app/config.py` sur la seule foi de `/models` : toujours valider par un appel d'inférence réel (`HTTP 200` ou validation de disponibilité).
  - Intégrer un repli automatique transparent vers les autres clés Cloud Vision gratuites disponibles sur la machine (`OLLAMA_API_KEY` sur `https://ollama.com/v1` avec `gemma4:31b`, et `NVIDIA_API_KEY` sur `https://integrate.api.nvidia.com/v1` avec `meta/llama-3.2-90b-vision-instruct`) dès qu'OpenRouter renvoie `free-models-per-day`.

---

## 4. Sélection de la clé API selon le fournisseur dans `app/ static/js/app.js`
- **Symptôme** : `app.js` envoyait `cfg-custom-api-key`, `cfg-custom-base-url` et `cfg-custom-model` quel que soit le fournisseur sélectionné (`gemini`, `openrouter`, `auto`).
- **Cause racine** : Absence de branchement conditionnel sur `provider` lors de la construction du payload `/api/translate/start`.
- **Correctif & Règle** : Sélectionner `api_key` dynamiquement selon `provider` (`gemini` → `#cfg-gemini-key`, `openrouter` → `#cfg-openrouter-key`, `custom` → `#cfg-custom-api-key`) et n'envoyer `base_url`/`model` que si `provider === 'custom'`.

---

## 5. Bug Critique dans `app/groq_refine.py` (Groq jamais appelé)
- **Symptôme** : `refine_translations_with_groq()` filtrait uniquement les blocs où `not b.get("fr")`. Comme le modèle Vision fournit déjà un premier jet dans `translation`/`fr`, Groq n'était jamais appelé.
- **Cause racine** : Condition trop restrictive `if b.get("ja") and not b.get("fr")`.
- **Correctif & Règle** : Envoyer **toutes** les bulles de la page (`[{"ja": ..., "draft_fr": ...}]`) à Groq pour polir et harmoniser systématiquement chaque réplique en français naturel de manga, et nettoyer les balises `<think>...</think>` éventuelles de `qwen/qwen3.8-27b`.

---

## 6. Calibration Empirique du Masque Intelligent (`smart`) et Optimisation C (`Pillow`)
- **Symptôme** :
  - Un rectangle blanc naïf écrase les traits noirs des bulles et détruit les boîtes de narration ou pages titres sombres (ex: `002.jpg` de `Official_Chapter 37.cbz` où la médiane de luminance est `87–89` avec texte blanc `p90=242`).
  - Un parcours BFS en Python pur sur une boîte de `950×430` pixels prenait ~200 ms par boîte (`760 ms` par page).
- **Correctif & Règle** :
  - Utiliser `core_gray.histogram()` et `core_gray.point(lut)` en C (`Pillow`) + détection des composantes reliées au bord sur grille bornée (`<= 110×110`) + `ImageChops.subtract`, réduisant le temps de rendu complet d'une planche `1403×2000` à `~180 ms` tout en préservant à 100 % les contours noirs et les fonds sombres.
