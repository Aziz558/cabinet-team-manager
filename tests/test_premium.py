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
    """base.html : une seule feuille système, chargée en dernier.

    Depuis la consolidation, les 8 couches qui s'empilaient (polish, workspace,
    orbit-premium, mobile-responsive, filters-premium, orbit-elevate,
    orbit-hallmark-fix, orbit-ds) sont fusionnées dans orbit-system.css à ordre
    de cascade identique. L'intention du test d'origine est conservée : la
    couche qui a le dernier mot est bien chargée en dernier, et aucune couche
    historique ne doit réapparaître dans la page.
    """
    html = admin_client.get('/dashboard', follow_redirects=True).get_data(as_text=True)
    assert 'orbit-system.css' in html
    assert re.search(r'orbit-premium\.js\?v=\d+', html)
    # Chaque asset de base porte une version -> cache long possible.
    for fichier in ('css/style.css', 'css/light-theme.css', 'css/orbit-system.css',
                    'css/orbit-elevate.css', 'css/orbit-fixes.css'):
        assert re.search(re.escape(fichier) + r'\?v=\d+', html), \
            'asset sans version (donc non cachable) : %s' % fichier
    # Ordre : socle (style) -> thème clair -> feuille système -> couche Elevate
    # (jetons « Editorial Ink & Amber ») -> correctifs accessibilité (dernier mot).
    assert (html.index('style.css')
            < html.index('light-theme.css')
            < html.index('orbit-system.css')
            < html.index('orbit-elevate.css')
            < html.index('orbit-fixes.css'))
    # Les anciennes couches fusionnées dans orbit-system.css ne sont plus
    # chargées séparément par l'application (orbit-elevate.css est desormais
    # chargee VOLONTAIREMENT en dernier, voir couche Elevate).
    for old in ('polish.css', 'workspace.css', 'orbit-premium.css',
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
