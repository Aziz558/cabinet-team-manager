"""annuaire — contacts hors cabinet (clients, notaires, intervenants externes).

Fiches rangées par catégories gérées depuis l'application (pas de catégorie
figée dans le code). La catégorie « Client » est créée au premier démarrage.
Alimente la popup « destinataire sans email » du suivi nouveaux dossiers.
"""
from flask import (render_template, request, redirect, url_for, flash, jsonify)
from flask_login import login_required, current_user

from . import app, db
from .models import FicheAnnuaire, AnnuaireCategorie


def _peut_editer():
    return current_user.role in ('admin', 'manager')


@app.route('/annuaire')
@login_required
def annuaire():
    q = (request.args.get('q') or '').strip()
    fcat = request.args.get('categorie', type=int)
    query = FicheAnnuaire.query
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(FicheAnnuaire.nom.ilike(like),
                                    FicheAnnuaire.email.ilike(like),
                                    FicheAnnuaire.organisation.ilike(like)))
    if fcat:
        query = query.filter(FicheAnnuaire.categorie_id == fcat)
    fiches = query.order_by(FicheAnnuaire.nom).all()
    categories = AnnuaireCategorie.query.order_by(AnnuaireCategorie.ordre,
                                                  AnnuaireCategorie.nom).all()
    total = FicheAnnuaire.query.count()
    avec_mail = FicheAnnuaire.query.filter(FicheAnnuaire.email.isnot(None),
                                           FicheAnnuaire.email != '').count()
    return render_template('annuaire.html', fiches=fiches, categories=categories,
                           q=q, fcat=fcat, total=total, avec_mail=avec_mail,
                           peut_editer=_peut_editer())


@app.route('/annuaire/categorie/ajouter', methods=['POST'])
@login_required
def annuaire_categorie_ajouter():
    if current_user.role != 'admin':
        flash('Réservé aux admins.', 'danger')
        return redirect(url_for('annuaire'))
    nom = (request.form.get('nom') or '').strip()[:80]
    if not nom:
        flash('Nom de catégorie requis.', 'warning')
        return redirect(url_for('annuaire'))
    if AnnuaireCategorie.query.filter_by(nom=nom).first():
        flash('Cette catégorie existe déjà.', 'warning')
        return redirect(url_for('annuaire'))
    db.session.add(AnnuaireCategorie(nom=nom))
    db.session.commit()
    flash(f'Catégorie « {nom} » ajoutée.', 'success')
    return redirect(url_for('annuaire'))


@app.route('/annuaire/categorie/<int:cat_id>/supprimer', methods=['POST'])
@login_required
def annuaire_categorie_supprimer(cat_id):
    if current_user.role != 'admin':
        flash('Réservé aux admins.', 'danger')
        return redirect(url_for('annuaire'))
    cat = db.session.get(AnnuaireCategorie, cat_id)
    if cat is None:
        return redirect(url_for('annuaire'))
    if cat.fiches.count():
        flash('Catégorie utilisée par des fiches — videz-la d\'abord.', 'warning')
        return redirect(url_for('annuaire'))
    db.session.delete(cat)
    db.session.commit()
    flash(f'Catégorie « {cat.nom} » supprimée.', 'success')
    return redirect(url_for('annuaire'))


@app.route('/annuaire/fiche/ajouter', methods=['POST'])
@login_required
def annuaire_fiche_ajouter():
    if not _peut_editer():
        flash('Modification réservée aux managers et admins.', 'danger')
        return redirect(url_for('annuaire'))
    nom = (request.form.get('nom') or '').strip()
    if not nom:
        flash('Le nom est obligatoire.', 'warning')
        return redirect(url_for('annuaire'))
    db.session.add(FicheAnnuaire(
        categorie_id=request.form.get('categorie_id', type=int) or None,
        nom=nom[:200],
        email=(request.form.get('email') or '').strip() or None,
        telephone=(request.form.get('telephone') or '').strip() or None,
        organisation=(request.form.get('organisation') or '').strip() or None,
        note=(request.form.get('note') or '').strip() or None,
        cree_par_id=current_user.id,
    ))
    db.session.commit()
    flash(f'Fiche « {nom} » ajoutée à l\'annuaire.', 'success')
    return redirect(url_for('annuaire'))


@app.route('/annuaire/fiche/<int:fiche_id>/maj', methods=['POST'])
@login_required
def annuaire_fiche_maj(fiche_id):
    if not _peut_editer():
        flash('Modification réservée aux managers et admins.', 'danger')
        return redirect(url_for('annuaire'))
    f = db.session.get(FicheAnnuaire, fiche_id)
    if f is None:
        abort(404)
    f.categorie_id = request.form.get('categorie_id', type=int) or None
    f.nom = (request.form.get('nom') or '').strip() or f.nom
    f.email = (request.form.get('email') or '').strip() or None
    f.telephone = (request.form.get('telephone') or '').strip() or None
    f.organisation = (request.form.get('organisation') or '').strip() or None
    f.note = (request.form.get('note') or '').strip() or None
    db.session.commit()
    flash('Fiche mise à jour.', 'success')
    return redirect(url_for('annuaire'))


@app.route('/annuaire/fiche/<int:fiche_id>/supprimer', methods=['POST'])
@login_required
def annuaire_fiche_supprimer(fiche_id):
    if current_user.role != 'admin':
        flash('Réservé aux admins.', 'danger')
        return redirect(url_for('annuaire'))
    f = db.session.get(FicheAnnuaire, fiche_id)
    if f is None:
        abort(404)
    db.session.delete(f)
    db.session.commit()
    flash(f'Fiche « {f.nom} » supprimée.', 'success')
    return redirect(url_for('annuaire'))


# --- API JSON (popup « destinataire sans email » du suivi onboarding) ---

@app.route('/api/annuaire/fiches', methods=['POST'])
@login_required
def api_annuaire_fiche_creer():
    if not _peut_editer():
        return jsonify({'ok': False, 'message': 'Modification réservée aux managers et admins.'}), 403
    data = request.get_json(silent=True) or {}
    nom = (data.get('nom') or '').strip()
    if not nom:
        return jsonify({'ok': False, 'message': 'Le nom est obligatoire.'}), 400
    fiche = FicheAnnuaire(
        categorie_id=data.get('categorie_id') or None,
        nom=nom[:200],
        email=(data.get('email') or '').strip() or None,
        telephone=(data.get('telephone') or '').strip() or None,
        organisation=(data.get('organisation') or '').strip() or None,
        cree_par_id=current_user.id,
    )
    db.session.add(fiche)
    db.session.commit()
    return jsonify({'ok': True, 'fiche_id': fiche.id, 'nom': fiche.nom})
