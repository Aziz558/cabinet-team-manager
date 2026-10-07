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


def test_carte_triage_pl_repliable_avec_totaux(flask_app, admin_client, seed):
    """La carte Triage Pennylane : bouton repli + synthese des totaux par nature."""
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

    html = admin_client.get('/dashboard', follow_redirects=True).get_data(as_text=True)
    assert 'id="plTriageCard"' in html, 'carte de triage absente'
    assert 'id="plTriageToggle"' in html, 'bouton repli/agrandir absent'
    assert 'data-bs-target="#plTriageBody"' in html, 'liaison collapse absente'
    assert 'pl-tr-summary' in html, 'barre de synthese des totaux absente'
    # Totaux par nature affiches dans la synthese (2 vente, 1 achat, 1 flux)
    seg = html[html.index('pl-tr-summary'):]
    seg = seg[:seg.index('</div>')]
    assert '<strong>2</strong> vente' in seg, 'total vente absent de la synthese'
    assert '<strong>1</strong> achat' in seg, 'total achat absent de la synthese'
    assert '<strong>1</strong> flux' in seg, 'total flux absent de la synthese'
    assert '<strong>4</strong> total' in seg, 'total general absent de la synthese'
    # Etat initial replie (sans classe show) + persistance localStorage
    import re
    m = re.search(r'<div class="card-body-premium p-0 collapse pl-tr-body" id="plTriageBody">', html)
    assert m, 'corps de la carte non repliable par defaut'
    assert "localStorage.getItem(KEY)" in html, 'etat du repli non memorise'

