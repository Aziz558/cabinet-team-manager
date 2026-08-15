@login_required
def dossiers():
    """Affiche la liste des dossiers selon le rôle de l'utilisateur."""
    if current_user.role == 'admin':
        from flask import session
        equipe_id = session.get('current_equipe_id')
        if equipe_id:
            equipe = Equipe.query.get(equipe_id)
            team_user_ids = [m.id for m in equipe.membres.all()] if equipe else []
            membres = User.query.filter(User.id.in_(team_user_ids), User.actif==True).all()
            all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_user_ids)).all()
        else:
            membres = User.query.filter_by(actif=True).all()
            all_dossiers = Dossier.query.all()
    elif current_user.role == 'manager':
        team_member_ids = [current_user.id]
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_member_ids)).all()
        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()
    else:
        team_member_ids = [current_user.id]
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_member_ids)).all()
        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()
    return render_template('dossiers.html', dossiers=all_dossiers, membres=membres, equipes=Equipe.query.order_by(Equipe.nom).all(), Tache=Tache, current_equipe=current_equipe, all_equipes_for_switch=all_equipes_for_switch, db=db)