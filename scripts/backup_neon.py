"""Sauvegarde automatique de la base Neon (pg_dump).
À exécuter via un Render Cron Job ou manuellement.
La sauvegarde est stockée dans le dossier backups/ (doit être persisté ou uploadé)."""
import os
import subprocess
import datetime
import logging
import time
import glob

logger = logging.getLogger(__name__)

BACKUP_DIR = os.environ.get('BACKUP_DIR', 'backups')
DB_URL = os.environ.get('DATABASE_URL', '')


def sauvegarder_neon():
    """Effectue un pg_dump de la base Neon et conserve les 7 derniers jours."""
    if not DB_URL:
        logger.error("[BACKUP] DATABASE_URL non definie — sauvegarde ignoree")
        return False

    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = os.path.join(BACKUP_DIR, f"neon_backup_{timestamp}.sql")

    try:
        # pg_dump avec format custom (compressé)
        result = subprocess.run(
            ['pg_dump', DB_URL, '-Fc', '-f', filename],
            capture_output=True,
            text=True,
            timeout=300  # 5 min max
        )
        if result.returncode != 0:
            logger.error(f"[BACKUP] pg_dump echoue : {result.stderr}")
            return False

        size_mb = os.path.getsize(filename) / (1024 * 1024)
        logger.info(f"[BACKUP] Sauvegarde reussie : {filename} ({size_mb:.1f} MB)")

        # Nettoyage : garder les 7 derniers jours
        _nettoyer_anciennes_sauvegardes(BACKUP_DIR, garder_jours=7)
        return True

    except subprocess.TimeoutExpired:
        logger.error("[BACKUP] pg_dump a expire (timeout 300s)")
        return False
    except Exception as e:
        logger.error(f"[BACKUP] Erreur : {e}")
        return False


def _nettoyer_anciennes_sauvegardes(backup_dir, garder_jours=7):
    """Supprime les sauvegardes plus vieilles de garde_jours."""
    now = time.time()
    seuil = now - (garder_jours * 86400)

    for f in os.listdir(backup_dir):
        filepath = os.path.join(backup_dir, f)
        if os.path.isfile(filepath):
            if os.path.getmtime(filepath) < seuil:
                os.remove(filepath)
                logger.info(f"[BACKUP] Ancienne sauvegarde supprimee : {f}")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    ok = sauvegarder_neon()
    print("BACKUP OK" if ok else "BACKUP ECHEC")