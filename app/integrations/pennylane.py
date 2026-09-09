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
import time
import json as _json
from datetime import datetime, date

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache DB partagé (TTL 5 min) — Render tourne avec plusieurs workers : un
# cache mémoire serait vide 3 fois sur 4. On stocke le résultat JSON sérialisé
# dans AppSetting (partagé par tous les workers) + stale-while-revalidate :
# la page est servie IMMÉDIATEMENT depuis le cache, l'API est rafraîchie en
# arrière-plan quand le cache expire.
# ---------------------------------------------------------------------------
_CACHE_TTL = 300     # secondes
_BG_REFRESH = set()  # dossiers en cours de rafraîchissement arrière-plan
_MEM = {}            # mini cache mémoire par worker (évite re-désérialiser)


def _cache_key(dossier_id):
    # V2 : change de préfixe pour ABANDONNER le cache empoisonné par l'ancien
    # code (montants vides, listes non filtrées) dès le déploiement du fix.
    return f'PL_CACHE_V2_{dossier_id}'


def _cache_load(dossier_id):
    """Renvoie (result_dict, is_fresh) ou (None, False)."""
    if dossier_id in _MEM:
        ts, res = _MEM[dossier_id]
        return res, (time.time() - ts <= _CACHE_TTL)
    from app.models import AppSetting
    import json as _json
    try:
        s = AppSetting.query.filter_by(cle=_cache_key(dossier_id)).first()
        if not s or not s.valeur:
            return None, False
        payload = _json.loads(s.valeur)
        res = payload.get('data')
        if not isinstance(res, dict):
            return None, False
        fresh = (time.time() - payload.get('ts', 0)) <= _CACHE_TTL
        _MEM[dossier_id] = (payload.get('ts', 0), res)
        return res, fresh
    except Exception as e:
        logger.warning(f'cache load {dossier_id}: {e}')
        return None, False


def _cache_save(dossier_id, res):
    from app import db
    from app.models import AppSetting
    import json as _json
    try:
        payload = _json.dumps({'ts': time.time(), 'data': res}, ensure_ascii=False, separators=(',', ':'), default=str)
        s = AppSetting.query.filter_by(cle=_cache_key(dossier_id)).first()
        if not s:
            s = AppSetting(cle=_cache_key(dossier_id), valeur=payload, type_valeur='json', service='pennylane')
            db.session.add(s)
        else:
            s.valeur = payload
        db.session.commit()
        _MEM[dossier_id] = (time.time(), res)
    except Exception as e:
        logger.warning(f'cache save {dossier_id}: {e}')
        try:
            db.session.rollback()
        except Exception:
            pass


def invalidate_dossier_cache(dossier_id):
    """Force le rechargement API au prochain accès (ex: après action utilisateur)."""
    _MEM.pop(dossier_id, None)
    from app import db
    from app.models import AppSetting
    try:
        s = AppSetting.query.filter_by(cle=_cache_key(dossier_id)).first()
        if s:
            db.session.delete(s)
            db.session.commit()
    except Exception as e:
        logger.warning(f'cache invalidate {dossier_id}: {e}')
        try:
            db.session.rollback()
        except Exception:
            pass


def _refresh_in_background(dossier_id):
    """Lance (au plus 1 par dossier/worker) un thread qui rafraîchit le cache via l'API."""
    if dossier_id in _BG_REFRESH:
        return
    _BG_REFRESH.add(dossier_id)

    def _work():
        from app import app as flask_app
        from app.models import Dossier as _D
        try:
            with flask_app.app_context():
                d = _D.query.get(dossier_id)
                if d is not None:
                    get_dossier_pennylane_data(d, force_refresh=True)
        except Exception as e:
            logger.warning(f'bg refresh {dossier_id}: {e}')
        finally:
            _BG_REFRESH.discard(dossier_id)

    import threading
    threading.Thread(target=_work, daemon=True).start()


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


