# -*- coding: utf-8 -*-
"""Synchronisation des declarations de TVA depuis l'espace web Pennylane (interface comptable).

Utilise l'endpoint interne du front-end (vat_forms) appele par la page
/companies/<id>/accountants/declarations/vat_returns avec les cookies de session
de l'utilisateur connecte (capturés via DevTools -> Copier comme cURL).

Réponse vat_forms : {"vat_returns": [...], "future_vat_returns": [...]}
  - vat_returns        : déclarations créées dans Pennylane (status: filed, sent, paid...)
  - future_vat_returns : périodes pas encore déclarées dans PL (status 'to_do', deadline, payable)

Règle : sur les dossiers reliés, la SYNCHRO fait foi sur les périodes qui existent dans
Pennylane (vat_returns + future_vat_returns) — elle réécrit/neutralise les cases
manuelles (ChecklistEntry.pl_mode) : declare/paye imposés pour les périodes faites
dans PL, forçages manuels annulés pour les périodes connues de PL. Les mois hors
périmètre PL restent 100 % manuels.

Persistance : les cookies sont stockés en BDD (AppSetting.PENNYLANE_WEB_COOKIES)
pour survivre aux redéploiements Render, + cache mémoire du process.
"""

import re
import threading
from datetime import datetime, date

import requests

from app.integrations.pl_cookies import nettoyer_cookies

# Cache mémoire des cookies (lazy-load depuis AppSetting au premier accès)
_pl_session_lock = threading.Lock()
_pl_session_cookies = ''
_pl_session_loaded = False

COOKIE_KEY = 'PENNYLANE_WEB_COOKIES'

# Statuts Pennylane considérés comme "déclarée / terminée"
# NB : 'ongoing' = envoyée mais pas encore acceptée -> la déclaration EST partie.
FILED_STATUSES = {'filed', 'sent', 'paid', 'partially_paid', 'completed', 'done',
                  'validated', 'accepted', 'transmitted', 'accounted', 'teletedeclaree',
                  'ongoing'}
# Statuts "en retard" selon Pennylane
LATE_STATUSES = {'late', 'late_to_do', 'overdue', 'en_retard', 'retard'}
# Statut brut -> libellé FR
STATUT_FR = {
    'to_do': 'À déclarer',
    'ready': 'Prêt',
    'ongoing': 'En cours',
    'in_progress': 'En cours',
    'draft': 'Prêt',
    'to_send': 'Prêt',
    'filed': 'Télédéclarée',
    'sent': 'Télédéclarée',
    'completed': 'Terminée',
    'done': 'Terminée',
    'validated': 'Validée',
    'accepted': 'Acceptée',
    'transmitted': 'Transmise',
    'accounted': 'Comptabilisée',
    'paid': 'Payée',
    'partially_paid': 'Partiellement payée',
    'late': 'En retard',
    'late_to_do': 'En retard',
    'overdue': 'En retard',
    'rejected': 'Rejetée',
    'cancelled': 'Annulée',
}


def _load_from_db():
    """Charge les cookies depuis AppSetting (une fois par process)."""
    global _pl_session_cookies, _pl_session_loaded
    if _pl_session_loaded:
        return
    try:
        from app.models import AppSetting
        s = AppSetting.query.filter_by(cle=COOKIE_KEY).first()
        if s and (s.valeur or '').strip():
            _pl_session_cookies = s.valeur.strip()
    except Exception:
        pass
    _pl_session_loaded = True


def set_web_session(cookies: str, firm_id: int = None) -> dict:
    """Nettoie et enregistre les cookies de session Pennylane, puis persiste en BDD.

    Accepte tout ce que l'utilisateur a sous la main : commande cURL complète
    (« Copier comme cURL »), option ``-b '...'``, ligne d'en-tête ``Cookie:``,
    liste brute ``nom=valeur; nom=valeur`` ou JSON. Le nettoyage est fait par
    ``pl_cookies.nettoyer_cookies`` ; le détail (nombre de cookies, cookies
    critiques manquants) est renvoyé pour que l'interface puisse en rendre
    compte au lieu d'un simple « OK ».

    Renvoie le dict de ``nettoyer_cookies`` (dont 'ok', 'header', 'message').
    """
    info = nettoyer_cookies(cookies or '')
    if not info.get('ok') or not info.get('header'):
        return info
    _store_cookies(info['header'])
    return info


def _store_cookies(header: str):
    """Met à jour le cache mémoire + persiste en BDD (survit aux redéploiements)."""
    global _pl_session_cookies, _pl_session_loaded
    with _pl_session_lock:
        _pl_session_cookies = header
        _pl_session_loaded = True
    try:
        from app.models import AppSetting
        from app import db
        s = AppSetting.query.filter_by(cle=COOKIE_KEY).first()
        if not s:
            s = AppSetting(cle=COOKIE_KEY, valeur=header, type_valeur='password',
                           service='pennylane', masque=True)
            db.session.add(s)
        else:
            s.valeur = header
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


