"""Login ORBIT DOCKING — scène spatiale V1 (voir docs/PLAN_PREMIUM.md §11).

Couvre : intégration des tags/markup, présence des 3 assets,
et préservation du fallback login classique.
"""


def test_login_integre_la_scene_spatiale(client):
    """Le login charge la scène + son armement anti-flash, markup complet."""
    r = client.get('/login')
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert 'orbit-space.css?v=1' in html
    assert 'orbit-space.js?v=2' in html
    assert 'id="orbitSpace"' in html
    assert 'id="orbitPlanetBtn"' in html
    assert 'id="orbitBackBtn"' in html
    assert 'id="orbitFlash"' in html
    assert 'orbit-space-armed' in html        # armement anticipé (inline head)
    assert 'three.module.min.js' in html      # vendor LOCAL, aucun CDN a l'execution


def test_assets_spatiaux(client):
    """Les 3 assets existent, syntaxe/braces valides, etat docked present."""
    css = client.get('/static/css/orbit-space.css')
    js = client.get('/static/js/orbit-space.js')
    three = client.get('/static/js/vendor/three.module.min.js')

    cb = css.get_data(as_text=True)
    assert css.status_code == 200
    assert cb.count('{') == cb.count('}')
    assert 'orbit-state-docked' in cb
    assert 'orbitWarpFlash' in cb

    jb = js.get_data(as_text=True)
    assert js.status_code == 200
    assert 'orbit-space-armed' in jb
    assert 'three.module.min.js' in jb
    assert "import(" in jb                   # import ESM dynamique
    assert 'fps < 35' in jb                  # garde-fou performance

    assert three.status_code == 200
    assert len(three.data) > 500000          # three r160 complet


def test_fallback_login_classique(client):
    """Sans scene (JS off / reduce / pas de WebGL), le form reste utilisable."""
    r = client.get('/login')
    html = r.get_data(as_text=True)
    assert 'id="loginForm"' in html
    assert 'name="email"' in html
    assert 'name="password"' in html
    assert 'orbit-logo' in html              # marqueurs test_smoke preserves
