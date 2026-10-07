# JMH ORBIT — Plan d'Actions ULTRA-PREMIUM (reproductible par tout modèle)

> Objectif : refonte visuelle **non-breaking** niveau Linear / Stripe / Vercel.
> Surcouche progressive, zéro régression métier, fluidité 60fps, accessibilité intacte.
> Ce plan est **autosuffisant** : un autre modèle (ou humain) peut l'appliquer sans contexte.

---

## 1) Principes invariants

- **Non-breaking** : ne jamais modifier `style.css` / `workspace.css` / `light-theme.css` / templates métier. Tout passe par `orbit-premium.css` + `orbit-premium.js` chargés **en dernier**.
- **Progressif** : si `orbit-premium.*` échoue (404, JS error), l'app reste 100% fonctionnelle.
- **Tokens uniques** : `--orbit-ease: cubic-bezier(.16,1,.3,1)` (spring), radius 20px, `color-mix()` + `backdrop-filter`.
- **Perf** : `passive:true`, `requestAnimationFrame`, `IntersectionObserver`, guards `prefers-reduced-motion` + `hover:none`, `try/catch` sur chaque init.
- **Écriture fichiers (Windows, chemins avec espaces)** : `[System.IO.File]::ReadAllText/WriteAllText` en PowerShell ou éditeur direct. Ne jamais concaténer des chemins non quotés.

## 2) Fichiers cibles + ordre de chargement

| Fichier | Rôle | Position |
|---|---|---|
| `static/css/orbit-premium.css` | Surcouche visuelle | dernier `<link>`, **après** `workspace.css` + `light-theme.css` |
| `static/js/orbit-premium.js` | Micro-interactions | dernier `<script defer>`, **après** `orbit-workspace.js` |
| `templates/base.html` | Injection `?v=N` versionnés | bump `N` à chaque itération (cache Render) |
| `docs/PLAN_PREMIUM.md` | Ce plan | versionné dans le repo |

## 3) Design tokens (source unique — ne pas dupliquer)

```css
:root {
  --orbit-radius-xl: 20px;
  --orbit-radius-2xl: 24px;
  --orbit-ease: cubic-bezier(.16,1,.3,1);
  --orbit-ease-out: cubic-bezier(.4,0,.2,1);
  --orbit-shadow-card: 0 1px 2px rgba(16,24,40,.04), 0 8px 24px -12px rgba(16,24,40,.12);
  --orbit-shadow-float: 0 8px 32px -12px rgba(16,24,40,.18), 0 4px 16px -8px rgba(16,24,40,.10);
  --orbit-grid: rgba(20,22,26,.035);
}
```

- Halo focus : `rgba(255,140,0,.14)` — Hover lift : `translateY(-2px)` + `--orbit-shadow-float`
- Dark theme : décliner ombres/grille via `[data-theme="dark"]`

## 4) CSS — contenu de orbit-premium.css

### V1 (livré)
1. `body::before` : 3 radial gradients orange/bleu + grille 28px (fond signature)
2. `.app-topbar` : verre `saturate(1.2) blur(12px)` + `color-mix(... 82%, transparent)` + `.is-compact` au scroll
3. `.sidebar-nav-item` : hover `translateX(2px)`, `.active` halo orange + barre `::before`
4. `.card-premium` : radius 20, `box-shadow` card, hover border dégradée
5. `.stat-card` / `.qa-btn` / `.btn-premium` : hover lift `-2px`
6. Keyframes `orbitRise`, `shimmer`, `pulseBadge` ; classes `.stagger-1..6`
7. Toasts / modals / palette / empty-states / filtres `.avm-*` / responsive 767px
8. Ripple host : `.qa-btn, .btn-login { position:relative; overflow:hidden; }`

### V2 — Fluidité ULTRA (livré dans ce run)
```css
html { scrollbar-gutter: stable; }
@media (prefers-reduced-motion: no-preference) { html { scroll-behavior: smooth; } }
* { scrollbar-width: thin; scrollbar-color: var(--border-strong) transparent; }
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 999px; }
::-webkit-scrollbar-track { background: transparent; }
.card-premium, .stat-card, .task-card { contain: layout style paint; }
.btn-premium:active, .qa-btn:active, .btn-login:active { transform: scale(.98); transition-duration: .08s; }
.table-premium tbody tr, .table-premium tbody tr td { transition: background-color .18s ease; }
.table-premium tbody tr:hover td { background-color: var(--bg-hover); }
.orbit-progress { position: fixed; top:0; left:0; height:2px; width:0; z-index:9999;
  background: var(--orange-primary); opacity:0; pointer-events:none;
  transition: width .2s var(--orbit-ease); }
.orbit-progress.is-on { opacity: 1; }
```

