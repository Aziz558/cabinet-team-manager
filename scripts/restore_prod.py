# -*- coding: utf-8 -*-
"""Restauration prod : comptes + 10 dossiers via l'API du site (session admin).

Usage (variables d'environnement OBLIGATOIRES, aucun mot de passe en dur) :

    set RESTORE_ADMIN_EMAIL=admin@cabinet-jmh.com
    set RESTORE_ADMIN_PASSWORD=...          # mot de passe admin ACTUEL en prod
    set RESTORE_AZIZ_PASSWORD=...           # mot de passe du compte admin cree
    set RESTORE_HAMZA_PASSWORD=...          # mot de passe du compte membre cree
    python scripts/restore_prod.py

Optionnel : RESTORE_BASE_URL (defaut : https://cabinet-team-manager.onrender.com)
"""
import os
import re
import sys

import requests

BASE = os.environ.get('RESTORE_BASE_URL', 'https://cabinet-team-manager.onrender.com').rstrip('/')

def _env(nom):
    v = (os.environ.get(nom) or '').strip()
    if not v:
        print(f"ERREUR : variable d'environnement manquante : {nom}")
        sys.exit(2)
    return v

ADMIN_EMAIL = _env('RESTORE_ADMIN_EMAIL')
ADMIN_PASSWORD = _env('RESTORE_ADMIN_PASSWORD')
MDP_AZIZ = _env('RESTORE_AZIZ_PASSWORD')
MDP_HAMZA = _env('RESTORE_HAMZA_PASSWORD')

s = requests.Session()
s.headers['User-Agent'] = 'Mozilla/5.0 restore'

def txt(r):
    return r.text[:300].replace('\n', ' ') if r.status_code != 200 else ''

# 1. Login
r = s.get(f'{BASE}/login', timeout=30)
print(f"GET /login -> {r.status_code}")
r = s.post(f'{BASE}/login', data={'email': ADMIN_EMAIL, 'password': ADMIN_PASSWORD},
           timeout=30, allow_redirects=True)
ok_login = ('Bienvenue' in r.text) or ('dossiers' in r.url) or (r.status_code == 200 and 'logout' in r.text.lower())
print(f"POST /login -> {r.status_code} url={r.url} login_ok={ok_login}")
if not ok_login:
    print("DETAIL:", txt(r)[:200])
    sys.exit(1)

# 2. État actuel : membres + équipes + dossiers
r = s.get(f'{BASE}/liste_membres', timeout=30)
print(f"GET /liste_membres -> {r.status_code}")
try:
    membres = r.json()
    if isinstance(membres, dict):
        membres = membres.get('membres', membres.get('users', []))
except Exception:
    membres = []
print("membres actuels:", [m.get('email', m) for m in membres][:10] if membres else r.text[:150])

r = s.get(f'{BASE}/dossiers', timeout=30)
print(f"GET /dossiers -> {r.status_code}")
dossiers_existants = re.findall(r'data-dossier="(\d+)"', r.text)
print("dossiers (ids) actuels:", sorted(set(dossiers_existants)))

# 3. Créer Aziz (admin) + Hamza (membre) si absents
def creer_membre(prenom, nom, email, mdp, role, poste):
    r = s.post(f'{BASE}/ajouter_membre', data={
        'prenom': prenom, 'nom': nom, 'email': email, 'mot_de_passe': mdp,
        'role': role, 'poste': poste, 'telephone': ''
    }, timeout=30, allow_redirects=True)
    err = 'déjà utilisé' in r.text or 'deja utilise' in r.text.lower()
    print(f"  + membre {prenom} {nom} ({role}) -> {r.status_code} {'(déjà existant)' if err else ''}")
    return not err

CREATED_AZIZ = creer_membre('Mohamed Aziz', 'JLASSI', 'mohamed-aziz.jlassi@cabinet-jmh.com', MDP_AZIZ, 'admin', 'Comptable')
CREATED_HAMZA = creer_membre('Hamza', 'Boujemaa', 'hamza.boujemaa@cabinet-jmh.com', MDP_HAMZA, 'membre', 'Collaborateur comptable')

# ids frais
r = s.get(f'{BASE}/liste_membres', timeout=30)
try:
    membres = r.json()
    if isinstance(membres, dict):
        membres = membres.get('membres', membres.get('users', []))
except Exception:
    membres = []
ids = {}
for m in membres:
    email = (m.get('email') or '').lower()
    ids['aziz' if 'jlassi' in email else 'hamza' if 'hamza' in email else None] = m.get('id')
print("ids membres:", ids)

# 4. Id équipe (par défaut)
r = s.get(f'{BASE}/equipes', timeout=30)
eq_m = re.search(r'/set-team/(\d+)', r.text) or re.search(r'data-equipe-id="(\d+)"', r.text)
equipe_id = eq_m.group(1) if eq_m else '1'
print("equipe_id =", equipe_id)

# 5. Les 10 dossiers (extraits de la grille prod sauvegardée)
#    (jour limite = jour du mois extrait de la grille : "le NN du mois suivant")
DOSSIERS = [
    ('IB CIES',     'CIES',                   23, 'SCI'),
    ('IB LATAVERNE','LA TAVERNE DE CHOISY',   19, 'SARL'),
    ('IB M2ATRAN',  'M2A TRANSPORT IDF',      24, 'SAS'),
    ('IB AKMOB',    'ECOLOGIE ET SAGESSE',    24, 'SAS'),
    ('IB TANIS',    'SCI TANIS',              20, 'SCI'),
    ('IB AUPETIT',  'AU PETIT GOURMET',       24, 'SARL'),
    ('IB NATSOU',   'NATSOU',                 24, 'SAS'),
    ('IB LIAMS',    'LIAMS',                  23, 'SAS'),
    ('IB DMSPER',   'DMS PERMIS',             24, 'SAS'),
    ('AJ PROST',    'PROSTORE',               24, 'SAS'),
]
collab_hamza = ids.get('hamza') or ids.get('aziz')
for num, intitule, jour, forme in DOSSIERS:
    r = s.post(f'{BASE}/ajouter_dossier', data={
        'numero_dossier': num, 'intitule': intitule,
        'collaborateur_id': collab_hamza, 'equipe_id': equipe_id,
        'regime_tva': 'ca3', 'frequence_tva': 'mensuelle',
        'date_limite_declaration': f'2026-10-{jour:02d}',
        'regime_fiscale': 'IS', 'forme_juridique': forme,
        'secteur_activite': '', 'has_cfe': 'on' if num == 'AJ PROST' else '',
    }, timeout=60, allow_redirects=True)
    deja = 'existe' in r.text.lower()
    ok = 'créé avec succès' in r.text or 'succ' in r.text.lower()
    print(f"  + dossier {num:<12} -> {r.status_code} {'OK' if ok else ('existe déjà' if deja else '?? ' + re.sub('<[^>]+>', ' ', r.text[:120]))}")

# 6. Vérification finale
r = s.get(f'{BASE}/dossiers', timeout=30)
final = sorted(set(re.findall(r'data-dossier="(\d+)"', r.text)))
print(f"\n=== VERIF FINALE : {len(final)} dossiers en prod : {final}")
print(f"=== Membres : Aziz={'OK' if CREATED_AZIZ else '?'}, Hamza={'OK' if CREATED_HAMZA else '?'}")
