"""
Intégration Pennylane (Company API v2)
=======================================
Module de connexion à l'API Pennylane pour synchroniser les données
des dossiers du cabinet : factures, écritures comptables, transactions.

Documentation : https://pennylane.readme.io/docs/api-overview
Base URL API   : https://api.pennylane.com
"""

import requests
import logging
from datetime import datetime, date

logger = logging.getLogger(__name__)

PENNYLANE_API_URL = 'https://app.pennylane.com/api/external'
PENNYLANE_API_VERSION = 'v2'


def get_pennylane_token() -> str:
    from app.models import AppSetting
    try:
        setting = AppSetting.query.filter_by(cle='PENNYLANE_API_TOKEN').first()
        return (setting.valeur or '').strip() if setting else ''
    except Exception:
        return ''


def save_pennylane_token(token: str) -> None:
    from app.models import AppSetting
    from app import db
    token = (token or '').strip()
    setting = AppSetting.query.filter_by(cle='PENNYLANE_API_TOKEN').first()
    if token:
        if not setting:
            setting = AppSetting(cle='PENNYLANE_API_TOKEN', valeur=token,
                                 type_valeur='password', service='pennylane', masque=True)
            db.session.add(setting)
        else:
            setting.valeur = token
        db.session.commit()
    else:
        if setting:
            db.session.delete(setting)
            db.session.commit()


def _headers(token: str) -> dict:
    return {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'accept': 'application/json',
    }


def _api_url(path: str) -> str:
    return f'{PENNYLANE_API_URL}/{PENNYLANE_API_VERSION}/{path.lstrip("/")}'


def test_connexion(token: str = None) -> dict:
    """Teste la connexion à l'API Pennylane. Retourne {ok, message, ...}."""
    token = token or get_pennylane_token()
    if not token:
        return {'ok': False, 'message': 'Token API Pennylane non configuré.'}
    try:
        resp = requests.get(_api_url('me'), headers=_headers(token), timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            company = data.get('company', {}) if isinstance(data, dict) else {}
            return {'ok': True,
                    'message': 'Connexion réussie',
                    'societe': company.get('name', 'Société Pennylane'),
                    'siret': company.get('siret', '')}
        elif resp.status_code == 401:
            return {'ok': False, 'message': 'Token invalide (401 Unauthorized).'}
        elif resp.status_code == 403:
            return {'ok': False, 'message': 'Accès refusé (403) : vérifiez les scopes du token.'}
        else:
            return {'ok': False, 'message': f'Erreur API ({resp.status_code}) : {resp.text[:200]}'}
    except requests.exceptions.Timeout:
        return {'ok': False, 'message': 'Délai dépassé : API Pennylane injoignable.'}
    except Exception as e:
        logger.error(f'Test connexion Pennylane: {e}')
        return {'ok': False, 'message': f'Erreur: {str(e)}'}


def _paginated_get(path: str, params: dict = None, token: str = None, max_pages: int = 20) -> list:
    """Récupère tous les éléments d'un endpoint paginé (cursor-based)."""
    token = token or get_pennylane_token()
    if not token:
        return []
    params = dict(params or {})
    results = []
    for _ in range(max_pages):
        try:
            resp = requests.get(_api_url(path), headers=_headers(token), params=params, timeout=20)
        except Exception as e:
            logger.error(f'Pennylane GET {path}: {e}')
            break
        if resp.status_code != 200:
            logger.warning(f'Pennylane GET {path} -> {resp.status_code}: {resp.text[:200]}')
            break
        data = resp.json()
        key = None
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list):
                    key = k
                    break
        if key:
            results.extend(data.get(key, []))
        next_cursor = None
        if isinstance(data, dict):
            pagination = data.get('pagination') or {}
            next_cursor = pagination.get('next_cursor')
        if next_cursor:
            params['cursor'] = next_cursor
        else:
            break
    return results


