"""onboarding — suivi des nouveaux dossiers et des dossiers partis.

Remplace le classeur « Suivi Nouveaux Doss CABINET JMH.xlsx » :
grille par phases + barre d'avancement + mails automatiques (Brevo, fallback
SMTP) + import d'une liste préparée selon le modèle Excel du cabinet.
"""
from io import BytesIO
import json
import re
import secrets
import unicodedata
from datetime import date, datetime

from flask import (render_template, request, redirect, url_for, flash,
                   send_file, abort, jsonify)
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash

from . import app, db
from .models import (OnboardingDossier, OnboardingEtape, OnboardingDepart,
                     OnboardingMail, OnboardingActionMail, AnnuaireCategorie,
                     FicheAnnuaire, AppSetting, User, Notification)
from .onboarding_steps import (ONBOARDING_ETAPES, ONBOARDING_PHASES,
                               ONBOARDING_CODES, etapes_pour_type,
                               etape_label, TYPES_DOSSIER)


# ---------------------------------------------------------------------------
# Droits & petits utilitaires
# ---------------------------------------------------------------------------
def _peut_editer():
    return current_user.role in ('admin', 'manager')


def _refuse_edition():
    flash('Modification réservée aux managers et admins.', 'danger')
    return redirect(url_for('onboarding'))


def _to_date(v):
    """Date ISO 'YYYY-MM-DD' (input date) -> date, sinon None."""
    if not v:
        return None
    try:
        return datetime.strptime(str(v).strip(), '%Y-%m-%d').date()
    except ValueError:
        return None


def _setting(cle, default=''):
    s = AppSetting.query.filter_by(cle=cle).first()
    if s and s.valeur:
        return s.valeur.strip()
    return default


def _norm(text):
    """Normalise un en-tête Excel : minuscules, sans accents, espaces réduits."""
    if text is None:
        return ''
    t = str(text).lower().strip()
    t = ''.join(c for c in unicodedata.normalize('NFD', t) if unicodedata.category(c) != 'Mn')
    t = re.sub(r'\s+', ' ', t)
    return t


# En-têtes Excel normalisés -> champ cible (étapes incluses)
HEADER_MAP = {
    'auteur': 'auteur',
    'nom dossier': 'nom_dossier',
    'nom client': 'nom_client',
    'mail': 'mail',
    'n tel': 'telephone', 'no tel': 'telephone', 'n° tel': 'telephone',
    'ec/chef de mission': 'ec_chef_mission', 'ec/chef de mission ': 'ec_chef_mission',
    'etablissement': 'etablissement',
    'creation/reprise': 'type_dossier', 'creation/reprise ': 'type_dossier',
    'polyacte': 'polyacte',
    'honoraires /an (compta+jurid) ht': 'honoraires_an',
    'date debut mission': 'date_debut_mission',
    'social (oui / non)': 'social', 'social (oui/non)': 'social',
    'edition lettre de mission': 'ldm_editee',
    'lettre de mission signee': 'ldm_signee',
    'mail deon ancien ec': 'mail_deontologie',
    'retour docs ancien ec': 'retour_docs_ancien_ec',
    'projet de statuts': 'projet_statuts',
    'certificat de dep k': 'certificat_dep_k',
    'juridique creation': 'juridique_creation',
    'retour jurid creation signe': 'retour_jurid_creation',
    'statuts': 'statuts_etape',
    'kbis': 'kbis',
    'creation doss acd': 'dossier_pennylane',
    'creation dossier pennylane': 'dossier_pennylane',
    'activ isuite': 'invitation_client',  # ancien libellé Excel conservé pour compat
    'inviter le client': 'invitation_client', 'invitation client': 'invitation_client',
    'rib': 'rib',
    'adhesion/substit imots.gouv': 'adhesion_imots',
    'code impots': 'code_impots',
    'envoi ldm/ facturation': 'envoi_ldm_facturation',
    'mandat de prlvt': 'mandat_prlvt',
    'retour m prlvt signe': 'retour_mandat_prlvt',
    'mandat so bank': 'mandat_so_bank',
    'retour yasmina': 'retour_yasmina',
    'retour mandat so bank signe': 'retour_mandat_so_bank',
    'collaborateur comptable': 'collab_comptable',
    'collaborateur social': 'collab_social',
    'collaborateur juridique': 'collab_juridique',
    'envoi au client mail identite des collaborateurs': 'mail_identite_collabs',
    'commentaires': 'commentaires',
}

ETAPE_FIELDS = [c for c in ONBOARDING_CODES]


# ---------------------------------------------------------------------------
# Actions automatiques par étape (configurables dans Paramètres)
# ---------------------------------------------------------------------------
# Tokens destinataires : 'client' | 'resp:<cle>' | 'user:<id>' | 'email:<addr>'
#                       | 'setting:<CLE>'
_TOKENS_RESP = {
    'chef_mission': 'chef_mission_id',
    'expert_comptable': 'expert_comptable_id',
    'resp_juridique': 'resp_juridique_id',
    'resp_social': 'resp_social_id',
}
_LIBELLES_RESP = {
    'chef_mission': 'Chef de mission',
    'expert_comptable': 'Expert-comptable',
    'resp_juridique': 'Responsable juridique',
    'resp_social': 'Responsable social',
}
_SETTINGS_RESP = {
    'chef_mission': 'ONBOARDING_RESP_CHEF_MISSION',
    'expert_comptable': 'ONBOARDING_RESP_EXPERT_COMPTABLE',
    'resp_juridique': 'ONBOARDING_RESP_JURIDIQUE',
    'resp_social': 'ONBOARDING_RESP_SOCIAL',
}

# Anciennes étapes codées en dur -> seeds d'actions (sujets/corps identiques)


def _user_du_setting(cle):
    """User référencé par un réglage « ONBOARDING_RESP_* » (id de membre)."""
    v = _setting(cle)
    if v and v.isdigit():
        return db.session.get(User, int(v))
    return None


def _nom(u):
    return u.nom_complet() if u else ''


