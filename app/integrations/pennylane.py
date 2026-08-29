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
    """Récupère le token API Pennylane depuis les settings."""
    from app.models import AppSetting
    try:
        setting = AppSetting.query.filter_by(cle='PENNYLANE_API_TOKEN').first()
        return (setting.valeur or '').strip() if setting else ''
    except Exception:
        return ''


def save_pennylane_token(token: str) -> None:
    """Enregistre le token API Pennylane (si vide → supprime)."""
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
        # Endpoint le plus léger : récupérer les infos de la société connectée
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
        # La clé de la liste varie selon l'endpoint (customer_invoices, ledger_accounts...)
        key = None
        if isinstance(data, dict):
            # Trouver la première clé qui est une liste
            for k, v in data.items():
                if isinstance(v, list):
                    key = k
                    break
        if key:
            results.extend(data.get(key, []))
        # Pagination curseur
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
    """Récupère les dernières factures clients."""
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
    """Récupère les dernières factures fournisseurs (dépenses)."""
    invoices = _paginated_get('supplier_invoices', params={'limit': limit}, token=token)
    return [{
        'id': inv.get('id'),
        'numero': inv.get('invoice_number') or '',
        'fournisseur': (inv.get('supplier') or {}).get('name', ''),
        'montant_ht': inv.get('total_without_tax'),
        'montant_ttc': inv.get('total_with_tax'),
        'statut': inv.get('status') or '',
        'date': inv.get('date'),
    } for inv in invoices]


def get_ledger_entries(token: str = None, limit: int = 50) -> list:
    """Récupère les dernières écritures comptables."""
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
    """Récupère les dernières transactions bancaires."""
    txs = _paginated_get('transactions', params={'limit': limit}, token=token)
    return [{
        'id': t.get('id'),
        'date': t.get('transaction_date') or t.get('date'),
        'libelle': t.get('label') or '',
        'montant': t.get('amount'),
        'statut': t.get('status') or '',
        'source': (t.get('source') or {}).get('label', ''),
    } for t in txs]


def get_customers(token: str = None, limit: int = 200) -> list:
    """Récupère la liste des clients (pour matcher les dossiers)."""
    customers = _paginated_get('customers', params={'limit': limit}, token=token)
    return [{
        'id': c.get('id'),
        'nom': c.get('name', ''),
        'siret': c.get('siret') or '',
        'email': c.get('email') or '',
    } for c in customers]


def sync_dossiers_pennylane(token: str = None) -> dict:
    """
    Synchronise les dossiers du cabinet avec les clients Pennylane.
    Associe chaque dossier (numéro/SIRET) à un client Pennylane si trouvé.
    """
    from app.models import Dossier
    from app import db

    token = token or get_pennylane_token()
    if not token:
        return {'ok': False, 'message': 'Token non configuré.', 'associes': 0}

    customers = get_customers(token=token)
    if not customers:
        return {'ok': False, 'message': 'Aucun client Pennylane récupéré.', 'associes': 0}

    # Index par SIRET (le plus fiable) puis par nom normalisé
    par_siret = {}
    par_nom = {}
    for c in customers:
        if c['siret']:
            par_siret[c['siret']] = c
        nom_norm = c['nom'].strip().lower()
        par_nom.setdefault(nom_norm, c)

    associes = 0
    for d in Dossier.query.all():
        found = None
        # 1) Par SIRET (champ present sur le dossier ? on utilise intitule/numero en fallback)
        # 2) Par intitule normalisé
        nom_d = (d.intitule or '').strip().lower()
        if nom_d in par_nom:
            found = par_nom[nom_d]
        if found:
            d.pennylane_customer_id = found['id']
            associes += 1

    db.session.commit()
    return {'ok': True, 'message': f'{associes} dossier(s) associé(s) à Pennylane.', 'associes': associes}