def get_customer_invoices(token: str = None, limit: int = 50) -> list:
    invoices = _paginated_get('customer_invoices', params={'limit': limit}, token=token)
    return [{
        'id': inv.get('id'),
        'numero': inv.get('invoice_number') or inv.get('invoice_number_formatted') or '',
        'client': (inv.get('customer') or {}).get('name', ''),
        'montant_ht': inv.get('total_without_tax'),
        'montant_ttc': inv.get('total_with_tax'),
        'statut': inv.get('status') or inv.get('invoice_status') or '',
        'date': inv.get('date'),
        'devise': inv.get('currency') or 'EUR',
    } for inv in invoices]


def get_supplier_invoices(token: str = None, limit: int = 50) -> list:
    invoices = _paginated_get('supplier_invoices', params={'limit': limit}, token=token)
    return [{
        'id': inv.get('id'),
        'numero': inv.get('invoice_number') or '',
        'fournisseur': (inv.get('supplier') or {}).get('name', ''),
        'montant_ht': inv.get('total_without_tax'),
        'montant_ttc': inv.get('total_with_tax'),
        'statut': inv.get('accounting_status') or inv.get('payment_status') or '',
        'date': inv.get('date'),
    } for inv in invoices]


def get_ledger_entries(token: str = None, limit: int = 50) -> list:
    entries = _paginated_get('ledger_entries', params={'limit': limit}, token=token)
    return [{
        'id': e.get('id'),
        'date': e.get('date'),
        'libelle': e.get('label') or '',
        'montant_debit': e.get('amount') if (e.get('direction') or '').lower() == 'debit' else 0,
        'montant_credit': e.get('amount') if (e.get('direction') or '').lower() == 'credit' else 0,
        'compte': (e.get('ledger_account') or {}).get('label', ''),
    } for e in entries]


def get_transactions(token: str = None, limit: int = 50) -> list:
    txs = _paginated_get('transactions', params={'limit': limit}, token=token)
    return [{
        'id': t.get('id'),
        'date': t.get('transaction_date') or t.get('date'),
        'libelle': t.get('label') or '',
        'montant': t.get('amount'),
        'statut': 'unaffected' if t.get('attachment_required') in (True, 'true') else 'affected',
        'attachment_required': t.get('attachment_required'),
    } for t in txs]


def get_customers(token: str = None, limit: int = 200) -> list:
    return _paginated_get('customers', params={'limit': limit}, token=token)


def sync_dossiers_pennylane(token: str = None) -> dict:
    from app import db
    from app.models import Dossier
    token = token or get_pennylane_token()
    if not token:
        return {'ok': False, 'message': 'Token non configuré.'}
    try:
        customers = get_customers(token=token)
        dossiers = Dossier.query.all()
        associe = 0
        for d in dossiers:
            if d.pennylane_customer_id and d.pennylane_api_token:
                continue
            nom = (d.intitule or '').strip().lower()
            siret = (d.siret or '').strip()
            for c in customers:
                cid = str(c.get('id', ''))
                cname = (c.get('name') or '').strip().lower()
                csiret = (c.get('siret') or '').strip()
                if (siret and csiret and siret == csiret) or (nom and cname and nom == cname):
                    d.pennylane_customer_id = cid
                    associe += 1
                    break
        db.session.commit()
        return {'ok': True, 'message': f'{associe} dossier(s) associé(s).'}
    except Exception as e:
        logger.error(f'sync_dossiers_pennylane: {e}')
        return {'ok': False, 'message': str(e)}