def _merge_cookie_headers(base: str, updates: dict) -> str:
    """Fusionne des cookies (Set-Cookie de la réponse) dans le header existant."""
    current = _parse_cookie_header(base)
    for k, v in (updates or {}).items():
        if v:
            current[k] = v
    return '; '.join(f'{k}={v}' for k, v in current.items())


_cookie_last_persist = [0.0]  # throttle persist BDD : max 1x / 10 min


def _refresh_session_cookies(r):
    """Pennylane renvoie régulièrement des cookies de session frais (Set-Cookie).
    On les réinjecte automatiquement pour garder la session vivante sans intervention."""
    global _pl_session_cookies, _pl_session_loaded
    import time as _time
    try:
        updates = {}
        for c in getattr(r, 'cookies', None) or []:
            if getattr(c, 'value', None):
                updates[c.name] = c.value
        if not updates:
            return
        with _pl_session_lock:
            current = _pl_session_cookies
        merged = _merge_cookie_headers(current, updates)
        if merged == current:
            return
        with _pl_session_lock:
            _pl_session_cookies = merged
            _pl_session_loaded = True
        now = _time.time()
        if now - _cookie_last_persist[0] >= 600:
            _cookie_last_persist[0] = now
            _store_cookies(merged)
    except Exception:
        pass


def has_web_session() -> bool:
    _load_from_db()
    return bool(_pl_session_cookies)


def clear_web_session():
    global _pl_session_cookies
    with _pl_session_lock:
        _pl_session_cookies = ''
    try:
        from app.models import AppSetting
        from app import db
        s = AppSetting.query.filter_by(cle=COOKIE_KEY).first()
        if s:
            db.session.delete(s)
            db.session.commit()
    except Exception:
        pass


def _headers(cookies: str = None):
    """En-têtes d'un appel XHR légitime depuis app.pennylane.com.

    Le 418 renvoyé par Pennylane est une protection anti-bot : plus l'appel
    ressemble à une requête du front (Accept-Language, Origin, sec-fetch-*,
    jeton CSRF), moins elle se déclenche. Ces en-têtes ne changent rien à
    l'authentification (elle se fait par cookies).

    Le jeton CSRF est le *reflet* du cookie ``my_csrf_token`` : le front envoie
    exactement la même valeur dans les deux. On le dérive donc du header cookie
    courant plutôt que de demander à l'utilisateur de le copier.
    """
    h = {
        'accept': 'application/json, text/plain, */*',
        # Indispensable : sans cet en-tête, Rails/Pennylane ne traite pas la
        # requête comme un XHR et renvoie la coquille HTML de la SPA
        # (HTTP 200, text/html, ~14 Ko, <title>Pennylane</title>) au lieu du
        # JSON attendu. C'était la cause du « Réponse non JSON » en prod.
        'x-requested-with': 'XMLHttpRequest',
        'accept-language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
        'user-agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36 Edg/152.0.0.0'),
        'x-reseller': 'pennylane',
        'x-plan-used-by-front-end': 'v1_saas_free',
        'origin': 'https://app.pennylane.com',
        'referer': 'https://app.pennylane.com/',
        'sec-fetch-site': 'same-origin',
        'sec-fetch-mode': 'cors',
        'sec-fetch-dest': 'empty',
    }
    try:
        jeton = (_parse_cookie_header(cookies if cookies is not None
                                      else _pl_session_cookies).get('my_csrf_token') or '').strip()
        if jeton:
            h['x-csrf-token'] = jeton
    except Exception:
        pass
    return h


def _parse_cookie_header(header: str) -> dict:
    out = {}
    for part in (header or '').split(';'):
        part = part.strip()
        if '=' in part:
            k, _, v = part.partition('=')
            out[k.strip()] = v.strip()
    return out


