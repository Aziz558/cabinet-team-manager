"""Origine du statut « terminée » d'une tâche : manuel ou automatique (Checklist / Pennylane).

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-10-12 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c8d9e0f1a2b3'
down_revision = 'b7c8d9e0f1a2'
branch_labels = None
depends_on = None


def upgrade():
    # Idempotent : app/__init__.py peut deja avoir ajoute la colonne au demarrage.
    cols = [c['name'] for c in sa.inspect(op.get_bind()).get_columns('taches')]
    if 'statut_source' not in cols:
        op.add_column('taches', sa.Column('statut_source', sa.String(length=20), nullable=True))


def downgrade():
    op.drop_column('taches', 'statut_source')
