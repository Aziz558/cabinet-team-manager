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

# Cache mémoire des cookies (lazy-load depuis AppSetting au premier accès)
_pl_session_lock = threading.Lock()
_pl_session_cookies = ''
_pl_session_loaded = False

COOKIE_KEY = 'PENNYLANE_WEB_COOKIES'

# Statuts Pennylane considérés comme "déclarée / terminée"
FILED_STATUSES = {'filed', 'sent', 'paid', 'partially_paid', 'completed', 'done',
                  'validated', 'accepted', 'transmitted', 'accounted', 'teletedeclaree'}
# Statuts "en retard" selon Pennylane
LATE_STATUSES = {'late', 'late_to_do', 'overdue', 'en_retard', 'retard'}
# Statut brut -> libellé FR
STATUT_FR = {
    'to_do': 'À déclarer',
    'in_progress': 'En cours',
    'draft': 'Brouillon',
    'to_send': 'À envoyer',
    'filed': 'Télédéclarée',
    'sent': 'Télédéclarée',
    'completed': 'Terminée',
    'done': 'Terminée',
    'validated': 'Validée',
    'accepted': 'Validée',
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


def set_web_session(cookies: str, firm_id: int = None):
    """Stocke les cookies de session Pennylane (colle le header -b du cURL) et persiste en BDD."""
    cookies = (cookies or '').strip()
    # Enlever un éventuel "-b '...'" collé par erreur
    m = re.search(r"""-b\s+['"](.+?)['"]""", cookies)
    if m:
        cookies = m.group(1)
    _store_cookies(cookies)


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


def _headers():
    return {
        'accept': 'application/json',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36 Edg/152.0.0.0',
        'x-reseller': 'pennylane',
        'x-plan-used-by-front-end': 'v1_saas_free',
        'referer': 'https://app.pennylane.com/',
    }


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
        period_start = f'{today.year - 1}-12-01'  # marge : CA3 de déc. N-1 déposée en janv. N
    if not period_end:
        period_end = f'{today.year}-12-31'

    url = (f'https://app.pennylane.com/companies/{customer_id}'
           f'/accountants/declarations/vat_forms'
           f'?period_start={period_start}&period_end={period_end}')
    with _pl_session_lock:
        cookies = _pl_session_cookies
    try:
        r = requests.get(url, headers=_headers(), cookies=_parse_cookie_header(cookies),
                         timeout=25)
    except Exception as e:
        return {'ok': False, 'message': f'Erreur réseau: {e}',
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
        return {'ok': False, 'message': 'Réponse non JSON',
                'vat_returns': [], 'future_vat_returns': []}
    # Auto-refresh de la session : réutiliser les cookies frais renvoyés par PL
    _refresh_session_cookies(r)
    return {'ok': True, 'vat_returns': data.get('vat_returns') or [],
            'future_vat_returns': data.get('future_vat_returns') or []}


def traduire_statut(statut: str) -> str:
    """Statut Pennylane brut -> libellé FR pour l'affichage."""
    return STATUT_FR.get((statut or '').lower(), statut or '')


def _extract_period(vr: dict):
    """Extrait (annee, mois) d'un objet vat_return (period='2026-01' ou '2026-01-01')."""
    period = vr.get('period') or vr.get('label') or ''
    m = re.match(r'(\d{4})-(\d{2})', str(period))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _vat_taxe_for(dossier) -> str:
    """taxe ChecklistEntry selon le régime TVA du dossier."""
    regime = (dossier.regime_tva or '').lower().strip()
    if regime in ('trimestriel', 'trimestrielle'):
        return 'tva_trimestriel'
    return 'tva_mensuel'


LAST_SYNC_KEY = 'PENNYLANE_WEB_LAST_SYNC'


def _save_last_sync(ok: bool, message: str):
    """Trace du dernier passage de la synchro (auto ou manuel) — affichée sur la carte admin."""
    try:
        import json as _json
        from app.models import AppSetting
        from app import db
        payload = _json.dumps({
            'quand': datetime.utcnow().strftime('%d/%m/%Y %H:%M'),
            'ok': bool(ok),
            'message': message,
        }, ensure_ascii=False)
        s = AppSetting.query.filter_by(cle=LAST_SYNC_KEY).first()
        if not s:
            s = AppSetting(cle=LAST_SYNC_KEY, valeur=payload, type_valeur='json',
                           service='pennylane')
            db.session.add(s)
        else:
            s.valeur = payload
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
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

    dossiers = Dossier.query.filter(Dossier.pennylane_customer_id.isnot(None),
                                    Dossier.pennylane_customer_id != '').all()
    if not dossiers:
        return {'ok': False, 'message': 'Aucun dossier relié à Pennylane.',
                'synces': 0, 'dossiers_ok': 0, 'erreurs': []}

    annee_courante = date.today().year
    synced = 0
    statuts_ecrits = 0
    en_retard = 0
    forces_annules = 0
    dossiers_ok = 0
    erreurs = []

    for d in dossiers:
        res = fetch_vat_forms(d.pennylane_customer_id)
        if not res['ok']:
            erreurs.append(f"{d.numero_dossier}: {res['message']}")
            if 'Session expirée' in res['message']:
                break  # inutile de continuer, tout va échouer
            continue

        dossiers_ok += 1
        taxe = _vat_taxe_for(d)

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

    db.session.commit()
    msg = (f"{dossiers_ok}/{len(dossiers)} dossier(s) synchronisé(s) — "
           f"{statuts_ecrits} statut(s) Pennylane enregistré(s) "
           f"(visibles dans la grille : pastille bleue au coin des cases), "
           f"{synced} case(s) marquée(s) déclarée(s) (déclarations faites dans Pennylane), "
           f"{forces_annules} forçage(s) manuel(s) annulé(s) sur des périodes connues de Pennylane.")
    if erreurs:
        msg += f" {len(erreurs)} erreur(s)."
    if en_retard:
        msg += f" ⚠️ {en_retard} déclaration(s) EN RETARD (non saisie(s) dans Pennylane, échéance dépassée)."

    # Trace du dernier passage (carte admin) + alerte email si problème
    _save_last_sync(ok=(not erreurs), message=msg)
    if erreurs:
        _alerter_session(msg)

    return {'ok': True, 'synces': synced, 'statuts': statuts_ecrits,
            'en_retard': en_retard, 'dossiers_ok': dossiers_ok,
            'erreurs': erreurs[:10], 'message': msg}


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
    """Teste la validité de la session web en appelant vat_forms sur un customer_id de test."""
    cid = customer_id or '23281030'
    res = fetch_vat_forms(cid, period_start=f'{date.today().year}-01-01',
                          period_end=f'{date.today().year}-12-31')
    if res['ok']:
        all_vr = res['vat_returns'] + res['future_vat_returns']
        n = len(all_vr)
        from collections import Counter
        cnt = Counter(((v.get('status') or '?').lower() or '?') for v in all_vr)
        detail = ', '.join(f'{k}:{v}' for k, v in sorted(cnt.items()))
        return {'ok': True, 'message': f'Session OK — {n} période(s) TVA lue(s) sur company {cid} ({detail}).'}
    return {'ok': False, 'message': res['message']}