def fetch_vat_forms(customer_id, period_start: str = None, period_end: str = None) -> dict:
    """Récupère les déclarations TVA d'une company Pennylane via l'endpoint interne.

    Retourne {'ok': bool, 'vat_returns': [...], 'future_vat_returns': [...], 'message': str}
    """
    _load_from_db()
    if not _pl_session_cookies:
        return {'ok': False, 'message': 'Session web Pennylane non configurée.',
                'vat_returns': [], 'future_vat_returns': []}
    if not customer_id:
        return {'ok': False, 'message': 'Pas de pennylane_customer_id.',
                'vat_returns': [], 'future_vat_returns': []}

    today = date.today()
    if not period_start:
        # Fenêtre [1er déc N-1 -> déc N] : couvre la CA3 de décembre N-1 (déposée en
        # janvier N) même quand les périodes de N existent déjà dans vat_returns.
        period_start = f'{today.year - 1}-12-01'
    if not period_end:
        period_end = f'{today.year}-12-31'

    url = (f'https://app.pennylane.com/companies/{customer_id}'
           f'/accountants/declarations/vat_forms'
           f'?period_start={period_start}&period_end={period_end}')
    with _pl_session_lock:
        cookies = _pl_session_cookies

    # --- Appel avec ré-essais -------------------------------------------------
    # 418 (anti-bot) et 429 (débit) sont TRANSITOIRES côté Pennylane : sans
    # nouvelle tentative, un seul 418 faisait échouer le dossier et l'interface
    # ne bougeait pas. 5xx idem.
    import random as _random
    import time as _time

    tentatives = 3
    r = None
    derniere_erreur = None
    for essai in range(tentatives):
        try:
            r = requests.get(url, headers=_headers(cookies), cookies=_parse_cookie_header(cookies),
                             timeout=25)
        except Exception as e:
            r = None
            derniere_erreur = f'Erreur réseau: {e}'
        if r is not None and r.status_code not in (418, 429) and r.status_code < 500:
            break
        if essai < tentatives - 1:
            attente = (2 ** essai) * 1.5 + _random.uniform(0, 0.9)
            _time.sleep(attente)
    if r is None:
        return {'ok': False, 'message': derniere_erreur or 'Erreur réseau',
                'vat_returns': [], 'future_vat_returns': []}

    if r.status_code in (418, 429):
        _msg = (f'Pennylane limite temporairement les appels (HTTP {r.status_code}) après '
                f'{tentatives} tentative(s). La session est probablement encore valide : '
                f'réessaie dans 2 à 3 minutes. Si le blocage revient systématiquement, '
                f'recolle les cookies Pennylane (page Intégration).')
        _save_last_sync(ok=False, message=_msg)
        return {'ok': False, 'bloque': True, 'message': _msg,
                'vat_returns': [], 'future_vat_returns': []}

    if r.status_code == 401:
        _msg = 'Session expirée — recolle les cookies Pennylane (page Intégration).'
        _save_last_sync(ok=False, message=_msg)
        _alerter_session(_msg)
        return {'ok': False, 'message': _msg,
                'vat_returns': [], 'future_vat_returns': []}
    if r.status_code != 200:
        _msg = f'HTTP {r.status_code} sur vat_forms (company {customer_id}).'
        if r.status_code in (401, 403):
            _save_last_sync(ok=False, message='Session Pennylane invalide (HTTP %d).' % r.status_code)
            _alerter_session('Session Pennylane invalide (HTTP %d).' % r.status_code)
        return {'ok': False, 'message': _msg,
                'vat_returns': [], 'future_vat_returns': []}
    try:
        data = r.json()
    except Exception:
        # Un HTTP 200 qui n'est PAS du JSON est presque toujours une page HTML :
        # redirection vers /login (cookies non reconnus) ou challenge anti-bot.
        # « Réponse non JSON » n'aidait personne : on dit la cause probable et
        # l'action à faire, et on marque `bloque` pour que le disjoncteur de la
        # synchro s'arrête au lieu d'interroger les 53 dossiers pour rien.
        ct = (r.headers.get('Content-Type') or 'inconnu').split(';')[0].strip()
        url_finale = getattr(r, 'url', '') or url
        # Extrait TEXTUEL uniquement (balises et attributs retirés) : permet de
        # distinguer un challenge Cloudflare, une page de maintenance ou une
        # erreur applicative, sans jamais exposer de jeton ni de cookie.
        try:
            corps = re.sub(r'<[^>]+>', ' ', (r.text or '')[:1500])
            extrait = re.sub(r'\s+', ' ', corps).strip()[:180]
        except Exception:
            extrait = ''
        bas = url_finale.lower()
        redirection = any(k in bas for k in ('/login', 'sign_in', 'sign-in', '/auth', '/session'))
        if redirection:
            msg = ("Session Pennylane NON RECONNUE : Pennylane a renvoyé sa page de "
                   "connexion au lieu des données. Recolle les cookies depuis un onglet "
                   "app.pennylane.com réellement connecté (F12 → Network → filtre "
                   "'pennylane' → Headers → ligne cookie → Copier la valeur).")
        elif 'html' in ct.lower():
            msg = (f"Pennylane a renvoyé une page HTML au lieu de JSON (HTTP {r.status_code}, "
                   f"{ct}) : protection anti-bot ou cookies qui ne correspondent pas à ce "
                   "compte. Attends 2-3 min puis recolle des cookies frais depuis "
                   "app.pennylane.com.")
        else:
            try:
                extrait = re.sub(r'\s+', ' ', (r.text or '')[:100]).strip()
            except Exception:
                extrait = ''
            msg = (f"Réponse illisible (HTTP {r.status_code}, {ct})"
                   + (f" : {extrait[:70]!r}" if extrait else ''))
        return {'ok': False, 'bloque': True, 'message': msg,
                'diagnostic': {'http': r.status_code, 'content_type': ct,
                               'url_finale': url_finale, 'redirection_login': redirection,
                               'extrait': extrait,
                               'taille_octets': len((r.text or '').encode('utf-8', 'replace'))},
                'vat_returns': [], 'future_vat_returns': []}
    vat = data.get('vat_returns') or []
    future = data.get('future_vat_returns') or []
    # Repli : Pennylane renvoie parfois vide pour une plage trop large — on retente
    # sur [déc N-1 → déc N] qui couvre aussi la CA3 de décembre déposée en janvier.
    if not vat and not future and period_start == f'{today.year}-01-01':
        return fetch_vat_forms(customer_id, period_start=f'{today.year - 1}-12-01',
                               period_end=period_end)
    # Auto-refresh de la session : réutiliser les cookies frais renvoyés par PL
    _refresh_session_cookies(r)
    return {'ok': True, 'vat_returns': vat, 'future_vat_returns': future}


