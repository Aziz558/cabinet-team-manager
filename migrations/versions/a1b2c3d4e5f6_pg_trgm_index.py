"""Ajout extension pg_trgm et index trigram pour recherche rapide.

Revision ID: a1b2c3d4e5f6
Revises: 9be1d41da284
Create Date: 2026-10-05 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '9be1d41da284'
branch_labels = None
depends_on = None


def upgrade():
    # Extension pg_trgm disponible uniquement sur PostgreSQL
    connection = op.get_context().connection
    dialect = connection.dialect.name
    if dialect == 'postgresql':
        op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
        op.execute(
            'CREATE INDEX IF NOT EXISTS idx_dossiers_numero_trgm '
            'ON dossiers USING gist (numero_dossier gist_trgm_ops)'
        )
        op.execute(
            'CREATE INDEX IF NOT EXISTS idx_dossiers_intitule_trgm '
            'ON dossiers USING gist (intitule gist_trgm_ops)'
        )
        op.execute(
            'CREATE INDEX IF NOT EXISTS idx_taches_titre_trgm '
            'ON taches USING gist (titre gist_trgm_ops)'
        )
        op.execute(
            'CREATE INDEX IF NOT EXISTS idx_users_nom_trgm '
            'ON users USING gist (nom gist_trgm_ops)'
        )
        op.execute(
            'CREATE INDEX IF NOT EXISTS idx_users_prenom_trgm '
            'ON users USING gist (prenom gist_trgm_ops)'
        )


def downgrade():
    # Suppression des index (uniquement sur PostgreSQL)
    connection = op.get_context().connection
    dialect = connection.dialect.name
    if dialect == 'postgresql':
        op.execute('DROP INDEX IF EXISTS idx_dossiers_numero_trgm')
        op.execute('DROP INDEX IF EXISTS idx_dossiers_intitule_trgm')
        op.execute('DROP INDEX IF EXISTS idx_taches_titre_trgm')
        op.execute('DROP INDEX IF EXISTS idx_users_nom_trgm')
        op.execute('DROP INDEX IF EXISTS idx_users_prenom_trgm')
    
    # L'extension pg_trgm est partagée, on ne la supprime pas
    # (d'autres tables pourraient l'utiliser)