def _to_float(v):
    if v is None or v == '':
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def traduire_statut_pl(statut_raw: str, item_type: str = 'facture_vente') -> str:
    """Traduit le statut brut Pennylane en français (Traité / Prétraité / À traiter).
    
    Ventes (customer_invoices) : champ `status`
    Achats (supplier_invoices) : champ `accounting_status`
    Banque (transactions)       : inféré (attachment_required → unaffected)
    """
    status = (statut_raw or '').strip().lower()
    if not status:
        return '—'

    # Banque (transactions)
    if item_type == 'transaction':
        mapping = {
            'unaffected': 'À traiter',
            'partially_affected': 'Prétraité',
            'affected': 'Traité',
            'marked_as_unexpected': 'Marqué',
        }
        return mapping.get(status, status.replace('_', ' ').title())

    # Factures clients (ventes)
    if item_type == 'facture_vente':
        if status in ('paid', 'completed', 'late', 'overdue', 'unpaid', 'upcoming'):
            return 'Traité'
        elif status in ('incomplete', 'partially_paid'):
            return 'Prétraité'
        elif status in ('draft', 'to_be_sent', 'sent', 'pending', 'overdue_invoice'):
            return 'À traiter'
        elif status in ('credit_note',):
            return 'Avoir'
        elif status in ('cancelled', 'void', 'archived', 'refunded'):
            return 'Annulé'
        return status.replace('_', ' ').title()

    # Factures fournisseurs (achats) — champ `accounting_status`
    if item_type == 'facture_achat':
        if status in ('complete', 'paid', 'approved', 'affected'):
            return 'Traité'
        elif status in ('validation_needed', 'to_be_processed', 'pending_approval',
                        'draft', 'pending', 'unpaid', 'unaffected'):
            return 'À traiter'
        elif status in ('cancelled', 'void', 'archived'):
            return 'Annulé'
        return status.replace('_', ' ').title()

    return status.replace('_', ' ').title()


def est_pl_traite(statut_raw: str, item_type: str = 'facture_vente') -> bool:
    """Un item est-il explicitement marqué comme traité côté Pennylane ?"""
    fr = traduire_statut_pl(statut_raw, item_type)
    return fr in ('Traité', 'Avoir')


def est_pl_a_traiter(statut_raw: str, item_type: str = 'facture_vente') -> bool:
    """Un item nécessite-t-il une action ?
    Retourne True pour À traiter, Prétraité, ou statut inconnu (sécurité : on prévient par défaut)."""
    fr = traduire_statut_pl(statut_raw, item_type)
    if fr == '—':
        return True  # statut inconnu = à traiter par sécurité
    return fr in ('À traiter', 'Prétraité')

def _detecter_nouveaux_items(dossier, invs, sinvs, txs) -> list:
    """Compare les items reçus avec la table pennylane_items.
    - Nouveau item → inséré en DB avec api_statut + statut 'a_traiter'.
    - Item connu → mis à jour.
    - Seuls les items NON explicitement traités côté Pennylane sont retournés comme nouveaux.
    """
    from app import db
    from app.models import PennylaneItem

    nouveaux = []
    all_rows = PennylaneItem.query.filter_by(dossier_id=dossier.id).all()
    existing = {(it.item_type, it.item_id): it for it in all_rows}
    dirty = False

    def _process(item_type, items, ref_keys, montant_key, date_keys, status_key='status'):
        nonlocal dirty
        for it in items or []:
            iid = str(it.get('id') or '')
            if not iid:
                continue
            ref = ''
            for k in ref_keys:
                if it.get(k):
                    ref = str(it[k])
                    break
            montant = _to_float(it.get(montant_key))
            date_item = ''
            for k in date_keys:
                if it.get(k):
                    date_item = str(it[k])
                    break
            api_statut = str(it.get(status_key) or '').strip()
            row = existing.get((item_type, iid))
            if row is None:
                initial_statut = 'traite' if est_pl_traite(api_statut, item_type) else 'a_traiter'
                row = PennylaneItem(
                    dossier_id=dossier.id, item_type=item_type, item_id=iid,
                    reference=ref[:120], montant=montant, date_item=date_item[:30],
                    api_statut=api_statut[:30], statut=initial_statut,
                )
                db.session.add(row)
                existing[(item_type, iid)] = row
                if not est_pl_traite(api_statut, item_type):
                    nouveaux.append({'type': item_type, 'reference': ref, 'montant': montant, 'date': date_item, 'api_statut': api_statut})
                dirty = True
            else:
                if ref and row.reference != ref[:120]:
                    row.reference = ref[:120]; dirty = True
                if montant is not None and row.montant != montant:
                    row.montant = montant; dirty = True
                if api_statut and row.api_statut != api_statut[:30]:
                    row.api_statut = api_statut[:30]; dirty = True
                if row.statut == 'a_traiter' and api_statut and est_pl_traite(api_statut, item_type):
                    row.statut = 'traite'; dirty = True
                elif row.statut == 'traite' and api_statut and not est_pl_traite(api_statut, item_type):
                    row.statut = 'a_traiter'; dirty = True

    _process('facture_vente', invs, ('invoice_number', 'invoice_number_formatted'), 'total_with_tax', ('date',))
    _process('facture_achat', sinvs, ('invoice_number',), 'total_with_tax', ('date',), status_key='accounting_status')
    # Transactions : le statut est inféré depuis attachment_required
    txs_mapped = []
    for t in txs or []:
        t2 = dict(t)
        t2['status'] = 'unaffected' if t.get('attachment_required') in (True, 'true') else 'affected'
        txs_mapped.append(t2)
    _process('transaction', txs_mapped, ('label',), 'amount', ('transaction_date', 'date'))

    if dirty:
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.warning(f'commit pennylane_items: {e}')
    return nouveaux


