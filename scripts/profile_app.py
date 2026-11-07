"""Profileur de pages JMH Orbit — temps de réponse, requêtes SQL, poids HTML.

Usage :
    python scripts/profile_app.py                # sur data/app.db
    python scripts/profile_app.py --scale 5      # copie la base et multiplie
                                                 # les dossiers/tâches par 5
                                                 # (~60 dossiers comme en prod)

Objectif : sortir du « je sens que c'est lent » et obtenir des chiffres
reproductibles (ms, nombre de requêtes SQL, octets) avant/après nettoyage.
La base d'origine n'est JAMAIS modifiée : --scale travaille sur une copie
temporaire.
"""
import argparse
import os
import pathlib
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PAGES = [
    ('/', None),
    ('/dashboard', None),
    ('/dossiers', None),
    ('/taches', None),
    ('/mes_taches', None),
    ('/checklist', None),
    ('/checklist?etape=grille&taxe=tva_mensuel', None),
    ('/pennylane', None),
    ('/suivi_avancement', None),
    ('/calendrier', None),
    ('/notifications', None),
    ('/analytics', None),
    ('/settings', None),
    ('/api/notifications', None),
    ('/api/recherche-globale?q=a', None),
]


def preparer_base(scale: int) -> pathlib.Path:
    """Copie la base locale et, si demandé, duplique les volumes."""
    source = ROOT / 'data' / 'app.db'
    if not source.exists():
        sys.exit(f'Base introuvable : {source}')
    if scale <= 1:
        return source
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='orbit_prof_')) / 'app.db'
    shutil.copy2(source, tmp)
    c = sqlite3.connect(tmp)
    nb = c.execute('select count(*) from dossiers').fetchone()[0]
    cols = [r[1] for r in c.execute('pragma table_info(dossiers)')]
    for i in range(scale - 1):
        for row in c.execute('select * from dossiers').fetchall()[:nb]:
            d = dict(zip(cols, row))
            d.pop('id', None)
            d['numero_dossier'] = f"{d.get('numero_dossier') or 'D'}-x{i}"
            keys = ','.join(d)
            vals = ','.join('?' * len(d))
            c.execute(f'insert into dossiers ({keys}) values ({vals})', list(d.values()))
    c.commit()
    c.close()
    return tmp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scale', type=int, default=1)
    ap.add_argument('--runs', type=int, default=3)
    args = ap.parse_args()

    base = preparer_base(args.scale)
    os.environ['SECRET_KEY'] = 'profile-secret'
    os.environ.setdefault('ORBIT_NO_SCHEDULER', '1')
    os.environ['ORBIT_SQLITE_PATH'] = str(base)

    from sqlalchemy import event
    from app import app, db

    compteur = {'n': 0}

    with app.app_context():
        engine = db.engine

    @event.listens_for(engine, 'before_cursor_execute')
    def _compter(conn, cursor, statement, params, context, executemany):
        compteur['n'] += 1

    app.config['TESTING'] = True
    client = app.test_client()

    with app.app_context():
        from app.models import User
        admin = User.query.filter_by(role='admin').first()
        if not admin:
            sys.exit('Aucun admin en base')
        uid = admin.id
        nb_dossiers = db.session.execute(db.text('select count(*) from dossiers')).scalar()

    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
        sess['_fresh'] = True

    print(f'Base : {base}')
    print(f'Dossiers : {nb_dossiers} | {args.runs} passage(s) par page\n')
    entete = f'{"page":44s} {"ms (méd.)":>10s} {"SQL":>6s} {"Ko":>8s}  code'
    print(entete)
    print('-' * len(entete))

    resultats = []
    for chemin, _ in PAGES:
        temps, sqls, tailles, code = [], [], [], 0
        for _ in range(args.runs):
            compteur['n'] = 0
            t0 = time.perf_counter()
            r = client.get(chemin)
            temps.append((time.perf_counter() - t0) * 1000)
            sqls.append(compteur['n'])
            tailles.append(len(r.data))
            code = r.status_code
        med = statistics.median(temps)
        resultats.append((chemin, med, max(sqls), max(tailles), code))
        print(f'{chemin[:44]:44s} {med:10.0f} {max(sqls):6d} '
              f'{max(tailles) / 1024:8.1f}  {code}')

    print('\nPages les plus coûteuses (ms) :')
    for chemin, med, sql, taille, code in sorted(resultats, key=lambda x: -x[1])[:5]:
        print(f'  {med:7.0f} ms  {sql:4d} SQL  {chemin}')
    print('\nPages qui explosent en requêtes SQL :')
    for chemin, med, sql, taille, code in sorted(resultats, key=lambda x: -x[2])[:5]:
        print(f'  {sql:4d} SQL  {med:7.0f} ms  {chemin}')


if __name__ == '__main__':
    main()