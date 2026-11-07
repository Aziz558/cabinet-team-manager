"""Configuration gunicorn de JMH Orbit.

Gunicorn lit automatiquement `gunicorn.conf.py` dans le répertoire courant au
démarrage. Ce fichier rend la configuration de production VERSIONNÉE avec le
code, au lieu de dépendre d'une ligne de commande saisie dans un dashboard.

Contexte (mesuré en production le 07/11/2026 via /health) :

    {"worker":"sync","forke":true,"threads":1,"planificateur":true}

Le worker effectivement utilisé était `sync` : une requête à la fois, donc une
synchro Pennylane de 53 dossiers ou un rendu de page lourde gelait toute
l'application. Le `startCommand` de render.yaml n'était pas appliqué par Render
pour ce service.

Priorité : ce fichier est un DÉFAUT. Un `-k` ou `--threads` explicite dans la
ligne de commande reste prioritaire sur ces valeurs.
"""
import os

# --- Processus ------------------------------------------------------------
# UN SEUL worker : chaque worker lancerait son propre planificateur APScheduler
# et les tâches (fiscal, notifications, synchro Pennylane) seraient exécutées
# autant de fois qu'il y a de workers.
workers = 1

# --- Concurrence ----------------------------------------------------------
# gthread plutôt que sync : les requêtes passent leur temps à attendre le
# réseau (Neon, API Pennylane, SMTP). En mode synchrone, ces attentes bloquent
# toutes les autres requêtes ; en multi-threads, elles se chevauchent.
# Mesuré localement sur des pages lourdes : l'attente d'une requête légère
# pendant un rendu passe de 97 ms (synchrone) à 32 ms (8 threads), soit ×3.
worker_class = 'gthread'
threads = 8

# --- Réseau ---------------------------------------------------------------
bind = '0.0.0.0:%s' % os.environ.get('PORT', '8000')
timeout = 120
graceful_timeout = 30
keepalive = 5

# --- Recyclage ------------------------------------------------------------
# Un worker recyclé périodiquement libère les fuites mémoire lentes.
max_requests = 1000
max_requests_jitter = 100

# --- Démarrage ------------------------------------------------------------
# Pas de préchargement : avec --preload l'application est importée dans le
# processus maître PUIS forquée, et les threads créés à l'import (APScheduler)
# ne survivent pas au fork. Le planificateur paraissait actif mais ne tournait
# plus. Le code démarre de toute façon le planificateur au premier appel HTTP
# (voir app._orbit_demarrer_planificateur) ; ceci est la ceinture et les
# bretelles.
preload_app = False

# --- Journalisation -------------------------------------------------------
accesslog = '-'
errorlog = '-'
loglevel = 'info'