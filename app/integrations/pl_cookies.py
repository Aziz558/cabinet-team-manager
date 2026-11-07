# -*- coding: utf-8 -*-
"""Nettoyage du texte collé pour la session Pennylane — zéro dépendance.

Ce que l'utilisateur trouve le plus vite dans son navigateur, c'est rarement
« juste les cookies » : c'est un « Copier comme cURL » qui contient 40 appels
d'affichage, dés fois la commande entière, dés fois plusieurs requêtes à la
suite. Sans nettoyage, l'appli enregistre un header tronqué et la synchro
échoue en silence.

Ce module accepte indifféremment :
  * la commande cURL complète (« Copier comme cURL ») — même plusieurs
    collées à la suite ;
  * l'option ``-b '...'`` ou ``--cookie '...'`` seule ;
  * la ligne d'en-tête ``Cookie: a=b; c=d`` d'un panneau DevTools ;
  * la simple liste brute ``a=b; c=d`` ;
  * un JSON ``{"cookie": "a=b; c=d"}``.

Il rend un header cookie propre, dédoublonné, et **dit ce qu'il a compris**
(nombre de cookies, cookies critiques manquants) pour que l'utilisateur sache
si son collage est utilisable avant de lancer une synchro.
"""

from __future__ import annotations

import re

__all__ = ['nettoyer_cookies', 'COOKIES_CRITIQUES', 'COOKIES_ANTIBOT']

# Sans eux, la session Pennylane ne peut pas fonctionner : le premier est la
# session web elle-même, les deux autres servent au renouvellement du login.
COOKIES_CRITIQUES = ('_jeancaisse_session', 'remember_user_token')
# Posés par Cloudflare devant app.pennylane.com. Leur absence fait déclencher
# la protection anti-bot (HTTP 418) au bout de quelques appels : la session
# « marche » puis se bloque toute seule, ce qui est très dur à diagnostiquer.
COOKIES_ANTIBOT = ('cf_clearance', '__cf_bm')

_NOM_VALIDE = re.compile(r'^[A-Za-z0-9_.\-~%+]+$')
_LONGUEUR_MAX = 20000          # un header cookie légitime fait ~4-6 ko

# Caractères de contrôle écrits explicitement : dans un patch on ne peut pas
# distinguer un vrai retour à la ligne de la séquence « barre oblique inversée + n ».
_BS, _LF, _CR, _TAB = chr(92), chr(10), chr(13), chr(9)
_LIGNE_ENTETE = re.compile(r'^[ 	]*[A-Za-z0-9-]+[ 	]*:')   # « Accept: », « Referer: »…

_TAILLE_ANALYSEE = 400000      # au-delà, on ne lit plus : ce n'est pas ça

# Un nom de cookie tel qu'il apparaît dans un header : « nom=valeur »
_MOTIF_PAIRE = re.compile(r'[A-Za-z0-9_.\-~%+]{2,}=.')


def _candidats(texte: str):
    """Rend [(origine, brut)] pour chaque zone du texte qui peut être un header cookie."""
    t = (texte or '')[: _TAILLE_ANALYSEE]
    t = t.replace('\r\n', '\n').replace('\r', '\n')
    out = []

    # 1. curl -b '...'  /  -b "..."
    out += [('cURL (-b)', m.group(2))
            for m in re.finditer(r"(?<![-\w])-b\s*(['\"])([^'\"]*)\1", t)]
    # 2. curl --cookie '...'
    out += [('cURL (--cookie)', m.group(2))
            for m in re.finditer(r"--cookie\s*(['\"])([^'\"]*)\1", t)]
    # 3. curl -H 'cookie: ...' / --header 'Cookie: ...'
    out += [('en-tête curl', m.group(2))
            for m in re.finditer(r"(?:-H|--header)\s*(['\"])\s*cookie\s*:\s*([^'\"]*)\1",
                                 t, re.IGNORECASE)]
    # 4. ligne d'en-tête « Cookie: ... » (panneau DevTools). Un header étalé sur
    #    plusieurs lignes compte pour UN seul candidat : on avale les lignes de
    #    continuation jusqu'à la première ligne vide ou au prochain « Entête: »
    #    (sinon on ne garderait que le premier cookie et la session serait partielle).
    for m in re.finditer(r"(?im)^[ \t]*cookie[ \t]*:[ \t]*(.*)$", t):
        bloc_lignes = [m.group(1)]
        for suite in t[m.end():].split(_LF)[1:]:
            if not suite.strip() or _LIGNE_ENTETE.match(suite):
                break
            bloc_lignes.append(suite)
        out.append(('ligne Cookie:', _LF.join(bloc_lignes)))
    # 5. JSON "cookie": "..."
    out += [('JSON', m.group(1))
            for m in re.finditer(r"[\"']cookie[\"']\s*:\s*[\"']([^\"']*)[\"']", t,
                                 re.IGNORECASE)]
    if not out:
        # 6. Dernier recours : tout le texte est peut-être déjà un header nu.
        out.append(('texte brut', t))
    return out


