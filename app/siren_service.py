# -*- coding: utf-8 -*-
"""Extraction automatique des infos d'une entreprise depuis son SIREN.

Source : API publique officielle de l'Etat francais
(https://recherche-entreprises.api.gouv.fr) qui agrege INSEE + RNE/greffes
(les donnees affichees sur Infogreffe) + dirigeants. Sans cle API, gratuit.

On ne scrape PAS infogreffe.fr (CGU + fragilite) : cette API renvoie les memes
informations officielles, de facon stable et legale.
"""
from __future__ import annotations

import re
import requests

API_URL = "https://recherche-entreprises.api.gouv.fr/search"
_TIMEOUT = 12
_CACHE = {}  # siren -> resultat (evite de rappeler l'API au clic repete)

# code nature juridique (INSEE) -> libelle court
_NATURE = {
    '1000': 'Entreprise individuelle', '5202': 'SNC', '5306': "Société d'exercice libéral",
    '5410': 'SARL', '5412': 'SARL', '5415': 'SARL', '5499': 'SARL',
    '5411': "SARL unipersonnelle", '5498': 'SARL',
    '5430': "Société en commandite simple", '5440': "Société en commandite par actions",
    '5505': 'SA', '5510': 'SA', '5599': 'SA',
    '5600': 'Association déclarée', '5710': 'Société civile',
    '6220': "GIE", '6500': "Société étrangère",
    '5479': 'SCI', '5478': 'SCI', '6544': 'SCI',
    '5496': "Société civile de moyens",
}

# tranches effectif INSEE -> libellé lisible
_EFFECTIFS = {
    'NN': 'Non renseigné', '00': '0 salarié',
    '01': '1 ou 2 salariés', '02': '3 à 5 salariés', '03': '6 à 9 salariés',
    '11': '10 à 19 salariés', '12': '20 à 49 salariés', '21': '50 à 99 salariés',
    '22': '100 à 199 salariés', '31': '200 à 249 salariés', '32': '250 à 499 salariés',
    '41': '500 à 999 salariés', '42': '1 000 à 1 999 salariés', '51': '2 000 à 4 999 salariés',
    '52': '5 000 à 9 999 salariés', '53': '10 000 et plus',
}

# NAF -> forme la plus probable quand nature_juridique absente
def _forme_from_nature(nature_code, nom_complet=''):
    if not nature_code:
        return None
    code = str(nature_code)
    if code in _NATURE:
        return _NATURE[code]
    # prefixes : 54xx = SARL-ish, 55xx = SA, 57xx = societe civile
    if code.startswith('54'):
        return 'SARL'
    if code.startswith('55'):
        return 'SA'
    if code.startswith('57'):
        return 'Autre'
    return None


def _clean_dirigeants(dirigeants):
    out = []
    for d in (dirigeants or []):
        nom = (d.get('nom') or '').title()
        prenoms = (d.get('prenoms') or '').title()
        qualite = (d.get('qualite') or '').strip()
        if d.get('type_dirigeant') == 'personne physique':
            lib = f"{prenoms} {nom}".strip()
        else:
            lib = (d.get('denomination') or nom or '').strip()
        if lib:
            out.append({'nom': lib, 'qualite': qualite,
                        'texte': f"{lib} — {qualite}" if qualite else lib})
    return out