def _paginated_get(path: str, params: dict = None, token: str = None, max_pages: int = 60) -> list:
    """Récupère tous les éléments d'un endpoint paginé (cursor-based)."""
    token = token or get_pennylane_token()
    if not token:
        return []
    params = dict(params or {})
    results = []
    for _ in range(max_pages):
        resp = None
        for attempt in range(3):  # retry sur 429/5xx (erreur silencieuse = données tronquées)
            try:
                resp = requests.get(_api_url(path), headers=_headers(token), params=params, timeout=20)
            except Exception as e:
                logger.error(f'Pennylane GET {path}: {e}')
                break
            if resp.status_code == 200:
                break
            if resp.status_code == 429 or resp.status_code >= 500:
                import time as _time
                _time.sleep(2 * (attempt + 1))
                continue
            break
        if resp is None or resp.status_code != 200:
            logger.warning(f'Pennylane GET {path} -> {getattr(resp, "status_code", "?")}: '
                           f'{getattr(resp, "text", "")[:200]}')
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
        # Pagination : Pennylane renvoie `has_more` + `next_cursor` au niveau RACINE
        next_cursor = None
        if isinstance(data, dict):
            pagination = data.get('pagination') or {}
            next_cursor = pagination.get('next_cursor') or data.get('next_cursor')
            has_more = data.get('has_more')
            if has_more is False:
                next_cursor = None
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


def list_companies(token: str = None) -> list:
    """Liste les companies (dossiers) visibles par ce token via l'API externe v2."""
    return _paginated_get('companies', params={'limit': 100}, token=token)


def _norm_name(s) -> str:
    """Normalise un nom pour le matching : minuscules, sans accents/ponctuation."""
    import re as _re
    import unicodedata as _ud
    s = (s or '').strip().lower()
    s = _ud.normalize('NFKD', s)
    s = ''.join(c for c in s if not _ud.combining(c))
    s = _re.sub(r'[^a-z0-9]+', ' ', s).strip()
    return s