def _vars_modele(d):
    """Variables disponibles dans les modèles de mail des actions."""
    chef = d.chef_mission or _user_du_setting('ONBOARDING_RESP_CHEF_MISSION')
    expert = d.expert_comptable or _user_du_setting('ONBOARDING_RESP_EXPERT_COMPTABLE')
    jurid = d.resp_juridique or _user_du_setting('ONBOARDING_RESP_JURIDIQUE')
    social = d.resp_social or _user_du_setting('ONBOARDING_RESP_SOCIAL')
    return {
        'client': d.nom_client or '',
        'dossier': d.nom_dossier or '',
        'etablissement': d.etablissement or '',
        'etape': '',
        'ec': d.ec_chef_mission or _nom(chef),
        'chef_mission': _nom(chef) or d.ec_chef_mission or '',
        'expert_comptable': _nom(expert),
        'resp_juridique': _nom(jurid) or d.collab_juridique or '',
        'resp_social': _nom(social) or d.collab_social or '',
    }


def _rendre(texte, vars_):
    """Remplace {{variable}} par sa valeur (variables inconnues -> vides)."""
    if not texte:
        return ''
    out = str(texte)
    for k, v in vars_.items():
        out = out.replace('{{' + k + '}}', str(v or ''))
    return re.sub(r'\{\{\s*\w+\s*\}\}', '', out)


def _email_pour_token(token, d):
    """Token -> (email | None, info_manquant | None)."""
    token = (token or '').strip()
    if token == 'client':
        email = (d.mail or '').strip()
        if '@' in email:
            return email, None
        return None, {'token': token, 'type': 'client',
                      'libelle': f'Client — {d.nom_client or d.nom_dossier}'}
    if token.startswith('resp:'):
        cle = token.split(':', 1)[1]
        if cle in _TOKENS_RESP:
            u = getattr(d, cle, None) or _user_du_setting(_SETTINGS_RESP[cle])
            if u and u.email:
                return u.email, None
            return None, {'token': token, 'type': 'resp', 'role_resp': cle,
                          'libelle': _LIBELLES_RESP[cle]}
    if token.startswith('user:'):
        try:
            u = db.session.get(User, int(token.split(':', 1)[1]))
        except ValueError:
            u = None
        if u and u.email:
            return u.email, None
        return None, {'token': token, 'type': 'user',
                      'libelle': 'Membre du cabinet (fiche introuvable ou sans email)'}
    if token.startswith('email:'):
        addr = token.split(':', 1)[1].strip()
        if '@' in addr:
            return addr, None
        return None, {'token': token, 'type': 'email',
                      'libelle': 'Adresse email invalide'}
    if token.startswith('setting:'):
        val = _setting(token.split(':', 1)[1])
        if '@' in val:
            return val, None
        return None, {'token': token, 'type': 'setting',
                      'libelle': f"Réglage {token.split(':', 1)[1]} (non configuré)"}
    return None, {'token': token, 'type': 'autre', 'libelle': token}


def _action_etape(code):
    return OnboardingActionMail.query.filter_by(etape_code=code).first()


def _executer_action(d, code, skip=None):
    """Exécute l'action mail configurée pour l'étape (si active).
    Retourne (mails: [{destinataire, statut, erreur}], manquants: [info])."""
    action = _action_etape(code)
    if not action or not action.actif:
        return [], []
    vars_ = _vars_modele(d)
    sujet = _rendre(action.sujet, vars_) or f"Cabinet JMH — {d.nom_dossier}"
    corps = _rendre(action.corps, vars_) or f"Dossier {d.nom_dossier} : étape « {etape_label(code)} » complétée."
    skip_set = {(s or '').lower() for s in (skip or [])}
    mails, manquants = [], []
    for token in action.tokens():
        email, info = _email_pour_token(token, d)
        if email:
            if email.lower() in skip_set:
                continue
            ok, err = _envoyer_mail(code, email, sujet, corps, dossier_onb=d)
            mails.append({'destinataire': email, 'statut': 'envoye' if ok else 'erreur',
                          'erreur': err})
        elif info:
            manquants.append(info)
    return mails, manquants


def _seed_actions_defaut():
    """Crée les actions par défaut (anciens mails codés en dur + invitation
    client). Idempotent : n'écrase jamais une config déjà modifiée."""
    defauts = {
        'envoi_ldm_facturation': {
            'sujet': 'Cabinet JMH — Lettre de mission & facturation ({{dossier}})',
            'corps': ("Bonjour {{client}},\n\n"
                      "Nous vous confirmons l'envoi de la lettre de mission et des éléments "
                      "de facturation concernant votre dossier {{dossier}}.\n\n"
                      "Merci de nous retourner la lettre de mission signée.\n\n"
                      "Cordialement,\nCabinet JMH"),
            'destinataires': ['client'],
        },
        'invitation_client': {
            'sujet': 'Cabinet JMH — Votre accès client ({{dossier}})',
            'corps': ("Bonjour {{client}},\n\n"
                      "Votre dossier {{dossier}} est créé au sein du Cabinet JMH.\n\n"
                      "Vous allez recevoir une invitation vous permettant d'accéder à votre "
                      "espace client sécurisé (documents, pièces comptables, échanges avec "
                      "votre équipe).\n\n"
                      "Notre équipe reste à votre disposition pour vous accompagner lors de "
                      "votre première connexion.\n\n"
                      "Cordialement,\nCabinet JMH"),
            'destinataires': ['client'],
        },
        'mail_identite_collabs': {
            'sujet': 'Cabinet JMH — Vos interlocuteurs ({{dossier}})',
            'corps': ("Bonjour {{client}},\n\n"
                      "Votre dossier {{dossier}} est désormais installé. Voici vos interlocuteurs :\n\n"
                      "• EC / chef de mission : {{ec}}\n"
                      "• Juridique : {{resp_juridique}}\n"
                      "• Social : {{resp_social}}\n\n"
                      "Ils restent à votre disposition pour toute question.\n\n"
                      "Cordialement,\nCabinet JMH"),
            'destinataires': ['client'],
        },
    }
    try:
        for code, cfg in defauts.items():
            if OnboardingActionMail.query.filter_by(etape_code=code).first() is None:
                db.session.add(OnboardingActionMail(
                    etape_code=code, actif=True, sujet=cfg['sujet'],
                    corps=cfg['corps'], destinataires=json.dumps(cfg['destinataires'])))
        db.session.commit()
    except Exception:
        db.session.rollback()