def recherche_siren(siren: str):
    """Interroge l'API et renvoie un dict d'infos pretes a remplir le formulaire.

    Retourne {'ok': False, 'error': '...'} si non trouve / erreur reseau.
    Les champs proposes sont non vide uniquement quand la source les fournit.
    """
    s = re.sub(r'\D', '', str(siren or ''))
    if len(s) != 9:
        return {'ok': False, 'error': 'SIREN invalide : 9 chiffres attendus.'}

    # la validation luhn du SIREN
    total = 0
    for i, ch in enumerate(reversed(s)):
        v = int(ch)
        if i % 2 == 1:
            v *= 2
            if v > 9:
                v -= 9
        total += v
    if total % 10 != 0:
        return {'ok': False, 'error': 'SIREN invalide (clé de contrôle non conforme).'}

    if s in _CACHE:
        return dict(_CACHE[s])

    try:
        import time as _t
        resp = None
        for _attempt in range(4):
            resp = requests.get(API_URL, params={'q': s, 'per_page': 1, 'page': 1},
                                timeout=_TIMEOUT, headers={'User-Agent': 'cabinet-jmh-app'})
            if resp.status_code != 429:
                break
            _t.sleep(2 + 3 * _attempt)  # backoff progressif sur quota public (~7 req/s)
    except requests.RequestException as e:
        return {'ok': False, 'error': f'Réseau/indisponible : {e.__class__.__name__}'}

    if resp.status_code != 200:
        return {'ok': False, 'error': f'API {resp.status_code} — réessayez dans un instant.'}

    try:
        data = resp.json()
    except ValueError:
        return {'ok': False, 'error': 'Réponse API illisible.'}

    results = data.get('results') or []
    if not results:
        return {'ok': False, 'error': f'Aucune entreprise trouvée pour le SIREN {s}.'}

    r = results[0]
    siege = r.get('siege') or {}

    # raison sociale
    nom = (r.get('nom_complet') or r.get('nom_raison_sociale') or '').strip()

    # forme juridique
    forme = _forme_from_nature(r.get('nature_juridique'), nom)

    # activite (NAF) -> on garde le code + un libelle si l'API en fournit un
    naf = r.get('activite_principale') or siege.get('activite_principale')
    naf_label = r.get('libelle_activite_principale') or ''

    dirigeants = _clean_dirigeants(r.get('dirigeants'))

    # adresse siege
    addr = ' '.join(x for x in [
        siege.get('adresse') or '',
    ] if x).strip()

    creation = r.get('date_creation') or siege.get('date_creation')

    result = {
        'ok': True,
        'siren': s,
        'siret': siege.get('siret') or r.get('siret'),
        'nom': nom or None,
        'forme_juridique': forme,
        'secteur_activite': (naf_label or naf) or None,
        'activite_principale': naf,
        'dirigeants': dirigeants,
        'dirigeant_principal': dirigeants[0]['texte'] if dirigeants else None,
        'adresse': addr or None,
        'date_creation': creation,
        'effectif': r.get('tranche_effectif_salarie'),
        'effectif_label': _EFFECTIFS.get(str(r.get('tranche_effectif_salarie') or '').strip()),
        'categorie_entreprise': r.get('categorie_entreprise'),
        'tva_intra': (r.get('tva') or [None])[0],
        'etat_administratif': r.get('etat_administratif'),
    }
    _CACHE[s] = dict(result)
    return result


def _parse_date_str(v):
    if not v:
        return None
    from datetime import datetime
    try:
        return datetime.strptime(str(v)[:10], '%Y-%m-%d').date()
    except ValueError:
        return None


def apply_siren_to_dossier(dossier, siren: str, overwrite=False):
    """Récupère les infos via l'API et les écrit dans le dossier (flush seulement,
    pas de commit — c'est l'appelant qui gere la transaction).

    overwrite=False : ne remplit que les champs vides (sans ecraser une saisie manuelle).
    Retourne (True, None) si enrichi, (False, message_erreur) sinon.
    """
    from datetime import datetime as _dt
    from .models import Dossier  # noqa: F401  (referencement explicite)
    info = recherche_siren(siren)
    if not info.get('ok'):
        return False, info.get('error') or 'SIREN injoignable'

    s = info['siren']
    dossier.siren = s
    if overwrite or not dossier.intitule:
        if info.get('nom'):
            dossier.intitule = info['nom']
    if (overwrite or not dossier.forme_juridique) and info.get('forme_juridique'):
        dossier.forme_juridique = info['forme_juridique'][:20]
    if (overwrite or not dossier.secteur_activite) and info.get('secteur_activite'):
        dossier.secteur_activite = info['secteur_activite'][:60]
    if (overwrite or not dossier.tva_intra) and info.get('tva_intra'):
        dossier.tva_intra = info['tva_intra'][:20]
    if (overwrite or not dossier.naf_code) and info.get('activite_principale'):
        dossier.naf_code = str(info['activite_principale'])[:10]
    if (overwrite or not dossier.effectif_label) and info.get('effectif_label'):
        dossier.effectif_label = info['effectif_label'][:40]
    if (overwrite or not dossier.categorie_entreprise) and info.get('categorie_entreprise'):
        dossier.categorie_entreprise = info['categorie_entreprise'][:5]
    if (overwrite or not dossier.date_creation_entreprise):
        dc = _parse_date_str(info.get('date_creation'))
        if dc:
            dossier.date_creation_entreprise = dc
    if (overwrite or not dossier.dirigeant) and info.get('dirigeant_principal'):
        dossier.dirigeant = info['dirigeant_principal'][:200]
    if (overwrite or not dossier.adresse_siege) and info.get('adresse'):
        dossier.adresse_siege = info['adresse'][:250]
    if info.get('etat_administratif'):
        dossier.etat_administratif = info['etat_administratif'][:5]
    dossier.enrichi_le = _dt.utcnow()
    return True, None