def traduire_statut(statut: str) -> str:
    """Statut Pennylane brut -> libellé FR pour l'affichage."""
    return STATUT_FR.get((statut or '').lower(), statut or '')


# Couleurs des pastilles Pennylane (demande Aziz — sémantique Pennylane réelle) :
# vert = ACCEPTÉE (envoyée ET acceptée par le service d'impôt) ;
# orange = EN COURS (envoyée mais pas encore acceptée) ;
# bleu = PRÊT (préparée mais pas encore envoyée) ;
# gris = À DÉCLARER (ni préparée ni envoyée, échéance à venir) ;
# rouge = EN RETARD (échéance dépassée, ni préparée ni envoyée ni acceptée).
PILL_OK = {'accepted', 'validated', 'filed', 'sent', 'completed', 'done', 'transmitted',
           'accounted', 'paid', 'partially_paid'}
PILL_READY = {'ready', 'draft', 'to_send', 'prepared'}          # bleu
PILL_PROGRESS = {'ongoing', 'in_progress', 'pending', 'processing'}  # orange
PILL_TODO = {'to_do', 'unknown', ''}                            # gris


def pill_class(statut: str, affiche: str = '') -> str:
    """Classe CSS de la pastille Pennylane pour la grille checklist.

    Retourne '' (bleu par défaut) si le statut n'est pas mappé.
    Ordre de priorité : retard > acceptée > prêt > en cours > à déclarer.
    """
    s = (statut or '').lower()
    aff = (affiche or traduire_statut(s) or '').strip().lower()
    # En retard : statut brut OU 'to_do' avec échéance dépassée (statut_affiche)
    if s in LATE_STATUSES or aff == 'en retard':
        return ' sym-pl-late'
    if s in PILL_OK or aff in ('acceptée', 'acceptee', 'validée', 'validee', 'télédéclarée',
                               'telegedeclaree', 'terminée', 'terminee', 'payée', 'payee',
                               'comptabilisée', 'comptabilisee', 'transmise'):
        return ' sym-pl-ok'
    if s in PILL_READY or aff in ('prêt', 'pret', 'brouillon', 'à envoyer', 'a envoyer'):
        return ' sym-pl-ready'
    if s in PILL_PROGRESS or aff == 'en cours':
        return ' sym-pl-progress'
    if s in PILL_TODO or aff in ('à déclarer', 'a declarer'):
        return ' sym-pl-todo'
    return ''


def pill_icon(statut: str, affiche: str = '') -> str:
    """Icône Bootstrap affichée DANS la case colorée de la grille checklist.

    Case entière colorée (demande Aziz) : vert = acceptée (✓), orange = en cours
    (⏳), bleu = prêt (🛠), gris = à déclarer (…), rouge = en retard (✗).
    Chaîne vide = statut non mappé (affichage neutre).
    """
    cls = pill_class(statut, affiche).strip()
    if cls == 'sym-pl-ok':
        return '<i class="bi bi-check-lg"></i>'
    if cls == 'sym-pl-progress':
        return '<i class="bi bi-hourglass-split"></i>'
    if cls == 'sym-pl-ready':
        return '<i class="bi bi-tools"></i>'
    if cls == 'sym-pl-todo':
        return '<i class="bi bi-three-dots"></i>'
    if cls == 'sym-pl-late':
        return '<i class="bi bi-x-lg"></i>'
    return ''