def _to_float(v):
    """Convertit une valeur API (string ou number) en float ou None."""
    if v is None or v == '':
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def traduire_statut_pl(statut_raw: str, item_type: str = 'transaction') -> str:
    """Traduit le statut brut Pennylane en français (Traité / Prétraité / À traiter).
    
    Pour les transactions (bank) : unaffected→À traiter, partially_affected→Prétraité, affected→Traité
    Pour les factures clients : draft→À traiter, to_be_sent→À traiter, sent→À traiter,
                                paid→Traité, partially_paid→Prétraité, overdue→À traiter
    Pour les factures fournisseurs : draft→À traiter, pending_approval→À traiter,
                                     approved→Traité, paid→Traité, partially_paid→Prétraité
    """
    status = (statut_raw or '').strip().lower()
    
    if not status:
        return '—'
    
    # Mapping par type
    if item_type == 'transaction':
        mapping = {
            'unaffected': 'À traiter',
            'partially_affected': 'Prétraité',
            'affected': 'Traité',
            'marked_as_unexpected': 'Marqué',
        }
        return mapping.get(status, status.replace('_', ' ').title())
    
    # Factures (client ou fournisseur)
    if item_type in ('facture_vente', 'facture_achat'):
        if status in ('paid', 'approved', 'completed'):
            return 'Traité'
        elif status in ('partially_paid', 'partially_approved'):
            return 'Prétraité'
        elif status in ('draft', 'to_be_sent', 'sent', 'pending_approval', 'pending', 'overdue', 'late', 'unpaid', 'overdue_invoice'):
            return 'À traiter'
        elif status in ('cancelled', 'void'):
            return 'Annulé'
        return status.replace('_', ' ').title()
    
    return status.replace('_', ' ').title()


def est_pl_a_traiter(statut_raw: str, item_type: str = 'transaction') -> bool:
    """Un item Pennylane nécessite-t-il une action ?
    Seuls les items À traiter ou Prétraité comptent comme 'à traiter'."""
    fr = traduire_statut_pl(statut_raw, item_type)
    return fr in ('À traiter', 'Prétraité')


