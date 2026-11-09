"""Jeu de données de démonstration pour le développement local.

Idempotent : ne touche à rien si la base contient déjà des dossiers.
Usage :  python scripts/seed_demo.py
"""
import os
import random
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db  # noqa: E402
from app.models import (  # noqa: E402
    ChecklistEntry, CommentaireTache, Dossier, Equipe, Notification,
    PennylaneItem, Rappel, SuggestionTache, Tache, User,
)

random.seed(20261108)
TODAY = date.today()

PERSONNES = [
    ('Aziz', 'Jlassi', 'manager', 'comptable', 'Associé — responsable du pôle comptable'),
    ('Hamza', 'Ben Salem', 'manager', 'les_deux', 'Chef de mission'),
    ('Salma', 'Trabelsi', 'membre', 'comptable', 'Collaboratrice comptable senior'),
    ('Youssef', 'Gharbi', 'membre', 'comptable', 'Collaborateur comptable'),
    ('Ines', 'Bouazizi', 'membre', 'social', 'Gestionnaire de paie'),
    ('Mehdi', 'Kchaou', 'membre', 'social', 'Chargé de paie & DSN'),
    ('Nour', 'Chaabane', 'membre', 'les_deux', 'Assistante polyvalente'),
    ('Karim', 'Ayari', 'membre', 'comptable', 'Collaborateur comptable junior'),
]

ENTREPRISES = [
    ('SARL Atlas Distribution', 'Commerce de gros', 'ca3', 'SARL'),
    ('SAS Méditerranée Tech', 'Programmation informatique', 'ca3', 'SAS'),
    ('EURL Café des Arts', 'Restauration', 'ca12', 'EURL'),
    ('SARL Batiplus Construction', 'Travaux de bâtiment', 'ca3', 'SARL'),
    ('SCI Les Oliviers', 'Location immobilière', 'exonere', 'SCI'),
    ('SAS Nova Santé', 'Activités de santé', 'ca3', 'SAS'),
    ('SARL Transports du Sud', 'Transports routiers', 'ca3', 'SARL'),
    ('EURL Studio Karma', 'Design & communication', 'ca12', 'EURL'),
    ('SARL Épicerie du Port', 'Commerce de détail', 'ca3', 'SARL'),
    ('SAS Ingénierie Delta', 'Ingénierie & études', 'ca3', 'SAS'),
    ('SARL Ferme El Amal', 'Agriculture', 'ca12', 'SARL'),
    ('EURL Pharmacie Centrale', 'Commerce de détail', 'ca3', 'EURL'),
    ('SAS Digital Wave', 'Publicité en ligne', 'ca3', 'SAS'),
    ('SARL Menuiserie Bois Noble', 'Fabrication de meubles', 'ca3', 'SARL'),
    ('SCI Résidence Jasmin', 'Location immobilière', 'exonere', 'SCI'),
    ('SARL Auto Prestige', 'Entretien automobile', 'ca3', 'SARL'),
    ('EURL Cabinet Dentaire Sourire', 'Activités de santé', 'ca12', 'EURL'),
    ('SAS Logistique Express', 'Entreposage & logistique', 'ca3', 'SAS'),
    ('SARL Boulangerie La Mie Dorée', 'Commerce de détail', 'ca3', 'SARL'),
    ('SAS Conseil & Patrimoine', 'Conseil de gestion', 'ca3', 'SAS'),
    ('SARL Textile Sud Mode', 'Industrie textile', 'ca3', 'SARL'),
    ('EURL Jardin Vert', 'Services paysagers', 'ca12', 'EURL'),
    ('SAS Énergie Solaire Plus', 'Installation énergétique', 'ca3', 'SAS'),
    ('SARL Hôtel La Pergola', 'Hébergement & restauration', 'ca3', 'SARL'),
]

TACHES_TYPES = [
    ('Déclaration TVA {mois}', 'haute', 'Rapprochement des comptes de TVA, contrôle de la collecte et de la déductible, puis télédéclaration.'),
    ('Révision comptable {mois}', 'haute', 'Lettrage, revue des comptes de charges et produits, justification des soldes.'),
    ('Rapprochement bancaire {mois}', 'moyenne', 'Pointage des relevés et justification des écarts de trésorerie.'),
    ('DSN {mois}', 'haute', 'Contrôle des données de paie, dépôt de la DSN mensuelle et suivi des anomalies.'),
    ('Écritures de paie {mois}', 'moyenne', 'Intégration du journal de paie dans la comptabilité du dossier.'),
    ('Relance client — pièces manquantes', 'moyenne', 'Liste des justificatifs non reçus, relance par mail et suivi des retours.'),
    ('Établissement du bilan', 'haute', 'Clôture des comptes, immobilisations, provisions et liasse fiscale.'),
    ('Acompte IS', 'moyenne', 'Calcul et télérèglement de l’acompte d’impôt sur les sociétés.'),
    ('Contrôle des notes de frais', 'basse', 'Vérification des justificatifs et validation avant comptabilisation.'),
    ('Point hebdomadaire équipe', 'basse', 'Revue de l’avancement des dossiers et arbitrage des priorités.'),
    ('Archivage des pièces {mois}', 'basse', 'Classement et archivage numérique des justificatifs du mois.'),
    ('Déclaration CFE', 'moyenne', 'Vérification de la base d’imposition et préparation du règlement.'),
]