# ---------------------------------------------------------------------------
# Corps de mails
# ---------------------------------------------------------------------------
def _corps_ldm_facturation(d):
    return (
        f"Bonjour {d.nom_client or ''},\n\n"
        f"Nous vous confirmons l'envoi de la lettre de mission et des éléments de facturation "
        f"concernant votre dossier {d.nom_dossier}.\n\n"
        f"Merci de nous retourner la lettre de mission signée.\n\n"
        f"Cordialement,\nCabinet JMH"
    )


def _corps_identite(d):
    lignes = []
    if d.collab_comptable:
        lignes.append(f"• Comptable : {d.collab_comptable}")
    if d.collab_social and d.social:
        lignes.append(f"• Social : {d.collab_social}")
    if d.collab_juridique:
        lignes.append(f"• Juridique : {d.collab_juridique}")
    return (
        f"Bonjour {d.nom_client or ''},\n\n"
        f"Votre dossier {d.nom_dossier} est désormais installé. Voici vos interlocuteurs :\n\n"
        + ("\n".join(lignes) or '• (à compléter)')
        + "\n\nIls restent à votre disposition pour toute question.\n\n"
        f"Cordialement,\nCabinet JMH"
    )


def _corps_deontologie(d):
    return (
        f"Bonjour,\n\n"
        f"Le dossier de votre client {d.nom_client or d.nom_dossier} est repris par le Cabinet JMH "
        f"à compter de {d.date_debut_mission.strftime('%d/%m/%Y') if d.date_debut_mission else 'à définir'}.\n\n"
        f"Conformément aux règles déontologiques de la profession, merci de nous transmettre "
        f"le dossier et les pièces nécessaires à la poursuite de la mission.\n\n"
        f"Cordialement,\nCabinet JMH"
    )


def _corps_facturation_depart(dep):
    return (
        f"Bonjour,\n\n"
        f"Le client {dep.nom_client or dep.nom_dossier} quitte le cabinet "
        f"(départ {dep.date_depart.strftime('%d/%m/%Y') if dep.date_depart else 'à définir'}).\n\n"
        f"Merci de :\n"
        f"• stoper la facturation à compter de cette date ;\n"
        f"• désactiver le dossier Pennylane.\n\n"
        f"Cordialement,\nCabinet JMH"
    )


def _corps_rappel(d):
    c, l, _p = d.prochaine_etape()
    return (
        f"Bonjour,\n\n"
        f"Dossier {d.nom_dossier} ({d.nom_client or ''}) : l'étape « {l} » est en attente "
        f"depuis {d.jours_attente()} jours.\n\n"
        f"Merci de la traiter dans Orbit (Suivi nouveaux dossiers).\n\n"
        f"Cabinet JMH — rappel automatique"
    )


def _envoyer_mail(type_mail, destinataire, sujet, corps, dossier_onb=None, depart=None):
    """Envoie (Brevo/SMTP), trace dans onboarding_mails, retourne (ok, erreur)."""
    ok, err = False, None
    if not destinataire or '@' not in destinataire:
        err = 'Destinataire manquant ou invalide'
    else:
        try:
            from .integrations.brevo import send_email_via_brevo_api
            ok = send_email_via_brevo_api(to_email=destinataire.strip(), subject=sujet, body=corps)
            if not ok:
                err = 'Envoi en échec (Brevo/SMTP non configuré ou refusé)'
        except Exception as e:
            err = str(e)[:400]
    db.session.add(OnboardingMail(
        dossier_onb_id=dossier_onb.id if dossier_onb else None,
        depart_id=depart.id if depart else None,
        type_mail=type_mail, destinataire=(destinataire or '')[:200],
        sujet=sujet[:300], statut='envoye' if ok else 'erreur', erreur=err,
        envoye_par_id=current_user.id,
    ))
    db.session.commit()
    return ok, err


# ---------------------------------------------------------------------------
# Liste : 2 onglets + filtres + KPI
# ---------------------------------------------------------------------------
@app.route('/onboarding')
@login_required
def onboarding():
    tab = request.args.get('tab', 'nouveaux')
    q = (request.args.get('q') or '').strip()
    ftype = request.args.get('type') or ''
    fetab = request.args.get('etab') or ''

    query = OnboardingDossier.query
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(OnboardingDossier.nom_dossier.ilike(like),
                                    OnboardingDossier.nom_client.ilike(like)))
    if ftype in TYPES_DOSSIER:
        query = query.filter(OnboardingDossier.type_dossier == ftype)
    if fetab:
        query = query.filter(OnboardingDossier.etablissement == fetab)
    dossiers = query.order_by(OnboardingDossier.date_creation.desc()).all()

    partis = OnboardingDepart.query.order_by(OnboardingDepart.date_creation.desc()).all()

    etablissements = sorted({d.etablissement for d in OnboardingDossier.query.with_entities(
        OnboardingDossier.etablissement).all() if d.etablissement})

    en_cours = [d for d in dossiers if d.statut == 'en_cours']
    kpis = {
        'total': len(dossiers),
        'en_cours': len(en_cours),
        'termines': len(dossiers) - len(en_cours),
        'bloques': sum(1 for d in en_cours if d.prochaine_etape() and d.jours_attente() >= _seuil_rappel()),
        'honoraires': sum(d.honoraires_an or 0 for d in en_cours),
    }
    kpis_partis = {'total': len(partis),
                   'ce_mois': sum(1 for p in partis if p.date_depart and
                                  p.date_depart.month == date.today().month and
                                  p.date_depart.year == date.today().year)}
    membres_actifs = User.query.filter_by(actif=True).order_by(User.prenom, User.nom).all()
    resp_prefill = {f'{cle}_id': (_user_du_setting(val).id if _user_du_setting(val) else None)
                    for cle, val in _SETTINGS_RESP.items()}
    return render_template('onboarding.html', tab=tab, dossiers=dossiers, partis=partis,
                           kpis=kpis, kpis_partis=kpis_partis, q=q, ftype=ftype, fetab=fetab,
                           etablissements=etablissements, types=TYPES_DOSSIER,
                           phases=ONBOARDING_PHASES, seuil_rappel=_seuil_rappel(),
                           membres_actifs=membres_actifs, resp_prefill=resp_prefill,
                           peut_editer=_peut_editer())


def _seuil_rappel():
    try:
        return int(_setting('ONBOARDING_RAPPEL_JOURS', '7'))
    except ValueError:
        return 7


