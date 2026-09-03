# -*- coding: utf-8 -*-
"""Synchronisation des déclarations de TVA depuis l'espace web Pennylane (interface comptable).

Utilise l'endpoint interne du front-end (vat_forms) appelé par la page
/companies/<id>/accountants/declarations/vat_returns avec les cookies de session
de l'utilisateur connecté (capturés via DevTools → Copier comme cURL).

Réponse vat_forms : {"vat_returns": [...], "future_vat_returns": [...], "vat_settings": {...}}
  - vat_returns        : déclarations déjà créées dans Pennylane (avec status: 'filed', 'sent'...)
  - future_vat_returns : périodes à venir (status 'to_do', deadline, payable)
Les déclarations faites via impots.gouv (ACD) n'apparaissent PAS ici => elles restent
'to_do' dans Pennylane. L'app permet de les marquer manuellement (ChecklistEntry).
"""

import json
import re
import threading
import time
from datetime import datetime, date

import requests

# Stockage en mémoire des cookies de session Pennylane (session web, jamais persistés en BDD)
_pl_session_lock = threading.Lock()
_pl_session_cookies = ''
_pl_session_firm_id = None  # FirmContext : 76917 pour JMH


def set_web_session(cookies: str, firm_id: int = 76917):
    """Stocke les cookies de session Pennylane (colle le header -b du cURL)."""
    global _pl_session_cookies, _pl_session_firm_id
    cookies = (cookies or '').strip()
    # Enlever un éventuel "-b '...'" ou -b "..." collé par erreur
    m = re.search(r"""-b\s+['"](.+?)['"]""", cookies)
    if m:
        cookies = m.group(1)
    with _pl_session_lock:
        _pl_session_cookies = cookies
        _pl_session_firm_id = int(firm_id) if firm_id else 76917


def has_web_session() -> bool:
    return bool(_pl_session_cookies)


def clear_web_session():
    global _pl_session_cookies
    with _pl_session_lock:
        _pl_session_cookies = ''


def _headers():
    return {
        'accept': 'application/json',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36 Edg/152.0.0.0',
        'x-reseller': 'pennylane',
        'x-plan-used-by-front-end': 'v1_saas_free',
        'referer': 'https://app.pennylane.com/',
    }


def fetch_vat_forms(customer_id: str, period_start: str = None, period_end: str = None) -> dict:
    """Récupère les déclarations TVA d'une company Pennylane via l'endpoint interne.

    Retourne {'ok': bool, 'vat_returns': [...], 'future_vat_returns': [...], 'message': str}
    """
    if not has_web_session():
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


def _parse_cookie_header(header: str) -> dict:
    out = {}
    for part in (header or '').split(';'):
        part = part.strip()
        if '=' in part:
            k, _, v = part.partition('=')
            out[k.strip()] = v.strip()
    return out


def traduire_statut(statut: str) -> str:
    """Statut Pennylane brut -> libellé FR pour l'affichage."""
    s = (statut or '').lower()
    return {
        'to_do': 'À déclarer',
        'in_progress': 'En cours',
        'filed': 'Télédéclarée',
        'sent': 'Télédéclarée',
        'paid': 'Payée',
        'partially_paid': 'Partiellement payée',
        'rejected': 'Rejetée',
        'cancelled': 'Annulée',
    }.get(s, statut or '')


def sync_checklist_tva() -> dict:
    """Boucle sur tous les dossiers reliés à Pennylane et synchronise les statuts
    de déclaration TVA dans ChecklistEntry (kind='depot').

    Priorité : les entrées MANUELLES (updated_by_id renseigné) ne sont jamais écrasées.
    Les statuts Pennylane ne remplissent que les cases vides.

    Retour : {'ok', 'synces': n, 'erreurs': [...], 'message'}
    """
    from app import db
    from app.models import Dossier, ChecklistEntry

    dossiers = Dossier.query.filter(Dossier.pennylane_customer_id.isnot(None),
                                    Dossier.pennylane_customer_id != '').all()
    if not dossiers:
        return {'ok': False, 'message': 'Aucun dossier relié à Pennylane.', 'synces': 0, 'erreurs': []}

    annee_courante = date.today().year
    synced = 0
    erreurs = []

    for d in dossiers:
        res = fetch_vat_forms(d.pennylane_customer_id)
        if not res['ok']:
            erreurs.append(f"{d.numero_dossier}: {res['message']}")
            if 'Session expirée' in res['message']:
                break  # inutile de continuer, tout va échouer
            continue

        # vat_returns : déclarations créées dans Pennylane (télédéclarées via PL)
        for vr in res['vat_returns']:
            _apply_statut(d, vr, annee_courante, declare=True, paye=None)
            synced += 1

        # future_vat_returns : périodes non déclarées dans PL ('to_do')
        # => on ne touche PAS : la déclaration peut avoir été faite via impots.gouv (ACD).
        #    L'utilisateur peut les marquer manuellement dans l'app.

    db.session.commit()
    msg = f'{synced} statut(s) synchronisé(s) sur {len(dossiers)} dossier(s).'
    if erreurs:
        msg += f' {len(erreurs)} erreur(s).'
    return {'ok': True, 'synces': synced, 'erreurs': erreurs[:10], 'message': msg}


def _apply_statut(dossier, vat_return: dict, annee: int, declare: bool, paye):
    """Applique un statut Pennylane à une ChecklistEntry sans écraser une entrée manuelle."""
    from app.models import ChecklistEntry, User

    period = vat_return.get('period') or vat_return.get('label') or ''
    # format '2026-01' ou '2026-01-01'
    m = re.match(r'(\d{4})-(\d{2})', str(period))
    if not m:
        return
    y, mo = int(m.group(1)), int(m.group(2))

    kind = 'depot'
    regime = (dossier.regime_tva or '').lower().strip()
    if regime in ('trimestriel', 'trimestrielle'):
        # aligner sur le 1er mois du trimestre
        mo = ((mo - 1) // 3) * 3 + 1

    if y != annee:
        return

    e = ChecklistEntry.query.filter_by(dossier_id=dossier.id, taxe='tva_mensuel' if regime in ('ca3', 'mensuel', 'mensuelle') else 'tva_trimestriel',
                                       annee=y, mois=mo, kind=kind).first()
    if not e:
        taxe = 'tva_mensuel' if regime in ('ca3', 'mensuel', 'mensuelle') else 'tva_trimestriel'
        e = ChecklistEntry(dossier_id=dossier.id, taxe=taxe, annee=y, mois=mo, kind=kind)
        from app import db
        db.session.add(e)
    if e.updated_by_id:
        return  # jamais écraser une entrée saisie manuellement

    if declare:
        e.declare = True
    if paye is not None:
        e.paye = bool(paye)


def test_web_session(customer_id: str = None) -> dict:
    """Teste la validité de la session web en appelant vat_forms sur un customer_id de test."""
    cid = customer_id or '23281030'
    res = fetch_vat_forms(cid, period_start=f'{date.today().year}-01-01',
                          period_end=f'{date.today().year}-12-31')
    if res['ok']:
        n = len(res['vat_returns']) + len(res['future_vat_returns'])
        return {'ok': True, 'message': f'Session OK — {n} période(s) TVA lue(s) sur company {cid}.'}
    return {'ok': False, 'message': res['message']}