MOIS_FR = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet',
           'août', 'septembre', 'octobre', 'novembre', 'décembre']


def build():
    with app.app_context():
        if Dossier.query.count() > 0:
            print('Base déjà peuplée — seed ignoré.')
            return

        admin = User.query.filter_by(role='admin').first()
        pole_compta = Equipe(nom='Pôle Comptable', description='Tenue, révision et fiscalité des dossiers clients.',
                             couleur='#FF8C00', icon='bi-calculator', manager_id=admin.id if admin else None)
        pole_social = Equipe(nom='Pôle Social', description='Paie, DSN et déclarations sociales.',
                             couleur='#3B82F6', icon='bi-people', manager_id=admin.id if admin else None)
        db.session.add_all([pole_compta, pole_social])
        db.session.flush()

        users = []
        for prenom, nom, role, pole, poste in PERSONNES:
            u = User(email=f'{prenom.lower()}@cabinet-jmh.com', nom=nom, prenom=prenom,
                     role=role, pole=pole, poste=poste, actif=True,
                     equipe_id=pole_social.id if pole == 'social' else pole_compta.id,
                     date_arrivee=TODAY - timedelta(days=random.randint(120, 1600)),
                     telephone=f'+216 {random.randint(20, 99)} {random.randint(100, 999)} {random.randint(100, 999)}')
            u.set_password('OrbitDemo2026!')
            db.session.add(u)
            users.append(u)
        db.session.flush()

        managers = [u for u in users if u.role == 'manager']
        compta = [u for u in users if u.pole in ('comptable', 'les_deux') and u.role == 'membre']
        social = [u for u in users if u.pole in ('social', 'les_deux')]
        creator = admin or managers[0]

        dossiers = []
        for i, (intitule, secteur, regime, forme) in enumerate(ENTREPRISES, start=1):
            collab = compta[i % len(compta)]
            d = Dossier(
                numero_dossier=f'D-{2026}-{i:04d}', intitule=intitule,
                collaborateur_id=collab.id, equipe_id=pole_compta.id,
                regime_tva=regime, frequence_tva='mensuel' if regime == 'ca3' else 'trimestriel',
                date_limite_declaration=TODAY + timedelta(days=random.choice([-6, -2, 3, 7, 12, 18, 25])),
                regime_fiscale='reel', forme_juridique=forme, secteur_activite=secteur,
                has_cfe=(i % 3 != 0), honoraires_mensuel=round(random.uniform(180, 950), 2),
                siren=f'{random.randint(100000000, 999999999)}',
                dirigeant=f'{random.choice(["Ali", "Sonia", "Marc", "Leila", "Thomas", "Fatma"])} {random.choice(["Moreau", "Ben Ali", "Dubois", "Haddad", "Lefevre"])}',
                adresse_siege=f'{random.randint(1, 120)} avenue Habib Bourguiba, Tunis',
                etat_administratif='A', categorie_entreprise=random.choice(['PME', 'TPE']),
                date_creation_entreprise=TODAY - timedelta(days=random.randint(400, 4000)),
                date_creation=datetime.utcnow() - timedelta(days=random.randint(30, 900)),
            )
            if social and i % 2 == 0:
                d.collaborateur_social_id = random.choice(social).id
            db.session.add(d)
            dossiers.append(d)
        db.session.flush()

        taches = []
        for d in dossiers:
            for k in range(random.randint(4, 9)):
                titre_tpl, prio, desc = random.choice(TACHES_TYPES)
                mois_nom = MOIS_FR[(TODAY.month - 1 + random.choice([0, 0, 1])) % 12]
                titre = titre_tpl.format(mois=mois_nom)
                offset = random.choice([-18, -11, -7, -4, -2, -1, 0, 0, 1, 2, 3, 5, 8, 13, 21, 30])
                echeance = TODAY + timedelta(days=offset)
                if offset < -1:
                    statut = random.choices(['terminee', 'a_faire', 'en_cours'], weights=[6, 3, 1])[0]
                elif offset <= 2:
                    statut = random.choices(['en_cours', 'a_faire', 'terminee'], weights=[5, 4, 1])[0]
                else:
                    statut = random.choices(['a_faire', 'en_cours'], weights=[8, 2])[0]
                assigne = d.collaborateur
                if 'DSN' in titre or 'paie' in titre:
                    assigne = d.social or (random.choice(social) if social else d.collaborateur)
                t = Tache(titre=titre, description=desc, dossier_id=d.id,
                          assigne_a=assigne.id if assigne else None, cree_par=creator.id,
                          priorite=prio, statut=statut, date_echeance=echeance,
                          date_creation=datetime.utcnow() - timedelta(days=random.randint(2, 40)))
                if statut in ('en_cours', 'terminee'):
                    t.date_prise_en_charge = datetime.utcnow() - timedelta(days=random.randint(1, 10))
                if statut == 'terminee':
                    t.date_completion = t.date_prise_en_charge + timedelta(hours=random.randint(4, 72))
                    t.statut_source = 'manuel'
                db.session.add(t)
                taches.append(t)
        db.session.flush()

        for t in random.sample(taches, min(28, len(taches))):
            if not t.assigne_a:
                continue
            db.session.add(Notification(
                user_id=t.assigne_a, tache_id=t.id,
                message=f'Nouvelle tâche assignée : {t.titre}' + (f' ({t.dossier.numero_dossier})' if t.dossier else ''),
                lu=random.random() < 0.45, type_notification='assignation',
                date_envoi=datetime.utcnow() - timedelta(hours=random.randint(1, 96))))
        for t in random.sample([x for x in taches if x.statut == 'terminee'], 12):
            db.session.add(Notification(
                user_id=creator.id, tache_id=t.id,
                message=f'{t.assigne.prenom} {t.assigne.nom} a terminé « {t.titre} ».',
                lu=random.random() < 0.3, type_notification='completion',
                date_envoi=datetime.utcnow() - timedelta(hours=random.randint(1, 60))))

        for t in random.sample(taches, 14):
            auteur = random.choice(users)
            db.session.add(CommentaireTache(
                tache_id=t.id, user_id=auteur.id,
                message=random.choice([
                    'Pièces reçues, je commence le lettrage demain matin.',
                    'Il manque le relevé bancaire du mois, relance envoyée au client.',
                    'Écart de TVA justifié par une facture d’avoir non comptabilisée.',
                    'RAS de mon côté, en attente de validation du chef de mission.',
                    'Dossier prioritaire : échéance déclarative vendredi.',
                ]),
                date_creation=datetime.utcnow() - timedelta(hours=random.randint(2, 200))))

        for d in dossiers[:14]:
            for m in range(max(1, TODAY.month - 2), TODAY.month + 1):
                taxe = 'tva_mensuel' if d.regime_tva == 'ca3' else 'tva_trimestriel'
                declare = random.random() < (0.85 if m < TODAY.month else 0.35)
                db.session.add(ChecklistEntry(
                    dossier_id=d.id, taxe=taxe, annee=TODAY.year, mois=m, kind='declaration',
                    declare=declare, paye=declare and random.random() < 0.8,
                    updated_by_id=d.collaborateur_id,
                    date_modif=datetime.utcnow() - timedelta(days=random.randint(1, 45))))

        for d in random.sample(dossiers, 9):
            for n in range(random.randint(2, 7)):
                kind = random.choice(['facture_vente', 'facture_achat', 'transaction'])
                db.session.add(PennylaneItem(
                    dossier_id=d.id, item_type=kind, item_id=f'pl_{d.id}_{n}_{random.randint(1000, 9999)}',
                    reference=(f'FA-2026-{random.randint(100, 999)}' if kind == 'facture_vente'
                               else f'FF-{random.randint(1000, 9999)}' if kind == 'facture_achat'
                               else f'Virement {random.choice(["loyer", "fournisseur", "salaire", "EDF"])}'),
                    montant=round(random.uniform(45, 8400), 2),
                    date_item=(TODAY - timedelta(days=random.randint(0, 25))).isoformat(),
                    statut=random.choices(['a_traiter', 'traite', 'ignore'], weights=[7, 2, 1])[0],
                    api_statut=random.choice(['affected', 'paid', 'draft']),
                    vu_premiere_fois=datetime.utcnow() - timedelta(days=random.randint(0, 20))))

        for d in random.sample(dossiers, 6):
            db.session.add(SuggestionTache(
                sujet=f'Échéance déclarative — {d.intitule}',
                corps=f'La date limite de déclaration du dossier {d.numero_dossier} approche. Une tâche de préparation est proposée automatiquement.',
                dossier_id=d.id, titre_suggere=f'Préparer la déclaration TVA — {d.intitule}',
                description_suggeree='Rassembler les pièces, contrôler la TVA collectée/déductible et préparer la télédéclaration.',
                statut='en_attente', priorite_suggeree='haute', cree_par=creator.id,
                date_creation=datetime.utcnow() - timedelta(days=random.randint(1, 8))))

        for u in users[:6]:
            db.session.add(Rappel(
                user_id=u.id, titre=random.choice(['Relancer le client Atlas', 'Valider le journal de paie',
                                                   'Préparer la réunion hebdo', 'Vérifier les acomptes IS']),
                message='Rappel personnel créé depuis la fiche dossier.',
                date_echeance=TODAY + timedelta(days=random.choice([0, 1, 2, 5, 9])),
                date_creation=datetime.utcnow() - timedelta(days=random.randint(1, 6)),
                lu=False, source='manuel'))

        db.session.commit()
        print(f'Seed terminé : {len(users)} membres, {len(dossiers)} dossiers, {len(taches)} tâches.')
        print('Connexion : admin@cabinet-jmh.com (mot de passe admin defini en local)  (membres : prenom@cabinet-jmh.com / OrbitDemo2026!)')


if __name__ == '__main__':
    build()