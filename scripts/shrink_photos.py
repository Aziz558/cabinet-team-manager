"""Reduit les photos de profil deja stockees en base (BYTEA -> JPEG 256 px).

Objectif : faire baisser le poids des photos stockees et surtout le transfert
reseau relu a chaque affichage (quota Neon : 5 Go/mois).

    python scripts/shrink_photos.py            # simulation (aucune ecriture)
    python scripts/shrink_photos.py --apply    # ecrit reellement en base
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main():
    appliquer = '--apply' in sys.argv
    from app import app, db
    from app.models import User
    from app.routes_tache_actions import _reduire_photo

    total_avant = 0
    total_apres = 0
    modifies = 0

    with app.app_context():
        users = User.query.filter(User.photo_mimetype.isnot(None)).all()
        print(f'[photos] {len(users)} photo(s) en base')
        for u in users:
            avant = u.photo_data or b''
            if not avant:
                continue
            apres, mimetype = _reduire_photo(avant, u.photo_mimetype or 'image/png')
            total_avant += len(avant)
            total_apres += len(apres)
            if len(apres) < len(avant):
                modifies += 1
                print(f'  user {u.id} ({u.email}) : {len(avant)} -> {len(apres)} octets')
                if appliquer:
                    u.photo_data = apres
                    u.photo_mimetype = mimetype
                    db.session.commit()

    etat = 'optimisee(s)' if appliquer else 'optimisable(s)'
    print(f'\n[photos] Total {total_avant} -> {total_apres} octets — {modifies} {etat}')
    if not appliquer:
        print('[photos] Simulation : relancer avec --apply pour ecrire en base.')
    return 0


if __name__ == '__main__':
    sys.exit(main())