def _extract_period(vr: dict):
    """Extrait (annee, mois) d'un objet vat_return.

    L'API vat_forms renvoie period_start/period_end ('2026-01-01'), pas 'period'.
    Repli historique : period ('2026-01') ou label ('TVA janvier 2026').
    """
    for key in ('period_start', 'period', 'period_end'):
        raw = vr.get(key)
        if raw:
            m = re.match(r'(\d{4})-(\d{2})', str(raw))
            if m:
                return int(m.group(1)), int(m.group(2))
    # Repli : label du type 'TVA janvier 2026' / 'TVA 1er trimestre 2026'
    label = str(vr.get('label') or '')
    mois_fr = {'janvier': 1, 'fevrier': 2, 'février': 2, 'mars': 3, 'avril': 4,
               'mai': 5, 'juin': 6, 'juillet': 7, 'aout': 8, 'août': 8,
               'septembre': 9, 'octobre': 10, 'novembre': 11, 'decembre': 12, 'décembre': 12}
    low = label.lower()
    m_annee = re.search(r'(\d{4})', low)
    annee = int(m_annee.group(1)) if m_annee else None
    for nom, num in mois_fr.items():
        if nom in low and annee:
            return annee, num
    return None


def _vat_taxe_for(dossier) -> str:
    """taxe ChecklistEntry selon le régime TVA du dossier."""
    regime = (dossier.regime_tva or '').lower().strip()
    if regime in ('trimestriel', 'trimestrielle'):
        return 'tva_trimestriel'
    return 'tva_mensuel'


LAST_SYNC_KEY = 'PENNYLANE_WEB_LAST_SYNC'


def _save_last_sync(ok: bool, message: str):
    """Trace du dernier passage de la synchro (auto ou manuel) — affichée sur la carte admin.
    Upsert SQL brut + relecture immédiate : toute anomalie est logguée (visible Render)."""
    try:
        import json as _json
        from sqlalchemy import text as _text
        from app import db
        payload = _json.dumps({
            'quand': datetime.utcnow().strftime('%d/%m/%Y %H:%M'),
            'ok': bool(ok),
            'message': (message or '')[:1000],
        }, ensure_ascii=False)
        with db.engine.begin() as conn:
            conn.execute(_text(
                "UPDATE app_settings SET valeur = :v, type_valeur = 'json', service = 'pennylane', "
                "date_modification = NOW() WHERE cle = :k"), {'v': payload, 'k': LAST_SYNC_KEY})
            conn.execute(_text(
                "INSERT INTO app_settings (cle, valeur, type_valeur, service, masque) "
                "SELECT :k, :v, 'json', 'pennylane', FALSE "
                "WHERE NOT EXISTS (SELECT 1 FROM app_settings WHERE cle = :k)"),
                {'v': payload, 'k': LAST_SYNC_KEY})
        # Vérification immédiate (doit TOUJOURS trouver la ligne)
        with db.engine.connect() as conn:
            row = conn.execute(_text("SELECT valeur FROM app_settings WHERE cle = :k"),
                               {'k': LAST_SYNC_KEY}).fetchone()
        if not row or not row[0]:
            try:
                from flask import current_app
                current_app.logger.error("PENNYLANE LAST_SYNC: trace NON persistée (upsert sans effet) !")
            except Exception:
                pass
    except Exception as e:
        try:
            from flask import current_app
            current_app.logger.error(f"PENNYLANE LAST_SYNC error: {e}")
        except Exception:
            pass


def get_last_sync() -> dict:
    """Dernier passage de synchro (auto ou manuel) — lisible par tous les rôles."""
    try:
        import json as _json
        from app.models import AppSetting
        s = AppSetting.query.filter_by(cle=LAST_SYNC_KEY).first()
        if s and s.valeur:
            return _json.loads(s.valeur)
    except Exception:
        pass
    return {}


_last_alert = {'ts': 0.0, 'msg': ''}


def _alerter_session(message: str):
    """Alerte email des admins si la synchro échoue (session expirée, réseau...).
    Max 1 alerte / 6 h par message identique pour éviter le spam."""
    import time as _time
    try:
        now = _time.time()
        if _last_alert['msg'] == message and now - _last_alert['ts'] < 6 * 3600:
            return
        _last_alert.update(ts=now, msg=message)
        from app.models import User
        from app.integrations.brevo import send_email_via_brevo_api
        for u in User.query.filter_by(role='admin').all():
            if not u.email:
                continue
            send_email_via_brevo_api(
                u.email,
                '⚠️ Pennylane TVA — synchro en échec',
                "La synchro automatique des statuts TVA Pennylane a rencontré un problème :\n\n"
                f"{message}\n\n"
                "Si la session est expirée, recolle les cookies sur la page Intégration Pennylane.",
            )
    except Exception:
        pass


