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
        resp = requests.get(API_URL, params={'q': s, 'per_page': 1, 'page': 1},
                            timeout=_TIMEOUT, headers={'User-Agent': 'cabinet-jmh-app'})
        # retry unique sur rate-limit (quota public ~7 req/s)
        if resp.status_code == 429:
            import time as _t
            _t.sleep(2)
            resp = requests.get(API_URL, params={'q': s, 'per_page': 1, 'page': 1},
                                timeout=_TIMEOUT, headers={'User-Agent': 'cabinet-jmh-app'})
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
        'etat_administratif': r.get('etat_administratif'),
    }
    _CACHE[s] = dict(result)
    return result
