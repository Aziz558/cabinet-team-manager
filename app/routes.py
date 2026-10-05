"""Routes de l'application, decoupees par domaine (voir modules routes_*).

Agregateur : `from app import routes` (app/__init__.py) charge tous les modules.
Les helpers partages entre domaines vivent dans app/route_common.py."""
from . import routes_auth  # noqa: F401 — index, login, logout, team-select, dashboard
from . import routes_checklist  # noqa: F401 — checklist des obligations fiscales
from . import routes_planning  # noqa: F401 — calendrier + analytics
from . import routes_dossiers  # noqa: F401 — liste dossiers + tva-taches + planification
from . import routes_taches  # noqa: F401 — liste/creation de taches
from . import routes_equipe  # noqa: F401 — equipes, notifications, membres, fiche
from . import routes_suggestions  # noqa: F401 — suggestions de taches (LLM/mail)
from . import routes_dossiers_ops  # noqa: F401 — mes vues, modifier/enrichir dossier, admin DB, prise en charge
from . import routes_api  # noqa: F401 — settings + API (mail, notifier, recherche globale)
from . import routes_dossiers_gest  # noqa: F401 — suppressions + CSV dossiers/equipes/taches
from . import routes_avancement  # noqa: F401 — suivi avancement + taches du jour
from . import routes_tache_actions  # noqa: F401 — changer/terminer statut + photos profil
from . import routes_notifications  # noqa: F401 — notifications, commentaires, vue tache
from . import routes_admin  # noqa: F401 — profil, reset admin, photos admin, debug
from . import routes_fiscal  # noqa: F401 — page fiscal + creation dossier + config equipes
from . import routes_pennylane  # noqa: F401 — integration Pennylane + error handlers
