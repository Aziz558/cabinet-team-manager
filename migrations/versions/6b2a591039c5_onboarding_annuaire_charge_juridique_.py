"""Suivi nouveaux dossiers (onboarding) + annuaire : tables et colonnes des modeles.

Comble l'ecart entre les migrations et les models (commits 9b2164a / efd3ef2) :
- 7 tables : onboarding_dossiers, onboarding_etapes, onboarding_dossiers_partis,
  onboarding_mails, onboarding_actions_mail, annuaire_categories, annuaire_fiches
- 2 colonnes : dossiers.charge_juridique_id, checklist_entries.source
- rappels : table absente de la baseline (ecart preexistant, comble ici)

Revision ID: 6b2a591039c5
Revises: c8d9e0f1a2b3
Create Date: 2026-11-09 15:47:52.627057

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6b2a591039c5'
down_revision = 'c8d9e0f1a2b3'
branch_labels = None
depends_on = None


def upgrade():
    # Idempotent : app/__init__.py peut deja avoir cree tables/colonnes au
    # demarrage (create_all + ALTER ad hoc) — on ne touche que ce qui manque.
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()

    if 'dossiers' in tables:
        cols = [c['name'] for c in inspector.get_columns('dossiers')]
        if 'charge_juridique_id' not in cols:
            op.add_column('dossiers', sa.Column('charge_juridique_id', sa.Integer(), nullable=True))

    if 'checklist_entries' in tables:
        cols = [c['name'] for c in inspector.get_columns('checklist_entries')]
        if 'source' not in cols:
            op.add_column('checklist_entries', sa.Column('source', sa.String(length=20), nullable=True))

    if 'rappels' not in tables:
        op.create_table('rappels',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('titre', sa.String(length=200), nullable=False),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('date_echeance', sa.Date(), nullable=False),
            sa.Column('date_creation', sa.DateTime(), nullable=True),
            sa.Column('date_envoi_notification', sa.DateTime(), nullable=True),
            sa.Column('lu', sa.Boolean(), nullable=True),
            sa.Column('date_lu', sa.DateTime(), nullable=True),
            sa.Column('email_j1_envoye', sa.Boolean(), nullable=True),
            sa.Column('email_echeance_envoye', sa.Boolean(), nullable=True),
            sa.Column('archive', sa.Boolean(), nullable=True),
            sa.Column('source', sa.String(length=30), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_rappels_user_id'), 'rappels', ['user_id'], unique=False)

    if 'annuaire_categories' not in tables:
        op.create_table('annuaire_categories',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('nom', sa.String(length=80), nullable=False),
            sa.Column('couleur', sa.String(length=20), nullable=True),
            sa.Column('ordre', sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('nom')
        )

    if 'annuaire_fiches' not in tables:
        op.create_table('annuaire_fiches',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('categorie_id', sa.Integer(), nullable=True),
            sa.Column('nom', sa.String(length=200), nullable=False),
            sa.Column('email', sa.String(length=200), nullable=True),
            sa.Column('telephone', sa.String(length=40), nullable=True),
            sa.Column('organisation', sa.String(length=200), nullable=True),
            sa.Column('note', sa.Text(), nullable=True),
            sa.Column('actif', sa.Boolean(), nullable=True),
            sa.Column('cree_par_id', sa.Integer(), nullable=True),
            sa.Column('date_creation', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['categorie_id'], ['annuaire_categories.id'], ),
            sa.ForeignKeyConstraint(['cree_par_id'], ['users.id'], ),
            sa.PrimaryKeyConstraint('id')
        )

    if 'onboarding_dossiers' not in tables:
        op.create_table('onboarding_dossiers',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('auteur', sa.String(length=80), nullable=True),
            sa.Column('nom_dossier', sa.String(length=200), nullable=False),
            sa.Column('nom_client', sa.String(length=200), nullable=True),
            sa.Column('mail', sa.String(length=200), nullable=True),
            sa.Column('telephone', sa.String(length=40), nullable=True),
            sa.Column('ec_chef_mission', sa.String(length=80), nullable=True),
            sa.Column('etablissement', sa.String(length=120), nullable=True),
            sa.Column('type_dossier', sa.String(length=20), nullable=False),
            sa.Column('polyacte', sa.Boolean(), nullable=True),
            sa.Column('honoraires_an', sa.Float(), nullable=True),
            sa.Column('date_debut_mission', sa.Date(), nullable=True),
            sa.Column('social', sa.Boolean(), nullable=True),
            sa.Column('collab_comptable', sa.String(length=80), nullable=True),
            sa.Column('collab_social', sa.String(length=80), nullable=True),
            sa.Column('collab_juridique', sa.String(length=80), nullable=True),
            sa.Column('statut', sa.String(length=20), nullable=False),
            sa.Column('commentaires', sa.Text(), nullable=True),
            sa.Column('dossier_id', sa.Integer(), nullable=True),
            sa.Column('cree_par_id', sa.Integer(), nullable=True),
            sa.Column('date_creation', sa.DateTime(), nullable=True),
            sa.Column('date_modif', sa.DateTime(), nullable=True),
            sa.Column('chef_mission_id', sa.Integer(), nullable=True),
            sa.Column('expert_comptable_id', sa.Integer(), nullable=True),
            sa.Column('resp_juridique_id', sa.Integer(), nullable=True),
            sa.Column('resp_social_id', sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(['chef_mission_id'], ['users.id'], ),
            sa.ForeignKeyConstraint(['cree_par_id'], ['users.id'], ),
            sa.ForeignKeyConstraint(['dossier_id'], ['dossiers.id'], ),
            sa.ForeignKeyConstraint(['expert_comptable_id'], ['users.id'], ),
            sa.ForeignKeyConstraint(['resp_juridique_id'], ['users.id'], ),
            sa.ForeignKeyConstraint(['resp_social_id'], ['users.id'], ),
            sa.PrimaryKeyConstraint('id')
        )

    if 'onboarding_dossiers_partis' not in tables:
        op.create_table('onboarding_dossiers_partis',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('auteur', sa.String(length=80), nullable=True),
            sa.Column('nom_dossier', sa.String(length=200), nullable=False),
            sa.Column('nom_client', sa.String(length=200), nullable=True),
            sa.Column('mail', sa.String(length=200), nullable=True),
            sa.Column('telephone', sa.String(length=40), nullable=True),
            sa.Column('ec_chef_mission', sa.String(length=80), nullable=True),
            sa.Column('etablissement', sa.String(length=120), nullable=True),
            sa.Column('collaborateur', sa.String(length=80), nullable=True),
            sa.Column('cause_depart', sa.String(length=200), nullable=True),
            sa.Column('date_depart', sa.Date(), nullable=True),
            sa.Column('mail_deontologie_recu', sa.Date(), nullable=True),
            sa.Column('envoi_documents', sa.Date(), nullable=True),
            sa.Column('mail_facturation', sa.Date(), nullable=True),
            sa.Column('commentaires', sa.Text(), nullable=True),
            sa.Column('dossier_id', sa.Integer(), nullable=True),
            sa.Column('date_creation', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['dossier_id'], ['dossiers.id'], ),
            sa.PrimaryKeyConstraint('id')
        )

    if 'onboarding_etapes' not in tables:
        op.create_table('onboarding_etapes',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('dossier_onb_id', sa.Integer(), nullable=False),
            sa.Column('code', sa.String(length=40), nullable=False),
            sa.Column('date_fait', sa.Date(), nullable=True),
            sa.Column('sans_date', sa.Boolean(), nullable=True),
            sa.Column('fait_par_id', sa.Integer(), nullable=True),
            sa.Column('commentaire', sa.String(length=500), nullable=True),
            sa.Column('date_modif', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['dossier_onb_id'], ['onboarding_dossiers.id'], ),
            sa.ForeignKeyConstraint(['fait_par_id'], ['users.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('dossier_onb_id', 'code', name='uq_onb_etape')
        )
        op.create_index(op.f('ix_onboarding_etapes_dossier_onb_id'), 'onboarding_etapes', ['dossier_onb_id'], unique=False)

    if 'onboarding_mails' not in tables:
        op.create_table('onboarding_mails',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('dossier_onb_id', sa.Integer(), nullable=True),
            sa.Column('depart_id', sa.Integer(), nullable=True),
            sa.Column('type_mail', sa.String(length=40), nullable=False),
            sa.Column('destinataire', sa.String(length=200), nullable=False),
            sa.Column('sujet', sa.String(length=300), nullable=True),
            sa.Column('statut', sa.String(length=20), nullable=False),
            sa.Column('erreur', sa.Text(), nullable=True),
            sa.Column('envoye_par_id', sa.Integer(), nullable=True),
            sa.Column('sent_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['depart_id'], ['onboarding_dossiers_partis.id'], ),
            sa.ForeignKeyConstraint(['dossier_onb_id'], ['onboarding_dossiers.id'], ),
            sa.ForeignKeyConstraint(['envoye_par_id'], ['users.id'], ),
            sa.PrimaryKeyConstraint('id')
        )

    if 'onboarding_actions_mail' not in tables:
        op.create_table('onboarding_actions_mail',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('etape_code', sa.String(length=40), nullable=False),
            sa.Column('actif', sa.Boolean(), nullable=False),
            sa.Column('sujet', sa.String(length=300), nullable=True),
            sa.Column('corps', sa.Text(), nullable=True),
            sa.Column('destinataires', sa.Text(), nullable=True),
            sa.Column('maj_le', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_onboarding_actions_mail_etape_code'), 'onboarding_actions_mail', ['etape_code'], unique=True)


def downgrade():
    op.drop_index(op.f('ix_onboarding_actions_mail_etape_code'), table_name='onboarding_actions_mail')
    op.drop_table('onboarding_actions_mail')
    op.drop_table('onboarding_mails')
    op.drop_index(op.f('ix_onboarding_etapes_dossier_onb_id'), table_name='onboarding_etapes')
    op.drop_table('onboarding_etapes')
    op.drop_table('onboarding_dossiers_partis')
    op.drop_table('onboarding_dossiers')
    op.drop_table('annuaire_fiches')
    op.drop_table('annuaire_categories')
    op.drop_index(op.f('ix_rappels_user_id'), table_name='rappels')
    op.drop_table('rappels')
    op.drop_column('checklist_entries', 'source')
    op.drop_column('dossiers', 'charge_juridique_id')