def _paires(brut: str):
    """Transforme une zone en [(nom, valeur)] propres, dans l'ordre, sans doublon."""
    t = brut or ''
    t = re.sub(r"\$'[^']*'", ' ', t)        # blocs --data-raw binaires des cURL
    t = t.replace(_BS + _LF, ' ')        # continuations de ligne du shell (barre oblique inversee + retour)
    t = t.replace('\n', ';').replace('\t', ' ')
    t = re.sub(r"(?i)(^|[;'\"\s])cookie\s*:", r'\1', t)   # le mot-clé éventuel
    t = t.replace('\\"', '"').replace("\\'", "'").replace('\\\\', '\\')

    vus = set()
    paires = []
    for morceau in t.split(';'):
        morceau = morceau.strip().strip('"\'').strip()
        morceau = re.sub(r"^-b\s*", '', morceau).strip()        # « -b 'a=b »
        morceau = morceau.rstrip('^\\').strip()                 # fin de ligne cmd.exe
        if not morceau or '=' not in morceau or ' ' in morceau:
            continue                                            # jamais d'espace dans un cookie
        nom, _, valeur = morceau.partition('=')
        nom, valeur = nom.strip(), valeur.strip()
        if not _NOM_VALIDE.match(nom) or nom.lower() == 'cookie' or nom in vus:
            continue
        vus.add(nom)
        paires.append((nom, valeur))
    return paires


def nettoyer_cookies(texte: str) -> dict:
    """Nettoie un collage navigateur et rend un header cookie prêt à l'emploi.

    Renvoie un dict :
      ok        : True si un header exploitable a été extrait
      header    : « nom=valeur; nom=valeur » ('' si échec)
      n         : nombre de cookies retenus
      cles      : noms des cookies retenus (jamais les valeurs)
      source    : d'où ça a été extrait (« cURL (-b) », « ligne Cookie: »…)
      critiques_manquants / antibot_manquants : listes de noms absents
      avertissements : phrases prêtes à afficher à l'utilisateur
      message   : résumé lisible
    """
    meilleur = None                       # (score, origine, paires)
    for origine, brut in _candidats(texte):
        paires = _paires(brut)
        if not paires:
            continue
        header = '; '.join(f'{k}={v}' for k, v in paires)
        if len(header) > _LONGUEUR_MAX:
            continue
        if not _MOTIF_PAIRE.search(header):
            continue
        score = (len(paires), len(header))
        if meilleur is None or score > meilleur[0]:
            meilleur = (score, origine, paires, header)

    if meilleur is None:
        return {
            'ok': False, 'header': '', 'n': 0, 'cles': [], 'source': '',
            'critiques_manquants': list(COOKIES_CRITIQUES),
            'antibot_manquants': list(COOKIES_ANTIBOT),
            'avertissements': [],
            'message': ("Aucun cookie trouvé dans ce texte. Dans le navigateur : F12 → Réseau → "
                        "clic droit sur une requête vers app.pennylane.com → Copier → "
                        "« Copier comme cURL », puis colle ici la commande entière. "
                        "La liste brute « nom=valeur; nom=valeur » fonctionne aussi."),
        }

    _, origine, paires, header = meilleur
    cles = [k for k, _ in paires]
    critiques_manquants = [c for c in COOKIES_CRITIQUES if c not in cles]
    antibot_manquants = [c for c in COOKIES_ANTIBOT if c not in cles]

    avertissements = []
    if critiques_manquants:
        avertissements.append(
            "Cookie(s) de session absent(s) : " + ', '.join(critiques_manquants) +
            ". Vérifie que la requête copiée allait bien vers app.pennylane.com.")
    if antibot_manquants:
        avertissements.append(
            "Cookie(s) anti-bot absent(s) : " + ', '.join(antibot_manquants) +
            ". Pennylane pourra répondre 418 après quelques appels — dans DevTools, "
            "réseau, rechargement de la page Pennylane, puis recopie (ces cookies "
            "sont posés par Cloudflare).")

    if critiques_manquants:
        message = (f"{len(paires)} cookie(s) lus depuis « {origine} », mais incomplets — "
                   f"voir l'avertissement ci-dessous.")
    elif avertissements:
        message = f"{len(paires)} cookie(s) lus depuis « {origine} »."
    else:
        message = (f"{len(paires)} cookie(s) lus depuis « {origine} » — session complète "
                   f"(session + anti-bot).")

    return {
        'ok': True, 'header': header, 'n': len(paires), 'cles': cles, 'source': origine,
        'critiques_manquants': critiques_manquants,
        'antibot_manquants': antibot_manquants,
        'avertissements': avertissements,
        'message': message,
    }
