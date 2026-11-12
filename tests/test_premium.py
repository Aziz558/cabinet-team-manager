"""Premium layer V2 : versionnement des assets (?v=mtime), ordre de chargement.

Plan de reference : docs/PLAN_PREMIUM.md (§8 checklist).

Depuis le 2026-11-07 les « ?v=3 » ecrits a la main sont remplaces par asset(),
qui derive la version de la date de modification du fichier. Les tests ne
peuvent donc plus figer un numero : ils verifient la PRESENCE d'une version.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_login_charged_la_couche_premium(client):
    """La page publique /login charge bien la surcouche versionnee."""
    r = client.get('/login')
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert re.search(r'orbit-premium\.css\?v=\d+', html)
    assert re.search(r'orbit-premium\.js\?v=\d+', html)
    assert 'class="orbit-premium"' in html


def test_pages_authentifiees_chargent_la_feuille_systeme(admin_client):
    """base.html : design system unifie, charge en dernier.

    Depuis la refonte 9b2164a, base.html ne charge plus que orbit-system.css
    (composants/structure) puis orbit.css (thème unifié clair/sombre, dernier
    mot). Les couches historiques (style, light-theme, elevate, fixes…) ne
    doivent plus réapparaître. Chaque asset porte une version -> cache long.
    """
    html = admin_client.get('/dashboard', follow_redirects=True).get_data(as_text=True)
    assert 'orbit-system.css' in html
    assert re.search(r'orbit-premium\.js\?v=\d+', html)
    for fichier in ('css/orbit-system.css', 'css/orbit.css'):
        assert re.search(re.escape(fichier) + r'\?v=\d+', html), \
            'asset sans version (donc non cachable) : %s' % fichier
    # Ordre : composants/structure -> thème unifié (dernier mot).
    assert html.index('orbit-system.css') < html.index('orbit.css')
    for old in ('style.css', 'light-theme.css', 'orbit-elevate.css', 'orbit-fixes.css',
                'polish.css', 'workspace.css', 'orbit-premium.css',
                'mobile-responsive.css', 'filters-premium.css',
                'orbit-hallmark-fix.css', 'orbit-ds.css'):
        assert 'css/%s' % old not in html, 'couche obsolete encore chargee : %s' % old
    assert html.index('orbit-workspace.js') < html.index('orbit-premium.js')


def test_pages_authentifiees_sans_mojibake_ni_pourcentage_anglais(admin_client):
    """Garde-fou de rendu : plus de mojibake ni de « 75.0% » dans l'app."""
    import re
    pages = ['/dashboard', '/dossiers', '/taches', '/suivi_avancement', '/checklist',
             '/equipes', '/liste_membres', '/fiscal', '/settings', '/profil',
             '/notifications', '/pennylane', '/analytics']
    mojibake = re.compile(r'Ã[\u0080-\u00bf]|â[\u0080-\u00bf\u0153\u0161]|ð[\u0080-\u00bf]|Â[\u00a0-\u00bf]')
    pourcentage_en = re.compile(r'>\s*\d+\.\d+\s*%')
    for page in pages:
        r = admin_client.get(page, follow_redirects=True)
        assert r.status_code == 200, page
        body = r.get_data(as_text=True)
        assert not mojibake.search(body), 'mojibake sur %s : %s' % (page, set(mojibake.findall(body)))
        assert not pourcentage_en.search(body), 'pourcentage non francais sur %s' % page


def test_cache_statiques_versionnes(client):
    """Fichier avec ?v= : cache long. Sans ?v= : pas de cache long. sw.js : jamais."""
    r = client.get('/static/js/orbit-premium.js?v=8')
    assert r.status_code == 200
    assert 'max-age=31536000' in r.headers.get('Cache-Control', '')
    r = client.get('/static/css/style.css?v=9')
    assert 'max-age=31536000' in r.headers.get('Cache-Control', '')
    # Les images versionnees aussi (elles pesent lourd dans les listes).
    r = client.get('/static/img/logo-jmh.png?v=1')
    assert 'max-age=31536000' in r.headers.get('Cache-Control', '')
    r = client.get('/static/js/orbit-premium.js')
    assert 'max-age' not in r.headers.get('Cache-Control', '')
    r = client.get('/static/sw.js')
    assert 'no-cache' in r.headers.get('Cache-Control', '')
    # Meme avec une version, le service worker ne doit JAMAIS etre mis en cache :
    # un worker fige un an casse l'application pour tous les utilisateurs.
    r = client.get('/static/sw.js?v=1')
    assert 'max-age' not in r.headers.get('Cache-Control', '')


def test_asset_css_v2_complet(client):
    """CSS premium : 200, bloc V2 + transition de navigation native, braces equilibrees."""
    r = client.get('/static/css/orbit-premium.css')
    body = r.get_data(as_text=True)
    assert r.status_code == 200
    assert 'V2 FLUIDITE' in body
    assert 'orbit-progress' in body          # barre de progression V2
    assert '@view-transition { navigation: auto; }' in body  # pas d'ecran noir
    assert body.count('{') == body.count('}')


def test_asset_js_v21_modules(client):
    """JS premium V2.1 : modules attendus presents, effets retires absents."""
    r = client.get('/static/js/orbit-premium.js')
    body = r.get_data(as_text=True)
    assert r.status_code == 200
    for fn in ('initReveal', 'initRipple', 'initToastDock',
               'initPrefetch', 'initProgress', 'initSmoothAnchors'):
        assert fn in body, 'module manquant: %s' % fn
    # Retires (feedback) : fondu inter-pages = ecran noir, tilt = hover instable.
    assert 'initPageTransition' not in body
    assert 'initTilt' not in body
    assert 'orbit-leaving' not in body
    # Piege connu (PLAN Â§5) : un join('\\\\n') casserait silencieusement le
    # CSS injecte sans que node --check ne le voie. On exige '\n' (escape JS).
    assert "].join('\\n')" in body
