---
name: ui-ux-pro-designer
description: >-
  Use this skill whenever designing, auditing, polishing, or refactoring UI/UX components, CSS architectures, design systems, and visual layouts in web applications.
---

# UI/UX Pro Designer — Guidelines & Rigorous Standards

Ce skill formalise les règles d'or et standards professionnels d'UI/UX design appliqués aux interfaces modernes (style Linear, Apple HIG, Tailwind CSS & Modern Web Guidance).

---

## 1. Principes Fondamentaux de Conception

1. **Hiérarchie Visuelle Implacable & Zéro Bruit Inutile** :
   - Chaque élément sur l'écran doit avoir un rôle précis et unique.
   - Ne jamais répéter une même information d'état à deux endroits visibles simultanément (ex: badges de connexion API).
   - Privilégier des typographies équilibrées : Title (Semibold/Bold, tracking serré `-0.02em`), Subtitle (Regular, couleur secondaire atténuée), Body (14-15px, interlignage 1.5).

2. **Système de Design Tokens Harmonisé** :
   - **Échelle d'espacement modulaire (base 4px / 8px)** : `4px`, `8px`, `12px`, `16px`, `20px`, `24px`, `32px`, `48px`.
   - **Rayons de courbure cohérents** :
     - Éléments imbriqués : le rayon intérieur doit être strictement égal au rayon extérieur moins le padding (`R_interieur = R_exterieur - padding`).
     - Boutons & inputs : `10px`.
     - Cartes & panneaux : `16px` à `20px`.
     - Badges & pilules : `9999px` (full pill).
   - **Couleurs & Contrastes WCAG AA/AAA** :
     - Thème clair : Fond principal doux (`#f8fafc` ou `#fafafa`), cartes blanches pures (`#ffffff`) avec bordure subtile (`rgba(0, 0, 0, 0.06)` à `rgba(0, 0, 0, 0.08)`) et ombre diffuse portée.
     - Thème sombre : Fond riche et profond (`#0c0d12` ou `#0f1117`), surfaces étagées (`#151821`, `#1c202d`), bordures fines (`rgba(255, 255, 255, 0.08)`), surbrillance spéculaire discrète (`top border highlight`).

3. **Micro-Interactions & Physique Réaliste** :
   - Utiliser des courbes d'animation naturelles :
     - Entrée / transition rapide : `cubic-bezier(0.16, 1, 0.3, 1)` ou spring `cubic-bezier(0.34, 1.56, 0.64, 1)`.
     - Durée perçue idéale : `150ms` à `250ms` pour les états `hover`/`active`, `300ms` à `400ms` pour les modales et tiroirs.
   - Retours d'action tangibles : `transform: scale(0.97)` ou `translateY(-1px)` au hover/active.

4. **Accessibilité & État de Focus** :
   - Tout élément interactif doit posséder un `:focus-visible` net (`outline: 2px solid var(--accent)` avec `outline-offset: 2px`).
   - Respect strict des zones tactiles minimales : `40×40px` minimum sur desktop et mobile.
   - Respect de `prefers-reduced-motion: reduce`.

---

## 2. Protocole de Validation Obligatoire (No Blind UI)

Toute modification apportée à l'UI doit obligatoirement être validée via le protocole en 3 points :
1. **Inspection DOM & Syntaxe** : `node --check` sur le code JS et validation des balises sémantiques.
2. **Mesure des Dimensions Réelles** : Vérification dans Playwright via `getBoundingClientRect()` pour éliminer tout débordement (overflow invisible, texte tronqué anormalement, scrollbar parasite).
3. **Double Capture d'Écran Rendu Réel** : Capture d'écran Playwright en thème clair ET en thème sombre, avec comparaison visuelle avant/après.
