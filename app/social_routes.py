# -*- coding: utf-8 -*-
"""Pôle social : routes de suivi DSN & écritures de paie (Couche 1).

Acces : admin + membres de pole 'social' ou 'les_deux' (et managers sociaux).
Vue dossiers/taches etendue aux dossiers dont on est le referent social.
"""
from datetime import date, datetime

from flask import render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_required, current_user

from . import app, db
from .models import Dossier, DsnSuivi, User, Tache, Notification
from . import social_service as SS


def _acces_social():
    return SS.est_pole_social(current_user)


@app.route('/suivi_social')
@login_required
def suivi_social():
    """Grille annuelle DSN + écritures de paie par dossier suivi par le social.

    Acces : admin + pôle social (complet) + COLLABORATEUR COMPTABLE d'un dossier
    suivi (lecture de ses lignes + validation du volet « écritures » uniquement)."""
    if not _acces_social():
        # Un comptable non-social peut consulter la grille s'il est le collaborateur
        # comptable d'au moins un dossier ayant un referent social.
        if current_user.role == 'membre':
            a_suivi = Dossier.query.filter(
                Dossier.collaborateur_social_id.isnot(None),
                Dossier.collaborateur_id == current_user.id).count()
            if not a_suivi:
                flash('Accès réservé au pôle social.', 'danger')
                return redirect(url_for('dashboard'))
        else:
            flash('Accès réservé au pôle social.', 'danger')
            return redirect(url_for('dashboard'))

    annee = request.args.get('annee', type=int) or date.today().year
    annees = [date.today().year - 1, date.today().year, date.today().year + 1]
    if annee not in annees:
        annees.append(annee); annees.sort()

    if current_user.role == 'admin' or current_user.dans_pole_social:
        dossiers = SS.dossiers_suivis_par(current_user)
        lecture_seule = False
    else:
        # comptable : uniquement ses dossiers qui ont un referent social
        dossiers = Dossier.query.filter(
            Dossier.collaborateur_social_id.isnot(None),
            Dossier.collaborateur_id == current_user.id).all()
        lecture_seule = True
    today = date.today()
    lignes = []
    for d in dossiers:
        grille = SS.grille(d, annee)
        # periode echoee = la date d'exigibilite est passee
        a_deposer_passes = sum(1 for c in grille
                               if c['ligne'].dsn_statut in ('a_deposer', 'deposee', 'rejetee')
                               and c['exigible'] < today)
        ecrit_att = sum(1 for c in grille if c['ligne'].ecritures_statut != 'integrees'
                        and c['exigible'] < today)
        lignes.append({'d': d, 'grille': grille,
                       'a_deposer_passes': a_deposer_passes, 'ecrit_att': ecrit_att})
    nb_retard = sum(1 for l in lignes for c in l['grille'] if c['retard'] and c['exigible'] < today)
    nb_a_deposer = sum(l['a_deposer_passes'] for l in lignes)
    nb_ecrit_att = sum(l['ecrit_att'] for l in lignes)
    social_retard = SS.taches_dsn_retard()

    membres_social = User.query.filter(User.pole.in_(['social', 'les_deux']), User.actif == True)\
        .order_by(User.nom).all()
    filtre_social = request.args.get('social', type=int)
    if filtre_social:
        lignes = [l for l in lignes if l['d'].collaborateur_social_id == filtre_social]

    return render_template('suivi_social.html', annee=annee, annees=annees, lignes=lignes,
                           nb_retard=nb_retard, nb_a_deposer=nb_a_deposer,
                           nb_ecrit_att=nb_ecrit_att, social_retard=social_retard,
                           membres_social=membres_social, filtre_social=filtre_social,
                           lecture_seule=lecture_seule,
                           mois_fr=SS.MOIS_FR)


