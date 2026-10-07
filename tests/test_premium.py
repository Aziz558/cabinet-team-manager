"""Premium layer V2 : tags ?v=N, assets statiques, ordre de chargement.

Plan de reference : docs/PLAN_PREMIUM.md (§8 checklist).
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_login_charged_la_couche_premium(client):
    """La page publique /login charge bien la surcouche versionnee."""
    r = client.get('/login')
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert 'orbit-premium.css?v=2' in html
    assert 'orbit-premium.js?v=2' in html
    assert 'class="orbit-premium"' in html


def test_pages_authentifiees_chargent_le_premium(admin_client):
    """base.html : premium charge en DERNIER (apres workspace), jamais avant."""
    html = admin_client.get('/dashboard', follow_redirects=True).get_data(as_text=True)
    assert 'orbit-premium.css?v=2' in html
    assert 'orbit-premium.js?v=2' in html
    # Ordre imparatif : la surcouche ecrase (ou complète) le socle.
    assert html.index('workspace.css') < html.index('orbit-premium.css')
    assert html.index('orbit-workspace.js') < html.index('orbit-premium.js')


def test_asset_css_v2_complet(client):
    """CSS premium : 200, bloc V2 present, braces equilibrees."""
    r = client.get('/static/css/orbit-premium.css')
    body = r.get_data(as_text=True)
    assert r.status_code == 200
    assert 'V2 FLUIDITE' in body
    assert 'orbit-progress' in body  # barre de progression V2
    assert body.count('{') == body.count('}')


def test_asset_js_v2_modules(client):
    """JS premium : 200, les 8 modules V1+V2 presents, join('\\n') correct."""
    r = client.get('/static/js/orbit-premium.js')
    body = r.get_data(as_text=True)
    assert r.status_code == 200
    for fn in ('initReveal', 'initRipple', 'initTilt', 'initPageTransition',
               'initToastDock', 'initPrefetch', 'initProgress', 'initSmoothAnchors'):
        assert fn in body, 'module manquant: %s' % fn
    # Piege connu (PLAN §5) : un join('\\\\n') casserait silencieusement le
    # CSS injecte sans que node --check ne le voie. On exige '\n' (escape JS).
    assert "].join('\\n')" in body