# ---------------------------------------------------------------------------
# Nouveau dossier + fiche détail
# ---------------------------------------------------------------------------
@app.route('/onboarding/nouveau', methods=['POST'])
@login_required
def onboarding_nouveau():
    if not _peut_editer():
        return _refuse_edition()
    nom = (request.form.get('nom_dossier') or '').strip()
    if not nom:
        flash('Le nom du dossier est obligatoire.', 'warning')
        return redirect(url_for('onboarding'))
    d = OnboardingDossier(
        auteur=(request.form.get('auteur') or '').strip() or None,
        nom_dossier=nom,
        nom_client=(request.form.get('nom_client') or '').strip() or None,
        mail=(request.form.get('mail') or '').strip() or None,
        telephone=(request.form.get('telephone') or '').strip() or None,
        ec_chef_mission=(request.form.get('ec_chef_mission') or '').strip() or None,
        etablissement=(request.form.get('etablissement') or '').strip() or None,
        type_dossier=request.form.get('type_dossier') if request.form.get('type_dossier') in TYPES_DOSSIER else 'creation',
        polyacte=request.form.get('polyacte') == 'on',
        honoraires_an=request.form.get('honoraires_an', type=float),
        date_debut_mission=_to_date(request.form.get('date_debut_mission')),
        social=request.form.get('social') == 'on',
        collab_comptable=(request.form.get('collab_comptable') or '').strip() or None,
        collab_social=(request.form.get('collab_social') or '').strip() or None,
        collab_juridique=(request.form.get('collab_juridique') or '').strip() or None,
        commentaires=(request.form.get('commentaires') or '').strip() or None,
        dossier_id=request.form.get('dossier_id', type=int) or None,
        cree_par_id=current_user.id,
    )
    # Responsables pré-remplis depuis les réglages (modifiables par dossier)
    def _resp(champ, setting_cle):
        v = request.form.get(champ, type=int)
        if v:
            return v
        v = _setting(setting_cle)
        return int(v) if v and v.isdigit() else None
    d.chef_mission_id = _resp('chef_mission_id', 'ONBOARDING_RESP_CHEF_MISSION')
    d.expert_comptable_id = _resp('expert_comptable_id', 'ONBOARDING_RESP_EXPERT_COMPTABLE')
    d.resp_juridique_id = _resp('resp_juridique_id', 'ONBOARDING_RESP_JURIDIQUE')
    d.resp_social_id = _resp('resp_social_id', 'ONBOARDING_RESP_SOCIAL')
    db.session.add(d)
    db.session.flush()
    for code in ONBOARDING_CODES:
        db.session.add(OnboardingEtape(dossier_onb_id=d.id, code=code))
    db.session.commit()
    flash(f"Dossier « {nom} » créé avec son pipeline complet.", 'success')
    return redirect(url_for('onboarding_detail', dossier_id=d.id))


@app.route('/onboarding/<int:dossier_id>')
@login_required
def onboarding_detail(dossier_id):
    d = db.session.get(OnboardingDossier, dossier_id)
    if d is None:
        abort(404)
    mails = OnboardingMail.query.filter_by(dossier_onb_id=d.id).order_by(
        OnboardingMail.sent_at.desc()).limit(20).all()
    # Étapes groupées par phase dans l'ordre du pipeline
    par_phase = {p: [] for p in ONBOARDING_PHASES}
    for code, label, phase in d.etapes_applicables():
        par_phase[phase].append((code, label, d.etape(code)))
    membres_actifs = User.query.filter_by(actif=True).order_by(User.prenom, User.nom).all()
    categories_annuaire = AnnuaireCategorie.query.order_by(AnnuaireCategorie.ordre,
                                                           AnnuaireCategorie.nom).all()
    mail_labels = {
        'ldm_facturation': 'Lettre de mission / facturation',
        'identite': 'Identité collaborateurs',
        'deontologie': 'Déontologie ancien EC',
        'facturation_depart': 'Stop facturation (départ)',
        'rappel': 'Rappel automatique',
        'test_action': 'Test d\'action',
    }
    mail_labels.update({code: etape_label(code) for code in ONBOARDING_CODES})
    return render_template('onboarding_detail.html', d=d, par_phase=par_phase,
                           phases=ONBOARDING_PHASES, mails=mails,
                           mail_labels=mail_labels, membres_actifs=membres_actifs,
                           categories_annuaire=categories_annuaire,
                           types=TYPES_DOSSIER, peut_editer=_peut_editer())


@app.route('/onboarding/<int:dossier_id>/maj', methods=['POST'])
@login_required
def onboarding_maj(dossier_id):
    if not _peut_editer():
        return _refuse_edition()
    d = db.session.get(OnboardingDossier, dossier_id)
    if d is None:
        abort(404)
    d.auteur = (request.form.get('auteur') or '').strip() or None
    d.nom_dossier = (request.form.get('nom_dossier') or '').strip() or d.nom_dossier
    d.nom_client = (request.form.get('nom_client') or '').strip() or None
    d.mail = (request.form.get('mail') or '').strip() or None
    d.telephone = (request.form.get('telephone') or '').strip() or None
    d.ec_chef_mission = (request.form.get('ec_chef_mission') or '').strip() or None
    d.etablissement = (request.form.get('etablissement') or '').strip() or None
    t = request.form.get('type_dossier')
    if t in TYPES_DOSSIER and t != d.type_dossier:
        d.type_dossier = t  # recrée les lignes d'étapes pour le nouveau type
        for code in ONBOARDING_CODES:
            if not d.etape(code):
                db.session.add(OnboardingEtape(dossier_onb_id=d.id, code=code))
    d.polyacte = request.form.get('polyacte') == 'on'
    d.honoraires_an = request.form.get('honoraires_an', type=float)
    d.date_debut_mission = _to_date(request.form.get('date_debut_mission'))
    d.social = request.form.get('social') == 'on'
    d.collab_comptable = (request.form.get('collab_comptable') or '').strip() or None
    d.collab_social = (request.form.get('collab_social') or '').strip() or None
    d.collab_juridique = (request.form.get('collab_juridique') or '').strip() or None
    d.commentaires = (request.form.get('commentaires') or '').strip() or None
    d.dossier_id = request.form.get('dossier_id', type=int) or None
    d.chef_mission_id = request.form.get('chef_mission_id', type=int) or None
    d.expert_comptable_id = request.form.get('expert_comptable_id', type=int) or None
    d.resp_juridique_id = request.form.get('resp_juridique_id', type=int) or None
    d.resp_social_id = request.form.get('resp_social_id', type=int) or None
    db.session.commit()
    flash('Fiche mise à jour.', 'success')
    return redirect(url_for('onboarding_detail', dossier_id=d.id))


