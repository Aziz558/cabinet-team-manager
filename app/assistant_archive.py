"""Archives ASTRO — export fin de journée hors de l'application.

Objectif quota Neon : la mémoire active et les conversations vivent en base le
temps de la journée (tampon léger), puis un job du soir les exporte vers un
stockage externe et purge le tampon.

- Stockage principal : Google Drive via COMPTE DE SERVICE (clé JSON saisie dans
  les Réglages + dossier partagé avec l'adresse du compte de service). Tout y
  passe : mémoire du cabinet + mémoires personnelles + conversations par collab.
- Secours : dossier local (ARCHIVE_LOCAL_DIR), UNIQUEMENT pour les mémoires
  personnelles et les conversations de chaque membre (jamais la mémoire cabinet).

Formats doubles : Markdown (lisible dans Obsidian / aperçu Drive) + JSON (index
fiable pour la déduplication et la recherche par l'assistant).

Avant d'écrire le recap journalier, on relit le fichier mémoire principal et on
ne rajoute que les infos pas déjà archivées les jours précédents (dédup).
"""
import base64
import json
import logging
import os
import time
import unicodedata
from datetime import date, datetime

import requests
from urllib.parse import quote

logger = logging.getLogger(__name__)

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OAUTH_URL = 'https://oauth2.googleapis.com/token'
_DRIVE = 'https://www.googleapis.com/drive/v3/files'
_UPLOAD = 'https://www.googleapis.com/upload/drive/v3/files'
_SCOPE = 'https://www.googleapis.com/auth/drive'
_FOLDER_MIME = 'application/vnd.google-apps.folder'


def _setting(cle, default=''):
    from .models import AppSetting
    row = AppSetting.query.filter_by(cle=cle).first()
    return (row.valeur.strip() if row and row.valeur else default)


def _normaliser(texte):
    sans = unicodedata.normalize('NFKD', texte or '').encode('ascii', 'ignore').decode('ascii')
    return ' '.join(sans.lower().replace("'", ' ').replace('\u2019', ' ').split())


def _slug(user):
    """Nom de dossier stable pour un collaborateur (prenom-nom, sans accents)."""
    base = _normaliser(f"{user.prenom or ''} {user.nom or ''}").replace(' ', '-')
    return ''.join(c for c in base if c.isalnum() or c == '-') or f'user-{user.id}'


