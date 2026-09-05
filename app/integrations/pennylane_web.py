# -*- coding: utf-8 -*-
"""Synchronisation des declarations de TVA depuis l'espace web Pennylane (interface comptable).

Utilise l'endpoint interne du front-end (vat_forms) appele par la page
/companies/<id>/accountants/declarations/vat_returns avec les cookies de session
de l'utilisateur connecte (capturés via DevTools -> Copier comme cURL).

Réponse vat_forms : {"vat_returns": [...], "future_vat_returns": [...]}
  - vat_returns        : déclarations créées dans Pennylane (status: filed, sent, paid...)
  - future_vat_returns : périodes pas encore déclarées dans PL (status 'to_do', deadline, payable)

Les déclarations faites via impots.gouv (ACD) n'apparaissent PAS dans PL => 'to_do'.
Elles sont marquées manuellement dans l'app (ChecklistEntry) et ne sont jamais écrasées.

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

# Statuts Pennylane considérés comme "déclarée"
FILED_STATUSES = {'filed', 'sent', 'paid', 'partially_paid'}
# Statut brut -> libellé FR
STATUT_FR = {
    'to_do': 'À déclarer',
    'in_progress': 'En cours',
    'filed': 'Télédéclarée',
    'sent': 'Télédéclarée',
    'paid': 'Payée',
    'partially_paid': 'Partiellement payée',
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
    global _pl_session_cookies, _pl_session_loaded
    cookies = (cookies or '').strip()
    # Enlever un éventuel "-b '...'" collé par erreur
    m = re.search(r"""-b\s+['"](.+?)['"]""", cookies)
    if m:
        cookies = m.group(1)
    with _pl_session_lock:
        _pl_session_cookies = cookies
        _pl_session_loaded = True
    # Persister en BDD pour survivre aux redéploiements
    try:
        from app.models import AppSetting
        from app import db
        s = AppSetting.query.filter_by(cle=COOKIE_KEY).first()
        if not s:
            s = AppSetting(cle=COOKIE_KEY, valeur=cookies, type_valeur='password',
                           service='pennylane', masque=True)
            db.session.add(s)
        else:
            s.valeur = cookies
        db.session.commit()
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
        period_start = f'{today.year}-01-01'
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
        return {'ok': False, 'message': 'Session expirée — recolle les cookies Pennylane.',
                'vat_returns': [], 'future_vat_returns': []}
    if r.status_code != 200:
        return {'ok': False, 'message': f'HTTP {r.status_code}',
                'vat_returns': [], 'future_vat_returns': []}
    try:
        data = r.json()
    except Exception:
        return {'ok': False, 'message': 'Réponse non JSON',
                'vat_returns': [], 'future_vat_returns': []}
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


def sync_checklist_tva() -> dict:
    """Boucle sur tous les dossiers reliés à Pennylane :
    1. stocke le statut PL brut dans TvaStatutPennylane (tableau de suivi, affichage grille)
    2. remplit ChecklistEntry pour les déclarations faites DANS Pennylane
       (vat_returns avec statut filed/paid) — jamais les périodes 'to_do'.

    Priorité : les entrées MANUELLES (updated_by_id renseigné) ne sont jamais écrasées.

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
        for vr in (res['vat_returns'] + res['future_vat_returns']):
            per = _extract_period(vr)
            if not per:
                continue
            y, mo = per
            if taxe == 'tva_trimestriel':
                mo = ((mo - 1) // 3) * 3 + 1
            st = (vr.get('status') or '').lower()
            st_row = TvaStatutPennylane.query.filter_by(
                dossier_id=d.id, annee=y, mois=mo).first()
            if not st_row:
                st_row = TvaStatutPennylane(dossier_id=d.id, annee=y, mois=mo)
                db.session.add(st_row)
            st_row.statut = st or 'unknown'
            st_row.deadline = vr.get('deadline') or None
            payable = vr.get('payable') or vr.get('amount_due') or vr.get('total_amount')
            try:
                st_row.montant = float(payable) if payable is not None else None
            except (TypeError, ValueError):
                st_row.montant = None
            st_row.date_sync = datetime.utcnow()
            statuts_ecrits += 1

        # --- 2. ChecklistEntry : seulement les déclarations réellement faites dans PL ---
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
            if y != annee_courante:
                continue
            e = ChecklistEntry.query.filter_by(dossier_id=d.id, taxe=taxe,
                                               annee=y, mois=mo, kind='depot').first()
            if not e:
                e = ChecklistEntry(dossier_id=d.id, taxe=taxe, annee=y, mois=mo, kind='depot')
                db.session.add(e)
            # Priorité à la SYNCHRO Pennylane sur les dossiers reliés :
            # PL dit filed/paid -> la déclaration est réellement faite dans Pennylane,
            # on écrase même une saisie manuelle antérieure.
            e.declare = True
            e.paye = (st == 'paid')
            synced += 1

    db.session.commit()
    msg = (f"{dossiers_ok}/{len(dossiers)} dossier(s) synchronisé(s) — "
           f"{statuts_ecrits} statut(s) Pennylane enregistré(s) "
           f"(visibles dans la grille : pastille bleue au coin des cases), "
           f"{synced} case(s) marquée(s) déclarée(s) (déclarations faites dans Pennylane).")
    if erreurs:
        msg += f" {len(erreurs)} erreur(s)."
    return {'ok': True, 'synces': synced, 'statuts': statuts_ecrits,
            'dossiers_ok': dossiers_ok, 'erreurs': erreurs[:10], 'message': msg}


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
        n = len(res['vat_returns']) + len(res['future_vat_returns'])
        return {'ok': True, 'message': f'Session OK — {n} période(s) TVA lue(s) sur company {cid}.'}
    return {'ok': False, 'message': res['message']}