@app.route('/onboarding/<int:dossier_id>/etape', methods=['POST'])
@login_required
def onboarding_etape(dossier_id):
    if not _peut_editer():
        return _refuse_edition()
    d = db.session.get(OnboardingDossier, dossier_id)
    if d is None:
        abort(404)
    code = request.form.get('code')
    if code not in ONBOARDING_CODES:
        abort(400)
    s = d.etape(code)
    if s is None:
        s = OnboardingEtape(dossier_onb_id=d.id, code=code)
        db.session.add(s)
    nouvelle_date = _to_date(request.form.get('date_fait'))
    if not nouvelle_date:
        nouvelle_date = date.today() if request.form.get('marquer') == '1' else None
    s.date_fait = nouvelle_date
    s.sans_date = bool(request.form.get('sans_date')) and not nouvelle_date
    s.commentaire = (request.form.get('commentaire') or '').strip() or None
    s.fait_par_id = current_user.id if s.est_fait else None
    db.session.commit()

    # Action automatique configurée pour cette étape (Paramètres) — optionnelle
    mails, manquants = ([], [])
    if s.est_fait:
        mails, manquants = _executer_action(d, code)
    db.session.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'ok': True,
                        'date_fait': s.date_fait.isoformat() if s.date_fait else None,
                        'sans_date': bool(s.sans_date),
                        'est_fait': s.est_fait,
                        'mails': mails, 'manquants': manquants})

    for r in mails:
        flash(f"Mail « {etape_label(code)} » → {r['destinataire']} : "
              + ('envoyé.' if r['statut'] == 'envoye' else f"échec ({r['erreur']})"),
              'success' if r['statut'] == 'envoye' else 'warning')
    if manquants:
        flash('Destinataire sans email (' + ', '.join(m['libelle'] for m in manquants)
              + ') — complétez sa fiche depuis la fiche du dossier.', 'warning')
    return redirect(url_for('onboarding_detail', dossier_id=d.id))


@app.route('/onboarding/<int:dossier_id>/etape/<code>/destinataire', methods=['POST'])
@login_required
def onboarding_etape_destinataire(dossier_id, code):
    """Popup « destinataire sans email » : crée la fiche manquante (membre du
    cabinet ou fiche annuaire hors cabinet), rattache le responsable si
    nécessaire, puis (re)lance l'action de l'étape."""
    if not _peut_editer():
        return jsonify({'ok': False, 'message': 'Modification réservée aux managers et admins.'}), 403
    d = db.session.get(OnboardingDossier, dossier_id)
    if d is None:
        abort(404)
    if code not in ONBOARDING_CODES:
        abort(400)
    data = request.get_json(silent=True) or {}
    token = (data.get('token') or '').strip()
    email = (data.get('email') or '').strip()
    if not email or '@' not in email:
        return jsonify({'ok': False, 'message': 'Adresse email obligatoire.'}), 400

    role_resp = None
    if token.startswith('resp:'):
        cle = token.split(':', 1)[1]
        if cle in _TOKENS_RESP:
            role_resp = cle
    nom_fiche = (data.get('nom') or '').strip() or (data.get('libelle') or 'Contact').strip()

    try:
        if data.get('mode') == 'cabinet':
            addr = email.lower()
            if User.query.filter_by(email=addr).first():
                return jsonify({'ok': False,
                                'message': 'Un membre utilise déjà cet email.'}), 400
            pole = data.get('pole') if data.get('pole') in (
                'comptable', 'social', 'juridique', 'les_deux') else 'comptable'
            role = data.get('role') if (
                data.get('role') in ('membre', 'manager')
                and current_user.role in ('admin', 'manager')) else 'membre'
            if role == 'manager' and current_user.role != 'admin':
                role = 'membre'
            u = User(email=addr, prenom=(data.get('prenom') or '').strip() or '—',
                     nom=nom_fiche[:80], role=role, pole=pole,
                     poste=(data.get('poste') or '').strip() or None,
                     telephone=(data.get('telephone') or '').strip() or None,
                     password_hash=generate_password_hash(secrets.token_urlsafe(12)),
                     actif=True)
            db.session.add(u)
            db.session.flush()
            if role_resp:
                setattr(d, _TOKENS_RESP[role_resp], u.id)
        else:
            cat_id = data.get('categorie_id') or None
            fiche = FicheAnnuaire(categorie_id=cat_id, nom=nom_fiche[:200],
                                  email=email,
                                  telephone=(data.get('telephone') or '').strip() or None,
                                  organisation=(data.get('organisation') or '').strip() or None,
                                  cree_par_id=current_user.id)
            db.session.add(fiche)
            db.session.flush()
            if role_resp == 'resp_juridique':
                d.collab_juridique = nom_fiche[:80]
            elif role_resp == 'resp_social':
                d.collab_social = nom_fiche[:80]
            elif role_resp == 'chef_mission' and not d.ec_chef_mission:
                d.ec_chef_mission = nom_fiche[:80]
            if token == 'client':
                d.mail = email
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"onboarding_etape_destinataire: {e}")
        return jsonify({'ok': False, 'message': 'Erreur lors de la création de la fiche.'}), 500

    mails, manquants = _executer_action(d, code, skip=data.get('deja_envoyes') or [])
    db.session.commit()
    return jsonify({'ok': True, 'mails': mails, 'manquants': manquants,
                    'message': f'Fiche créée — action « {etape_label(code)} » relancée.'})


@app.route('/api/onboarding/actions', methods=['POST'])
@login_required
def api_onboarding_actions():
    """Admin : enregistre la configuration d'une action automatique d'étape."""
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'message': 'Accès refusé.'}), 403
    data = request.get_json(silent=True) or {}
    code = (data.get('etape_code') or '').strip()
    if code not in ONBOARDING_CODES:
        return jsonify({'ok': False, 'message': 'Étape inconnue.'}), 400
    action = OnboardingActionMail.query.filter_by(etape_code=code).first()
    if action is None:
        action = OnboardingActionMail(etape_code=code)
        db.session.add(action)
    action.actif = bool(data.get('actif'))
    action.sujet = (data.get('sujet') or '').strip()[:300] or None
    action.corps = (data.get('corps') or '').strip() or None
    dests = data.get('destinataires')
    if isinstance(dests, list):
        action.destinataires = json.dumps([str(x).strip() for x in dests if str(x).strip()])
    db.session.commit()
    return jsonify({'ok': True, 'etape_code': code})