def _b64url(data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


# ---------------------------------------------------------------------------
# Backends de stockage (interface commune : read / write / list_files)
# ---------------------------------------------------------------------------

class LocalBackend:
    kind = 'local'

    def __init__(self, racine=None):
        self.racine = racine or _setting('ARCHIVE_LOCAL_DIR') or os.path.join(_REPO, 'data', 'archives')

    def _path(self, path):
        return os.path.join(self.racine, *path.split('/'))

    def read(self, path):
        p = self._path(path)
        if not os.path.isfile(p):
            return None
        with open(p, 'r', encoding='utf-8') as f:
            return f.read()

    def write(self, path, content):
        p = self._path(path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(content)

    def list_files(self, prefix):
        p = self._path(prefix)
        if not os.path.isdir(p):
            return []
        return sorted(f'{prefix}/{n}' for n in os.listdir(p) if os.path.isfile(os.path.join(p, n)))


class DriveBackend:
    """Google Drive REST v3, authentifié par JWT RS256 (compte de service).
    Signé avec cryptography (déjà présent via msal) : aucune dépendance ajoutée."""
    kind = 'drive'

    def __init__(self, sa_json, folder_id):
        self.sa = json.loads(sa_json) if isinstance(sa_json, str) else sa_json
        self.root = folder_id.strip()
        self._token = None
        self._expiry = 0
        self._folders = {'': self.root}

    def _access_token(self):
        if self._token and time.time() < self._expiry - 60:
            return self._token
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        now = int(time.time())
        claim = {'iss': self.sa['client_email'], 'scope': _SCOPE, 'aud': _OAUTH_URL,
                 'iat': now, 'exp': now + 3600}
        signing_input = _b64url(json.dumps({'alg': 'RS256', 'typ': 'JWT'})) + '.' + \
            _b64url(json.dumps(claim))
        key = load_pem_private_key(self.sa['private_key'].encode('utf-8'), password=None)
        sig = key.sign(signing_input.encode('ascii'), padding.PKCS1v15(), hashes.SHA256())
        assertion = signing_input + '.' + _b64url(sig)
        r = requests.post(_OAUTH_URL, timeout=20, data={
            'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer', 'assertion': assertion})
        r.raise_for_status()
        j = r.json()
        self._token = j['access_token']
        self._expiry = now + int(j.get('expires_in', 3600))
        return self._token

    def _headers(self):
        return {'Authorization': f'Bearer {self._access_token()}'}

    def ping(self):
        r = requests.get(f'{_DRIVE}/{self.root}', headers=self._headers(),
                         params={'fields': 'id,name'}, timeout=20)
        r.raise_for_status()
        return r.json()

    def _find_folder(self, parts):
        """Id du dossier sous la racine, sans le créer. None si absent."""
        parent = self.root
        chemin = ''
        for nom in parts:
            chemin = f'{chemin}/{nom}' if chemin else nom
            if chemin in self._folders:
                parent = self._folders[chemin]
                continue
            q = (f"'{parent}' in parents and name = '{nom.replace(chr(39), chr(92) + chr(39))}' "
                 f"and mimeType = '{_FOLDER_MIME}' and trashed = false")
            r = requests.get(_DRIVE, headers=self._headers(),
                             params={'q': q, 'fields': 'files(id)', 'pageSize': 1}, timeout=20)
            r.raise_for_status()
            files = r.json().get('files', [])
            if not files:
                return None
            parent = files[0]['id']
            self._folders[chemin] = parent
        return parent

    def _ensure_folder(self, parts):
        parent = self.root
        chemin = ''
        for nom in parts:
            chemin = f'{chemin}/{nom}' if chemin else nom
            if chemin in self._folders:
                parent = self._folders[chemin]
                continue
            # recherche ciblée dans le parent courant
            q = (f"'{parent}' in parents and name = '{nom.replace(chr(39), chr(92) + chr(39))}' "
                 f"and mimeType = '{_FOLDER_MIME}' and trashed = false")
            r = requests.get(_DRIVE, headers=self._headers(),
                             params={'q': q, 'fields': 'files(id)', 'pageSize': 1}, timeout=20)
            r.raise_for_status()
            files = r.json().get('files', [])
            if files:
                fid = files[0]['id']
            else:
                r = requests.post(_DRIVE, headers={**self._headers(), 'Content-Type': 'application/json'},
                                  json={'name': nom, 'mimeType': _FOLDER_MIME, 'parents': [parent]},
                                  params={'fields': 'id'}, timeout=20)
                r.raise_for_status()
                fid = r.json()['id']
            self._folders[chemin] = fid
            parent = fid
        return parent

    def _find_file(self, folder_id, name):
        q = (f"'{folder_id}' in parents and name = '{name.replace(chr(39), chr(92) + chr(39))}' "
             f"and trashed = false")
        r = requests.get(_DRIVE, headers=self._headers(),
                         params={'q': q, 'fields': 'files(id)', 'pageSize': 1}, timeout=20)
        r.raise_for_status()
        files = r.json().get('files', [])
        return files[0]['id'] if files else None

    def read(self, path):
        parts = path.split('/')
        folder = self._find_folder(parts[:-1])
        if folder is None:
            return None
        fid = self._find_file(folder, parts[-1])
        if not fid:
            return None
        r = requests.get(f'{_DRIVE}/{fid}', headers=self._headers(),
                         params={'alt': 'media'}, timeout=30)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.text

    def write(self, path, content):
        parts = path.split('/')
        folder = self._ensure_folder(parts[:-1])
        name = parts[-1]
        fid = self._find_file(folder, name)
        if fid:
            r = requests.patch(f'{_UPLOAD}/{fid}', headers={**self._headers(),
                               'Content-Type': 'text/plain; charset=utf-8'},
                               params={'uploadType': 'media'}, data=content.encode('utf-8'), timeout=30)
            r.raise_for_status()
            return
        boundary = 'orbit_archive_boundary'
        metadata = json.dumps({'name': name, 'parents': [folder]})
        body = (f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'
                f'{metadata}\r\n--{boundary}\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n'
                f'{content}\r\n--{boundary}--').encode('utf-8')
        r = requests.post(_UPLOAD, headers={**self._headers(),
                          'Content-Type': f'multipart/related; boundary={boundary}'},
                          params={'uploadType': 'multipart', 'fields': 'id'}, data=body, timeout=30)
        r.raise_for_status()

    def list_files(self, prefix):
        folder = self._find_folder(prefix.split('/'))
        if folder is None:
            return []
        q = f"'{folder}' in parents and mimeType != '{_FOLDER_MIME}' and trashed = false"
        r = requests.get(_DRIVE, headers=self._headers(),
                         params={'q': q, 'fields': 'files(name)', 'pageSize': 1000}, timeout=20)
        r.raise_for_status()
        return sorted(f"{prefix}/{f['name']}" for f in r.json().get('files', []))

    def list_children(self, folder_id=None):
        """Entrées (dossiers + fichiers) d'un dossier, métadonnées utiles à l'affichage."""
        parent = folder_id or self.root
        q = f"'{parent}' in parents and trashed = false"
        r = requests.get(_DRIVE, headers=self._headers(),
                         params={'q': q, 'orderBy': 'folder,name', 'pageSize': 200,
                                 'fields': 'files(id,name,mimeType,size,modifiedTime,webViewLink)'},
                         timeout=25)
        r.raise_for_status()
        return r.json().get('files', [])


def choisir_backend():
    """Drive si configuré et joignable, sinon secours local. Retourne (backend, mode)."""
    sa = _setting('GOOGLE_DRIVE_SA_JSON')
    folder = _setting('GOOGLE_DRIVE_FOLDER_ID')
    if sa and folder:
        try:
            b = DriveBackend(sa, folder)
            b.ping()
            return b, 'drive'
        except Exception as exc:
            logger.warning('Drive indisponible (%s) : secours local personnel uniquement.', exc)
            return LocalBackend(), 'local_secours'
    return LocalBackend(), 'local_secours'


def tester_connexion_drive():
    sa = _setting('GOOGLE_DRIVE_SA_JSON')
    folder = _setting('GOOGLE_DRIVE_FOLDER_ID')
    if not sa or not folder:
        return {'ok': False, 'message': "Renseignez la clé JSON du compte de service et l'ID du dossier Drive."}
    try:
        info = DriveBackend(sa, folder).ping()
        return {'ok': True, 'message': f"Connecté au dossier Drive « {info.get('name', folder)} »."}
    except Exception as exc:
        return {'ok': False, 'message': f"Connexion Drive impossible : {exc}"}


# ---------------------------------------------------------------------------
# Rendus Markdown / JSON
# ---------------------------------------------------------------------------

def _memoire_md(entrees, titre):
    lignes = [f'# {titre}', f'Mise à jour : {datetime.utcnow().strftime("%d/%m/%Y %H:%M")} UTC', '']
    cabinet = [e for e in entrees if e['portee'] == 'cabinet']
    lignes.append('## Mémoire du cabinet (partagée avec toute l\'équipe)')
    lignes += [f"- {e['contenu']}  _({e.get('categorie') or 'fait'}, {e.get('date', '')[:10]})_"
               for e in cabinet] or ['- (vide)']
    par_user = {}
    for e in entrees:
        if e['portee'] == 'personnel':
            par_user.setdefault(e.get('user_nom') or e.get('user_slug') or 'inconnu', []).append(e)
    for nom, items in sorted(par_user.items()):
        lignes.append(f'\n## Mémoire personnelle — {nom}')
        lignes += [f"- {e['contenu']}  _({e.get('categorie') or 'fait'}, {e.get('date', '')[:10]})_"
                   for e in items]
    return '\n'.join(lignes) + '\n'


def _conversation_md(nom, jour, messages):
    lignes = [f'# Conversation ASTRO — {nom} — {jour.strftime("%d/%m/%Y")}', '']
    for m in messages:
        qui = 'Vous' if m['role'] == 'user' else 'ASTRO'
        lignes.append(f"**{m.get('heure', '')} — {qui} :** {m['contenu']}")
        lignes.append('')
    return '\n'.join(lignes) + '\n'


def _recap_md(jour, rapport):
    lignes = [f'# Recap journalier ASTRO — {jour.strftime("%d/%m/%Y")}',
              f"Stockage : {rapport['backend']} ({rapport['mode']})", '']
    lignes.append('## Nouvelles mémoires archivées')
    lignes += [f"- [{e['portee']}] {e['contenu']}" for e in rapport.get('nouvelles', [])] or ['- (aucune nouvelle)']
    lignes.append('\n## Conversations archivées')
    lignes += [f"- {c['nom']} : {c['nb']} message(s)" for c in rapport.get('conversations', [])] or ['- (aucune)']
    if rapport.get('alerte'):
        lignes.append(f"\n> ⚠ {rapport['alerte']}")
    return '\n'.join(lignes) + '\n'


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def _entree_memoire(m):
    from .models import User
    user = User.query.get(m.user_id) if m.user_id else None
    return {'contenu': m.contenu, 'portee': m.portee,
            'user_slug': _slug(user) if user else None,
            'user_nom': user.nom_complet() if user else None,
            'categorie': m.categorie or 'fait', 'source': m.source,
            'date': (m.date_creation or datetime.utcnow()).isoformat()}


def _cle_entree(e):
    return (e['portee'], e.get('user_slug') or 'cabinet', _normaliser(e['contenu']))


def _fusionner(existing, nouveaux):
    """Ajoute les entrées non déjà présentes (dédup insensible casse/accents)."""
    cles = {_cle_entree(e) for e in existing}
    ajoutes = []
    for e in nouveaux:
        k = _cle_entree(e)
        if k not in cles:
            existing.append(e)
            cles.add(k)
            ajoutes.append(e)
    return ajoutes


def _export_memoire(backend, jour, rapport):
    from .models import AssistantMemoire
    toutes = AssistantMemoire.query.order_by(AssistantMemoire.date_creation).all()
    if backend.kind == 'drive':
        chemin = 'memoire/memoire_principale'
        brut = backend.read(chemin + '.json')
        existing = (json.loads(brut).get('entrees', []) if brut else [])
        nouveaux = [_entree_memoire(m) for m in toutes]
        ajoutes = _fusionner(existing, nouveaux)
        backend.write(chemin + '.json', json.dumps({'maj': datetime.utcnow().isoformat(),
                                                   'entrees': existing}, ensure_ascii=False, indent=2))
        backend.write(chemin + '.md', _memoire_md(existing, 'Mémoire principale d\'ASTRO — Cabinet JMH'))
        rapport['fichiers'] += [chemin + '.json', chemin + '.md']
        rapport['nouvelles'] = ajoutes
        rapport['nb_memoires'] = len(existing)
    else:
        # Secours local : mémoires personnelles uniquement, par membre.
        par_user = {}
        for m in toutes:
            if m.portee == 'personnel' and m.user_id:
                par_user.setdefault(m.user_id, []).append(m)
        from .models import User
        ajoutes = []
        for uid, mems in par_user.items():
            user = User.query.get(uid)
            slug = _slug(user)
            chemin = f'personnel/{slug}/memoire'
            brut = backend.read(chemin + '.json')
            existing = (json.loads(brut).get('entrees', []) if brut else [])
            ajoutes += _fusionner(existing, [_entree_memoire(m) for m in mems])
            backend.write(chemin + '.json', json.dumps({'maj': datetime.utcnow().isoformat(),
                                                       'entrees': existing}, ensure_ascii=False, indent=2))
            backend.write(chemin + '.md', _memoire_md(existing, f'Mémoire personnelle — {user.nom_complet()}'))
            rapport['fichiers'] += [chemin + '.json', chemin + '.md']
        rapport['nouvelles'] = ajoutes
        rapport['nb_memoires'] = len(ajoutes)


def _export_conversations(backend, jour, rapport):
    from . import db
    from .models import AssistantMessage, User
    messages = (AssistantMessage.query.filter_by(exporte=False)
                .order_by(AssistantMessage.date_creation).all())
    par_user = {}
    for m in messages:
        par_user.setdefault(m.user_id, []).append(m)
    compteur = []
    for uid, mems in par_user.items():
        user = User.query.get(uid)
        slug = _slug(user)
        nom = user.nom_complet()
        par_jour = {}
        for m in mems:
            j = (m.date_creation or datetime.utcnow()).date()
            par_jour.setdefault(j, []).append(
                {'id': m.id, 'role': m.role, 'contenu': m.contenu,
                 'heure': (m.date_creation or datetime.utcnow()).strftime('%H:%M')})
        for j, msgs in par_jour.items():
            base = (f'conversations/{slug}/{j.isoformat()}' if backend.kind == 'drive'
                    else f'personnel/{slug}/conversations/{j.isoformat()}')
            brut = backend.read(base + '.json')
            existants = (json.loads(brut).get('messages', []) if brut else [])
            ids = {x['id'] for x in existants}
            existants += [x for x in msgs if x['id'] not in ids]
            existants.sort(key=lambda x: x['id'])
            backend.write(base + '.json', json.dumps({'date': j.isoformat(), 'collaborateur': nom,
                                                     'messages': existants}, ensure_ascii=False, indent=2))
            backend.write(base + '.md', _conversation_md(nom, j, existants))
            rapport['fichiers'] += [base + '.json', base + '.md']
        compteur.append({'nom': nom, 'nb': len(mems)})
        for m in mems:
            m.exporte = True
    db.session.commit()
    rapport['conversations'] = compteur
    rapport['nb_messages'] = len(messages)


def _purger(jour):
    """Supprime le tampon déjà exporté ET antérieur au jour d'export : les
    conversations du jour restent en base jusqu'au lendemain (recherche rapide)."""
    from . import db
    from .models import AssistantMessage
    debut = datetime(jour.year, jour.month, jour.day)
    suppr = AssistantMessage.query.filter(AssistantMessage.exporte == True,  # noqa: E712
                                          AssistantMessage.date_creation < debut).delete()
    db.session.commit()
    return suppr


def _save_statut(rapport):
    from . import db
    from .models import AppSetting
    row = AppSetting.query.filter_by(cle='ARCHIVE_DERNIER_EXPORT').first()
    if row is None:
        row = AppSetting(cle='ARCHIVE_DERNIER_EXPORT', service='google_drive', type_valeur='json')
        db.session.add(row)
    row.valeur = json.dumps(rapport, ensure_ascii=False)
    db.session.commit()


def _exporter(backend, jour, rapport):
    _export_memoire(backend, jour, rapport)
    _export_conversations(backend, jour, rapport)
    # recap journalier (Drive uniquement ; en local il est par membre via les fichiers)
    if backend.kind == 'drive':
        base = f'memoire/recap/{jour.isoformat()}'
        backend.write(base + '.json', json.dumps(rapport, ensure_ascii=False, indent=2))
        backend.write(base + '.md', _recap_md(jour, rapport))
        rapport['fichiers'] += [base + '.json', base + '.md']
    rapport['purges'] = _purger(jour)
    rapport['ok'] = True


def _rapport_vide(jour):
    return {'date': jour.isoformat(), 'fichiers': [], 'nouvelles': [],
            'conversations': [], 'nb_messages': 0, 'nb_memoires': 0}


def exporter_archives(jour=None):
    """Export complet (mémoire dédupliquée + conversations par collab) puis purge.
    Retourne un rapport ; ne lève jamais d'exception bloquante pour le scheduler.
    Si Drive est choisi mais que l'écriture échoue (compte de service sans quota
    sur un Drive personnel), repli automatique sur le secours local."""
    from . import db
    jour = jour or date.today()
    rapport = _rapport_vide(jour)
    backend, mode = choisir_backend()
    rapport['backend'] = backend.kind
    rapport['mode'] = mode
    if mode == 'local_secours' and _setting('GOOGLE_DRIVE_SA_JSON'):
        rapport['alerte'] = "Drive indisponible : export local de secours (mémoires personnelles + conversations uniquement)."
    try:
        _exporter(backend, jour, rapport)
    except Exception as exc:
        if backend.kind != 'drive':
            logger.exception('Export archives ASTRO en échec')
            rapport['ok'] = False
            rapport['erreur'] = str(exc)
        else:
            logger.warning('Écriture Drive impossible (%s) : repli local personnel.', exc)
            db.session.rollback()
            rapport = _rapport_vide(jour)
            backend = LocalBackend()
            rapport['backend'] = backend.kind
            rapport['mode'] = 'local_secours'
            rapport['alerte'] = ("Écriture Drive impossible : export local de secours "
                                 f"(personnel + conversations). Détail : {str(exc)[:160]}")
            try:
                _exporter(backend, jour, rapport)
            except Exception as exc2:
                logger.exception('Export archives ASTRO en échec (secours local aussi)')
                rapport['ok'] = False
                rapport['erreur'] = str(exc2)
    _save_statut(rapport)
    return rapport


# ---------------------------------------------------------------------------
# Recherche dans l'historique (tampon base + archives)
# ---------------------------------------------------------------------------

def rechercher_historique(user, requete, limite=12):
    """Cherche une info dite dans une conversation précédente : tampon base d'abord
    (rapide), puis archives du collaborateur (Drive/local). Retourne des extraits."""
    from .models import AssistantMessage
    q = _normaliser(requete)
    if not q:
        return []
    extraits = []
    recentes = (AssistantMessage.query.filter_by(user_id=user.id)
                .order_by(AssistantMessage.date_creation.desc()).limit(400).all())
    for m in recentes:
        if q in _normaliser(m.contenu):
            extraits.append({'date': (m.date_creation or datetime.utcnow()).strftime('%d/%m/%Y %H:%M'),
                             'role': m.role, 'texte': m.contenu[:300], 'source': 'Orbit'})
            if len(extraits) >= limite:
                return extraits
    try:
        backend, _ = choisir_backend()
        slug = _slug(user)
        prefix = ('conversations/' + slug) if backend.kind == 'drive' else f'personnel/{slug}/conversations'
        fichiers = backend.list_files(prefix)
        for chemin in reversed(fichiers[-20:]):
            if not chemin.endswith('.json'):
                continue
            brut = backend.read(chemin)
            if not brut:
                continue
            for msg in json.loads(brut).get('messages', []):
                if q in _normaliser(msg.get('contenu', '')):
                    extraits.append({'date': json.loads(brut).get('date', ''),
                                     'role': msg.get('role'), 'texte': msg['contenu'][:300],
                                     'source': 'archive'})
                    if len(extraits) >= limite:
                        return extraits
    except Exception as exc:
        logger.warning('Recherche archives indisponible : %s', exc)
    return extraits


# ---------------------------------------------------------------------------
# Rayon « Modèles » — plaquettes et modèles de documents (lecture seule)
# ---------------------------------------------------------------------------

MODELES_FOLDER_DEFAUT = '1bGe9XEIce2OL-cRALon5gZS9MnXszXPf'
_CACHE_MODELES = {'t': 0.0, 'data': None}


def _dossier_modeles():
    return _setting('GOOGLE_DRIVE_MODELES_FOLDER_ID') or MODELES_FOLDER_DEFAUT


def _dossier_modeles_local():
    return os.path.join(_setting('ARCHIVE_LOCAL_DIR') or os.path.join(_REPO, 'data', 'archives'), 'modeles')


def _icone_modele(mime):
    if mime == _FOLDER_MIME:
        return 'bi-folder2'
    if mime == 'application/pdf':
        return 'bi-file-earmark-pdf'
    if mime == 'application/vnd.google-apps.document':
        return 'bi-file-earmark-word'
    if mime == 'application/vnd.google-apps.spreadsheet':
        return 'bi-file-earmark-excel'
    if mime == 'application/vnd.google-apps.presentation':
        return 'bi-file-earmark-slides'
    if (mime or '').startswith('image/'):
        return 'bi-file-earmark-image'
    return 'bi-file-earmark-text'


def _type_modele(mime):
    return {
        _FOLDER_MIME: 'Dossier',
        'application/pdf': 'PDF',
        'application/vnd.google-apps.document': 'Google Docs',
        'application/vnd.google-apps.spreadsheet': 'Google Sheets',
        'application/vnd.google-apps.presentation': 'Google Slides',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'Word',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'Excel',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'PowerPoint',
    }.get(mime) or ('Image' if (mime or '').startswith('image/') else 'Fichier')


def _modele(e, rayon='', lien=None):
    taille = e.get('size')
    try:
        taille = int(taille) if taille is not None else None
    except (TypeError, ValueError):
        taille = None
    mime = e.get('mimeType') or ''
    return {
        'id': e.get('id') or '',
        'nom': e.get('name') or '',
        'mime': mime,
        'type': _type_modele(mime),
        'icone': _icone_modele(mime),
        'taille': taille,
        'modifie': (e.get('modifiedTime') or '')[:10],
        'rayon': rayon,
        'lien': lien if lien is not None else (e.get('webViewLink') or
                (f"https://drive.google.com/open?id={e['id']}" if e.get('id') else '')),
    }


def _modeles_locaux():
    """Repli : fichiers déposés dans <ARCHIVE_LOCAL_DIR>/modeles (sans Drive)."""
    racine = _dossier_modeles_local()
    if not os.path.isdir(racine):
        return []
    fichiers = []
    for nom in sorted(os.listdir(racine)):
        p = os.path.join(racine, nom)
        if not os.path.isfile(p):
            continue
        fichiers.append({
            'id': '', 'nom': nom, 'mime': '', 'type': 'Fichier', 'icone': 'bi-file-earmark-text',
            'taille': os.path.getsize(p), 'rayon': '',
            'modifie': datetime.fromtimestamp(os.path.getmtime(p)).strftime('%Y-%m-%d'),
            'lien': f"/assistant/modeles/fichier/{quote(nom)}",
        })
    return fichiers


def lister_modeles(force=False):
    """Contenu du rayon Modèles (Drive en lecture seule, repli local).

    Le compte de service n'a pas de quota de stockage : il ne peut pas ÉCRIRE
    dans un Drive personnel, mais la LECTURE d'un dossier partagé avec lui
    fonctionne. Résultat mis en cache 5 minutes (une page = 1 à 2 appels API)."""
    if not force and _CACHE_MODELES['data'] is not None and time.time() - _CACHE_MODELES['t'] < 300:
        return _CACHE_MODELES['data']

    dossier = _dossier_modeles()
    resultat = {'ok': False, 'source': 'indisponible', 'dossier_id': dossier,
                'dossier_url': f'https://drive.google.com/drive/folders/{dossier}',
                'rayons': [], 'fichiers': [], 'message': ''}
    sa = _setting('GOOGLE_DRIVE_SA_JSON')

    if sa:
        try:
            backend = DriveBackend(sa, dossier)
            # Sans ping, une liste sur un dossier non partagé renvoie [] (silencieux) :
            # on distingue « vide » de « pas d'accès ».
            backend.ping()
            rayons, fichiers = [], []
            for entree in backend.list_children():
                if entree.get('mimeType') == _FOLDER_MIME:
                    try:
                        enfants = backend.list_children(entree['id'])
                    except Exception as exc:
                        logger.warning('Modèles : sous-dossier illisible (%s) : %s', entree.get('name'), exc)
                        enfants = []
                    rayons.append({'id': entree['id'], 'nom': entree['name'], 'nb': len(enfants)})
                    fichiers.extend(_modele(f, entree['name']) for f in enfants)
                else:
                    fichiers.append(_modele(entree))
            resultat.update(ok=True, source='drive', rayons=rayons, fichiers=fichiers)
            if not fichiers:
                resultat['message'] = 'Le dossier Modèles ne contient encore aucun fichier.'
        except Exception as exc:
            logger.warning('Rayon Modèles Drive indisponible : %s', exc)
            locaux = _modeles_locaux()
            if locaux:
                resultat.update(ok=True, source='local', fichiers=locaux,
                                message='Drive indisponible : modèles locaux affichés.')
            else:
                resultat['message'] = ("Drive indisponible ou dossier non partagé avec le compte de service. "
                                       "Le dossier reste consultable directement sur Google Drive.")
    else:
        locaux = _modeles_locaux()
        if locaux:
            resultat.update(ok=True, source='local', fichiers=locaux,
                            message='Modèles servis depuis le dossier local du serveur.')
        else:
            resultat['message'] = ("Compte de service Drive non configuré : le dossier reste "
                                   "consultable directement sur Google Drive.")

    _CACHE_MODELES.update(t=time.time(), data=resultat)
    return resultat