@app.route('/dsn/set', methods=['POST'])
@login_required
def dsn_set():
    """Met a jour une cellule : dossier_id, annee, mois, champ (dsn|ecritures), valeur."""
    j = request.get_json(silent=True) or {}
    did = j.get('dossier_id')
    annee = j.get('annee')
    mois = j.get('mois')
    champ = j.get('champ')       # 'dsn' | 'ecritures'
    valeur = j.get('valeur')
    motif = (j.get('motif') or '').strip()[:250]
    d = Dossier.query.get(did)
    if not d or not (annee and mois):
        return jsonify({'ok': False, 'error': 'Paramètres invalides.'}), 400
    # scoping : admin = tout ; le referent social (ou son manager social) de son cote.
    # Le COLLABORATEUR COMPTABLE du dossier a acces au volet « ecritures » uniquement
    # (il doit pouvoir confirmer l'integration comptable qu'il a faite) : c'est lui
    # qu'on notifie, autant il doit pouvoir repondre.
    if current_user.role != 'admin':
        est_social = (d.collaborateur_social_id == current_user.id)
        est_manager_social = False
        if current_user.role == 'manager' and d.collaborateur_social_id:
            cible = User.query.get(d.collaborateur_social_id)
            est_manager_social = bool(cible and (cible.pole or '') in ('social', 'les_deux'))
        est_comptable = (champ == 'ecritures' and d.collaborateur_id == current_user.id)
        if not (est_social or est_manager_social or est_comptable):
            return jsonify({'ok': False, 'error': 'Dossier hors de votre périmètre social.'}), 403
    ligne = DsnSuivi.query.filter_by(dossier_id=did, annee=annee, mois=mois).first()
    if not ligne:
        ligne = DsnSuivi(dossier_id=did, annee=annee, mois=mois)
        db.session.add(ligne)
    notif_social = None
    if champ == 'dsn':
        if valeur not in ('a_deposer', 'deposee', 'validee', 'rejetee'):
            return jsonify({'ok': False, 'error': 'Statut DSN invalide.'}), 400
        ligne.dsn_statut = valeur
        ligne.dsn_date_depot = date.today() if valeur == 'deposee' else None
        if motif:
            ligne.dsn_motif = motif
        # tache DSN associee -> auto-terminee si validee
        if valeur == 'validee':
            titre_prefix = f"Dépôt DSN {mois:02d}/{annee} — {d.numero_dossier}"
            t = Tache.query.filter(Tache.dossier_id == did, Tache.titre.like(titre_prefix + '%')).first()
            if t and t.statut != 'terminee':
                t.statut = 'terminee'
                t.date_completion = datetime.utcnow()
    elif champ == 'ecritures':
        if valeur not in ('non_passees', 'pretes', 'integrees'):
            return jsonify({'ok': False, 'error': 'Statut écritures invalide.'}), 400
        old = ligne.ecritures_statut
        ligne.ecritures_statut = valeur
        ligne.ecritures_date = datetime.utcnow()
        # Notification au collaborateur COMPTABLE quand les écritures deviennent prêtes
        if valeur == 'pretes' and old != 'pretes' and not ligne.notifie_compta:
            if d.collaborateur_id and d.collaborateur_id != current_user.id:
                lien = url_for('suivi_social', annee=annee)
                notif = Notification(
                    user_id=d.collaborateur_id,
                    message=(f"Écritures de paie {mois:02d}/{annee} prêtes pour {d.intitule} "
                             f"({d.numero_dossier}) — à intégrer en comptabilité, puis marquer « Intégrées »."),
                    type_notification='social_paie')
                db.session.add(notif)
                ligne.notifie_compta = True
                notif_social = True
                # email au comptable (le SMS/e-mail relie les deux poles hors de l'app)
                try:
                    from app.integrations.brevo import send_email_via_brevo_api
                    dest = User.query.get(d.collaborateur_id)
                    if dest and dest.email:
                        # lien direct vers l'annee concernee (pas l'annee courante)
                        url_ext = url_for('suivi_social', annee=annee, _external=True)
                        txt = (f"Bonjour {dest.prenom},\n\n"
                               f"Les écritures de paie de {mois:02d}/{annee} pour le dossier "
                               f"{d.intitule} ({d.numero_dossier}) sont prêtes.\n\n"
                               f"Merci de les intégrer en comptabilité dans Pennylane, puis de marquer "
                               f"la ligne comme « Intégrées » dans le suivi social.\n\n"
                               f"{url_ext}")
                        html = (f"<p>Bonjour {dest.prenom},</p>"
                                f"<p>Les écritures de paie de <b>{mois:02d}/{annee}</b> pour le dossier "
                                f"<b>{d.intitule} ({d.numero_dossier})</b> sont prêtes.</p>"
                                f"<p>Merci de les intégrer en comptabilité dans Pennylane, puis de marquer "
                                f"la ligne comme « Intégrées » dans le suivi social.</p>"
                                f'<p><a href="{url_ext}">Ouvrir le suivi social ({annee})</a></p>')
                        send_email_via_brevo_api(dest.email,
                                                  f"Écritures de paie prêtes — {d.intitule}",
                                                  txt, html)
                except Exception as _mail_e:
                    app.logger.warning(f"Email ecritures pretes -> compta: {_mail_e}")
    else:
        return jsonify({'ok': False, 'error': 'Champ inconnu.'}), 400
    ligne.modifie_par_id = current_user.id
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    return jsonify({'ok': True, 'notif_compta': bool(notif_social)})


@app.route('/paie/sync_pennylane/<int:dossier_id>', methods=['POST'])
@login_required
def paie_sync_pennylane(dossier_id):
    """Sonde le journal de paie Pennylane du dossier et confirme les periodes
    « ecritures integrees » (regle prudente : ne degrade jamais un etat humain)."""
    if current_user.role not in ('admin', 'manager'):
        return jsonify({'ok': False, 'error': 'Accès refusé.'}), 403
    d = Dossier.query.get_or_404(dossier_id)
    n, _ign, msg = SS.synchroniser_paie_pennylane(d)
    return jsonify({'ok': True, 'periodes': n, 'message': msg,
                    'session_pennylane': bool((d.pennylane_customer_id or '').strip())})


@app.route('/assigner_pole/<int:user_id>', methods=['POST'])
@login_required
def assigner_pole(user_id):
    """Admin : affecte le pole (comptable | social | les_deux) d'un membre."""
    if current_user.role != 'admin':
        flash('Accès refusé.', 'danger')
        return redirect(url_for('membres'))
    u = User.query.get_or_404(user_id)
    pole = request.form.get('pole')
    if pole not in ('comptable', 'social', 'les_deux'):
        flash('Pôle invalide.', 'danger')
        return redirect(url_for('membres'))
    u.pole = pole
    db.session.commit()
    flash(f'Pôle de {u.prenom} {u.nom} mis à jour : {pole}.', 'success')
    return redirect(url_for('membres'))