@app.route('/api/onboarding/actions/<code>/test', methods=['POST'])
@login_required
def api_onboarding_action_test(code):
    """Admin : teste une action mail — envoi à l'adresse de l'admin connecté,
    avec les variables rendues sur le premier dossier en cours (ou un dossier
    d'exemple). Fonctionne même si l'action n'est pas encore activée."""
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'message': 'Accès refusé.'}), 403
    if code not in ONBOARDING_CODES:
        return jsonify({'ok': False, 'message': 'Étape inconnue.'}), 400
    if not current_user.email:
        return jsonify({'ok': False, 'message': 'Aucun email sur votre compte.'})
    action = OnboardingActionMail.query.filter_by(etape_code=code).first()
    if not action:
        return jsonify({'ok': False, 'message': "Action non configurée — enregistrez-la d'abord."})
    d = OnboardingDossier.query.filter_by(statut='en_cours').first()
    vars_ = _vars_modele(d) if d else _vars_modele(
        OnboardingDossier(nom_dossier='Dossier exemple', nom_client='Client exemple'))
    vars_['etape'] = etape_label(code)
    sujet = _rendre(action.sujet, vars_) or f"Cabinet JMH — {vars_['dossier']}"
    corps = _rendre(action.corps, vars_) or (f"Test de l'action de l'étape "
                                             f"« {etape_label(code)} ».")
    ok, err = _envoyer_mail('test_action', current_user.email, f"[TEST] {sujet}",
                            corps, dossier_onb=d if (d and d.id) else None)
    return jsonify({'ok': True if ok else False,
                    'message': (f"Mail de test envoyé à {current_user.email}" if ok
                                else f"Échec de l'envoi : {err}")})


@app.route('/onboarding/<int:dossier_id>/statut', methods=['POST'])
@login_required
def onboarding_statut(dossier_id):
    if not _peut_editer():
        return _refuse_edition()
    d = db.session.get(OnboardingDossier, dossier_id)
    if d is None:
        abort(404)
    d.statut = 'en_cours' if d.statut == 'termine' else 'termine'
    db.session.commit()
    flash('Dossier réouvert.' if d.statut == 'en_cours' else 'Dossier marqué terminé.', 'success')
    return redirect(request.referrer or url_for('onboarding'))


@app.route('/onboarding/<int:dossier_id>/supprimer', methods=['POST'])
@login_required
def onboarding_supprimer(dossier_id):
    if current_user.role != 'admin':
        return _refuse_edition()
    d = db.session.get(OnboardingDossier, dossier_id)
    if d is None:
        abort(404)
    OnboardingMail.query.filter_by(dossier_onb_id=d.id).delete()
    db.session.delete(d)
    db.session.commit()
    flash(f'Dossier « {d.nom_dossier} » supprimé du suivi.', 'success')
    return redirect(url_for('onboarding'))


@app.route('/onboarding/<int:dossier_id>/mail', methods=['POST'])
@login_required
def onboarding_mail(dossier_id):
    if not _peut_editer():
        return _refuse_edition()
    d = db.session.get(OnboardingDossier, dossier_id)
    if d is None:
        abort(404)
    type_mail = request.form.get('type_mail') or 'deontologie'
    dest = (request.form.get('destinataire') or '').strip() or d.mail or ''
    corps = (request.form.get('corps') or '').strip()
    sujets = {'deontologie': f"Cabinet JMH — Transmission de dossier (déontologie) — {d.nom_dossier}",
              'ldm_facturation': f"Cabinet JMH — Lettre de mission & facturation ({d.nom_dossier})",
              'identite': f"Cabinet JMH — Vos interlocuteurs ({d.nom_dossier})"}
    corps_map = {'deontologie': _corps_deontologie, 'ldm_facturation': _corps_ldm_facturation,
                 'identite': _corps_identite}
    ok, err = _envoyer_mail(type_mail, dest,
                            sujets.get(type_mail, f"Cabinet JMH — {d.nom_dossier}"),
                            corps or corps_map.get(type_mail, lambda x: '')(d), dossier_onb=d)
    flash('Mail envoyé.' if ok else f'Mail non envoyé : {err}', 'success' if ok else 'warning')
    return redirect(url_for('onboarding_detail', dossier_id=d.id))


# ---------------------------------------------------------------------------
# Dossiers partis
# ---------------------------------------------------------------------------
@app.route('/onboarding/depart/nouveau', methods=['POST'])
@login_required
def depart_nouveau():
    if not _peut_editer():
        return _refuse_edition()
    nom = (request.form.get('nom_dossier') or '').strip()
    if not nom:
        flash('Le nom du dossier est obligatoire.', 'warning')
        return redirect(url_for('onboarding', tab='partis'))
    dep = OnboardingDepart(
        auteur=(request.form.get('auteur') or '').strip() or None,
        nom_dossier=nom,
        nom_client=(request.form.get('nom_client') or '').strip() or None,
        mail=(request.form.get('mail') or '').strip() or None,
        telephone=(request.form.get('telephone') or '').strip() or None,
        ec_chef_mission=(request.form.get('ec_chef_mission') or '').strip() or None,
        etablissement=(request.form.get('etablissement') or '').strip() or None,
        collaborateur=(request.form.get('collaborateur') or '').strip() or None,
        cause_depart=(request.form.get('cause_depart') or '').strip() or None,
        date_depart=_to_date(request.form.get('date_depart')),
        mail_deontologie_recu=_to_date(request.form.get('mail_deontologie_recu')),
        envoi_documents=_to_date(request.form.get('envoi_documents')),
        mail_facturation=_to_date(request.form.get('mail_facturation')),
        commentaires=(request.form.get('commentaires') or '').strip() or None,
    )
    db.session.add(dep)
    db.session.commit()
    flash(f'Départ de « {nom} » enregistré.', 'success')
    _mail_depart_si_du(dep)
    return redirect(url_for('onboarding', tab='partis'))


