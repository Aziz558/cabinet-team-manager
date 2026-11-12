"""Mémoire longue d'ASTRO : table assistant_memoires (cabinet partagée + personnelle).

Revision ID: d4e5f6a7b8c9
Revises: 6b2a591039c5
Create Date: 2026-11-09 18:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = '6b2a591039c5'
branch_labels = None
depends_on = None


def upgrade():
    # Idempotent : create_all au démarrage a pu créer la table avant la migration.
    inspector = sa.inspect(op.get_bind())
    if 'assistant_memoires' in inspector.get_table_names():
        return
    op.create_table('assistant_memoires',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('portee', sa.String(length=10), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('contenu', sa.String(length=500), nullable=False),
        sa.Column('categorie', sa.String(length=40), nullable=True),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('cree_par_id', sa.Integer(), nullable=True),
        sa.Column('date_creation', sa.DateTime(), nullable=True),
        sa.Column('date_modif', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['cree_par_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_assistant_memoires_portee'), 'assistant_memoires', ['portee'], unique=False)
    op.create_index(op.f('ix_assistant_memoires_user_id'), 'assistant_memoires', ['user_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_assistant_memoires_user_id'), table_name='assistant_memoires')
    op.drop_index(op.f('ix_assistant_memoires_portee'), table_name='assistant_memoires')
    op.drop_table('assistant_memoires')