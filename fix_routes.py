import sys
import os

file_path = 'app/routes.py'
with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the start and end of the fiscal function
fiscal_start = None
for i, line in enumerate(lines):
    if line.strip() == 'def fiscal():':
        fiscal_start = i
        break

if fiscal_start is None:
    print("Could not find fiscal function")
    sys.exit(1)

# Find the line after the fiscal function body (i.e., the line that is not indented or is the next function)
# We'll look for the line that starts with '# Error handlers' or '@app.route' or 'def ' after the fiscal_start.
# We'll assume the fiscal function ends before the line that contains '# Error handlers'.
# We'll find the index of the line that contains '# Error handlers' after fiscal_start.
error_handlers_idx = None
for i in range(fiscal_start, len(lines)):
    if lines[i].strip() == '# Error handlers':
        error_handlers_idx = i
        break

if error_handlers_idx is None:
    print("Could not find # Error handlers")
    sys.exit(1)

# Now we have the fiscal function from fiscal_start to error_handlers_idx (exclusive).
# We'll replace that block with a corrected fiscal function.

corrected_fiscal = [
    'def fiscal():\n',
    '    """Tableau de bord fiscal dédié"""\n',
    '    # Initialize variables for template (same as dossiers)\n',
    '    current_equipe = None\n',
    '    all_equipes_for_switch = []\n',
    '    membres = []\n',
    '    if current_user.role == \'admin\':\n',
    '        from flask import session\n',
    '        equipe_id = session.get(\'current_equipe_id\')\n',
    '        if equipe_id:\n',
    '            equipe = Equipe.query.get(equipe_id)\n',
    '            current_equipe = equipe\n',
    '            all_equipes_for_switch = Equipe.query.order_by(Equipe.nom).all()\n',
    '            team_user_ids = [m.id for m in equipe.membres.all()] if equipe else []\n',
    '            membres = User.query.filter(User.id.in_(team_user_ids), User.actif==True).all()\n',
    '            all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_user_ids)).all()\n',
    '        else:\n',
    '            current_equipe = None\n',
    '            all_equipes_for_switch = Equipe.query.order_by(Equipe.nom).all()\n',
    '            membres = User.query.filter_by(actif=True).all()\n',
    '            all_dossiers = Dossier.query.all()\n',
    '    elif current_user.role == \'manager\':\n',
    '        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()\n',
    '        all_equipes_for_switch = mes_equipes\n',
    '        current_equipe = None\n',
    '        team_member_ids = [current_user.id]\n',
    '        for eq in mes_equipes:\n',
    '            team_member_ids.extend([m.id for m in eq.membres.all()])\n',
    '        all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_member_ids)).all()\n',
    '        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()\n',
    '    else:\n',
    '        mes_equipes = current_user.equipes.filter_by(actif=True).all() if hasattr(current_user, \'equipes\') else []\n',
    '        all_equipes_for_switch = mes_equipes\n',
    '        current_equipe = None\n',
    '        team_member_ids = [current_user.id]\n',
    '        for eq in mes_equipes:\n',
    '            team_member_ids.extend([m.id for m in eq.membres.all()])\n',
    '        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()\n',
    '        all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_member_ids)).all()\n',
    '    # For each dossier, compute fiscal info\n',
    '    dossier_data = []\n',
    '    for d in all_dossiers:\n',
    '        tasks = Tache.query.filter(Tache.dossier_id == d.id).all()\n',
    '        # Filter tasks related to tax: TVA, IS, CFE\n',
    '        tax_tasks = [t for t in tasks if (\n',
    '                     \'TVA\' in t.titre.upper() or \'CA3\' in t.titre.upper() or \'CA12\' in t.titre.upper() or\n',
    '                      \'IS\' in t.titre.upper() or \'ACOMPTE\' in t.titre.upper() or \'CFE\' in t.titre.upper())]\n',
    '        # Determine next deadline among non-completed tax tasks\n',
    '        pending_tasks = [t for t in tax_tasks if t.statut != \'terminee\']\n',
    '        next_deadline = min([t.date_echeance for t in pending_tasks]) if pending_tasks else None\n',
    '        # Determine status\n',
    '        if any(t.statut == \'a_faire\' for t in tax_tasks):\n',
    '            status = \'a_faire\'\n',
    '            status_label = \'À faire\'\n',
    '            status_class = \'text-danger\'\n',
    '        elif any(t.statut == \'en_cours\' for t in tax_tasks):\n',
    '            status = \'en_cours\'\n',
    '            status_label = \'En cours\'\n',
    '            status_class = \'text-warning\'\n',
    '        else:\n',
    '            status = \'terminee\'\n',
    '            status_label = \'Terminé\'\n',
    '            status_class = \'text-success\'\n',
    '        dossier_data.append({\n',
    '            \'dossier\': d,\n',
    '            \'regime_fiscale\': d.regime_fiscale,\n',
    '            \'has_cfe\': d.has_cfe,\n',
    '            \'next_deadline\': next_deadline,\n',
    '            \'status\': status,\n',
    '            \'status_label\': status_label,\n',
    '            \'status_class\': status_class,\n',
    '            \'tax_tasks\': tax_tasks\n',
    '        })\n',
    '    return render_template(\'fiscal.html\', dossier_data=dossier_data, current_equipe=current_equipe, all_equipes_for_switch=all_equipes_for_switch, Tache=Tache, db=db)\n',
    '\n',
    '\n'
]

