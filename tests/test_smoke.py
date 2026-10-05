"""Smoke test : pages principales en 200 + marqueurs UI (logo, page-head)."""


def test_login_public(client):
    r = client.get('/login')
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert 'orbit-logo' in html
    assert 'orbit-ring-1' in html  # logo anime de la page de connexion


def test_redirection_racine_vers_login(client):
    r = client.get('/', follow_redirects=False)
    assert r.status_code == 302
    assert '/login' in r.headers.get('Location', '')


def test_pages_authentifiees(admin_client):
    pages = [
        ('/dashboard', ['orbit-logo', 'sidebar-brand']),
        ('/taches', ['orbitUrgBtn', 'orbitTaskCount', 'orbit-toolbar']),
        ('/dossiers', ['page-head']),
        ('/membres', ['page-head', 'page-head-icon']),
        ('/equipes', ['page-head', 'page-head-icon']),
        ('/analytics', ['page-head', 'anneeSelect']),
        ('/notifications', ['page-head', 'page-head-icon']),
        ('/mes_taches', ['page-head', 'page-head-icon']),
        ('/settings', ['page-head', 'page-head-icon']),
        ('/dossiers?q=ZZZTEST', ['page-head']),
    ]
    for path, must in pages:
        r = admin_client.get(path, follow_redirects=True)
        html = r.get_data(as_text=True)
        missing = [m for m in must if m not in html]
        assert r.status_code == 200, f'{path} -> {r.status_code}'
        assert not missing, f'{path}: marqueurs manquants {missing}'


def test_sidebar_structree(admin_client):
    """Le brand de la sidebar doit etre ferme avant le menu (regression </div>)."""
    import re
    html = admin_client.get('/dashboard', follow_redirects=True).get_data(as_text=True)
    m = re.search(r'<div class="sidebar-brand">([\s\S]{0,3000}?)<div class="sidebar-menu">', html)
    assert m, 'bloc sidebar-brand introuvable'
    seg = m.group(1)
    # +1 : la <div class="sidebar-brand"> d'ouverture est hors segment, sa
    # fermeture est dedans -> le desequilibre exact doit etre de 1.
    assert seg.count('<div') + 1 == seg.count('</div>'), 'sidebar-brand mal fermee (div non equilibree)'
    assert 'orbit-logo' in seg, 'logo orbit absent du brand sidebar'
