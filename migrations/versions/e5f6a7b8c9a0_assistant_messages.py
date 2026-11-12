"""Tampon journalier des conversations ASTRO : table assistant_messages.

Revision ID: e5f6a7b8c9a0
Revises: d4e5f6a7b8c9
Create Date: 2026-11-09 19:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e5f6a7b8c9a0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    # Idempotent : create_all au démarrage a pu créer la table avant la migration.
    inspector = sa.inspect(op.get_bind())
    if 'assistant_messages' in inspector.get_table_names():
        return
    op.create_table('assistant_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=12), nullable=False),
        sa.Column('contenu', sa.Text(), nullable=False),
        sa.Column('date_creation', sa.DateTime(), nullable=True),
        sa.Column('exporte', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_assistant_messages_user_id'), 'assistant_messages', ['user_id'], unique=False)
    op.create_index(op.f('ix_assistant_messages_date_creation'), 'assistant_messages', ['date_creation'], unique=False)
    op.create_index(op.f('ix_assistant_messages_exporte'), 'assistant_messages', ['exporte'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_assistant_messages_exporte'), table_name='assistant_messages')
    op.drop_index(op.f('ix_assistant_messages_date_creation'), table_name='assistant_messages')
    op.drop_index(op.f('ix_assistant_messages_user_id'), table_name='assistant_messages')
    op.drop_table('assistant_messages')