@app.route('/onboarding/depart/<int:depart_id>/maj', methods=['POST'])
@login_required
def depart_maj(depart_id):
    if not _peut_editer():
        return _refuse_edition()
    dep = db.session.get(OnboardingDepart, depart_id)
    if dep is None:
        abort(404)
    for champ in ('auteur', 'nom_dossier', 'nom_client', 'mail', 'telephone',
                  'ec_chef_mission', 'etablissement', 'collaborateur',
                  'cause_depart', 'commentaires'):
        setattr(dep, champ, (request.form.get(champ) or '').strip() or None)
    dep.date_depart = _to_date(request.form.get('date_depart'))
    dep.mail_deontologie_recu = _to_date(request.form.get('mail_deontologie_recu'))
    dep.envoi_documents = _to_date(request.form.get('envoi_documents'))
    dep.mail_facturation = _to_date(request.form.get('mail_facturation'))
    db.session.commit()
    flash('Départ mis à jour.', 'success')
    _mail_depart_si_du(dep)
    return redirect(url_for('onboarding', tab='partis'))


def _mail_depart_si_du(dep):
    """Déclenche le mail service facturation quand la date est saisie."""
    if not dep.mail_facturation:
        return
    dest = _setting('ONBOARDING_MAIL_FACTURATION')
    if not dest:
        flash("Mail facturation non envoyé : configurez ONBOARDING_MAIL_FACTURATION "
              "dans les réglages.", 'warning')
        return
    ok, err = _envoyer_mail('facturation_depart', dest,
                            f"Cabinet JMH — Départ client {dep.nom_dossier} : stop facturation",
                            _corps_facturation_depart(dep), depart=dep)
    flash('Mail service facturation envoyé.' if ok else f'Mail non envoyé : {err}',
          'success' if ok else 'warning')


@app.route('/onboarding/depart/<int:depart_id>/supprimer', methods=['POST'])
@login_required
def depart_supprimer(depart_id):
    if current_user.role != 'admin':
        return _refuse_edition()
    dep = db.session.get(OnboardingDepart, depart_id)
    if dep is None:
        abort(404)
    OnboardingMail.query.filter_by(depart_id=dep.id).delete()
    db.session.delete(dep)
    db.session.commit()
    flash(f'Départ « {dep.nom_dossier} » supprimé.', 'success')
    return redirect(url_for('onboarding', tab='partis'))


# ---------------------------------------------------------------------------
# Rappels : étapes bloquées
# ---------------------------------------------------------------------------
@app.route('/onboarding/rappels', methods=['POST'])
@login_required
def onboarding_rappels():
    if not _peut_editer():
        return _refuse_edition()
    seuil = _seuil_rappel()
    cibles = [d for d in OnboardingDossier.query.filter_by(statut='en_cours').all()
              if d.prochaine_etape() and d.jours_attente() >= seuil]
    admins = [u for u in User.query.filter_by(role='admin', actif=True).all() if u.email]
    envoyes = 0
    for d in cibles:
        dests = []
        if d.ec_chef_mission:
            u = User.query.filter(User.actif == True).all()  # noqa: E712
            for cand in u:
                full = f'{cand.prenom} {cand.nom}'.lower()
                if d.ec_chef_mission.lower() in full or full in d.ec_chef_mission.lower():
                    dests.append(cand.email)
                    db.session.add(Notification(user_id=cand.id,
                                                message=f"Onboarding : étape « {d.prochaine_etape()[1]} » "
                                                        f"en attente ({d.jours_attente()} j) — {d.nom_dossier}",
                                                type_notification='rappel_onboarding'))
                    break
        if not dests:
            dests = [a.email for a in admins]
        sujet = f"Orbit — Rappel onboarding : {d.nom_dossier} en attente ({d.jours_attente()} j)"
        for dest in dests:
            ok, _err = _envoyer_mail('rappel', dest, sujet, _corps_rappel(d), dossier_onb=d)
            envoyes += 1 if ok else 0
    db.session.commit()
    flash(f"{len(cibles)} dossier(s) bloqué(s) depuis {seuil} j — {envoyes} mail(s) de rappel envoyé(s).",
          'success' if envoyes else 'warning')
    return redirect(url_for('onboarding'))


# ---------------------------------------------------------------------------
# Import Excel + modèle téléchargeable
# ---------------------------------------------------------------------------
EN_TETES_MODELE = [
    'N°', 'AUTEUR', 'NOM DOSSIER', 'NOM CLIENT', 'MAIL', 'N° TEL',
    'EC/chef de mission', 'ETABLISSEMENT ', 'Création/Reprise ', 'PolyActe',
    'HONORAIRES /AN (compta+jurid) HT', 'DATE DEBUT MISSION',
    'Edition Lettre de mission ', 'Lettre de mission signée',
    'Social (oui / non)', 'Mail Déon ancien EC', 'Retour Docs Ancien EC',
    'Projet de statuts', 'certificat de dep K', 'juridique creation',
    'retour jurid création signé', 'STATUTS', 'kbis',
    'Création dossier Pennylane', 'Inviter le client', 'RIB',
    'Adhesion/Substit Imôts.gouv', 'CODE IMPOTS', 'Envoi LDM/ facturation ',
    'Mandat de PRLVT', 'Retour M PRLVT Signé', 'Mandat So bank',
    'retour yasmina', 'Retour Mandat So bank signé',
    'Collaborateur comptable', 'Collaborateur social ', 'Collaborateur juridique ',
    'Envoi au client Mail identité des collaborateurs ', 'Commentaires ',
]


