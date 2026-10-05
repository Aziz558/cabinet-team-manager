"""Securite : aucun mot de passe en dur dans le code tracke."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SECRETS = ("'admin1234'", '"admin1234"', "'Admin2026!'", '"Admin2026!"')


def test_aucun_secret_en_dur_dans_app():
    bad = []
    for pyf in list((ROOT / 'app').glob('*.py')):
        txt = pyf.read_text(encoding='utf-8')
        for s in SECRETS:
            if s in txt:
                bad.append(f'{pyf.name}: {s}')
    assert bad == [], f'Mots de passe en dur trouves : {bad}'


def test_migrations_baseline_existe():
    versions = list((ROOT / 'migrations' / 'versions').glob('*.py'))
    assert versions, 'aucune migration dans migrations/versions'
    joined = '\n'.join(p.read_text(encoding='utf-8') for p in versions)
    assert 'down_revision = None' in joined, 'baseline (revision racine) introuvable'
    assert "op.create_table('users'" in joined


def test_release_migrate_compile():
    src = (ROOT / 'scripts' / 'release_migrate.py').read_text(encoding='utf-8')
    compile(src, 'release_migrate.py', 'exec')