def _detecter_nouveaux_items(dossier, invs, sinvs, txs) -> list:
    """
    Compare les items reçus avec la table pennylane_items.
    - Nouveau item → inséré en DB avec api_statut (statut Pennylane) + statut 'a_traiter'.
    - Item connu → mis à jour (référence/montant/statut API).
    - Seuls les items DONT le statut Pennylane est "À traiter" ou "Prétraité" sont
      retournés comme nouveaux (pas ceux déjà traités/annulés).
    Retourne la liste des nouveaux items détectés.
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
                row = PennylaneItem(
                    dossier_id=dossier.id,
                    item_type=item_type,
                    item_id=iid,
                    reference=ref[:120],
                    montant=montant,
                    date_item=date_item[:30],
                    api_statut=api_statut[:30],
                    statut='a_traiter',
                )
                db.session.add(row)
                existing[(item_type, iid)] = row
                # Ne signaler que si pas encore traité/annulé côté Pennylane
                if est_pl_a_traiter(api_statut, item_type):
                    nouveaux.append({'type': item_type, 'reference': ref, 'montant': montant, 'date': date_item,
                                     'api_statut': api_statut})
                dirty = True
            else:
                # Mise à jour douce
                if ref and row.reference != ref[:120]:
                    row.reference = ref[:120]
                    dirty = True
                if montant is not None and row.montant != montant:
                    row.montant = montant
                    dirty = True
                if api_statut and row.api_statut != api_statut[:30]:
                    row.api_statut = api_statut[:30]
                    dirty = True
                # Si l'item était "a_traiter" mais que Pennylane dit maintenant "traité",
                # l'auto-marquer comme traité (le statut API fait foi)
                if row.statut == 'a_traiter' and api_statut and not est_pl_a_traiter(api_statut, item_type):
                    row.statut = 'traite'
                    dirty = True

    _process('facture_vente', invs, ('invoice_number', 'invoice_number_formatted'), 'total_with_tax', ('date',))
    _process('facture_achat', sinvs, ('invoice_number',), 'total_with_tax', ('date',))
    _process('transaction', txs, ('label',), 'amount', ('transaction_date', 'date'))

    if dirty:
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.warning(f'commit pennylane_items: {e}')
    return nouveaux


def _notifier_nouveaux_items(dossier, nouveaux: list):
    """Crée une notification in-app (et email léger) pour manager + collaborateur du dossier."""
    if not nouveaux:
        return
    from app import db
    from app.models import Notification

    try:
        eq = getattr(dossier, 'equipe', None)
        manager = getattr(eq, 'manager', None) if eq else None
        collab = getattr(dossier, 'collaborateur', None)
        type_label = {'facture_vente': 'Facture de vente', 'facture_achat': "Facture d'achat",
                      'transaction': 'Transaction bancaire'}
        n_ventes = sum(1 for n in nouveaux if n['type'] == 'facture_vente')
        n_achats = sum(1 for n in nouveaux if n['type'] == 'facture_achat')
        n_tx = sum(1 for n in nouveaux if n['type'] == 'transaction')
        parts = []
        if n_ventes:
            parts.append(f"{n_ventes} facture(s) de vente")
        if n_achats:
            parts.append(f"{n_achats} facture(s) d'achat")
        if n_tx:
            parts.append(f"{n_tx} transaction(s) bancaire(s)")
        resume = ' + '.join(parts)

        # Une notification résumée par destinataire (évite le spam)
        destinataires = set()
        if manager:
            destinataires.add(manager.id)
        if collab:
            destinataires.add(collab.id)
        for uid in destinataires:
            notif = Notification(
                user_id=uid,
                message=f"🆕 Pennylane — {dossier.numero_dossier} ({dossier.intitule[:30]}) : {resume} nouveau(x) à traiter",
                type_notification='pennylane'
            )
            db.session.add(notif)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning(f'notifications nouveaux items: {e}')


def get_dossier_pennylane_data(dossier, token: str = None) -> dict:
    """
    Récupère les données Pennylane associées à un dossier du cabinet
    (factures clients/fournisseurs, transactions, écritures) et DÉTECTE
    les nouveaux items (factures achats/ventes, transactions bancaires).

    Deux cas :
    - Le dossier a son propre token (Company API) : on liste TOUT directement.
    - Sinon token global (Firm API) filtré par customer_id.
    """
    from app import db
    from app.models import PennylaneItem

    token = token or getattr(dossier, 'pennylane_api_token', None) or get_pennylane_token()
    customer_id = getattr(dossier, 'pennylane_customer_id', None)
    if not token:
        return {'ok': False, 'message': 'Token non configuré pour ce dossier ni globalement.',
                'factures': [], 'factures_fournisseurs': [], 'ecritures': [], 'transactions': [],
                'nouveaux': [], 'resume_nouveaux': '', 'source_token': None}

    has_dossier_token = bool(getattr(dossier, 'pennylane_api_token', None))
    result = {'ok': True, 'factures': [], 'ecritures': [], 'transactions': [],
              'factures_fournisseurs': [], 'nouveaux': [], 'resume_nouveaux': '',
              'source_token': 'dossier' if has_dossier_token else 'global'}

    try:
        # 1) Auto-associer la société si token par dossier et pas de customer_id
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

        # 2) Factures clients (ventes)
        invs_params = {'limit': 100}
        if customer_id and not has_dossier_token:
            invs_params['customer_id'] = customer_id
        invs = _paginated_get('customer_invoices', params=invs_params, token=token)
        result['factures'] = [{
            'id': i.get('id'),
            'numero': i.get('invoice_number') or i.get('invoice_number_formatted') or '',
            'montant_ht': i.get('total_without_tax'),
            'montant_ttc': i.get('total_with_tax'),
            'statut': i.get('status') or '',
            'statut_fr': traduire_statut_pl(i.get('status') or '', 'facture_vente'),
            'date': i.get('date'),
        } for i in invs]

        # 3) Factures fournisseurs (achats)
        try:
            sinvs = _paginated_get('supplier_invoices', params={'limit': 100}, token=token)
            result['factures_fournisseurs'] = [{
                'id': s.get('id'),
                'numero': s.get('invoice_number') or '',
                'montant_ttc': s.get('total_with_tax'),
                'statut': s.get('status') or '',
                'statut_fr': traduire_statut_pl(s.get('status') or '', 'facture_achat'),
                'date': s.get('date'),
            } for s in sinvs]
        except Exception as e:
            logger.warning(f'supplier_invoices: {e}')
            result['factures_fournisseurs'] = []
            sinvs = []

        # 4) Transactions bancaires
        try:
            txs = _paginated_get('transactions', params={'limit': 100}, token=token)
            result['transactions'] = [{
                'id': t.get('id'),
                'date': t.get('transaction_date') or t.get('date'),
                'libelle': t.get('label') or '',
                'montant': t.get('amount'),
                'statut': t.get('status') or '',
                'statut_fr': traduire_statut_pl(t.get('status') or '', 'transaction'),
            } for t in txs]
        except Exception as e:
            logger.warning(f'transactions: {e}')
            result['transactions'] = []
            txs = []

        # 6) DÉTECTION des nouveaux items (facture_vente / facture_achat / transaction)
        nouveaux = _detecter_nouveaux_items(dossier, invs, sinvs, txs)
        if nouveaux:
            _notifier_nouveaux_items(dossier, nouveaux)
            result['nouveaux'] = nouveaux
            n_ventes = sum(1 for n in nouveaux if n['type'] == 'facture_vente')
            n_achats = sum(1 for n in nouveaux if n['type'] == 'facture_achat')
            n_tx = sum(1 for n in nouveaux if n['type'] == 'transaction')
            parts = []
            if n_ventes:
                parts.append(f"{n_ventes} vente(s)")
            if n_achats:
                parts.append(f"{n_achats} achat(s)")
            if n_tx:
                parts.append(f"{n_tx} transaction(s)")
            result['resume_nouveaux'] = ' + '.join(parts)

        # 7) Statuts de traitement par item (depuis pennylane_items)
        tracked = {(it.item_type, it.item_id): it
                   for it in PennylaneItem.query.filter_by(dossier_id=dossier.id).all()}

        def _stt(item_type, iid):
            row = tracked.get((item_type, str(iid)))
            return row.statut if row else 'a_traiter'

        def _is_new(item_type, iid, numero):
            row = tracked.get((item_type, str(iid)))
            if not row:
                return False
            return any(n['type'] == item_type and (n['reference'] == numero)
                       for n in result['nouveaux'])

        def _stt_full(item_type, iid):
            row = tracked.get((item_type, str(iid)))
            if not row:
                return 'a_traiter', None
            return row.statut, row.vu_premiere_fois

        for f in result['factures']:
            f['statut_traitement'], f['ajout_date'] = _stt_full('facture_vente', f['id'])
            f['nouveau'] = _is_new('facture_vente', f['id'], f['numero'])
        for f in result['factures_fournisseurs']:
            f['statut_traitement'], f['ajout_date'] = _stt_full('facture_achat', f['id'])
            f['nouveau'] = _is_new('facture_achat', f['id'], f['numero'])
        for t in result['transactions']:
            t['statut_traitement'], t['ajout_date'] = _stt_full('transaction', t['id'])
            t['nouveau'] = _is_new('transaction', t['id'], t['libelle'])

    except Exception as e:
        logger.error(f'get_dossier_pennylane_data: {e}')
        result['ok'] = False
        result['message'] = str(e)
    return result
