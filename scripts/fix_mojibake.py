"""Repare le double encodage UTF-8 (mojibake) dans les templates.

Symptome : un texte UTF-8 relu en latin-1/cp1252 puis re-enregistre en UTF-8.
Exemple reel constate dans ce projet : la sequence d'octets 54 C3 83 C2 A2 63 68
65 73 affiche « TÃ¢ches » au lieu de « Tâches ».

Strategie : ligne par ligne, tentative de retour en arriere (cp1252 puis latin-1)
vers UTF-8, en ne gardant le resultat que s'il supprime des marqueurs de mojibake.
Les lignes irreparables sont signalees pour inspection manuelle.

    python scripts/fix_mojibake.py            # simulation (aucune ecriture)
    python scripts/fix_mojibake.py --apply    # reecrit les fichiers
"""
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(ROOT, 'templates')

MARQUEURS = ('Ã', 'â€', 'Â«', 'Â»', 'â€™', 'â€“', 'â€”', 'â€¦', 'Â°', 'Â·')

# Restes isoles quand la ligne contient aussi des caracteres hors cp1252
CORRECTIONS = (
    ('â€™', '\u2019'), ('â€œ', '\u201c'), ('â€\x9d', '\u201d'),
    ('â€“', '\u2013'), ('â€”', '\u2014'), ('â€¦', '\u2026'),
    ('â‚¬', '\u20ac'), ('Â«', '\u00ab'), ('Â»', '\u00bb'),
    ('Â·', '\u00b7'), ('Â°', '\u00b0'), ('Â ', ' '), ('Â', ''),
    ('Ã¢â‚¬â„¢', '\u2019'), ('Ã ', '\u00e0'), ('Ã©', '\u00e9'),
    ('Ã¨', '\u00e8'), ('Ãª', '\u00ea'), ('Ã§', '\u00e7'), ('Ã¹', '\u00f9'),
    ('Ã´', '\u00f4'), ('Ã®', '\u00ee'), ('Ã«', '\u00eb'), ('Ã¯', '\u00ef'),
    ('Ã‰', '\u00c9'), ('Ã€', '\u00c0'), ('Ã‡', '\u00c7'), ('Ã”', '\u00d4'),
)


def _score(txt):
    return sum(txt.count(m) for m in MARQUEURS)


def reparer_ligne(ligne):
    """Renvoie la ligne reparee (ou inchangee si la reparation n'aide pas)."""
    avant = _score(ligne)
    if not avant:
        return ligne

    for codec in ('cp1252', 'latin-1'):
        try:
            candidat = ligne.encode(codec).decode('utf-8')
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if _score(candidat) < avant:
            return candidat

    # Dernier recours : corrections ciblees des sequences les plus frequentes
    candidat = ligne
    for src, dst in CORRECTIONS:
        candidat = candidat.replace(src, dst)
    return candidat if _score(candidat) < avant else ligne


def main():
    appliquer = '--apply' in sys.argv
    fichiers = sorted(glob.glob(os.path.join(TEMPLATES, '**', '*.html'), recursive=True))

    total_lignes = 0
    total_fichiers = 0
    restes = []

    for chemin in fichiers:
        with open(chemin, encoding='utf-8', newline='') as f:
            contenu = f.read()
        if _score(contenu) == 0:
            continue

        lignes = contenu.splitlines(keepends=True)
        nouvelles = [reparer_ligne(ligne) for ligne in lignes]
        modifiees = sum(1 for a, b in zip(lignes, nouvelles) if a != b)
        if not modifiees:
            continue

        total_lignes += modifiees
        total_fichiers += 1
        reste = _score(''.join(nouvelles))
        nom = os.path.relpath(chemin, ROOT)
        print(f'  {nom:<38} {modifiees:>3} ligne(s)  reste={reste}')

        if appliquer:
            with open(chemin, 'w', encoding='utf-8', newline='') as f:
                f.write(''.join(nouvelles))
        if reste:
            restes.append((nom, reste))

    action = 'reparees' if appliquer else 'reparables (simulation)'
    print(f'\n[mojibake] {total_lignes} ligne(s) {action} dans {total_fichiers} fichier(s)')
    if restes:
        print('[mojibake] Lignes restantes a verifier :')
        for nom, reste in restes:
            print(f'   {nom} : {reste} marqueur(s)')
    if not appliquer:
        print('[mojibake] Simulation : relancer avec --apply pour ecrire.')
    return 0


if __name__ == '__main__':
    sys.exit(main())