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
        ('/dashboard', ['orbit-logo', 'app-brand']),
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


def test_ui_3_pages_marqueurs(admin_client):
    """Marqueurs UI des 3 pages ciblees par le batch polish (page-head/KPI/toolbar/table)."""
    pages = {
        '/suivi_avancement': ['page-head', 'kpi-band', 'avm-kpis', 'av-tabs', 'kpiBar'],
        '/taches/aujourdhui': ['page-head', 'kpi-band', 'orbit-toolbar', 'task-board', 'taskBoard'],
        '/dossiers': ['page-head', 'kpi-band', 'orbit-toolbar', 'tableDossiers', 'emptyState'],
    }
    for path, marks in pages.items():
        r = admin_client.get(path, follow_redirects=True)
        html = r.get_data(as_text=True)
        missing = [m for m in marks if m not in html]
        assert r.status_code == 200, f'{path} -> {r.status_code}'
        assert not missing, f'{path}: marqueurs UI manquants {missing}'


def test_sidebar_structree(admin_client):
    """Refonte 9b2164a : le brand vit dans la topbar, la sidebar est une <nav> equilibree."""
    import re
    html = admin_client.get('/dashboard', follow_redirects=True).get_data(as_text=True)
    m = re.search(r'<a class="app-brand"[^>]*>([\s\S]*?)</a>', html)
    assert m, 'brand topbar introuvable'
    assert 'orbit-logo' in m.group(1), 'logo orbit absent du brand'
    m = re.search(r'<nav class="sidebar-menu"[^>]*>([\s\S]*?)</nav>', html)
    assert m, 'nav sidebar-menu introuvable'
    assert 'sidebar-nav-item' in m.group(1), 'items de navigation absents'
    seg = html[html.index('<aside class="app-sidebar"'):]
    seg = seg[:seg.index('</aside>')]
    assert seg.count('<div') == seg.count('</div>'), 'sidebar mal equilibree (div non fermees)'


def test_triage_pl_dashboard_avec_totaux(flask_app, admin_client, membre_client, seed):
    """Triage Pennylane : alerte avec totaux cote manager, carte repliable cote collaborateur."""
    from app import db
    from app.models import PennylaneItem
    with flask_app.app_context():
        db.session.add_all([
            PennylaneItem(dossier_id=seed['d1'], item_type='facture_vente',
                          item_id='fv-1', reference='FAC-001', montant=1200.0, statut='a_traiter'),
            PennylaneItem(dossier_id=seed['d1'], item_type='facture_vente',
                          item_id='fv-2', reference='FAC-002', montant=300.0, statut='a_traiter'),
            PennylaneItem(dossier_id=seed['d2'], item_type='facture_achat',
                          item_id='fa-1', reference='ACH-001', montant=450.0, statut='a_traiter'),
            PennylaneItem(dossier_id=seed['d2'], item_type='transaction',
                          item_id='tx-1', reference='VIR SFR', montant=89.99, statut='a_traiter'),
        ])
        db.session.commit()

    # Manager : alerte cliquable vers /pennylane avec totaux par nature (refonte 9b2164a).
    html = admin_client.get('/dashboard', follow_redirects=True).get_data(as_text=True)
    assert 'bi-inboxes-fill' in html, 'alerte triage absente'
    i = html.index('bi-inboxes-fill')
    seg = html[html.rfind('<a ', 0, i):html.index('</a>', i)]
    assert 'href="/pennylane"' in seg, 'lien vers la page Pennylane absent'
    assert '<span class="dar-num">4</span> documents Pennylane à traiter' in seg
    assert '2 dossiers' in seg
    assert '2 ventes' in seg
    assert '1 achat' in seg
    assert '1 flux bancaire' in seg

    # Collaborateur : carte detaillee repliable + persistance localStorage.
    html = membre_client.get('/dashboard', follow_redirects=True).get_data(as_text=True)
    assert 'id="plTriageCard"' in html, 'carte de triage absente'
    assert 'id="plTriageToggle"' in html, 'bouton repli/agrandir absent'
    assert 'data-bs-target="#plTriageBody"' in html, 'liaison collapse absente'
    assert 'pl-tr-summary' in html, 'barre de synthese des totaux absente'
    import re
    m = re.search(r'<div class="card-body-premium p-0 collapse pl-tr-body" id="plTriageBody">', html)
    assert m, 'corps de la carte non repliable par defaut'
    assert "localStorage.getItem(KEY)" in html, 'etat du repli non memorise'