# Now we want to insert the ajouter_dossier route just before the '# Error handlers' line.
ajouter_dossier_route = [
    '@app.route(\'/ajouter_dossier\', methods=[\'POST\'])\n',
    '@login_required\n',
    'def ajouter_dossier():\n',
    '    if current_user.role not in (\'admin\', \'manager\'):\n',
    '        flash(\'Accès refusé.\', \'danger\')\n',
    '        return redirect(url_for(\'dossiers\'))\n',
    '    try:\n',
    '        numero_dossier = request.form.get(\'numero_dossier\', \'\').strip()\n',
    '        intitule = request.form.get(\'intitule\', \'\').strip()\n',
    '        collaborateur_id = request.form.get(\'collaborateur_id\')\n',
    '        equipe_id = request.form.get(\'equipe_id\')\n',
    '        regime_tva = request.form.get(\'regime_tva\')\n',
    '        frequence_tva = request.form.get(\'frequence_tva\')\n',
    '        date_limite_declaration = request.form.get(\'date_limite_declaration\')\n',
    '        regime_fiscale = request.form.get(\'regime_fiscale\')\n',
    '        has_cfe = (\'has_cfe\' in request.form)\n',
    '\n',
    '        if not numero_dossier or not intitule or not collaborateur_id or not equipe_id:\n',
    '            flash(\'Veuillez remplir tous les champs obligatoires.\', \'danger\')\n',
    '            return redirect(url_for(\'dossiers\'))\n',
    '\n',
    '        # Convert date if provided\n',
    '        date_limite = None\n',
    '        if date_limite_declaration:\n',
    '            try:\n',
    '                date_limite = datetime.strptime(date_limite_declaration, \'%Y-%m-%d\').date()\n',
    '            except ValueError:\n',
    '                flash(\'Format de date invalide.\', \'danger\')\n',
    '                return redirect(url_for(\'dossiers\'))\n',
    '\n',
    '        nouveau_dossier = Dossier(\n',
    '            numero_dossier=numero_dossier,\n',
    '            intitule=intitule,\n',
    '            collaborateur_id=int(collaborateur_id),\n',
    '            equipe_id=int(equipe_id),\n',
    '            regime_tva=regime_tva if regime_tva else None,\n',
    '            frequence_tva=frequence_tva if frequence_tva else None,\n',
    '            date_limite_declaration=date_limite,\n',
    '            regime_fiscale=regime_fiscale if regime_fiscale else None,\n',
    '            has_cfe=has_cfe\n',
    '        )\n',
    '        db.session.add(nouveau_dossier)\n',
    '        db.session.flush()\n',
    '        from .tva_scheduler import planifier_impots_dossier\n',
    '        planifier_impots_dossier(nouveau_dossier)\n',
    '        db.session.commit()\n',
    '        flash(\'Dossier créé avec succès et les tâches fiscales ont été générées.\', \'success\')\n',
    '    except Exception as e:\n',
    '        db.session.rollback()\n',
    '        app.logger.error(f\"Erreur lors de la création du dossier: {e}\")\n',
    '        flash(\'Erreur lors de la création du dossier.\', \'danger\')\n',
    '    return redirect(url_for(\'dossiers\'))\n',
    '\n'
]

# Build the new lines:
# Keep everything before fiscal_start
new_lines = lines[:fiscal_start]
# Add the corrected fiscal function
new_lines.extend(corrected_fiscal)
# Add the ajouter_dossier route
new_lines.extend(ajouter_dossier_route)
# Keep everything from error_handlers_idx onwards (which includes the '# Error handlers' line and after)
new_lines.extend(lines[error_handlers_idx:])

# Write back
with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print('Fixed fiscal function and added ajouter_dossier route')