def _notifier_nouveaux_items(dossier, nouveaux: list):
    """Crée une notification in-app pour manager + collaborateur du dossier."""
    if not nouveaux:
        return
    from app import db
    from app.models import Notification
    try:
        eq = getattr(dossier, 'equipe', None)
        manager = getattr(eq, 'manager', None) if eq else None
        collab = getattr(dossier, 'collaborateur', None)
        n_ventes = sum(1 for n in nouveaux if n['type'] == 'facture_vente')
        n_achats = sum(1 for n in nouveaux if n['type'] == 'facture_achat')
        n_tx = sum(1 for n in nouveaux if n['type'] == 'transaction')
        parts = []
        if n_ventes: parts.append(f"{n_ventes} vente(s)")
        if n_achats: parts.append(f"{n_achats} achat(s)")
        if n_tx: parts.append(f"{n_tx} transaction(s)")
        resume = ' + '.join(parts)
        destinataires = set()
        if manager: destinataires.add(manager.id)
        if collab: destinataires.add(collab.id)
        for uid in destinataires:
            n = Notification(user_id=uid, message=f"🆕 Pennylane — {dossier.numero_dossier} : {resume} nouveau(x) à traiter", type_notification='pennylane')
            db.session.add(n)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning(f'notif nouveaux: {e}')


