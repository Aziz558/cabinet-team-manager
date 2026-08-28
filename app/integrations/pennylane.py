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


def get_dossier_pennylane_data(dossier, token: str = None) -> dict:
    """
    Récupère les données Pennylane associées à un dossier du cabinet
    (factures clients/fournisseurs, transactions, écritures).

    Deux cas :
    - Le dossier a son propre token (Company API d'une société) : on liste
      TOUT directement (le token est déjà lié à cette société, pas besoin de filtre).
    - Sinon on utilise le token global (Firm API) en filtrant par customer_id.
    """
    from app.models import Dossier
    from app import db

    token = token or getattr(dossier, 'pennylane_api_token', None) or get_pennylane_token()
    customer_id = getattr(dossier, 'pennylane_customer_id', None)
    if not token:
        return {'ok': False, 'message': 'Token non configuré pour ce dossier ni globalement.', 'factures': [], 'ecritures': [], 'transactions': []}

    has_dossier_token = bool(getattr(dossier, 'pennylane_api_token', None))
    result = {'ok': True, 'factures': [], 'ecritures': [], 'transactions': [], 'source_token': 'dossier' if has_dossier_token else 'global'}

    try:
        # 1) Auto-associer la société si on a un token par dossier et pas encore de customer_id
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

        # 2) Factures clients
        invs_params = {'limit': 50}
        if customer_id and not has_dossier_token:
            invs_params['customer_id'] = customer_id
        invs = _paginated_get('customer_invoices', params=invs_params, token=token)
        result['factures'] = [{
            'numero': i.get('invoice_number') or i.get('invoice_number_formatted') or '',
            'montant_ht': i.get('total_without_tax'),
            'montant_ttc': i.get('total_with_tax'),
            'statut': i.get('status') or '',
            'date': i.get('date'),
        } for i in invs]

        # 3) Factures fournisseurs (dépenses)
        try:
            sinvs = _paginated_get('supplier_invoices', params={'limit': 50}, token=token)
            result['factures_fournisseurs'] = [{
                'numero': s.get('invoice_number') or '',
                'montant_ttc': s.get('total_with_tax'),
                'statut': s.get('status') or '',
                'date': s.get('date'),
            } for s in sinvs]
        except Exception:
            result['factures_fournisseurs'] = []

        # 4) Transactions bancaires
        try:
            txs = _paginated_get('transactions', params={'limit': 30}, token=token)
            result['transactions'] = [{
                'date': t.get('transaction_date') or t.get('date'),
                'libelle': t.get('label') or '',
                'montant': t.get('amount'),
                'statut': t.get('status') or '',
            } for t in txs]
        except Exception:
            result['transactions'] = []

        # 5) Écritures comptables
        try:
            entries = _paginated_get('ledger_entries', params={'limit': 30}, token=token)
            result['ecritures'] = [{
                'date': e.get('date'),
                'libelle': e.get('label') or '',
                'montant_debit': e.get('amount') if (e.get('direction') or '').lower() == 'debit' else 0,
                'montant_credit': e.get('amount') if (e.get('direction') or '').lower() == 'credit' else 0,
            } for e in entries]
        except Exception:
            result['ecritures'] = []

    except Exception as e:
        logger.error(f'get_dossier_pennylane_data: {e}')
        result['ok'] = False
        result['message'] = str(e)
    return result