@app.route('/onboarding/import', methods=['GET', 'POST'])
@login_required
def onboarding_import():
    if not _peut_editer():
        return _refuse_edition()
    if request.method == 'GET':
        return render_template('onboarding_import.html')

    fichier = request.files.get('fichier')
    if not fichier or not fichier.filename:
        flash('Choisissez un fichier .xlsx.', 'warning')
        return redirect(url_for('onboarding_import'))
    if not fichier.filename.lower().endswith('.xlsx'):
        flash('Format attendu : .xlsx (le modèle téléchargeable).', 'danger')
        return redirect(url_for('onboarding_import'))

    try:
        import openpyxl
        wb = openpyxl.load_workbook(BytesIO(fichier.read()), data_only=True)
    except Exception as e:
        flash(f'Fichier illisible : {e}', 'danger')
        return redirect(url_for('onboarding_import'))

    ws = None
    for name in wb.sheetnames:
        if 'suivi' in name.lower() and 'parti' not in name.lower():
            ws = wb[name]
            break
    ws = ws or wb[wb.sheetnames[0]]

    # Trouve la ligne d'en-têtes (colonne A = « N° ») dans les 20 premières lignes
    header_row = None
    for r in range(1, min(20, ws.max_row) + 1):
        if _norm(ws.cell(r, 1).value) in ('n', 'n°', 'no'):
            header_row = r
            break
    if header_row is None:
        flash("Ligne d'en-têtes introuvable (colonne A doit contenir « N° »).", 'danger')
        return redirect(url_for('onboarding_import'))

    colonnes = {}
    for c in range(1, ws.max_column + 1):
        cible = HEADER_MAP.get(_norm(ws.cell(header_row, c).value))
        if cible:
            colonnes[cible] = c
    if 'nom_dossier' not in colonnes:
        flash('Colonne « NOM DOSSIER » introuvable dans le fichier.', 'danger')
        return redirect(url_for('onboarding_import'))

    importes, ignorees, erreurs = 0, 0, []
    for r in range(header_row + 1, min(ws.max_row, 2500) + 1):
        def cell(champ):
            c = colonnes.get(champ)
            return ws.cell(r, c).value if c else None

        nom = cell('nom_dossier')
        if nom is None or not str(nom).strip():
            if any(cell(ch) not in (None, '') for ch in colonnes):
                erreurs.append(f'Ligne {r} : NOM DOSSIER vide — ignorée')
                ignorees += 1
            continue

        type_val = _norm(cell('type_dossier'))
        if 'reprise' in type_val:
            type_d = 'reprise'
        elif 'revision' in type_val or 'révision' in type_val:
            type_d = 'revision'
        else:
            type_d = 'creation'

        d = OnboardingDossier(
            auteur=_txt(cell('auteur')),
            nom_dossier=str(nom).strip()[:200],
            nom_client=_txt(cell('nom_client')),
            mail=_txt(cell('mail')),
            telephone=_txt(cell('telephone')),
            ec_chef_mission=_txt(cell('ec_chef_mission')),
            etablissement=_txt(cell('etablissement')),
            type_dossier=type_d,
            polyacte=_norm(cell('polyacte')).startswith('oui'),
            honoraires_an=_nombre(cell('honoraires_an'), r, erreurs),
            date_debut_mission=_date_excel(cell('date_debut_mission')),
            social=_norm(cell('social')).startswith('oui'),
            collab_comptable=_txt(cell('collab_comptable')),
            collab_social=_txt(cell('collab_social')),
            collab_juridique=_txt(cell('collab_juridique')),
            commentaires=_txt(cell('commentaires')),
            cree_par_id=current_user.id,
        )
        db.session.add(d)
        db.session.flush()
        for code in ONBOARDING_CODES:
            fait, la_date, commentaire, sans_date = _valeur_etape(cell(code))
            db.session.add(OnboardingEtape(dossier_onb_id=d.id, code=code,
                                           date_fait=la_date, commentaire=commentaire,
                                           sans_date=sans_date,
                                           fait_par_id=current_user.id if (la_date or sans_date) else None))
        importes += 1

    db.session.commit()
    if erreurs:
        flash('Import terminé avec ' + f'{len(erreurs)} anomalie(s) : ' + ' · '.join(erreurs[:8]),
              'warning')
    else:
        flash('Import terminé.', 'success')
    flash(f'{importes} dossier(s) importé(s), {ignorees} ligne(s) ignorée(s).', 'info')
    return redirect(url_for('onboarding'))


def _txt(v):
    if v is None:
        return None
    s = str(v).strip()
    return s[:200] if s else None


def _nombre(v, ligne, erreurs):
    if v in (None, ''):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        erreurs.append(f'Ligne {ligne} : honoraires non numériques — ignorés')
        return None


def _date_excel(v):
    """Cellule date Excel (datetime) ou texte dd/mm/yyyy / yyyy-mm-dd."""
    if v in (None, ''):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d/%m/%y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _valeur_etape(v):
    """Cellule d'étape -> (fait?, date, commentaire, sans_date).
    Une date = fait à cette date ; « X » = fait sans date ; un texte = fait sans date + note."""
    if v in (None, ''):
        return False, None, None, False
    if isinstance(v, (datetime, date)):
        return True, _date_excel(v), None, False
    s = str(v).strip()
    if not s or s.upper() == 'X':
        return True, None, None, True
    d = _date_excel(s)
    if d:
        return True, d, None, False
    return True, None, s[:500], True


@app.route('/onboarding/modele.xlsx')
@login_required
def onboarding_modele():
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'SUIVI NOUVEAUX DOSSIERS'
    ws.cell(3, 3, 'CABINET').font = openpyxl.styles.Font(bold=True, size=14)
    ws.cell(3, 4, 'JMH / SUIVI NOUVEAUX DOSSIERS').font = openpyxl.styles.Font(bold=True, size=14)
    ws.cell(5, 3, 'Une ligne par dossier — une date quand une étape est faite, '
                  '« X » si fait sans date, un texte = note. Types : Création / Reprise / Revision.'
            ).font = openpyxl.styles.Font(italic=True, size=10)
    for i, h in enumerate(EN_TETES_MODELE, start=1):
        c = ws.cell(7, i, h)
        c.font = openpyxl.styles.Font(bold=True, size=10, color='FFFFFF')
        c.fill = openpyxl.styles.PatternFill('solid', fgColor='101010')
        c.alignment = openpyxl.styles.Alignment(wrap_text=True, vertical='center')
        ws.column_dimensions[c.column_letter].width = max(16, min(34, len(h) + 6))
    ws.row_dimensions[7].height = 42
    lg = wb.create_sheet('LEGENDE')
    lg.cell(1, 1, 'Création/Reprise').font = openpyxl.styles.Font(bold=True)
    lg.cell(2, 1, 'Création'); lg.cell(3, 1, 'Reprise'); lg.cell(4, 1, 'Revision')
    lg.cell(6, 1, 'OUI / NON').font = openpyxl.styles.Font(bold=True)
    lg.cell(7, 1, 'PolyActe, Social et les étapes acceptent OUI/NON, des dates (jj/mm/aaaa) ou « X ».')
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name='Modele_Suivi_Nouveaux_Dossiers_JMH.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