def sync_checklist_tva() -> dict:
    """Boucle sur tous les dossiers reliés à Pennylane :
    1. stocke le statut PL brut dans TvaStatutPennylane (tableau de suivi, affichage grille)
    2. remplit ChecklistEntry pour les déclarations faites DANS Pennylane
       (vat_returns avec statut filed/paid) — jamais les périodes 'to_do' ;
    3. neutralise les forçages manuels sur les périodes connues de PL (la synchro fait foi).

    Priorité : la SYNCHRO fait foi sur les dossiers reliés (écrase les saisies manuelles
    antérieures — cf. demande utilisateur).

    Retour : {'ok', 'synces', 'dossiers_ok', 'erreurs': [...], 'message'}
    """
    from app import db
    from app.models import Dossier, ChecklistEntry, TvaStatutPennylane

    # Dossiers reliés (customer_id) OU auto-associables (token API dédié -> ID
    # retrouvé automatiquement via l'API Company, cf. resolve_company_for_dossier)
    dossiers = Dossier.query.filter(
        db.or_(
            db.and_(Dossier.pennylane_customer_id.isnot(None), Dossier.pennylane_customer_id != ''),
            db.and_(Dossier.pennylane_api_token.isnot(None), Dossier.pennylane_api_token != '')
        )).all()
    if not dossiers:
        return {'ok': False, 'message': 'Aucun dossier relié à Pennylane.',
                'synces': 0, 'dossiers_ok': 0, 'erreurs': []}

    annee_courante = date.today().year
    synced = 0
    statuts_ecrits = 0
    en_retard = 0
    forces_annules = 0
    taches_liees = 0
    dossiers_ok = 0
    dossiers_vides = 0
    erreurs = []
    auto_associes = 0
    bloques = 0
    blocages_consecutifs = 0
    abandonne = False
    # Cadence : Pennylane déclenche sa protection anti-bot (418) sur des appels
    # trop rapprochés. On espace les dossiers d'environ 3/4 de seconde.
    import random as _random
    import time as _time
    cadence = 0.7 if len(dossiers) > 1 else 0.0

    for d in dossiers:
        if not (d.pennylane_customer_id or '').strip():
            # Auto-association : le dossier a un token API dédié, on retrouve
            # le company ID tout seul (match par nom, fallback /me).
            from app.integrations.pennylane import resolve_company_for_dossier
            res_auto = resolve_company_for_dossier(d)
            if res_auto.get('ok'):
                d.pennylane_customer_id = res_auto['company_id']
                db.session.commit()
                auto_associes += 1
            else:
                erreurs.append(f"{d.numero_dossier}: auto-association échouée — {res_auto.get('message')}")
                continue
        if cadence:
            _time.sleep(cadence + _random.uniform(0, 0.4))

        res = fetch_vat_forms(d.pennylane_customer_id)
        if not res['ok']:
            erreurs.append(f"{d.numero_dossier}: {res['message']}")
            if res.get('bloque'):
                bloques += 1
                blocages_consecutifs += 1
                # Disjoncteur : insister ne fait qu'allonger le blocage.
                if blocages_consecutifs >= 3:
                    abandonne = True
                    erreurs.append(
                        "Arrêt de la synchro : Pennylane bloque 3 dossiers d'affilée (HTTP 418). "
                        "Les autres dossiers n'ont pas été interrogés.")
                    break
            else:
                blocages_consecutifs = 0
            # La session est partagée par tous les dossiers : on marque l'erreur
            # mais on continue de tenter les suivants (chacun remonte son statut).
            continue

        blocages_consecutifs = 0
        dossiers_ok += 1
        taxe = _vat_taxe_for(d)
        if not (res['vat_returns'] or res['future_vat_returns']):
            dossiers_vides += 1
            continue  # rien à écrire, mais l'appel a réussi

        # --- 1. Miroir brut dans TvaStatutPennylane (toutes périodes, tout statut) ---
        per_connues = set()
        for vr in (res['vat_returns'] + res['future_vat_returns']):
            per = _extract_period(vr)
            if not per:
                continue
            y, mo = per
            if taxe == 'tva_trimestriel':
                mo = ((mo - 1) // 3) * 3 + 1
            per_connues.add((y, mo))
            st = (vr.get('status') or '').lower()
            st_row = TvaStatutPennylane.query.filter_by(
                dossier_id=d.id, annee=y, mois=mo).first()
            if not st_row:
                st_row = TvaStatutPennylane(dossier_id=d.id, annee=y, mois=mo)
                db.session.add(st_row)
            st_row.statut = st or 'unknown'
            st_row.deadline = vr.get('deadline') or None
            # Comptage des déclarations en retard (pas saisies dans PL + échéance dépassée)
            try:
                if (st or 'to_do') in ('to_do', 'unknown') and st_row.deadline:
                    dd = datetime.strptime(str(st_row.deadline)[:10], '%Y-%m-%d').date()
                    if dd < date.today():
                        en_retard += 1
            except Exception:
                pass
            payable = vr.get('payable') or vr.get('amount_due') or vr.get('total_amount')
            try:
                st_row.montant = float(payable) if payable is not None else None
            except (TypeError, ValueError):
                st_row.montant = None
            st_row.date_sync = datetime.utcnow()
            statuts_ecrits += 1
            # --- 1b. La synchro fait foi : annule un forçage manuel antérieur sur une
            #         période que Pennylane connaît (to_do/filed...) — cf. demande utilisateur ---
            old = ChecklistEntry.query.filter_by(dossier_id=d.id, taxe=taxe,
                                                 annee=y, mois=mo, kind='depot').first()
            if old and old.pl_mode and not (old.declare or old.paye):
                db.session.delete(old)
                forces_annules += 1

        # --- 2. ChecklistEntry : déclarations réellement faites DANS Pennylane ---
        for vr in res['vat_returns']:
            st = (vr.get('status') or '').lower()
            if st not in FILED_STATUSES:
                continue  # créée mais pas télédéclarée -> on ne coche pas
            per = _extract_period(vr)
            if not per:
                continue
            y, mo = per
            if taxe == 'tva_trimestriel':
                mo = ((mo - 1) // 3) * 3 + 1
            e = ChecklistEntry.query.filter_by(dossier_id=d.id, taxe=taxe,
                                               annee=y, mois=mo, kind='depot').first()
            if not e:
                e = ChecklistEntry(dossier_id=d.id, taxe=taxe, annee=y, mois=mo, kind='depot')
                db.session.add(e)
            # Priorité à la SYNCHRO Pennylane sur les dossiers reliés :
            # PL dit filed/paid -> la déclaration est réellement faite dans Pennylane,
            # on écrase même une saisie manuelle antérieure (pl_mode=True).
            e.declare = True
            e.paye = (st == 'paid')
            e.pl_mode = True
            synced += 1
            # LIAISON sync -> taches : la tache deadline de la periode declaree
            # dans Pennylane est auto-terminee (ex. aout -> "Dépôt TVA mensuel").
            try:
                from ..checklist_link import appliquer_case_a_taches
                t_lk = appliquer_case_a_taches(d.id, taxe, y, mo, 'depot', True, source='auto_pennylane', email=False)
                if t_lk:
                    taches_liees += t_lk
            except Exception as _lk_e:
                from flask import current_app
                current_app.logger.warning(f"Liaison auto-sync->taches {d.numero_dossier}: {_lk_e}")

    db.session.commit()
    msg = (f"{dossiers_ok}/{len(dossiers)} dossier(s) synchronisé(s) — "
           f"{statuts_ecrits} statut(s) Pennylane enregistré(s) "
           f"(visibles dans la grille : pastille bleue au coin des cases), "
           f"{synced} case(s) marquée(s) déclarée(s) (déclarations faites dans Pennylane), "
           f"{forces_annules} forçage(s) manuel(s) annulé(s) sur des périodes connues de Pennylane.")
    if erreurs:
        msg += f" {len(erreurs)} erreur(s)."
        # Quand TOUT échoue, la cause doit être visible sur la carte admin :
        # « 0/53, 53 erreurs » sans raison ne permet pas de savoir si c'est
        # un 418, des cookies morts ou des dossiers non reliés.
        if dossiers_ok == 0:
            msg += f" Première cause : {erreurs[0]}"
    if dossiers_vides:
        msg += (f" ⚠️ {dossiers_vides} dossier(s) : Pennylane a répondu mais n'a retourné "
                f"AUCUNE période TVA — session à revérifier (page Intégration).")
    if en_retard:
        msg += f" ⚠️ {en_retard} déclaration(s) EN RETARD (non saisie(s) dans Pennylane, échéance dépassée)."

    if auto_associes:
        msg += f" 🔗 {auto_associes} dossier(s) auto-associé(s) via API Company (token du dossier)."

    if bloques:
        msg += (f" ⛔ {bloques} dossier(s) refusé(s) par Pennylane. 418/anti-bot = "
                f"transitoire (attendre 2-3 min) ; page de connexion ou HTML = "
                f"cookies à recoller depuis app.pennylane.com.")
    if abandonne:
        msg += " Synchro interrompue volontairement pour ne pas aggraver le blocage."

    # Le bilan doit dire la VÉRITÉ : sans dossier synchronisé, l'opération a échoué.
    # (Avant, `ok` était toujours True : l'interface affichait un succès vert alors
    # que zéro statut n'avait changé — d'où l'impression que « rien ne se passe ».)
    succes = dossiers_ok > 0 and not abandonne
    if not succes and not erreurs:
        msg += " Aucun dossier à synchroniser."

    # Trace du dernier passage (carte admin) + alerte email si problème
    _save_last_sync(ok=succes, message=msg)
    if erreurs:
        _alerter_session(msg)

    return {'ok': succes, 'synces': synced, 'statuts': statuts_ecrits,
            'en_retard': en_retard, 'dossiers_ok': dossiers_ok,
            'dossiers_total': len(dossiers),
            'bloques': bloques, 'abandonne': abandonne,
            'auto_associes': auto_associes,
            'erreurs': erreurs[:10], 'message': msg}


def sync_si_necessaire(max_age_minutes: int = 120) -> dict:
    """Synchro TVA de rattrapage — appelée au premier usage du process.

    Même cause que la planification fiscale : la synchro tourne toutes les
    heures via un cron EN PROCESSUS. Sur un hébergeur qui endort l'instance,
    elle ne s'exécute presque jamais et l'appli affiche un état vieux de
    plusieurs jours — d'où des statuts qui ne correspondent plus à Pennylane.

    Ici on relance la synchro si la dernière trace est plus vieille que
    `max_age_minutes`, au moment où l'instance sort de veille.
    """
    if not has_web_session():
        return {'ok': False, 'skipped': True, 'message': 'Session web non configurée.'}
    last = get_last_sync() or {}
    quand = last.get('quand')
    if quand:
        try:
            dt = datetime.strptime(str(quand), '%d/%m/%Y %H:%M')
            age_min = (datetime.utcnow() - dt).total_seconds() / 60.0
            # La trace est en heure de Paris dans _save_last_sync ? On tolère
            # l'écart : un age négatif signifie « très récent », on ne resynce pas.
            if -180 <= age_min <= max_age_minutes:
                return {'ok': True, 'skipped': True,
                        'message': f'Synchro récente ({int(age_min)} min), rien à faire.'}
        except Exception:
            pass
    res = sync_checklist_tva()
    return res


def statuts_pour_grille(dossiers_ids, annee: int) -> dict:
    """Retourne {(dossier_id, mois): TvaStatutPennylane} pour l'affichage grille."""
    from app.models import TvaStatutPennylane
    if not dossiers_ids:
        return {}
    rows = TvaStatutPennylane.query.filter(
        TvaStatutPennylane.dossier_id.in_(dossiers_ids),
        TvaStatutPennylane.annee == annee).all()
    return {(r.dossier_id, r.mois): r for r in rows}


def test_web_session(customer_id: str = None) -> dict:
    """Teste la validité de la session web en appelant vat_forms sur un customer_id de test.

    Renvoie aussi un diagnostic sur les cookies STOCKÉS (noms uniquement,
    jamais les valeurs) : un collage issu d'un autre site passe le nettoyage
    mais ne contient pas `_jeancaisse_session`, et Pennylane renvoie alors une
    page HTML. Sans ce contrôle, l'appli disait seulement « Réponse non JSON ».
    """
    _load_from_db()
    ck = _parse_cookie_header(_pl_session_cookies or '')
    noms = sorted(ck.keys())
    sans_session = '_jeancaisse_session' not in ck
    rapport = {'nb_cookies': len(ck), 'cles': noms,
               'session_pennylane': not sans_session}
    cid = customer_id or '23281030'
    res = fetch_vat_forms(cid, period_start=f'{date.today().year}-01-01',
                          period_end=f'{date.today().year}-12-31')
    if res['ok']:
        all_vr = res['vat_returns'] + res['future_vat_returns']
        n = len(all_vr)
        from collections import Counter
        cnt = Counter(((v.get('status') or '?').lower() or '?') for v in all_vr)
        detail = ', '.join(f'{k}:{v}' for k, v in sorted(cnt.items()))
        out = {'ok': True, 'message': f'Session OK — {n} période(s) TVA lue(s) sur company {cid} ({detail}).'}
        out.update(rapport)
        return out
    if sans_session:
        out = {'ok': False,
               'message': (f"Cookies invalides : aucun `_jeancaisse_session` parmi les {len(ck)} "
                           "cookies enregistrés — tu as probablement copié une requête d'un "
                           "autre site. Dans F12 → Network, filtre 'pennylane', clique une "
                           "requête vers app.pennylane.com, onglet Headers → ligne cookie → "
                           "'Copier la valeur', puis recolle dans le champ ci-dessous.")}
        out.update(rapport)
        out['diagnostic'] = res.get('diagnostic')
        return out
    out = {'ok': False, 'message': res['message']}
    out.update(rapport)
    if res.get('diagnostic'):
        out['diagnostic'] = res['diagnostic']
    return out
