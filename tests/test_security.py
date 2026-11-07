"""Securite : aucun mot de passe ni cle de secours en dur dans le code tracke."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SECRETS = ("'admin1234'", '"admin1234"', "'Admin2026!'", '"Admin2026!"')


def _fichiers_python():
    """Tout le code applicatif, sous-dossiers compris (app/integrations/...)."""
    return [p for p in (ROOT / 'app').rglob('*.py') if '__pycache__' not in str(p)]


def test_aucun_secret_en_dur_dans_app():
    bad = []
    for pyf in _fichiers_python():
        txt = pyf.read_text(encoding='utf-8')
        for s in SECRETS:
            if s in txt:
                bad.append(f'{pyf.relative_to(ROOT)}: {s}')
    assert bad == [], f'Mots de passe en dur trouves : {bad}'


def test_aucune_cle_de_secours_en_dur():
    """Les clés de secours (reset admin, cron, webhooks) viennent de l'environnement.

    Le dépôt est public : une clé littérale dans le code est une porte ouverte.
    Ce test attrape les affectations du type MA_CLE = 'valeur-longue'.

    Ne sont PAS des secrets : les noms de réglages stockés en base
    (PENNYLANE_WEB_COOKIES, PENNYLANE_TVA_SYNC_JOB…) — identifiants en
    MAJUSCULES et soulignés uniquement.
    """
    motif = re.compile(
        r"^[A-Z0-9_]*(?:SECRET|KEY|TOKEN|PASSWORD|PASS|CLE)[A-Z0-9_]*\s*=\s*['\"]([^'\"]{8,})['\"]",
        re.MULTILINE)
    identifiant = re.compile(r'^[A-Z0-9_]+$')
    bad = []
    for pyf in _fichiers_python():
        for m in motif.finditer(pyf.read_text(encoding='utf-8')):
            if identifiant.match(m.group(1)):
                continue  # nom de réglage en base, pas un secret
            bad.append(f'{pyf.relative_to(ROOT)}: {m.group(0)[:60]}')
    assert bad == [], f'Clés en dur trouvees : {bad}'


def test_aucun_secret_dans_les_gabarits():
    """Aucun mot de passe ne doit être écrit dans un template."""
    bad = []
    for html in (ROOT / 'templates').glob('*.html'):
        txt = html.read_text(encoding='utf-8')
        for s in SECRETS:
            if s in txt:
                bad.append(f'{html.name}: {s}')
    assert bad == [], f'Secrets dans les gabarits : {bad}'


def test_fichiers_sensibles_non_suivis():
    """.env, cookies et bases locales ne doivent pas être dans le dépôt.

    Le dépôt GitHub est public : un cookies.txt ou un app.db versionné expose
    les sessions Pennylane et les données clients.
    """
    import subprocess
    suivis = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True,
                            text=True, check=False).stdout.splitlines()
    interdits = [f for f in suivis
                 if re.search(r'(^|/)(cookies?[^/]*\.txt|\.env|app\.db|.*\.sqlite3?)$', f)]
    assert interdits == [], f'Fichiers sensibles suivis par git : {interdits}'


def test_migrations_baseline_existe():
    versions = list((ROOT / 'migrations' / 'versions').glob('*.py'))
    assert versions, 'aucune migration dans migrations/versions'
    joined = '\n'.join(p.read_text(encoding='utf-8') for p in versions)
    assert 'down_revision = None' in joined, 'baseline (revision racine) introuvable'
    assert "op.create_table('users'" in joined


def test_release_migrate_compile():
    src = (ROOT / 'scripts' / 'release_migrate.py').read_text(encoding='utf-8')
    compile(src, 'release_migrate.py', 'exec')