def get_dossier_pennylane_data(dossier, token: str = None) -> dict:
    from app import db
    from app.models import PennylaneItem

    token = token or getattr(dossier, 'pennylane_api_token', None) or get_pennylane_token()
    customer_id = getattr(dossier, 'pennylane_customer_id', None)
    if not token:
        return {'ok': False, 'message': 'Token non configuré.',
                'factures': [], 'factures_fournisseurs': [], 'transactions': [],
                'nouveaux': [], 'resume_nouveaux': '', 'source_token': None}

    has_dossier_token = bool(getattr(dossier, 'pennylane_api_token', None))
    result = {'ok': True, 'factures': [], 'transactions': [], 'factures_fournisseurs': [],
              'nouveaux': [], 'resume_nouveaux': '',
              'source_token': 'dossier' if has_dossier_token else 'global'}

    try:
        if has_dossier_token and not customer_id:
            try:
                me = requests.get(_api_url('me'), headers=_headers(token), timeout=15)
                if me.status_code == 200:
                    me_data = me.json() or {}
                    company = me_data.get('company') or {}
                    if company.get('id'):
                        dossier.pennylane_customer_id = str(company['id'])
                        db.session.commit()
                        customer_id = str(company['id'])
            except Exception as e:
                logger.warning(f'auto-assoc me: {e}')

        invs_params = {'limit': 100}
        if customer_id and not has_dossier_token:
            invs_params['customer_id'] = customer_id
        invs = _paginated_get('customer_invoices', params=invs_params, token=token)
        result['factures'] = [{
            'id': i.get('id'), 'numero': i.get('invoice_number') or i.get('invoice_number_formatted') or '',
            'montant_ht': i.get('total_without_tax'), 'montant_ttc': i.get('total_with_tax'),
            'statut': i.get('status') or '', 'statut_fr': traduire_statut_pl(i.get('status') or '', 'facture_vente'),
            'date': i.get('date'),
        } for i in invs]

        try:
            sinvs = _paginated_get('supplier_invoices', params={'limit': 100}, token=token)
            result['factures_fournisseurs'] = [{
                'id': s.get('id'), 'numero': s.get('invoice_number') or '',
                'montant_ttc': s.get('total_with_tax'),
                'statut': s.get('accounting_status') or '',
                'statut_fr': traduire_statut_pl(s.get('accounting_status') or '', 'facture_achat'),
                'date': s.get('date'),
            } for s in sinvs]
        except Exception as e:
            logger.warning(f'supplier_invoices: {e}')
            result['factures_fournisseurs'] = []
            sinvs = []

        try:
            txs = _paginated_get('transactions', params={'limit': 100}, token=token)
            result['transactions'] = [{
                'id': t.get('id'), 'date': t.get('transaction_date') or t.get('date'),
                'libelle': t.get('label') or '', 'montant': t.get('amount'),
                'statut': 'unaffected' if t.get('attachment_required') in (True, 'true') else 'affected',
                'statut_fr': traduire_statut_pl(
                    'unaffected' if t.get('attachment_required') in (True, 'true') else 'affected', 'transaction'),
            } for t in txs]
        except Exception as e:
            logger.warning(f'transactions: {e}')
            result['transactions'] = []
            txs = []

        # Detection nouveaux items
        nouveaux = _detecter_nouveaux_items(dossier, invs, sinvs, txs)
        if nouveaux:
            _notifier_nouveaux_items(dossier, nouveaux)
            result['nouveaux'] = nouveaux
            parts = []
            if sum(1 for n in nouveaux if n['type'] == 'facture_vente'): parts.append(f"{sum(1 for n in nouveaux if n['type'] == 'facture_vente')} vente(s)")
            if sum(1 for n in nouveaux if n['type'] == 'facture_achat'): parts.append(f"{sum(1 for n in nouveaux if n['type'] == 'facture_achat')} achat(s)")
            if sum(1 for n in nouveaux if n['type'] == 'transaction'): parts.append(f"{sum(1 for n in nouveaux if n['type'] == 'transaction')} transaction(s)")
            result['resume_nouveaux'] = ' + '.join(parts)

        # Statut de traitement : dérivé du STATUT PENNYLANE (source de vérité),
        # avec possibilité de surcharge manuelle (traite/ignore) enregistrée en DB.
        tracked = {(it.item_type, it.item_id): it for it in PennylaneItem.query.filter_by(dossier_id=dossier.id).all()}

        def _stt(item_type, iid, statut_fr):
            row = tracked.get((item_type, str(iid)))
            if row and row.statut in ('traite', 'ignore'):
                # surcharge manuelle explicite
                return row.statut, row.vu_premiere_fois
            # sinon le statut Pennylane fait foi
            if statut_fr in ('Traité', 'Avoir', 'Annulé'):
                return 'traite', (row.vu_premiere_fois if row else None)
            return 'a_traiter', (row.vu_premiere_fois if row else None)

        for f in result['factures']:
            f['statut_traitement'], f['ajout_date'] = _stt('facture_vente', f['id'], f['statut_fr'])
            f['nouveau'] = f['statut_traitement'] == 'a_traiter'
        for f in result['factures_fournisseurs']:
            f['statut_traitement'], f['ajout_date'] = _stt('facture_achat', f['id'], f['statut_fr'])
            f['nouveau'] = f['statut_traitement'] == 'a_traiter'
        for t in result['transactions']:
            t['statut_traitement'], t['ajout_date'] = _stt('transaction', t['id'], t['statut_fr'])
            t['nouveau'] = t['statut_traitement'] == 'a_traiter'
    except Exception as e:
        logger.error(f'get_dossier_pennylane_data: {e}')
        result['ok'] = False
        result['message'] = str(e)
    return result
