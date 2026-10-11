"""Recapitulatif Pennylane : marqueur d'envoi des nouveaux documents.

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-11-10 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7c8d9e0f1a2'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    # server_default=true : les items EXISTANTS sont considerés comme deja notifies,
    # sinon le premier recapitulatif renverrait tout l'historique.
    op.add_column(
        'pennylane_items',
        sa.Column('digest_envoye', sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade():
    op.drop_column('pennylane_items', 'digest_envoye')
