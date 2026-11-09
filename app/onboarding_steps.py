"""Définition du pipeline d'onboarding — transposition fidèle du classeur
« SUIVI NOUVEAUX DOSSIERS » du cabinet (onglets LEGENDE + SUIVI NOUVEAUX DOSSIERS
+ SUIVI DOSSIERS PARTIS). Données pures, aucune dépendance à la base.

L'étape « Création Doss ACD » du fichier devient « Création dossier Pennylane »
(le cabinet utilise Pennylane, pas ACD).
"""

# Phase -> libellé affiché
ONBOARDING_PHASES = {
    1: 'Contractuel',
    2: 'Juridique (création)',
    3: 'Installation',
    4: 'Facturation & mandats',
    5: 'Équipe',
}

# (code, libellé, phase, applicable) — applicable: tous | creation | reprise
# L'ordre EST celui des colonnes du fichier Excel (import/export fidèle).
ONBOARDING_ETAPES = [
    ('ldm_editee',            'Édition lettre de mission',           1, 'tous'),
    ('ldm_signee',            'Lettre de mission signée',            1, 'tous'),
    ('mail_deontologie',      'Mail déontologie ancien EC',          1, 'reprise'),
    ('retour_docs_ancien_ec', 'Retour documents ancien EC',          1, 'reprise'),
    ('projet_statuts',        'Projet de statuts',                   2, 'creation'),
    ('certificat_dep_k',      'Certificat de dépôt K',               2, 'creation'),
    ('juridique_creation',    'Juridique création',                  2, 'creation'),
    ('retour_jurid_creation', 'Retour juridique création signé',     2, 'creation'),
    ('statuts',               'Statuts',                             2, 'creation'),
    ('kbis',                  'KBIS',                                2, 'creation'),
    ('dossier_pennylane',     'Création dossier Pennylane',          3, 'tous'),
    ('invitation_client',    'Inviter le client',                   3, 'tous'),
    ('rib',                   'RIB',                                 3, 'tous'),
    ('adhesion_imots',        'Adhésion/Substitution imots.gouv',    3, 'tous'),
    ('code_impots',           'Code impôts',                         3, 'tous'),
    ('envoi_ldm_facturation', 'Envoi LDM / facturation',             4, 'tous'),
    ('mandat_prlvt',          'Mandat de prélèvement',               4, 'tous'),
    ('retour_mandat_prlvt',   'Retour mandat de prélèvement signé',  4, 'tous'),
    ('mandat_so_bank',        'Mandat So bank',                      4, 'tous'),
    ('retour_yasmina',        'Retour Yasmina',                      4, 'tous'),
    ('retour_mandat_so_bank', 'Retour mandat So bank signé',         4, 'tous'),
    ('mail_identite_collabs', 'Mail identité collaborateurs envoyé', 5, 'tous'),
]

ONBOARDING_CODES = [e[0] for e in ONBOARDING_ETAPES]

TYPES_DOSSIER = {
    'creation': 'Création',
    'reprise': 'Reprise',
    'revision': 'Revision',
}


def etapes_pour_type(type_dossier):
    """Étapes applicables à un type de dossier (Création exclut le volet
    « ancien EC » et le volet juridique ; Reprise/Revision excluent le juridique)."""
    out = []
    for code, label, phase, applicable in ONBOARDING_ETAPES:
        if applicable == 'tous' or applicable == type_dossier:
            out.append((code, label, phase))
    return out


def phase_de(code):
    for c, _l, phase, _a in ONBOARDING_ETAPES:
        if c == code:
            return phase
    return 0


def etape_label(code):
    for c, l, _p, _a in ONBOARDING_ETAPES:
        if c == code:
            return l
    return code