def resolve_company_for_dossier(dossier, token: str = None) -> dict:
    """Retrouve AUTOMATIQUEMENT le company ID Pennylane d'un dossier.

    Ordre de résolution :
      1. token du dossier -> GET /companies -> match par nom (exact puis inclusif)
      2. token du dossier -> si /companies renvoie UNE seule company -> la prendre
         (token dédié au dossier = cette company)
      3. token du dossier -> GET /me -> company.id (token rattaché à une company)
      4. token global du cabinet -> GET /companies -> match par nom
    Ne logge JAMAIS le token.
    Retour : {'ok', 'company_id', 'company_name', 'via', 'message'}
    """
    tok_dossier = (getattr(dossier, 'pennylane_api_token', None) or '').strip()
    token = (token or tok_dossier or get_pennylane_token()).strip()
    if not token:
        return {'ok': False, 'message': 'Aucun token API (ni sur le dossier, ni global).'}

    nom_d = _norm_name(getattr(dossier, 'intitule', ''))
    num_d = _norm_name(getattr(dossier, 'numero_dossier', ''))

    def _match(companies):
        for c in companies:  # 1. match exact sur l'intitulé
            if nom_d and _norm_name(c.get('name')) == nom_d:
                return c
        for c in companies:  # 2. inclusion : "dms permis" dans "dms permis sarl"
            cn = _norm_name(c.get('name'))
            if nom_d and (nom_d in cn or cn in nom_d):
                return c
        for c in companies:  # 3. numéro de dossier (ex. "DMS PERMIS")
            cn = _norm_name(c.get('name'))
            if num_d and (cn == num_d or num_d in cn):
                return c
        return None

    dedicated = bool(tok_dossier) and token == tok_dossier
    companies = []
    try:
        companies = list_companies(token=token)
    except Exception as e:
        logger.warning(f'list_companies failed: {e}')

    if companies:
        c = _match(companies)
        if c:
            return {'ok': True, 'company_id': str(c.get('id')), 'company_name': c.get('name'),
                    'via': 'companies:match'}
        if dedicated and len(companies) == 1:
            c = companies[0]
            return {'ok': True, 'company_id': str(c.get('id')), 'company_name': c.get('name'),
                    'via': 'companies:unique'}

    # Fallback GET /me : token rattaché à une seule company
    try:
        resp = requests.get(_api_url('me'), headers=_headers(token), timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            comp = data.get('company', {}) if isinstance(data, dict) else {}
            cid = comp.get('id')
            if cid:
                return {'ok': True, 'company_id': str(cid), 'company_name': comp.get('name'),
                        'via': 'me'}
            u = data.get('user') or {}
            if u.get('company_id'):
                return {'ok': True, 'company_id': str(u['company_id']),
                        'company_name': u.get('company_name'), 'via': 'me:user'}
        elif resp.status_code == 401:
            return {'ok': False, 'message': 'Token invalide (401 Unauthorized).'}
    except Exception as e:
        logger.warning(f'/me fallback failed: {e}')

    if companies:
        return {'ok': False,
                'message': f'Company introuvable parmi {len(companies)} (match par nom échoué).'}
    return {'ok': False, 'message': 'Aucune company accessible avec ce token (vérifiez le token et ses scopes).'}


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


def _pl_montant(d: dict, *keys):
    """Premier montant numérique trouvé parmi les champs donnés.

    L'API v2 Pennylane renvoie les montants TTC dans `amount` (les champs
    total_with_tax/total_without_tax n'existent pas ou sont vides selon
    l'endpoint) — on teste plusieurs noms pour rester robuste.
    """
    for k in keys:
        f = _to_float(d.get(k))
        if f is not None:
            return f
    return None


def traduire_statut_pl(statut_raw: str, item_type: str = 'facture_vente') -> str:
    """Traduit le statut brut Pennylane en français (Traité / À traiter / Archivé).

    3 statuts uniquement (décision métier 2026-09) : À traiter, Traité, Archivé.
    L'ancien statut "Pré-traité" est supprimé et compté comme "À traiter".

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
            'partially_affected': 'À traiter',
            'affected': 'Traité',
            'marked_as_unexpected': 'Marqué',
        }
        return mapping.get(status, status.replace('_', ' ').title())

    # Factures clients (ventes)
    # IMPORTANT : sur Pennylane, le statut "Traitée" = facture comptabilisée (ledger_entry).
    # Le champ API `status` est un statut de cycle de vie (paid/late/archived...).
    # Seule `incomplete` = À traiter ; TOUT le reste des factures actives = Traité.
    if item_type == 'facture_vente':
        if status == 'archived':
            return 'Archivé'
        if status == 'incomplete':
            return 'À traiter'
        elif status in ('draft', 'to_be_sent', 'sent', 'pending', 'overdue_invoice'):
            return 'À traiter'
        # paid, late, upcoming, credit_note, partially_paid, completed, cancelled, void, refunded
        # → toutes considérées comme TRAITÉES (factures comptabilisées)
        return 'Traité'

    # Factures fournisseurs (achats) — champ `accounting_status`
    if item_type == 'facture_achat':
        if status == 'archived':
            return 'Archivé'
        elif status in ('complete', 'paid', 'approved', 'affected'):
            return 'Traité'
        elif status in ('validation_needed', 'to_be_processed', 'pending_approval',
                        'draft', 'pending', 'unpaid', 'unaffected'):
            return 'À traiter'
        elif status in ('cancelled', 'void'):
            return 'Annulé'
        return status.replace('_', ' ').title()

    return status.replace('_', ' ').title()


def est_pl_traite(statut_raw: str, item_type: str = 'facture_vente') -> bool:
    """Un item est-il explicitement marqué comme traité côté Pennylane ?"""
    fr = traduire_statut_pl(statut_raw, item_type)
    return fr in ('Traité', 'Avoir', 'Archivé')


def est_pl_a_traiter(statut_raw: str, item_type: str = 'facture_vente') -> bool:
    """Un item nécessite-t-il une action ?
    Retourne True pour À traiter (y compris ex-Prétraité) ou statut inconnu (sécurité : on prévient par défaut)."""
    fr = traduire_statut_pl(statut_raw, item_type)
    if fr == '—':
        return True  # statut inconnu = à traiter par sécurité
    return fr == 'À traiter'

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
    """Notifie manager + collaborateur du dossier : notification in-app + EMAIL.

    L'email (Brevo) est un bonus : s'il échoue, la notification in-app reste
    créée et le flux de synchronisation n'est jamais interrompu.
    """
    if not nouveaux:
        return
    from app import db
    from app.models import Notification
    eq = getattr(dossier, 'equipe', None)
    manager = getattr(eq, 'manager', None) if eq else None
    collab = getattr(dossier, 'collaborateur', None)
    destinataires = set()
    if manager: destinataires.add(manager.id)
    if collab: destinataires.add(collab.id)
    try:
        n_ventes = sum(1 for n in nouveaux if n['type'] == 'facture_vente')
        n_achats = sum(1 for n in nouveaux if n['type'] == 'facture_achat')
        n_tx = sum(1 for n in nouveaux if n['type'] == 'transaction')
        parts = []
        if n_ventes: parts.append(f"{n_ventes} vente(s)")
        if n_achats: parts.append(f"{n_achats} achat(s)")
        if n_tx: parts.append(f"{n_tx} transaction(s)")
        resume = ' + '.join(parts)
        for uid in destinataires:
            n = Notification(user_id=uid, message=f"🆕 Pennylane — {dossier.numero_dossier} : {resume} nouveau(x) à traiter", type_notification='pennylane')
            db.session.add(n)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning(f'notif nouveaux: {e}')

    # Email Brevo (best-effort, jamais bloquant)
    try:
        from app.integrations.brevo import send_pennylane_new_docs_email_brevo
        for uid in destinataires:
            try:
                send_pennylane_new_docs_email_brevo(dossier, nouveaux, uid)
            except Exception as e:
                logger.warning(f'email nouveauxPennylane user {uid}: {e}')
    except Exception as e:
        logger.warning(f'email nouveaux (import brevo): {e}')


def get_dossier_pennylane_data(dossier, token: str = None, force_refresh: bool = False) -> dict:
    from app import db
    from app.models import PennylaneItem

    # Stale-while-revalidate : servir le cache IMMÉDIATEMENT (même expiré),
    # rafraîchir en arrière-plan si expiré. Page toujours rapide.
    if not force_refresh and token is None:
        cached, fresh = _cache_load(dossier.id)
        if cached is not None:
            if not fresh:
                _refresh_in_background(dossier.id)
            return cached

    tok_dossier = (getattr(dossier, 'pennylane_api_token', None) or '').strip()
    token = (token or tok_dossier or get_pennylane_token()).strip()
    customer_id = getattr(dossier, 'pennylane_customer_id', None)
    if not token:
        return {'ok': False, 'message': 'Token non configuré.',
                'factures': [], 'factures_fournisseurs': [], 'transactions': [],
                'nouveaux': [], 'resume_nouveaux': '', 'source_token': None}

    has_dossier_token = bool(tok_dossier)
    # Garde-fou : si un token de dossier est posé mais ne couvre PAS la company
    # liée (ex. Pro Store relié à la company du vrai Pro Store alors que le token
    # du dossier appartient à une autre société), l'API ignore silencieusement le
    # filtre company_id et renvoie les données de la MAUVAISE société. On détecte
    # le mismatch et on bascule sur le token global du cabinet.
    # (source : incident PROST 09.09.2026 — données Impermisol sur le dossier Pro Store)
    if has_dossier_token and customer_id:
        try:
            covered = {str(c.get('id')) for c in list_companies(token=token)}
            if covered and str(customer_id).strip() not in covered:
                global_tok = get_pennylane_token()
                if global_tok and global_tok != token:
                    logger.warning(
                        f'dossier {dossier.id}: token dédié ne couvre pas la company '
                        f'{customer_id} -> bascule sur le token global du cabinet')
                    token = global_tok
                    has_dossier_token = False
        except Exception as e:
            logger.warning(f'dossier {dossier.id}: vérif couverture token: {e}')
    result = {'ok': True, 'factures': [], 'transactions': [], 'factures_fournisseurs': [],
              'nouveaux': [], 'resume_nouveaux': '',
              'source_token': 'dossier' if has_dossier_token else 'global'}

    try:
        # Auto-résolution du company_id si absent : même mécanisme que la synchro
        # checklist (list_companies + match nom + fallback /me) — cf. demande Aziz :
        # "dès que j'ajoute l'API au dossier, tout se branche tout seul".
        if has_dossier_token and not customer_id:
            try:
                res_auto = resolve_company_for_dossier(dossier, token=token)
                if res_auto.get('ok'):
                    dossier.pennylane_customer_id = str(res_auto['company_id'])
                    db.session.commit()
                    customer_id = str(res_auto['company_id'])
                    logger.info(f"auto-assoc dossier {dossier.id} -> company "
                                f"{customer_id} via {res_auto.get('via')}")
            except Exception as e:
                logger.warning(f'auto-assoc dossier {dossier.id}: {e}')

        invs_params = {'limit': 100}
        if customer_id:
            # API v2 : filtre par COMPANY du dossier (customer_id v2 = le CLIENT, pas le dossier)
            invs_params['company_id'] = customer_id
        invs = _paginated_get('customer_invoices', params=invs_params, token=token)
        result['factures'] = [{
            'id': i.get('id'), 'numero': i.get('invoice_number') or i.get('invoice_number_formatted') or '',
            'montant_ht': _pl_montant(i, 'total_without_tax', 'amount_without_tax', 'amount_ht'),
            'montant_ttc': _pl_montant(i, 'total_with_tax', 'amount', 'amount_with_tax', 'amount_ttc'),
            'statut': i.get('status') or '', 'statut_fr': traduire_statut_pl(i.get('status') or '', 'facture_vente'),
            'date': i.get('date'),
        } for i in invs]

        try:
            sinvs_params = {'limit': 100}
            if customer_id:
                sinvs_params['company_id'] = customer_id
            sinvs = _paginated_get('supplier_invoices', params=sinvs_params, token=token)
            result['factures_fournisseurs'] = [{
                'id': s.get('id'), 'numero': s.get('invoice_number') or s.get('supplier_invoice_number') or s.get('reference') or '',
                'montant_ttc': _pl_montant(s, 'total_with_tax', 'amount', 'amount_with_tax'),
                'statut': s.get('accounting_status') or '',
                'statut_fr': traduire_statut_pl(s.get('accounting_status') or '', 'facture_achat'),
                'date': s.get('date'),
            } for s in sinvs]
        except Exception as e:
            logger.warning(f'supplier_invoices: {e}')
            result['factures_fournisseurs'] = []
            sinvs = []

        try:
            txs_params = {'limit': 100}
            if customer_id:
                txs_params['company_id'] = customer_id
            txs = _paginated_get('transactions', params=txs_params, token=token)
            result['transactions'] = [{
                'id': t.get('id'), 'date': t.get('transaction_date') or t.get('date'),
                'libelle': t.get('label') or '', 'montant': _pl_montant(t, 'amount', 'amount_with_tax', 'value'),
                # Statut Pennylane réel : une transaction est TRAITÉE quand elle est
                # catégorisée/comptabilisée (liste `categories` non vide), À TRAITER
                # sinon. NB: `matched_invoices` est toujours {'url': ...} (même sans
                # rapprochement) -> inutilisable ; `attachment_required` (justificatif)
                # n'est PAS un critère de traitement — source : comparaison compteurs
                # UI Pennylane vs app (Pro Store : 152 à traiter / 999+ traitées).
                'statut': 'affected' if (t.get('categories') or []) else 'unaffected',
                'statut_fr': traduire_statut_pl(
                    'affected' if (t.get('categories') or []) else 'unaffected',
                    'transaction'),
            } for t in txs]
        except Exception as e:
            logger.warning(f'transactions: {e}')
            result['transactions'] = []
            txs = []

        # Detection nouveaux items
        nouveaux = _detecter_nouveaux_items(dossier, invs, sinvs, txs)
        # SONDE TEMPORAIRE (diagnostic compteurs) — à retirer après diagnostic
        try:
            # --- txs : distribution des valeurs BRUTES des champs candidats ---
            def _zero(v):
                try:
                    return abs(float(v)) < 0.005
                except (TypeError, ValueError):
                    return False
            from collections import Counter as _C
            txs_stat = {
                'total': len(txs),
                'cat_nonvide': sum(1 for t in txs if (t.get('categories') or [])),
                'uncat_outstanding_zero': sum(1 for t in txs
                                              if not (t.get('categories') or [])
                                              and _zero(t.get('outstanding_balance'))),
                'uncat_outstanding_nz': sum(1 for t in txs
                                            if not (t.get('categories') or [])
                                            and not _zero(t.get('outstanding_balance'))),
                'cat_outstanding_zero': sum(1 for t in txs
                                            if (t.get('categories') or [])
                                            and _zero(t.get('outstanding_balance'))),
                'att_true': sum(1 for t in txs if t.get('attachment_required') is True),
                'att_false': sum(1 for t in txs if t.get('attachment_required') is False),
            }
            # --- ventes : années + statuts, + marche pagination brute (meta) ---
            ventes_par_an = _C((i.get('date') or '????')[:4] for i in invs)
            ventes_draft = sum(1 for i in invs if i.get('draft') is True)
            pages_meta = []
            try:
                tok2 = token
                p2 = {'limit': 100}
                if customer_id:
                    p2['company_id'] = customer_id
                for _p in range(12):
                    rr = requests.get(_api_url('customer_invoices'),
                                      headers=_headers(tok2), params=p2, timeout=20)
                    if rr.status_code != 200:
                        pages_meta.append(f'HTTP{rr.status_code}')
                        break
                    dd = rr.json()
                    kk = next((k for k, v in dd.items() if isinstance(v, list)), None)
                    pages_meta.append(len(dd.get(kk) or []))
                    pg = dd.get('pagination') or {}
                    nc = pg.get('next_cursor') or dd.get('next_cursor')
                    if dd.get('has_more') is False:
                        pages_meta.append(f'has_more=False meta={_json.dumps(pg)[:120]}')
                        break
                    if not nc:
                        pages_meta.append(f'no_cursor meta={_json.dumps(pg)[:120]}')
                        break
                    p2['cursor'] = nc
            except Exception as _e:
                pages_meta.append(f'ERR {_e}')
            # --- brouillons (endpoint separe) + matched_invoices reel ---
            drafts_count = None
            try:
                p3 = {'limit': 1}
                if customer_id:
                    p3['company_id'] = customer_id
                rr = requests.get(_api_url('customer_invoice_drafts'),
                                  headers=_headers(token), params=p3, timeout=20)
                if rr.status_code == 200:
                    dd3 = rr.json()
                    pg3 = dd3.get('pagination') or {}
                    drafts_count = {'nb_page': len(dd3.get('customer_invoice_drafts') or []),
                                    'meta': {k: v for k, v in pg3.items()
                                             if 'total' in str(k).lower() or 'count' in str(k).lower()}
                                    or _json.dumps(pg3)[:200]}
                else:
                    drafts_count = f'HTTP{rr.status_code}'
            except Exception as _e:
                drafts_count = f'ERR {_e}'
            mi = []
            for t in txs:
                mv = t.get('matched_invoices')
                mi.append(type(mv).__name__ if mv is None else
                          ('dict:' + ','.join(sorted(mv.keys())) if isinstance(mv, dict)
                           else f'{type(mv).__name__}:{len(mv)}'))
            mi_stat = _C(mi).most_common(6)
            # echantillon matched_invoices non vide (dict avec cle de liste ?)
            sample_mi = None
            for t in txs:
                mv = t.get('matched_invoices')
                if isinstance(mv, dict):
                    interesting = {k: v for k, v in mv.items() if not isinstance(v, dict)}
                    if interesting:
                        sample_mi = interesting
                        break
            result['debug_probe'] = {
                'counts': {'ventes': len(invs), 'achats': len(sinvs), 'txs': len(txs)},
                'txs_stat': txs_stat,
                'ventes_par_an': dict(ventes_par_an),
                'ventes_draft_true': ventes_draft,
                'ventes_ledger_nonnull': sum(1 for i in invs if i.get('ledger_entry')),
                'pages_meta': pages_meta,
                'drafts_endpoint': drafts_count,
                'matched_invoices_shapes': dict(mi_stat),
                'sample_mi': sample_mi,
            }
            # --- SCRAPING UI PENNYLANE (memes cookies que vat_forms) ---
            ui = {}
            try:
                from app.integrations import pennylane_web as _plw
                _plw._load_from_db()
                _ck = _plw._parse_cookie_header(_plw._pl_session_cookies or '')
                _hd = {'accept': 'text/html,application/xhtml+xml',
                       'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                       'x-reseller': 'pennylane'}
                for label, path in (('ventes', f'/companies/{customer_id}/sales/invoices'),
                                    ('banque', f'/companies/{customer_id}/bank_accounts'),
                                    ('achats', f'/companies/{customer_id}/purchases/supplier_invoices')):
                    try:
                        ru = requests.get('https://app.pennylane.com' + path,
                                          headers=_hd, cookies=_ck, timeout=25)
                        body = ru.text or ''
                        ui[label] = {
                            'http': ru.status_code, 'len': len(body),
                            # cherche les compteurs connus dans la page
                            'hits_778': body.count('778'), 'hits_559': body.count('559'),
                            'hits_152': body.count('152'),
                        }
                    except Exception as _e2:
                        ui[label] = {'err': str(_e2)[:100]}
            except Exception as _e:
                ui['err'] = str(_e)[:150]
            result['debug_probe']['ui'] = ui
        except Exception as e:
            result['debug_probe'] = {'err': f'probe failed: {e}'}
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

        # Mise en cache du résultat (partagé entre workers)
        # NB: token a été réassigné plus haut, il n'est jamais None ici -> cache inconditionnel
        _cache_save(dossier.id, result)
    except Exception as e:
        logger.error(f'get_dossier_pennylane_data: {e}')
        result['ok'] = False
        result['message'] = str(e)
    return result