**Anti-patterns interdits** (fluidité) :
- `will-change` en masse sur toutes les cartes (gâche la mémoire GPU)
- `transform` sur `tr` de tableau (floute le texte, jank au survol)
- `content-visibility:auto` sur le `<main>` entier (saute la scrollbar si `contain-intrinsic-size` faux)
- animation que sur `opacity/transform` (jamais `width/height/top`)

## 5) JS — architecture de orbit-premium.js

### Squelette obligatoire
```js
(function () {
    'use strict';
    var reduce = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    function init() {
        try {
            initToastDock(); initReveal(); initRipple(); initTilt();
            initPageTransition(); initPrefetch(); initProgress(); initSmoothAnchors();
        } catch (e) { if (window.console && console.warn) console.warn('[orbit-premium]', e); }
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
```

### Modules
| # | Module | Règle clé |
|---|---|---|
| 1 | `initReveal` | IO `threshold .08`, stagger 45ms, retire les classes après 900ms |
| 2 | `initRipple` | `pointerdown` `passive:true` sur `.btn-premium/.qa-btn/.btn-login`, retiré à 650ms |
| 3 | `initTilt` | guard `hover:none`, perspective 700px, max 6deg, `pointerleave` reset |
| 4 | `initPageTransition` | classe `orbit-leaving` 160ms, skip `#`, `javascript:`, `form`, `data-no-transition=1`, cleanup `pageshow` |
| 5 | `initToastDock` | injecte `<style>` — **toujours** `[...].join('\n')` (jamais de template multiline) |
| 6 | `initPrefetch` | au `mouseover`/`focusin` d'un `a[href]` interne → `<link rel=prefetch>` (dédup `Set`, ignore `/#...`) |
| 7 | `initProgress` | `.orbit-progress` : 42% au clic lien, 100% `beforeunload`, reset `pageshow` |
| 8 | `initSmoothAnchors` | `a[href^="#"]` → `scrollIntoView({behavior:'smooth'})` si pas de `reduce` |

Piège récurrent : un `join('\\n')` (double backslash) casse silencieusement le CSS injecté → `node --check` ne le détecte **pas** (syntaxe valide). Vérifier le token après chaque édition.

## 6) Injection dans base.html

```html
<!-- </head> : après light-theme.css -->
<link href="{{ url_for('static', filename='css/orbit-premium.css') }}?v=2" rel="stylesheet">
<!-- </body> : après orbit-workspace.js -->
<script src="{{ url_for('static', filename='js/orbit-premium.js') }}?v=2" defer></script>
```

Bump `?v=N` à chaque livraison (Render sert un cache agressif).

## 7) Recettes PowerShell (chemins avec espaces)

```powershell
# Lire
[System.IO.File]::ReadAllText('C:\...\cabinet_team_manager\templates\base.html')
# Écrire un gros payload (here-string)
$b = @'
...contenu...
'@
[System.IO.File]::WriteAllText('C:\...\orbit-premium.css', $b)
# Vérifs
node --check 'C:\...\orbit-premium.js'          # doit être 0
([regex]::Matches([System.IO.File]::ReadAllText($css),'\{')).Count   # == compte '}'
```

## 8) Checklist AVANT chaque push

1. `node --check` JS OK + token `join('\n')` correct
2. Braces CSS équilibrées
3. Test local : `venv\Scripts\python.exe -m pytest tests\test_premium.py -q` → OK
   (couvre : /login + tags ?v=N, ordre workspace→premium, assets V2, join('\n'))
   La CI (`.github/workflows/ci.yml`) refait `ruff check` + `node --check` + `pytest -q`
4. `git add` (uniquement les fichiers premium + base.html) → `commit` → `push origin main`
5. Render : `Invoke-WebRequest https://cabinet-team-manager.onrender.com/login` contient `?v=N` ;
   `/static/css/orbit-premium.css` et `/static/js/orbit-premium.js` → 200 (attendre le redeploy si besoin)

## 9) Roadmap

- **V1** ✅ reveal, ripple, tilt, page transition, toast dock
- **V2** ✅ fluidité : scrollbar fine stable, smooth scroll, contain cartes, press feedback, prefetch, barre de progression, smooth anchors
- **V3** (demandé) : polish ciblé Dashboard / Tâches / Dossiers / Pennylane (tables, filtres animés, skeletons LCP)
- **V4** : audit Lighthouse (LCP <1.8s, CLS 0, a11y 100)

## 10) Garde-fous

- Toujours `prefers-reduced-motion` sur toute animation JS/CSS
- Toujours versionner `?v=N`
- Ne jamais casser la logique métier ni les sélecteurs existants
- Chaque itération : commit + vérif Render + mise à jour de ce plan
