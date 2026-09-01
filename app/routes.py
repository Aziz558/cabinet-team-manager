from flask import render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from . import app, db
from .models import User, Equipe, Dossier, Tache, Notification, CommentaireTache, SuggestionTache, PennylaneItem
from sqlalchemy import or_
import json
import os
from datetime import date, datetime, timedelta

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dossiers'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dossiers'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            if not user.actif:
                flash('Votre compte est d\u00e9sactiv\u00e9. Contactez le manager.', 'danger')
                return redirect(url_for('login'))
            login_user(user, remember=True)
            next_page = request.args.get('next')
            flash(f'Bienvenue, {user.prenom} !', 'success')
            return redirect(next_page or url_for('dossiers'))
        else:
            flash('Email ou mot de passe incorrect.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('D\u00e9connexion r\u00e9ussie.', 'info')
    return redirect(url_for('login'))

@app.route('/team-select')
def team_select():
    equipes = Equipe.query.order_by(Equipe.nom).all()
    return render_template('team_select.html', equipes=equipes)

@app.route('/dashboard')
@login_required
def dashboard():
    from datetime import timedelta
    
    # Horizon 3 mois pour les tâches
    horizon_3m = date.today() + timedelta(days=95)
    week_end = date.today() + timedelta(days=7)
    
    if current_user.role == 'manager':
        # Compute real KPIs for manager
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        team_member_ids = [current_user.id]
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        team_member_ids = list(set(team_member_ids))

        membres_actifs = User.query.filter(User.id.in_(team_member_ids), User.actif==True).count()
        all_dossiers_ids = [d.id for d in Dossier.query.filter(Dossier.collaborateur_id.in_(team_member_ids)).all()]
        dossiers_en_cours = len(all_dossiers_ids)
        
        taches_retard = 0
        taches_haute_priorite = 0
        total_taches = 0
        if all_dossiers_ids:
            taches_query = Tache.query.filter(
                Tache.dossier_id.in_(all_dossiers_ids),
                Tache.date_echeance <= horizon_3m
            )
            total_taches = taches_query.count()
            taches_retard = taches_query.filter(Tache.date_echeance < date.today(), Tache.statut != 'terminee').count()
            taches_haute_priorite = taches_query.filter_by(priorite='haute', statut='a_faire').count()
        
        taux_completion = 0
        if total_taches > 0:
            terminees = Tache.query.filter(
                Tache.dossier_id.in_(all_dossiers_ids),
                Tache.date_echeance <= horizon_3m,
                Tache.statut == 'terminee'
            ).count()
            taux_completion = int(terminees / total_taches * 100)

        kpi = {
            'membres_actifs': membres_actifs,
            'dossiers_en_cours': dossiers_en_cours,
            'taches_retard': taches_retard,
            'taches_haute_priorite': taches_haute_priorite,
            'taux_completion': taux_completion,
            'total_taches': total_taches
        }

        # Alertes : tâches en retard dans les 3 mois
        alertes = []
        if all_dossiers_ids:
            taches_en_retard = Tache.query.filter(
                Tache.dossier_id.in_(all_dossiers_ids),
                Tache.date_echeance.between(date.today() - timedelta(days=60), date.today()),
                Tache.statut != 'terminee'
            ).order_by(Tache.date_echeance.asc()).limit(5).all()
            for t in taches_en_retard:
                d = Dossier.query.get(t.dossier_id)
                alertes.append({'tache': t, 'dossier': d})

        # Suggestions
        suggestions = []
        try:
            from app.models import Suggestion
            suggestions = Suggestion.query.filter(Suggestion.cree_par.in_(team_member_ids))\
                .order_by(Suggestion.date_creation.desc()).limit(10).all()
        except Exception:
            suggestions = []

        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).order_by(User.nom).all()
        
        taches_jour = Tache.query.filter(
            Tache.assigne_a.in_(team_member_ids),
            Tache.date_echeance == date.today(),
            Tache.statut.in_(['a_faire', 'en_cours'])
        ).order_by(Tache.priorite.desc()).all()
        
        taches_semaine = Tache.query.filter(
            Tache.assigne_a.in_(team_member_ids),
            Tache.date_echeance.between(date.today(), week_end),
            Tache.statut.in_(['a_faire', 'en_cours'])
        ).order_by(Tache.date_echeance.asc()).all()

        # Notifications non lues
        notifications_non_lues = []
        try:
            notifications_non_lues = current_user.notifications.filter_by(lu=False).order_by(Notification.date_envoi.desc()).limit(5).all() if hasattr(current_user, 'notifications') else []
        except Exception:
            notifications_non_lues = []

        return render_template('dashboard_manager.html', kpi=kpi, alertes=alertes,
            suggestions=suggestions, membres=membres, taches_jour=taches_jour,
            taches_semaine=taches_semaine, notifications_non_lues=notifications_non_lues,
            horizon_3m=horizon_3m)
    else:
        # Dashboard collaborateur
        team_member_ids = [current_user.id]
        mes_equipes = current_user.equipes.filter_by(actif=True).all() if hasattr(current_user, 'equipes') else []
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        team_member_ids = list(set(team_member_ids))
        
        total_taches = Tache.query.filter(Tache.assigne_a.in_(team_member_ids), Tache.date_echeance <= horizon_3m).count()
        taches_auj = Tache.query.filter(
            Tache.assigne_a.in_(team_member_ids),
            Tache.date_echeance == date.today()
        ).count()
        terminees = Tache.query.filter(
            Tache.assigne_a.in_(team_member_ids),
            Tache.date_echeance <= horizon_3m,
            Tache.statut == 'terminee'
        ).count()
        taux_completion = int(terminees / total_taches * 100) if total_taches > 0 else 0

        taches_jour = Tache.query.filter(
            Tache.assigne_a == current_user.id,
            Tache.date_echeance == date.today(),
            Tache.statut.in_(['a_faire', 'en_cours'])
        ).order_by(Tache.priorite.desc()).all()
        taches_semaine = Tache.query.filter(
            Tache.assigne_a.in_(team_member_ids),
            Tache.date_echeance.between(date.today(), week_end),
            Tache.statut.in_(['a_faire', 'en_cours'])
        ).order_by(Tache.date_echeance.asc()).all()

        kpi = {
            'taches_aujourdhui': taches_auj,
            'taux_completion': taux_completion,
            'total_taches': total_taches
        }
        return render_template('dashboard_collaborateur.html', kpi=kpi,
            taches_jour=taches_jour, taches_semaine=taches_semaine)

def prochaine_echeance_theorique(dossier, today):
    """Calcule la prochaine échéance TVA théorique pour les tâches pas encore générées."""
    from .tva_scheduler import next_working_day
    import calendar
    r = (dossier.regime_tva or '').lower().strip()
    ref = dossier.date_limite_declaration
    if not ref or r in ('', 'exonere'):
        return None
    jour = ref.day
    annee = ref.year
    echeances = []
    if r in ('mensuel', 'ca3'):
        for m in range(1, 13):
            try:
                echeances.append(next_working_day(date(annee, m, jour)))
            except ValueError:
                echeances.append(next_working_day(date(annee, m, 15)))
    elif r == 'trimestriel':
        for m in (1, 4, 7, 10):
            try:
                echeances.append(next_working_day(date(annee, m, jour)))
            except ValueError:
                echeances.append(next_working_day(date(annee, m, 15)))
    elif r in ('annuel', 'ca12'):
        # Acomptes : dates personnalisées si définies, sinon défauts
        if dossier.date_acompte_1:
            echeances.append(next_working_day(dossier.date_acompte_1))
        else:
            echeances.append(next_working_day(date(annee, 7, 15)))
        if dossier.date_acompte_2:
            echeances.append(next_working_day(dossier.date_acompte_2))
        else:
            try:
                echeances.append(next_working_day(date(annee, 12, jour)))
            except ValueError:
                echeances.append(next_working_day(date(annee, 12, 15)))
        echeances.append(next_working_day(date(annee + 1, 5, 15)))
    # Prochaines échéances >= aujourd'hui
    futurs = [e for e in echeances if e >= today]
    if not futurs:
        # Si tout passé, générer l'année suivante pour mensuel/trimestriel
        if r in ('mensuel', 'ca3'):
            for m in range(1, 13):
                try:
                    futurs.append(next_working_day(date(annee + 1, m, jour)))
                except ValueError:
                    futurs.append(next_working_day(date(annee + 1, m, 15)))
        elif r == 'trimestriel':
            for m in (1, 4, 7, 10):
                try:
                    futurs.append(next_working_day(date(annee + 1, m, jour)))
                except ValueError:
                    futurs.append(next_working_day(date(annee + 1, m, 15)))
    return min(futurs) if futurs else None

def prochaine_echeance_par_nature(d, today):
    """Prochaines échéances (date, nature) par nature d'impôt : TVA, IS, CFE."""
    from .tva_scheduler import next_working_day
    import calendar
    resultats = []
    taches_d = [t for t in d.taches if t.titre and 'Préparation' not in t.titre]

    # --- TVA ---
    taches_tva = [t for t in taches_d if 'TVA' in t.titre or 'Dépôt' in t.titre]
    futurs_tva = [t.date_echeance for t in taches_tva if t.date_echeance and t.date_echeance >= today]
    if futurs_tva:
        resultats.append((min(futurs_tva), 'TVA'))
    else:
        theo = prochaine_echeance_theorique(d, today)
        if theo:
            resultats.append((theo, 'TVA'))

    # --- IS ---
    if (d.regime_fiscale or '').upper() == 'IS':
        taches_is = [t for t in taches_d if 'IS' in t.titre]
        futurs_is = [t.date_echeance for t in taches_is if t.date_echeance and t.date_echeance >= today]
        if futurs_is:
            resultats.append((min(futurs_is), 'IS'))
        else:
            echeances = []
            for y in [today.year, today.year + 1]:
                for m in [3, 6, 9, 12]:
                    echeances.append(next_working_day(date(y, m, 15)))
                echeances.append(next_working_day(date(y + 1, 5, 15)))
            futurs = [e for e in echeances if e >= today]
            if futurs:
                resultats.append((min(futurs), 'IS'))

    # --- CFE ---
    if d.has_cfe:
        taches_cfe = [t for t in taches_d if 'CFE' in t.titre]
        futurs_cfe = [t.date_echeance for t in taches_cfe if t.date_echeance and t.date_echeance >= today]
        if futurs_cfe:
            resultats.append((min(futurs_cfe), 'CFE'))
        else:
            echeances = [next_working_day(date(y, 12, 15)) for y in [today.year, today.year + 1]]
            futurs = [e for e in echeances if e >= today]
            if futurs:
                resultats.append((min(futurs), 'CFE'))

    resultats.sort(key=lambda x: x[0])
    return resultats[:4]

@app.route('/calendrier')
@login_required
def calendrier():
    """Calendrier prévisionnel : vue annuelle par catégorie (tva, IS, CFE, paie...)
    avec compteurs reste à faire / fait / prochaine échéance, onglets par module."""
    from collections import defaultdict

    annee = request.args.get('annee', type=int) or date.today().year

    team_member_ids = None
    if current_user.role == 'manager':
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        ids = [current_user.id]
        for eq in mes_equipes:
            ids.extend([m.id for m in eq.membres.all()])
        team_member_ids = list(set(ids))
    elif current_user.role != 'admin':
        team_member_ids = [current_user.id]

    taches_q = Tache.query.filter(
        Tache.date_echeance.between(date(annee, 1, 1), date(annee, 12, 31))
    )
    if team_member_ids:
        dossiers_ids = [d.id for d in Dossier.query.filter(Dossier.collaborateur_id.in_(team_member_ids)).all()]
        taches_q = taches_q.filter(Tache.dossier_id.in_(dossiers_ids))
    taches_list = taches_q.filter(~Tache.titre.ilike('%Préparation%')).all()

    def _categorie(t):
        titre = (t.titre or '').lower()
        if 'tva' in titre:
            return 'tva', 'Récurrents - TVA'
        if 'acompte' in titre and 'is' in titre:
            return 'is_acompte', 'IS - Acomptes'
        if 'is' in titre and ('dépôt' in titre or 'depot' in titre or 'déclaration' in titre or 'declaration' in titre):
            return 'is_depot', 'IS - Déclaration'
        if 'cfe' in titre:
            return 'cfe', 'CFE'
        if 'liasse' in titre:
            return 'liasse', 'Liasse fiscale'
        if 'paie' in titre or 'bulletin' in titre or 'salaire' in titre:
            return 'paie', 'Paie'
        if 'tenue' in titre:
            return 'tenue', 'Tenue comptable'
        if 'impot' in titre or 'fiscal' in titre or 'déclaration' in titre or 'declaration' in titre:
            return 'fiscal_autres', 'Fiscal - Autres'
        return 'autres', 'Autres'

    def _module(t):
        titre = (t.titre or '').lower()
        if any(k in titre for k in ('tva', 'is ', 'is-', 'acompte', 'cfe', 'liasse', 'impot', 'fiscal', 'déclaration', 'declaration')):
            return 'fiscal'
        if any(k in titre for k in ('paie', 'bulletin', 'salaire', 'social', 'urssaf')):
            return 'social'
        return 'comptable'

    groupes = defaultdict(lambda: {'reste': 0, 'fait': 0, 'prochaine': None, 'module': '', 'label': ''})
    compteurs_modules = {'fiscal': 0, 'comptable': 0, 'social': 0}
    for t in taches_list:
        cat, label = _categorie(t)
        mod = _module(t)
        g = groupes[cat]
        g['label'] = label
        g['module'] = mod
        if t.statut == 'terminee':
            g['fait'] += 1
        else:
            g['reste'] += 1
            if g['prochaine'] is None or t.date_echeance < g['prochaine']:
                g['prochaine'] = t.date_echeance
        compteurs_modules[mod] += 1

    lignes = []
    for cat in sorted(groupes.keys(), key=lambda c: (groupes[c]['module'], -groupes[c]['reste'])):
        g = groupes[cat]
        lignes.append({
            'cat': cat, 'label': g['label'], 'module': g['module'],
            'reste': g['reste'], 'fait': g['fait'],
            'prochaine': g['prochaine'].strftime('%d/%m/%Y') if g['prochaine'] else '—',
            'total': g['reste'] + g['fait'],
        })

    data = {
        'annee': annee,
        'lignes': lignes,
        'compteurs': {
            'tous': len(taches_list),
            'fiscal': compteurs_modules['fiscal'],
            'comptable': compteurs_modules['comptable'],
            'social': compteurs_modules['social'],
        },
    }
    if request.args.get('format') == 'json':
        from flask import jsonify
        return jsonify(data)
    return render_template('calendrier.html', data=data, annee=annee,
                           annees=sorted({date.today().year, date.today().year - 1, date.today().year - 2, date.today().year + 1}, reverse=True))


@app.route('/analytics')
@login_required
def analytics():
    """Dashboard analytics inspiré FollowApp : KPI annulaires, échéancier mensuel,
    répartition statuts, dossiers par utilisateur / forme juridique / secteur."""
    annee = request.args.get('annee', type=int) or date.today().year

    # ---- Scoping identique au dashboard : manager = ses équipes, sinon ses dossiers
    team_member_ids = None
    if current_user.role == 'manager':
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        ids = [current_user.id]
        for eq in mes_equipes:
            ids.extend([m.id for m in eq.membres.all()])
        team_member_ids = list(set(ids))
    elif current_user.role != 'admin':
        team_member_ids = [current_user.id]

    dossiers_q = Dossier.query
    if team_member_ids:
        dossiers_q = dossiers_q.filter(Dossier.collaborateur_id.in_(team_member_ids))
    dossiers_list = dossiers_q.all()

    # ---- Tâches de l'année (deadline fiscale ou échéance de tâche), hors « Préparation »
    taches_q = Tache.query.filter(
        Tache.date_echeance.between(date(annee, 1, 1), date(annee, 12, 31))
    )
    if team_member_ids:
        dossiers_ids = [d.id for d in dossiers_list]
        taches_q = taches_q.filter(Tache.dossier_id.in_(dossiers_ids))
    taches_list = taches_q.filter(~Tache.titre.ilike('%Préparation%')).all()

    def _module(t):
        titre = (t.titre or '').lower()
        if any(k in titre for k in ('tva', 'is ', 'is-', 'acompte', 'cfe', 'liasse', 'impot', 'fiscal', 'déclaration', 'declaration')):
            return 'fiscal'
        if any(k in titre for k in ('paie', 'bulletin', 'salaire', 'social', 'urssaf')):
            return 'social'
        return 'comptable'

    # ---- Par module : fait / reste
    modules = {'fiscal': {'fait': 0, 'reste': 0}, 'comptable': {'fait': 0, 'reste': 0}, 'social': {'fait': 0, 'reste': 0}}
    par_mois = {m: {'fait': 0, 'reste': 0} for m in range(1, 13)}
    statuts = {'fait': 0, 'a_faire': 0, 'en_retard': 0}
    for t in taches_list:
        mod = _module(t)
        est_fait = (t.statut == 'terminee')
        est_retard = t.est_en_retard()
        if est_fait:
            modules[mod]['fait'] += 1
            statuts['fait'] += 1
            par_mois[t.date_echeance.month]['fait'] += 1
        else:
            modules[mod]['reste'] += 1
            statuts['en_retard' if est_retard else 'a_faire'] += 1
            par_mois[t.date_echeance.month]['reste'] += 1
    total_taches = len(taches_list)

    # ---- Par utilisateur (dossiers suivis + tâches)
    par_user = {}
    for d in dossiers_list:
        u = d.collaborateur
        if u:
            e = par_user.setdefault(u.id, {'nom': f"{u.prenom} {u.nom}", 'dossiers': 0, 'taches': 0})
            e['dossiers'] += 1
    from collections import Counter
    tache_user = Counter(t.assigne_a for t in taches_list if t.assigne_a)
    for uid, c in tache_user.items():
        if uid in par_user:
            par_user[uid]['taches'] = c
        else:
            u = User.query.get(uid)
            if u:
                par_user[uid] = {'nom': f"{u.prenom} {u.nom}", 'dossiers': 0, 'taches': c}
    par_user_list = sorted(par_user.values(), key=lambda x: -x['taches'])[:10]

    # ---- Formes juridiques / secteurs
    formes = Counter((d.forme_juridique or 'Non renseigné') for d in dossiers_list)
    secteurs = Counter((d.secteur_activite or 'Non renseigné') for d in dossiers_list)

    data = {
        'annee': annee,
        'total_dossiers': len(dossiers_list),
        'total_taches': total_taches,
        'modules': modules,
        'par_mois': par_mois,
        'statuts': statuts,
        'par_user': par_user_list,
        'formes': formes.most_common(),
        'secteurs': secteurs.most_common(),
    }

    if request.args.get('format') == 'json':
        from flask import jsonify
        return jsonify(data)

    return render_template('analytics.html', data=data, annee=annee,
                           annees=sorted({date.today().year, date.today().year - 1, date.today().year - 2}, reverse=True))


@app.route('/dossiers')
@login_required
def dossiers():
    """Affiche la liste des dossiers selon le rôle de l'utilisateur."""
    current_equipe = None
    all_equipes_for_switch = []

    if current_user.role == 'admin':
        equipe_id = session.get('current_equipe_id')
        if equipe_id:
            equipe = Equipe.query.get(equipe_id)
            current_equipe = equipe
            all_equipes_for_switch = Equipe.query.order_by(Equipe.nom).all()
            team_user_ids = [m.id for m in equipe.membres.all()] if equipe else []
            membres = User.query.filter(User.id.in_(team_user_ids), User.actif==True).all()
            all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_user_ids)).all()
        else:
            current_equipe = None
            all_equipes_for_switch = Equipe.query.order_by(Equipe.nom).all()
            membres = User.query.filter_by(actif=True).all()
            all_dossiers = Dossier.query.all()
    elif current_user.role == 'manager':
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        all_equipes_for_switch = mes_equipes
        current_equipe = None
        team_member_ids = [current_user.id]
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_member_ids)).all()
        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()
    else:
        mes_equipes = current_user.equipes.filter_by(actif=True).all() if hasattr(current_user, 'equipes') else []
        all_equipes_for_switch = mes_equipes
        current_equipe = None
        team_member_ids = [current_user.id]
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_member_ids)).all()
        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()
    
    # Pre-calculate TVA task data for each dossier to avoid Jinja template errors
    for d in all_dossiers:
        d._tva_taches = [t for t in d.taches if t.titre and ('TVA' in t.titre.upper() or 'CA3' in t.titre.upper() or 'CA12' in t.titre.upper())]
        d._tva_taches_count = len(d._tva_taches)
        d._tva_taches_restantes = sum(1 for t in d._tva_taches if t.statut not in ('terminee', 'terminée'))
        # Calcul du statut délai/retard
        d._delai_label = '-'
        d._delai_class = 'text-tertiary'
        d._delai_icon = ''
        today = date.today()
        depot_taches = [t for t in d.taches if t.titre and 'Préparation' not in t.titre and ('Dépôt' in t.titre or 'Déclaration' in t.titre or 'Acompte' in t.titre)]
        if depot_taches:
            import calendar
            debut_mois = today.replace(day=1)
            fin_mois = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
            # 1. La tâche de la période courante (mois en cours) est la référence
            mois_courant = [t for t in depot_taches if t.date_echeance and debut_mois <= t.date_echeance <= fin_mois]
            if mois_courant:
                cible = min(mois_courant, key=lambda t: t.date_echeance)
            else:
                # 2. Sinon : prochaine tâche future déjà générée
                futurs = [t for t in depot_taches if t.date_echeance and t.date_echeance > today]
                if futurs:
                    cible = min(futurs, key=lambda t: t.date_echeance)
                else:
                    # 3. Aucune tâche générée (horizon 1 mois) → échéance théorique
                    cible = None
            if cible and cible.date_echeance:
                restant = (cible.date_echeance - today).days
                done = cible.statut in ('terminee', 'terminée')
                if done:
                    d._delai_label = 'Déclaré'
                    d._delai_class = 'text-success'
                    d._delai_icon = 'bi-check-circle-fill'
                elif restant < 0:
                    d._delai_label = f'En retard (+{abs(restant)} j)'
                    d._delai_class = 'text-danger'
                    d._delai_icon = 'bi-exclamation-triangle-fill'
                elif restant == 0:
                    d._delai_label = "Aujourd'hui"
                    d._delai_class = 'text-warning'
                    d._delai_icon = 'bi-clock'
                else:
                    d._delai_label = f'{restant} j'
                    d._delai_class = 'text-success'
                    d._delai_icon = 'bi-clock'
            else:
                # Échéance théorique : délai vers la prochaine échéance, sans statut Déclaré/En retard
                theo = prochaine_echeance_theorique(d, today)
                if theo:
                    restant = (theo - today).days
                    if restant == 0:
                        d._delai_label = "Aujourd'hui"
                        d._delai_class = 'text-warning'
                        d._delai_icon = 'bi-clock'
                    else:
                        d._delai_label = f'{restant} j'
                        d._delai_class = 'text-success'
                        d._delai_icon = 'bi-clock'
        elif d.date_limite_declaration:
            restant = (d.date_limite_declaration - today).days
            if restant < 0:
                d._delai_label = f'En retard (+{abs(restant)} j)'
                d._delai_class = 'text-danger'
                d._delai_icon = 'bi-exclamation-triangle-fill'
            elif restant == 0:
                d._delai_label = "Aujourd'hui"
                d._delai_class = 'text-warning'
                d._delai_icon = 'bi-clock'
            else:
                d._delai_label = f'{restant} j'
                d._delai_class = 'text-success'
                d._delai_icon = 'bi-clock'
        d._regime_norm = (d.regime_tva or '').lower()
        d._freq_norm = (d.frequence_tva or '').lower()
        d._date_iso = d.date_limite_declaration.strftime('%Y-%m-%d') if d.date_limite_declaration else ''
        d._echeances = prochaine_echeance_par_nature(d, today)
        # data-date-iso ← première échéance (pour le filtre date)
        if d._echeances:
            d._date_iso = d._echeances[0][0].strftime('%Y-%m-%d')
        # Combo régime + fréquence pour l'affichage et le filtre unifié
        _r = d._regime_norm
        _f = d._freq_norm
        if _r in ('mensuel', 'ca3') and _f not in ('trimestrielle', 'trimestriel'):
            d._regime_combo = 'ca3_mensuelle'
        elif _r == 'trimestriel' or (_r == 'ca3' and _f in ('trimestrielle', 'trimestriel')):
            d._regime_combo = 'ca3_trimestrielle'
        elif _r in ('annuel', 'ca12'):
            d._regime_combo = 'ca12_annuel'
        elif _r == 'exonere':
            d._regime_combo = 'exonere'
        else:
            d._regime_combo = ''
    
    # Construire les données JSON pour le modal d'édition
    dossiers_data = {}
    dossiers_par_collab = {}
    for d in all_dossiers:
        dossiers_data[d.id] = {
            'numero_dossier': d.numero_dossier,
            'intitule': d.intitule,
            'collaborateur_id': d.collaborateur_id,
            'equipe_id': d.equipe_id,
            'regime_tva': d.regime_tva,
            'frequence_tva': d.frequence_tva,
            'date_limite_declaration': d.date_limite_declaration.strftime('%Y-%m-%d') if d.date_limite_declaration else None,
            'date_acompte_1': d.date_acompte_1.strftime('%Y-%m-%d') if d.date_acompte_1 else None,
            'date_acompte_2': d.date_acompte_2.strftime('%Y-%m-%d') if d.date_acompte_2 else None,
            'regime_fiscale': d.regime_fiscale,
            'has_cfe': d.has_cfe,
            'forme_juridique': d.forme_juridique,
            'secteur_activite': d.secteur_activite,
            'pennylane_api_token_set': bool(d.pennylane_api_token),
        }
        if d.collaborateur_id:
            dossiers_par_collab[d.collaborateur_id] = dossiers_par_collab.get(d.collaborateur_id, 0) + 1

    return render_template('dossiers.html', dossiers=all_dossiers, membres=membres,
        equipes=Equipe.query.order_by(Equipe.nom).all(), Tache=Tache,
        current_equipe=current_equipe, all_equipes_for_switch=all_equipes_for_switch, db=db,
        show_actions=True, dossiers_data=dossiers_data, dossiers_par_collab=dossiers_par_collab)

@app.route('/tva-taches')
@login_required
def tva_taches():
    """Affiche la liste des t\u00e2ches TVA avec filtrage par statut."""
    statut_filter = request.args.get('statut', 'all')
    query = Tache.query.filter(
        db.or_(
            Tache.titre.like('%TVA%'),
            Tache.titre.like('%CA3%'),
            Tache.titre.like('%ca3%'),
            Tache.titre.like('%CA12%'),
            Tache.titre.like('%ca12%')
        )
    )
    if statut_filter != 'all':
        query = query.filter_by(statut=statut_filter)
    tva_taches = query.order_by(Tache.date_echeance.asc(), Tache.titre.asc()).all()

    base_filter = db.or_(
        Tache.titre.like('%TVA%'),
        Tache.titre.like('%CA3%'),
        Tache.titre.like('%ca3%'),
        Tache.titre.like('%CA12%'),
        Tache.titre.like('%ca12%')
    )
    total_taches = Tache.query.filter(base_filter).count()
    taches_a_faire = Tache.query.filter(base_filter, Tache.statut == 'a_faire').count()
    taches_en_cours = Tache.query.filter(base_filter, Tache.statut == 'en_cours').count()
    taches_terminees = Tache.query.filter(base_filter, Tache.statut == 'terminee').count()

    return render_template('tva_taches.html', tva_taches=tva_taches,
        statut_filter=statut_filter, total_taches=total_taches,
        taches_a_faire=taches_a_faire, taches_en_cours=taches_en_cours,
        taches_terminees=taches_terminees)

@app.route('/planifier_tous_impots', methods=['POST'])
@login_required
def planifier_tous_impots():
    """Endpoint pour planifier les impôts de TOUS les dossiers."""
    if current_user.role not in ('admin', 'manager'):
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dossiers'))
    try:
        from .tva_scheduler import planifier_tous_les_dossiers
        planifier_tous_les_dossiers()
        flash('Planification des impôts pour tous les dossiers terminée avec succès.', 'success')
    except Exception as e:
        app.logger.error(f"Erreur planification tous impôts: {e}")
        flash('Erreur lors de la planification.', 'danger')
    return redirect(url_for('dossiers'))

@app.route('/tva-planifier', methods=['POST'])
@login_required
def planifier_taches_tva():
    """Endpoint pour d\u00e9clencher la planification des t\u00e2ches TVA pour tous les dossiers."""
    if current_user.role not in ('admin', 'manager'):
        flash('Acc\u00e8s refus\u00e9.', 'danger')
        return redirect(url_for('dossiers'))
    try:
        from .tva_scheduler import planifier_impots_dossier
        from app.models import Dossier
        dossiers = Dossier.query.all()
        for dossier in dossiers:
            planifier_impots_dossier(dossier)
        flash('Planification des imp\u00f4ts (TVA, IS, CFE) termin\u00e9e avec succ\u00e8s.', 'success')
    except Exception as e:
        app.logger.error(f"Erreur lors de la planification des imp\u00f4ts: {e}")
        flash('Erreur lors de la planification des imp\u00f4ts.', 'danger')
    return redirect(url_for('dossiers'))

@app.route('/taches', methods=['GET', 'POST'])
@login_required
def taches():
    """Affiche la liste des tâches et gère la création."""
    if request.method == 'POST':
        titre = request.form.get('titre', '').strip()
        if not titre:
            flash('Le titre est obligatoire.', 'warning')
            return redirect(url_for('taches'))
        t = Tache(
            titre=titre,
            description=request.form.get('description', '').strip(),
            dossier_id=request.form.get('dossier_id', type=int) or None,
            assigne_a=request.form.get('assigne_a', type=int) or None,
            priorite=request.form.get('priorite', 'moyenne'),
            statut=request.form.get('statut', 'a_faire'),
            date_echeance=datetime.strptime(request.form['date_echeance'], '%Y-%m-%d').date() if request.form.get('date_echeance') else None,
            cree_par=current_user.id,
            frequence_repetition=request.form.get('frequence_repetition') or None,
        )
        # Date de fin de répétition
        fin_repetition_val = request.form.get('fin_repetition')
        if fin_repetition_val:
            try:
                t.fin_repetition = datetime.strptime(fin_repetition_val, '%Y-%m-%d').date()
            except ValueError:
                pass
        db.session.add(t)
        db.session.flush()  # pour obtenir t.id avant de pré-générer les occurrences
        
        # Pré-générer les occurrences récurrentes (horizon 1 mois comme les deadlines)
        if t.frequence_repetition and t.date_echeance:
            max_date = date.today() + timedelta(days=30)
            if t.fin_repetition and t.fin_repetition < max_date:
                max_date = t.fin_repetition
            next_date = t.date_echeance
            for _ in range(36):  # sécurité : max 36 occurrences
                if t.frequence_repetition == 'daily':
                    next_date += timedelta(days=1)
                elif t.frequence_repetition == 'weekly':
                    next_date += timedelta(weeks=1)
                elif t.frequence_repetition == 'monthly':
                    m = next_date.month + 1
                    y = next_date.year
                    if m > 12: m = 1; y += 1
                    try:
                        next_date = date(y, m, t.date_echeance.day)
                    except ValueError:
                        next_date = date(y, m, min(t.date_echeance.day, 28))
                elif t.frequence_repetition == 'yearly':
                    try:
                        next_date = date(next_date.year + 1, next_date.month, next_date.day)
                    except ValueError:
                        next_date = date(next_date.year + 1, next_date.month, 28)
                else:
                    break
                if next_date > max_date:
                    break
                new_t = Tache(
                    titre=t.titre, description=t.description,
                    dossier_id=t.dossier_id, assigne_a=t.assigne_a,
                    priorite=t.priorite, statut='a_faire',
                    date_echeance=next_date, cree_par=t.cree_par,
                    frequence_repetition=t.frequence_repetition,
                    fin_repetition=t.fin_repetition,
                    template_id=t.id,
                )
                db.session.add(new_t)
                # Notifier l'assigné
                if new_t.assigne_a:
                    from app.models import Notification as NotifCls
                    notif = NotifCls(user_id=new_t.assigne_a, tache_id=new_t.id,
                        message=f"Nouvelle occurrence : {new_t.titre}", type_notification='assignation')
                    db.session.add(notif)
            db.session.commit()
        db.session.commit()
        
        # Notification email + in-app
        fiscal_keywords = ['tva', 'is ', 'cfe ', 'acompte', 'dépôt', 'préparation', 'déclaration', 'prépa']
        is_fiscal = any(kw in titre.lower() for kw in fiscal_keywords)
        
        if t.assigne_a:
            # Vérifier si c'est une tâche de deadline antérieure → auto-terminée
            if is_fiscal and t.date_echeance and t.date_echeance < date.today():
                t.statut = 'terminee'
                t.date_completion = datetime.utcnow()
                db.session.commit()
            # Créer notification in-app
            notif_msg = f"Nouvelle tâche assignée : {t.titre}"
            notif = Notification(user_id=t.assigne_a, tache_id=t.id, message=notif_msg, type_notification='assignation')
            db.session.add(notif)
            db.session.commit()
            
            # Envoyer email d'assignation (tous les types de tâches)
            try:
                from app.integrations.brevo import send_task_assigned_email_brevo
                send_task_assigned_email_brevo(t, t.assigne_a)
            except Exception as e:
                app.logger.warning(f"Send email failed: {e}")
        
        flash('Tâche créée avec succès.', 'success')
        return redirect(url_for('taches'))
    
    current_equipe = None
    all_equipes_for_switch = []
    membres = []

    if current_user.role == 'admin':
        equipe_id = session.get('current_equipe_id')
        if equipe_id:
            equipe = Equipe.query.get(equipe_id)
            current_equipe = equipe
            all_equipes_for_switch = Equipe.query.order_by(Equipe.nom).all()
            team_user_ids = [m.id for m in equipe.membres.all()] if equipe else []
            membres = User.query.filter(User.id.in_(team_user_ids), User.actif==True).all()
            all_taches = Tache.query.filter(Tache.assigne_a.in_(team_user_ids)).all() if team_user_ids else []
        else:
            current_equipe = None
            all_equipes_for_switch = Equipe.query.order_by(Equipe.nom).all()
            membres = User.query.filter_by(actif=True).all()
            all_taches = Tache.query.all()
    elif current_user.role == 'manager':
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        all_equipes_for_switch = mes_equipes
        current_equipe = None
        team_member_ids = [current_user.id]
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()
        all_taches = Tache.query.filter(Tache.assigne_a.in_(team_member_ids)).all()
    else:
        mes_equipes = current_user.equipes.filter_by(actif=True).all() if hasattr(current_user, 'equipes') else []
        all_equipes_for_switch = mes_equipes
        current_equipe = None
        team_member_ids = [current_user.id]
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()
        all_taches = Tache.query.filter(Tache.assigne_a.in_(team_member_ids)).all()
    return render_template('taches.html', taches=all_taches, membres=membres,
        equipes=Equipe.query.order_by(Equipe.nom).all(), Tache=Tache,
        current_equipe=current_equipe, all_equipes_for_switch=all_equipes_for_switch, db=db,
        dossiers=Dossier.query.order_by(Dossier.numero_dossier).all(),
        dossier_filtre=request.args.get('dossier', type=int),
        date=date, timedelta=timedelta)

@app.route('/equipes')
@login_required
def equipes():
    """Affiche la liste des \u00e9quipes."""
    equipes = Equipe.query.order_by(Equipe.nom).all()
    return render_template('equipes.html', equipes=equipes)

@app.route('/notifications')
@login_required
def notifications_page():
    notifications = current_user.notifications.order_by(Notification.date_envoi.desc()).all() if hasattr(current_user, 'notifications') else []
    unread_count = sum(1 for n in notifications if not n.lu)
    return render_template('notifications.html', notifications=notifications, unread_count=unread_count)

@app.route('/notifications/non_lues')
@login_required
def notifications_non_lues():
    """API JSON pour les notifications non lues."""
    notifications = current_user.notifications.filter_by(lu=False).order_by(Notification.date_envoi.desc()).all() if hasattr(current_user, 'notifications') else []
    return jsonify({
        'count': len(notifications),
        'last_message': notifications[0].message if notifications else '',
        'notifications': [{'id': n.id, 'message': n.message, 'date': n.date_envoi.strftime('%d/%m/%Y %H:%M') if n.date_envoi else None} for n in notifications[:5]]
    })

@app.route('/set-team/<int:equipe_id>')
@login_required
def set_team(equipe_id):
    equipe = Equipe.query.get_or_404(equipe_id)
    session['current_equipe_id'] = equipe.id
    flash(f'\u00c9quipe s\u00e9lectionn\u00e9e : {equipe.nom}', 'success')
    return redirect(url_for('dossiers'))

# ==========================
# Routes membres
# ==========================
@app.route('/membres')
@login_required
def membres():
    """Page de gestion des membres - corrig\u00e9e avec toutes les variables attendues par le template."""
    from app.models import User, Equipe
    membres_list = User.query.filter_by(actif=True).order_by(User.nom).all()
    toutes_equipes = Equipe.query.order_by(Equipe.nom).all()
    mes_equipes = []
    if current_user.role == 'manager':
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
    return render_template('membres.html', membres=membres_list, toutes_equipes=toutes_equipes, mes_equipes=mes_equipes, title="Membres")

@app.route('/liste_membres')
@login_required
def liste_membres():
    return redirect(url_for('membres'))

@app.route('/fiche_membre/<int:user_id>', methods=['GET', 'POST'])
@login_required
def fiche_membre(user_id):
    """Page de fiche détaillée d'un membre."""
    user = User.query.get_or_404(user_id)
    from datetime import date
    from datetime import timedelta
    
    # Admin peut changer l'email
    if request.method == 'POST' and current_user.role == 'admin':
        new_email = request.form.get('email', '').strip()
        if new_email and new_email != user.email:
            existing = User.query.filter_by(email=new_email).first()
            if existing and existing.id != user.id:
                flash('Cet email est déjà utilisé.', 'danger')
            else:
                user.email = new_email
                db.session.commit()
                flash('Email mis à jour.', 'success')
        return redirect(url_for('fiche_membre', user_id=user.id))
    
    # Récupérer les dossiers du collaborateur
    dossiers_list = Dossier.query.filter_by(collaborateur_id=user.id).all()
    
    # Récupérer les tâches assignées
    taches_list = Tache.query.filter_by(assigne_a=user.id).order_by(Tache.date_echeance.desc()).all()
    
    # Calculer les stats
    dossiers_en_cours = [d for d in dossiers_list if not d.date_cloture]
    taches_terminees = [t for t in taches_list if t.statut in ('terminee', 'terminée')]
    taches_en_retard = [t for t in taches_list if t.statut not in ('terminee', 'terminée') and t.date_echeance and t.date_echeance < date.today()]
    total_taches = len(taches_list)
    
    taux_respect = 0
    if total_taches > 0:
        taux_respect = int(len(taches_terminees) / total_taches * 100)
    
    en_retard = len(taches_en_retard)
    score = max(0, min(100, taux_respect - en_retard * 5))
    
    return render_template('fiche_membre.html',
        membre=user,
        dossiers_en_cours=dossiers_en_cours,
        total_terminees=len(taches_terminees),
        taches_membre=taches_list[:20],
        taux_respect=taux_respect,
        en_retard=en_retard,
        score=score)

@app.route('/ajouter_membre', methods=['POST'])
@login_required
def ajouter_membre():
    """Ajoute un nouveau membre avec tous les champs du formulaire."""
    if current_user.role not in ('admin', 'manager'):
        flash('Acc\u00e8s refus\u00e9.', 'danger')
        return redirect(url_for('membres'))
    try:
        prenom = request.form.get('prenom', '').strip()
        nom = request.form.get('nom', '').strip()
        email = request.form.get('email', '').strip().lower()
        mot_de_passe = request.form.get('mot_de_passe', '').strip()
        role = request.form.get('role', 'membre')
        poste = request.form.get('poste', '').strip()
        telephone = request.form.get('telephone', '').strip()

        if not prenom or not nom or not email or not mot_de_passe:
            flash('Veuillez remplir tous les champs obligatoires.', 'danger')
            return redirect(url_for('membres'))

        if User.query.filter_by(email=email).first():
            flash('Cet email est d\u00e9j\u00e0 utilis\u00e9.', 'danger')
            return redirect(url_for('membres'))

        from werkzeug.security import generate_password_hash
        user = User(
            prenom=prenom,
            nom=nom,
            email=email,
            password_hash=generate_password_hash(mot_de_passe),
            role=role,
            poste=poste if poste else None,
            telephone=telephone if telephone else None,
            actif=True
        )
        db.session.add(user)
        db.session.commit()
        flash(f'Membre {prenom} {nom} ajout\u00e9 avec succ\u00e8s.', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erreur ajout membre: {e}")
        flash('Erreur lors de l\'ajout du membre.', 'danger')
    return redirect(url_for('membres'))

@app.route('/assigner_equipe', methods=['POST'])
@login_required
def assigner_equipe():
    """Assigner un membre \u00e0 une \u00e9quipe (admin seulement)."""
    if current_user.role != 'admin':
        flash('Acc\u00e8s refus\u00e9.', 'danger')
        return redirect(url_for('membres'))
    user_id = request.form.get('user_id')
    equipe_id = request.form.get('equipe_id')
    if user_id:
        user = User.query.get(int(user_id))
        if user and equipe_id:
            user.equipe_id = int(equipe_id)
            db.session.commit()
            flash(f'\u00c9quipe mise \u00e0 jour pour {user.prenom} {user.nom}.', 'success')
        elif user:
            user.equipe_id = None
            db.session.commit()
            flash(f'\u00c9quipe retir\u00e9e pour {user.prenom} {user.nom}.', 'info')
    return redirect(url_for('membres'))

@app.route('/assigner_equipe_manager', methods=['POST'])
@login_required
def assigner_equipe_manager():
    """Assigner un membre \u00e0 une \u00e9quipe (manager seulement)."""
    if current_user.role != 'manager':
        flash('Acc\u00e8s refus\u00e9.', 'danger')
        return redirect(url_for('membres'))
    user_id = request.form.get('user_id')
    equipe_id = request.form.get('equipe_id')
    if user_id:
        user = User.query.get(int(user_id))
        if user and equipe_id:
            user.equipe_id = int(equipe_id)
            db.session.commit()
            flash(f'\u00c9quipe mise \u00e0 jour pour {user.prenom} {user.nom}.', 'success')
    return redirect(url_for('membres'))

@app.route('/supprimer_membre/<int:user_id>', methods=['GET', 'POST'])
@login_required
def supprimer_membre(user_id):
    """Supprime un membre de façon définitive."""
    if current_user.role not in ('admin', 'manager'):
        flash('Accès refusé.', 'danger')
        return redirect(url_for('membres'))
    user = User.query.get_or_404(user_id)
    if user.role == 'admin' and current_user.role != 'admin':
        flash('Seul un admin peut supprimer un autre admin.', 'danger')
        return redirect(url_for('membres'))
    try:
        # Nettoyer les dépendances avant suppression
        from app.models import Tache, Notification, CommentaireTache, Suggestion, Dossier, Equipe, Performance
        # 1. Réassigner les tâches assignées à cet utilisateur (mettre à None)
        Tache.query.filter_by(assigne_a=user_id).update({'assigne_a': None})
        Tache.query.filter_by(cree_par=user_id).update({'cree_par': None})
        # 2. Supprimer les notifications
        Notification.query.filter_by(user_id=user_id).delete()
        # 3. Réassigner les dossiers dont il est collaborateur
        Dossier.query.filter_by(collaborateur_id=user_id).update({'collaborateur_id': None})
        # 4. Réassigner les suggestions
        Suggestion.query.filter_by(cree_par=user_id).update({'cree_par': None})
        # 5. Si l'utilisateur est manager d'équipes, retirer la gestion
        Equipe.query.filter_by(manager_id=user_id).update({'manager_id': None})
        # 6. Supprimer les commentaires de tâches
        CommentaireTache.query.filter_by(user_id=user_id).delete()
        # 7. Supprimer les performances
        Performance.query.filter_by(user_id=user_id).delete()
        db.session.flush()
        db.session.delete(user)
        db.session.commit()
        flash(f'Membre {user.prenom} {user.nom} supprimé.', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erreur suppression membre {user_id}: {e}")
        flash(f'Erreur lors de la suppression: {str(e)}', 'danger')
    return redirect(url_for('membres'))

# ==========================
# Suggestions
# ==========================
@app.route('/suggestions')
@login_required
def suggestions_page():
    """Page de suggestions - version corrigée."""
    from app.models import Suggestion, User, Equipe
    from app import db
    
    if current_user.role == 'admin':
        suggestions_list = Suggestion.query.order_by(Suggestion.date_creation.desc()).all()
    elif current_user.role == 'manager':
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        team_member_ids = [current_user.id]
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        suggestions_list = Suggestion.query.filter(Suggestion.cree_par.in_(team_member_ids)).order_by(Suggestion.date_creation.desc()).all()
    else:
        suggestions_list = Suggestion.query.filter_by(cree_par=current_user.id).order_by(Suggestion.date_creation.desc()).all()
    
    # Pass users and dossiers for the modal form
    all_users = User.query.filter_by(actif=True).order_by(User.nom).all()
    all_dossiers = Dossier.query.order_by(Dossier.numero_dossier).all()
    
    return render_template('suggestions.html', suggestions=suggestions_list, users=all_users, dossiers=all_dossiers)

@app.route('/api/suggestions', methods=['GET'])
@login_required
def api_suggestions():
    """API pour récupérer les suggestions au format JSON."""
    try:
        from app.models import Suggestion
        status_filter = request.args.get('status', 'all')
        
        if current_user.role == 'admin':
            query = Suggestion.query
        elif current_user.role == 'manager':
            mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
            team_member_ids = [current_user.id]
            for eq in mes_equipes:
                team_member_ids.extend([m.id for m in eq.membres.all()])
            query = Suggestion.query.filter(Suggestion.cree_par.in_(team_member_ids))
        else:
            query = Suggestion.query.filter_by(cree_par=current_user.id)
        
        if status_filter in ('en_attente', 'validee', 'rejetee'):
            query = query.filter_by(statut=status_filter)
        
        items = query.order_by(Suggestion.date_creation.desc()).limit(20).all()
        
        return jsonify({
            'ok': True,
            'suggestions': [{
                'id': s.id,
                'titre': s.titre,
                'titre_suggere': s.titre_suggere or s.titre,
                'sujet': s.sujet,
                'description_suggeree': s.description_suggeree or s.description,
                'priorite_suggeree': s.priorite_suggeree or s.priorite or 'moyenne',
                'statut': s.statut or 'en_attente',
                'date_creation': s.date_creation.strftime('%d/%m/%Y') if s.date_creation else None,
                'date_echeance': s.date_echeance.strftime('%d/%m/%Y') if s.date_echeance else None,
                'dossier_nom': f"{s.dossier.numero_dossier} - {s.dossier.intitule}" if s.dossier_id else None,
                'dossier_id': s.dossier_id,
                'assigne_a': s.assigne_a,
                'source': s.source,
                'mail_uid': s.mail_uid
            } for s in items]
        })
    except Exception as e:
        app.logger.error(f"api_suggestions error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/suggestions/refresh', methods=['POST'])
@login_required
def api_suggestions_refresh():
    """Endpoint pour rafraîchir les suggestions."""
    try:
        from app.models import Suggestion
        if current_user.role == 'admin':
            items = Suggestion.query.order_by(Suggestion.date_creation.desc()).limit(20).all()
        elif current_user.role == 'manager':
            mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
            team_member_ids = [current_user.id]
            for eq in mes_equipes:
                team_member_ids.extend([m.id for m in eq.membres.all()])
            items = Suggestion.query.filter(Suggestion.cree_par.in_(team_member_ids)).order_by(Suggestion.date_creation.desc()).limit(20).all()
        else:
            items = Suggestion.query.filter_by(cree_par=current_user.id).order_by(Suggestion.date_creation.desc()).limit(20).all()
        return jsonify({'ok': True, 'suggestions': [{'id': s.id, 'titre': s.titre} for s in items]})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/suggestions/<int:suggestion_id>/validate', methods=['POST'])
@login_required
def api_suggestions_validate(suggestion_id):
    """Valider une suggestion et créer la tâche correspondante."""
    try:
        from app.models import Suggestion, Tache
        suggestion = Suggestion.query.get_or_404(suggestion_id)
        data = request.get_json() or {}
        
        assignee = data.get('assignee') or suggestion.assigne_a
        due_date = data.get('due_date')
        if due_date:
            due_date = datetime.strptime(due_date, '%Y-%m-%d').date()
        priority = data.get('priority') or suggestion.priorite or 'moyenne'
        dossier_id = data.get('dossier_id') or suggestion.dossier_id
        
        titre = suggestion.titre_suggere or suggestion.titre or 'Tâche depuis suggestion'
        description = suggestion.description_suggeree or suggestion.description or ''
        
        nouvelle_tache = Tache(
            titre=titre,
            description=description,
            assigne_a=int(assignee) if assignee else None,
            dossier_id=int(dossier_id) if dossier_id else None,
            priorite=priority,
            date_echeance=due_date,
            statut='a_faire',
            cree_par=current_user.id
        )
        db.session.add(nouvelle_tache)
        suggestion.statut = 'validee'
        db.session.commit()
        return jsonify({'ok': True, 'message': 'Tâche créée avec succès'})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"validate suggestion error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/suggestions/<int:suggestion_id>/reject', methods=['POST'])
@login_required
def api_suggestions_reject(suggestion_id):
    """Rejeter une suggestion."""
    try:
        from app.models import Suggestion
        suggestion = Suggestion.query.get_or_404(suggestion_id)
        suggestion.statut = 'rejetee'
        db.session.commit()
        return jsonify({'ok': True, 'message': 'Suggestion rejetée'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/suggestions/<int:suggestion_id>/reanalyze', methods=['POST'])
@login_required
def api_suggestions_reanalyze(suggestion_id):
    """Relancer l'analyse IA sur une suggestion."""
    try:
        from app.models import Suggestion
        suggestion = Suggestion.query.get_or_404(suggestion_id)
        # Pour l'instant, juste marquer comme ré-analysé
        suggestion.statut = 'en_attente'
        db.session.commit()
        return jsonify({'ok': True, 'message': 'Analyse relancée'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/suggestions/<int:suggestion_id>/delete', methods=['DELETE'])
@login_required
def api_suggestions_delete(suggestion_id):
    """Supprimer une suggestion."""
    try:
        from app.models import Suggestion
        suggestion = Suggestion.query.get_or_404(suggestion_id)
        db.session.delete(suggestion)
        db.session.commit()
        return jsonify({'ok': True, 'message': 'Suggestion supprimée'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/suggestions/reset', methods=['POST'])
@login_required
def api_suggestions_reset():
    """Réinitialiser toutes les suggestions."""
    try:
        from app.models import Suggestion
        if current_user.role == 'admin':
            Suggestion.query.delete()
            db.session.commit()
            return jsonify({'ok': True, 'message': 'Toutes les suggestions ont été supprimées'})
        else:
            return jsonify({'ok': False, 'error': 'Accès refusé'}), 403
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/suggestions/refresh_mailbox', methods=['POST'])
@login_required
def api_suggestions_refresh_mailbox():
    """Scanner la mailbox pour générer de nouvelles suggestions."""
    try:
        # Pour l'instant, retourne un message indiquant que la fonctionnalité n'est pas encore implémentée
        return jsonify({'ok': True, 'message': 'Scan de la mailbox non implémenté. Aucune nouvelle suggestion.'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ==========================
# Routes s\u00e9curit\u00e9 (stubs fonctionnels)
# ==========================
@app.route('/mes_dossiers')
@login_required
def mes_dossiers():
    return redirect(url_for('dossiers'))

@app.route('/mes_taches')
@login_required
def mes_taches():
    return redirect(url_for('taches'))

@app.route('/modifier_dossier/<int:dossier_id>', methods=['POST'])
@login_required
def modifier_dossier(dossier_id):
    """Modifie les caractéristiques d'un dossier et régénère les tâches fiscales associées."""
    dossier = Dossier.query.get_or_404(dossier_id)
    if current_user.role not in ('admin', 'manager'):
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dossiers'))
    try:
        numero_dossier = request.form.get('numero_dossier', '').strip()
        intitule = request.form.get('intitule', '').strip()
        collaborateur_id = request.form.get('collaborateur_id')
        equipe_id = request.form.get('equipe_id')
        regime_tva = request.form.get('regime_tva')
        frequence_tva = request.form.get('frequence_tva')
        date_limite_declaration = request.form.get('date_limite_declaration')
        date_acompte_1 = request.form.get('date_acompte_1')
        date_acompte_2 = request.form.get('date_acompte_2')
        regime_fiscale = request.form.get('regime_fiscale')
        has_cfe = ('has_cfe' in request.form)
        forme_juridique = (request.form.get('forme_juridique') or '').strip() or None
        secteur_activite = (request.form.get('secteur_activite') or '').strip() or None

        if not numero_dossier or not intitule or not collaborateur_id or not equipe_id:
            flash('Veuillez remplir tous les champs obligatoires.', 'danger')
            return redirect(url_for('dossiers'))

        date_limite = None
        if date_limite_declaration:
            try:
                date_limite = datetime.strptime(date_limite_declaration, '%Y-%m-%d').date()
            except ValueError:
                flash('Format de date invalide.', 'danger')
                return redirect(url_for('dossiers'))

        def _parse_date(v):
            if not v:
                return None
            try:
                return datetime.strptime(v, '%Y-%m-%d').date()
            except ValueError:
                return None

        # Détecter si les paramètres fiscaux ont changé → régénération nécessaire
        params_fiscaux_changes = (
            dossier.regime_tva != (regime_tva or None) or
            dossier.frequence_tva != (frequence_tva or None) or
            dossier.date_limite_declaration != date_limite or
            dossier.date_acompte_1 != _parse_date(date_acompte_1) or
            dossier.date_acompte_2 != _parse_date(date_acompte_2) or
            dossier.regime_fiscale != (regime_fiscale or None) or
            dossier.has_cfe != has_cfe
        )

        dossier.numero_dossier = numero_dossier
        dossier.intitule = intitule
        dossier.collaborateur_id = int(collaborateur_id)
        dossier.equipe_id = int(equipe_id)
        dossier.regime_tva = regime_tva if regime_tva else None
        dossier.frequence_tva = frequence_tva if frequence_tva else None
        dossier.date_limite_declaration = date_limite
        dossier.date_acompte_1 = _parse_date(date_acompte_1)
        dossier.date_acompte_2 = _parse_date(date_acompte_2)
        dossier.regime_fiscale = regime_fiscale if regime_fiscale else None
        dossier.has_cfe = has_cfe
        dossier.forme_juridique = forme_juridique
        dossier.secteur_activite = secteur_activite
        # Token Pennylane : ne mettre à jour que si un nouveau token est fourni
        # (champ vide = conserver le token existant)
        token_val = (request.form.get('pennylane_api_token') or '').strip()
        if token_val:
            dossier.pennylane_api_token = token_val
        db.session.flush()

        # Régénérer les tâches deadlines si les paramètres fiscaux ont changé
        if params_fiscaux_changes:
            from .tva_scheduler import planifier_impots_dossier
            planifier_impots_dossier(dossier)

        db.session.commit()
        flash('Dossier modifié avec succès. Les tâches fiscales ont été mises à jour.', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erreur lors de la modification du dossier {dossier_id}: {e}")
        flash(f'Erreur lors de la modification du dossier: {str(e)}', 'danger')
    return redirect(url_for('dossiers'))

@app.route('/regenerer_taches_dossier/<int:dossier_id>', methods=['POST'])
@login_required
def regenerer_taches_dossier(dossier_id):
    """Régénère les tâches fiscales (TVA, IS, CFE) d'un dossier."""
    dossier = Dossier.query.get_or_404(dossier_id)
    if current_user.role not in ('admin', 'manager'):
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dossiers'))
    try:
        from .tva_scheduler import planifier_impots_dossier
        planifier_impots_dossier(dossier)  # planifier fait ses propres commits internes
        flash(f"Tâches fiscales régénérées pour {dossier.numero_dossier}.", "success")
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erreur régénération dossier {dossier_id}: {e}")
        flash(f'Erreur lors de la régénération: {str(e)}', 'danger')
    return redirect(url_for('dossiers'))

@app.route('/prendre_en_charge/<int:tache_id>', methods=['POST'])
@login_required
def prendre_en_charge(tache_id):
    """Prendre en charge une tâche (membre ou assigné)."""
    tache = Tache.query.get_or_404(tache_id)
    
    # Vérifier les droits
    if current_user.role == 'membre' and tache.assigne_a != current_user.id:
        flash('Vous ne pouvez pas prendre en charge cette tâche.', 'danger')
        return redirect(url_for('taches'))
    if tache.statut != 'a_faire':
        flash('Cette tâche n\'est pas en attente de prise en charge.', 'warning')
        return redirect(url_for('taches'))
    
    tache.statut = 'en_cours'
    tache.date_prise_en_charge = datetime.utcnow()
    db.session.commit()
    
    # Notifier le créateur (manager) + in-app
    collab_nom = f"{current_user.prenom} {current_user.nom}"
    cree_par_id = tache.cree_par
    team_manager = None
    if not cree_par_id and tache.dossier and tache.dossier.equipe and tache.dossier.equipe.manager:
        team_manager = tache.dossier.equipe.manager
        cree_par_id = team_manager.id
    if cree_par_id and cree_par_id != current_user.id:
        notif = Notification(
            user_id=cree_par_id,
            tache_id=tache.id,
            message=f"{collab_nom} a pris en charge : {tache.titre}",
            type_notification='prise_en_charge'
        )
        db.session.add(notif)
        db.session.commit()
        # Envoyer email
        dest_user = User.query.get(cree_par_id)
        if dest_user and dest_user.email:
            try:
                if team_manager:
                    from app.integrations.brevo import send_email_via_brevo_api
                    send_email_via_brevo_api(
                        to_email=dest_user.email,
                        subject=f"Prise en charge : {tache.titre}",
                        body=f"Bonjour {dest_user.prenom},\n\n{collab_nom} a pris en charge la tâche \"{tache.titre}\"."
                    )
                else:
                    from app.integrations.brevo import send_task_taken_email_brevo
                    send_task_taken_email_brevo(tache, collab_nom)
            except Exception as e:
                app.logger.warning(f"Send email failed: {e}")
    
    flash('Tâche prise en charge.', 'success')
    return redirect(url_for('taches'))

@app.route('/settings')
@login_required
def settings():
    return redirect(url_for('profil'))

@app.route('/api/dossiers-membres')
@login_required
def api_dossiers_membres():
    """API pour alimenter les menus déroulants du modal de création de tâche.
       Si ?membre_id=X est fourni, ne retourne que les dossiers de ce membre."""
    membre_id = request.args.get('membre_id', type=int)
    
    query = Dossier.query.order_by(Dossier.numero_dossier)
    if membre_id:
        query = query.filter_by(collaborateur_id=membre_id)
    dossiers = query.all()
    
    membres = User.query.filter_by(actif=True).order_by(User.prenom).all()
    
    return jsonify({
        'ok': True,
        'dossiers': [{'id': d.id, 'label': f"{d.numero_dossier} — {d.intitule}"} for d in dossiers],
        'membres': [{'id': m.id, 'label': f"{m.prenom} {m.nom}"} for m in membres]
    })

@app.route('/supprimer_dossier/<int:dossier_id>')
@login_required
def supprimer_dossier(dossier_id):
    """Supprimer un dossier et toutes ses tâches associées."""
    dossier = Dossier.query.get_or_404(dossier_id)
    
    # Vérifier les droits
    if current_user.role == 'membre' and dossier.collaborateur_id != current_user.id:
        flash('Vous n\'avez pas les droits pour supprimer ce dossier.', 'danger')
        return redirect(url_for('dossiers'))
    
    try:
        # Supprimer les notifications et commentaires liés aux tâches du dossier
        tache_ids = [t.id for t in Tache.query.filter_by(dossier_id=dossier.id).all()]
        if tache_ids:
            Notification.query.filter(Notification.tache_id.in_(tache_ids)).delete(synchronize_session=False)
            CommentaireTache.query.filter(CommentaireTache.tache_id.in_(tache_ids)).delete(synchronize_session=False)
        # Supprimer les suggestions liées au dossier
        SuggestionTache.query.filter_by(dossier_id=dossier.id).delete()
        # Supprimer les tâches associées
        Tache.query.filter_by(dossier_id=dossier.id).delete()
        # Supprimer le dossier
        db.session.delete(dossier)
        db.session.commit()
        flash(f'Dossier {dossier.numero_dossier} supprimé avec succès.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erreur lors de la suppression: {str(e)}', 'danger')
    
    return redirect(url_for('dossiers'))

@app.route('/supprimer_dossiers', methods=['POST'])
@login_required
def supprimer_dossiers():
    """Supprimer plusieurs dossiers sélectionnés."""
    if current_user.role not in ('admin', 'manager'):
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dossiers'))
    
    dossier_ids_str = request.form.get('dossier_ids', '')
    if not dossier_ids_str:
        flash('Aucun dossier sélectionné.', 'warning')
        return redirect(url_for('dossiers'))
    
    try:
        dossier_ids = [int(x) for x in dossier_ids_str.split(',') if x.strip()]
        count = 0
        for did in dossier_ids:
            dossier = Dossier.query.get(did)
            if dossier:
                tache_ids = [t.id for t in Tache.query.filter_by(dossier_id=dossier.id).all()]
                if tache_ids:
                    Notification.query.filter(Notification.tache_id.in_(tache_ids)).delete(synchronize_session=False)
                    CommentaireTache.query.filter(CommentaireTache.tache_id.in_(tache_ids)).delete(synchronize_session=False)
                # Supprimer aussi les suggestions liées au dossier
                SuggestionTache.query.filter_by(dossier_id=dossier.id).delete()
                Tache.query.filter_by(dossier_id=dossier.id).delete()
                db.session.delete(dossier)
                count += 1
        db.session.commit()
        flash(f'{count} dossier(s) supprimé(s) avec succès.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erreur lors de la suppression: {str(e)}', 'danger')
    
    return redirect(url_for('dossiers'))

@app.route('/telecharger_template_csv')
@login_required
def telecharger_template_csv():
    """Télécharger un modèle CSV pour l'import de dossiers."""
    import csv, io
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'numero_dossier', 'intitule', 'collaborateur_email', 'equipe_nom',
        'regime_tva', 'date_limite_declaration',
        'regime_fiscale', 'has_cfe'
    ])
    writer.writerow([
        'EXEMPLE-001', 'Exemple de dossier', 'collaborateur@cabinet-jmh.com', 'Équipe Cabinet JMH',
        'mensuel', '2026-09-15',
        'IS', 'TRUE'
    ])
    writer.writerow([
        'EXEMPLE-002', 'Deuxième exemple', '', '',
        'trimestriel', '',
        'IRPP', 'FALSE'
    ])
    
    output.seek(0)
    from flask import Response
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=template_dossiers.csv'}
    )

@app.route('/importer_csv', methods=['POST'])
@login_required
def importer_csv():
    """Importer des dossiers depuis un fichier CSV."""
    import csv, io, os
    
    if current_user.role not in ('admin', 'manager'):
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dossiers'))
    
    if 'csv_file' not in request.files:
        flash('Aucun fichier sélectionné.', 'warning')
        return redirect(url_for('dossiers'))
    
    file = request.files['csv_file']
    if file.filename == '':
        flash('Aucun fichier sélectionné.', 'warning')
        return redirect(url_for('dossiers'))
    
    creer_taches = 'creer_taches' in request.form
    
    try:
        content = file.read().decode('utf-8-sig')
        dialect = csv.Sniffer().sniff(content[:1024])
        reader = csv.DictReader(io.StringIO(content), dialect=dialect)
    except Exception:
        # Fallback: try with semicolon delimiter + latin1 encoding
        try:
            file.seek(0)
            content = file.read().decode('ISO-8859-1')
            reader = csv.DictReader(io.StringIO(content), delimiter=';')
        except Exception:
            try:
                file.seek(0)
                content = file.read().decode('utf-8-sig')
                reader = csv.DictReader(io.StringIO(content), delimiter=';')
            except Exception as e:
                flash(f'Erreur de lecture du CSV: {str(e)}. Vérifiez que le fichier est au format CSV avec séparateur point-virgule (;)', 'danger')
                return redirect(url_for('dossiers'))
    
    success_count = 0
    error_count = 0
    errors = []
    
    for row_num, row in enumerate(reader, start=2):
        try:
            numero = row.get('numero_dossier', '').strip()
            intitule = row.get('intitule', '').strip()
            if not numero or not intitule:
                error_count += 1
                errors.append(f'Ligne {row_num}: numéro ou intitulé manquant')
                continue
            
            # Vérifier doublon
            existing = Dossier.query.filter_by(numero_dossier=numero).first()
            if existing:
                error_count += 1
                errors.append(f'Ligne {row_num}: dossier {numero} existe déjà')
                continue
            
            # Chercher collaborateur par email
            email = row.get('collaborateur_email', '').strip()
            collab = None
            if email:
                collab = User.query.filter_by(email=email).first()
                if not collab:
                    error_count += 1
                    errors.append(f'Ligne {row_num}: email collaborateur {email} introuvable')
                    continue
            
            # Chercher équipe par nom
            equipe_nom = row.get('equipe_nom', '').strip()
            equipe = None
            if equipe_nom:
                equipe = Equipe.query.filter_by(nom=equipe_nom).first()
                if not equipe:
                    error_count += 1
                    errors.append(f'Ligne {row_num}: équipe {equipe_nom} introuvable')
                    continue
            
            regime_tva = (row.get('regime_tva', '').strip() or None)
            if regime_tva:
                regime_tva = regime_tva.lower()
            frequence_tva = (row.get('frequence_tva', '').strip().lower() or None)
            regime_fiscale = row.get('regime_fiscale', '').strip() or None
            
            date_limite_str = row.get('date_limite_declaration', '').strip()
            date_limite = None
            if date_limite_str:
                try:
                    date_limite = datetime.strptime(date_limite_str, '%Y-%m-%d').date()
                except ValueError:
                    try:
                        date_limite = datetime.strptime(date_limite_str, '%d/%m/%Y').date()
                    except ValueError:
                        error_count += 1
                        errors.append(f'Ligne {row_num}: date limite invalide {date_limite_str}')
                        continue
            
            has_cfe_str = row.get('has_cfe', '').strip().upper()
            has_cfe = has_cfe_str in ('TRUE', '1', 'OUI', 'YES', 'ON')

            # Dates des acomptes CA12 (optionnel)
            def _parse_csv_date(v):
                if not v:
                    return None
                try:
                    return datetime.strptime(v, '%Y-%m-%d').date()
                except ValueError:
                    try:
                        return datetime.strptime(v, '%d/%m/%Y').date()
                    except ValueError:
                        return None

            date_acompte_1 = _parse_csv_date(row.get('date_acompte_1', '').strip())
            date_acompte_2 = _parse_csv_date(row.get('date_acompte_2', '').strip())

            dossier = Dossier(
                numero_dossier=numero,
                intitule=intitule,
                collaborateur_id=collab.id if collab else None,
                equipe_id=equipe.id if equipe else None,
                regime_tva=regime_tva,
                frequence_tva=frequence_tva,
                date_limite_declaration=date_limite,
                date_acompte_1=date_acompte_1,
                date_acompte_2=date_acompte_2,
                regime_fiscale=regime_fiscale,
                has_cfe=has_cfe
            )
            db.session.add(dossier)
            db.session.flush()
            
            # Planifier les impôts si demandé
            if creer_taches:
                from app.tva_scheduler import planifier_impots_dossier
                try:
                    planifier_impots_dossier(dossier)
                except Exception as e:
                    app.logger.warning(f'Erreur planification pour {numero}: {e}')
            
            success_count += 1
        except Exception as e:
            error_count += 1
            errors.append(f'Ligne {row_num}: {str(e)}')
    
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f'Erreur lors de l\'enregistrement: {str(e)}', 'danger')
        return redirect(url_for('dossiers'))
    
    msg = f'{success_count} dossier(s) importé(s) avec succès.'
    if error_count > 0:
        msg += f' {error_count} erreur(s).'
        for err in errors[:5]:
            msg += f' {err}'
    flash(msg, 'success' if success_count > 0 else 'warning')
    
    return redirect(url_for('dossiers'))

@app.route('/supprimer_equipe/<int:equipe_id>')
@login_required
def supprimer_equipe(equipe_id):
    flash('Fonctionnalit\u00e9 de suppression d\'\u00e9quipe non encore impl\u00e9ment\u00e9e.', 'info')
    return redirect(url_for('equipes'))

@app.route('/supprimer_tache/<int:tache_id>', methods=['POST'])
@login_required
def supprimer_tache(tache_id):
    """Supprimer une tâche."""
    tache = Tache.query.get_or_404(tache_id)
    
    # Vérifier les droits
    if current_user.role == 'membre':
        flash('Seuls les managers et administrateurs peuvent supprimer des tâches.', 'danger')
        return redirect(url_for('taches'))
    
    try:
        # Supprimer les notifications liées
        Notification.query.filter_by(tache_id=tache.id).delete()
        # Supprimer les commentaires
        CommentaireTache.query.filter_by(tache_id=tache.id).delete()
        # Supprimer la tâche
        db.session.delete(tache)
        db.session.commit()
        flash('Tâche supprimée.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erreur lors de la suppression: {str(e)}', 'danger')
    
    return redirect(url_for('taches'))

@app.route('/taches/aujourdhui')
@login_required
def taches_aujourdhui():
    """Tâches dont l'échéance est aujourd'hui."""
    today_taches = Tache.query.filter(Tache.date_echeance == date.today()).all()
    return render_template('taches.html', taches=today_taches, date=date, timedelta=timedelta)

# ==========================
# Suivi d'avancement par membre
# ==========================
@app.route('/suivi_avancement')
@login_required
def suivi_avancement():
    """Page de suivi d'avancement des tâches par membre."""
    from app.models import User, Equipe, Tache
    from datetime import date
    
    # Récupérer les membres selon le rôle
    if current_user.role == 'admin':
        membres = User.query.filter_by(actif=True).order_by(User.prenom).all()
    elif current_user.role == 'manager':
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        team_ids = [current_user.id]
        for eq in mes_equipes:
            team_ids.extend([m.id for m in eq.membres.all()])
        # Inclure aussi tous les utilisateurs actifs pour voir les tâches assignées
        membres = User.query.filter_by(actif=True).order_by(User.prenom).all()
    else:
        membres = [current_user]
    
    # Collecter les stats par membre
    suivi_data = []
    dossiers_par_membre = {}
    for m in membres:
        taches = Tache.query.filter_by(assigne_a=m.id).order_by(Tache.date_echeance).all()
        a_faire = [t for t in taches if t.statut == 'a_faire']
        en_cours = [t for t in taches if t.statut == 'en_cours']
        terminees = [t for t in taches if t.statut in ('terminee', 'terminée')]
        en_retard = [t for t in taches if t.est_en_retard()]
        # Dossiers uniques pour ce membre
        dossiers_ids = set()
        for t in taches:
            if t.dossier_id:
                dossiers_ids.add(t.dossier_id)
        dossiers_par_membre[m.id] = Dossier.query.filter(Dossier.id.in_(dossiers_ids)).order_by(Dossier.numero_dossier).all() if dossiers_ids else []
        suivi_data.append({
            'membre': m,
            'total': len(taches),
            'a_faire': len(a_faire),
            'en_cours': len(en_cours),
            'terminees': len(terminees),
            'en_retard': len(en_retard),
            'toutes_taches': taches,  # toutes les tâches pour le tableau
            'taches_a_faire': a_faire[:10],
            'taches_en_cours': en_cours[:10],
            'taches_terminees': terminees[:5],
        })
    
    return render_template('suivi_avancement.html', suivi_data=suivi_data, membres=membres, dossiers_par_membre=dossiers_par_membre)

# Gérer le changement de statut depuis le suivi
@app.route('/suivi_avancement/changer_statut/<int:tache_id>', methods=['POST'])
@login_required
def suivi_changer_statut(tache_id):
    tache = Tache.query.get_or_404(tache_id)
    if current_user.role == 'membre' and tache.assigne_a != current_user.id:
        flash('Accès refusé.', 'danger')
        return redirect(url_for('suivi_avancement'))
    nouveau = request.form.get('statut', '').strip()
    if nouveau not in ('a_faire', 'en_cours', 'terminee'):
        flash('Statut invalide.', 'warning')
        return redirect(url_for('suivi_avancement'))
    tache.statut = nouveau
    if nouveau == 'terminee':
        tache.date_completion = datetime.utcnow()
    elif nouveau == 'a_faire':
        tache.date_completion = None
        tache.date_prise_en_charge = None
    elif nouveau == 'en_cours' and not tache.date_prise_en_charge:
        tache.date_prise_en_charge = datetime.utcnow()
    db.session.commit()
    flash(f'Statut changé.', 'success')
    return redirect(url_for('suivi_avancement'))

@app.route('/api/suivi_membre/<int:membre_id>')
@login_required
def api_suivi_membre(membre_id):
    """API pour le suivi avec filtres JSON."""
    from app.models import Tache
    
    if current_user.role == 'membre' and current_user.id != membre_id:
        return jsonify({'ok': False, 'message': 'Accès refusé'}), 403
    
    statut = request.args.get('statut', 'all')
    debut = request.args.get('debut', '')
    fin = request.args.get('fin', '')
    
    query = Tache.query.filter_by(assigne_a=membre_id)
    
    if statut != 'all':
        query = query.filter(Tache.statut == statut)
    
    if debut:
        try:
            d_debut = datetime.strptime(debut, '%Y-%m-%d').date()
            query = query.filter(Tache.date_echeance >= d_debut)
        except ValueError:
            pass
    if fin:
        try:
            d_fin = datetime.strptime(fin, '%Y-%m-%d').date()
            query = query.filter(Tache.date_echeance <= d_fin)
        except ValueError:
            pass
    
    taches = query.order_by(Tache.date_echeance).all()
    
    return jsonify({
        'ok': True,
        'taches': [{
            'id': t.id,
            'titre': t.titre,
            'statut': t.statut,
            'priorite': t.priorite,
            'date_echeance': t.date_echeance.strftime('%d/%m/%Y') if t.date_echeance else '',
            'en_retard': t.est_en_retard(),
            'dossier': t.dossier.numero_dossier if t.dossier else '',
        } for t in taches]
    })

@app.route('/api/envoyer_notifications_echeances')
@login_required
def envoyer_notifications_echeances():
    """Envoyer les notifications par email pour les tâches fiscales échéant aujourd'hui."""
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'message': 'Accès refusé'}), 403
    
    from app.integrations.brevo import send_task_assigned_email_brevo
    fiscal_keywords = ['tva', 'is ', 'cfe ', 'acompte', 'dépôt', 'préparation', 'déclaration', 'prépa']
    
    tasks = Tache.query.filter(Tache.date_echeance == date.today()).all()
    sent = 0
    for t in tasks:
        titre = (t.titre or '').lower()
        is_fiscal = any(kw in titre for kw in fiscal_keywords)
        if is_fiscal and t.assigne_a and t.statut != 'terminee':
            try:
                send_task_assigned_email_brevo(t, t.assigne_a)
                sent += 1
            except Exception as e:
                app.logger.warning(f"Send due notification failed: {e}")
    
    return jsonify({'ok': True, 'message': f'{sent} notification(s) envoyée(s).'})

@app.route('/changer_statut_tache/<int:tache_id>', methods=['POST'])
@login_required
def changer_statut_tache(tache_id):
    """Changer librement le statut d'une tâche."""
    tache = Tache.query.get_or_404(tache_id)
    
    # Vérifier que le membre ne change que ses propres tâches
    if current_user.role == 'membre' and tache.assigne_a != current_user.id:
        flash('Vous ne pouvez modifier que vos propres tâches.', 'danger')
        return redirect(url_for('taches'))
    
    nouveau_statut = request.form.get('statut', '').strip()
    if nouveau_statut not in ('a_faire', 'en_cours', 'terminee'):
        flash('Statut invalide.', 'warning')
        return redirect(url_for('taches'))
    
    tache.statut = nouveau_statut
    if nouveau_statut == 'terminee':
        tache.date_completion = datetime.utcnow()
        if not tache.date_prise_en_charge:
            tache.date_prise_en_charge = datetime.utcnow()
    elif nouveau_statut == 'en_cours' and not tache.date_prise_en_charge:
        tache.date_prise_en_charge = datetime.utcnow()
    elif nouveau_statut == 'a_faire':
        tache.date_prise_en_charge = None
        tache.date_completion = None
    
    db.session.commit()
    
    # Notifier le créateur (manager) du changement + email
    collab_nom = f"{current_user.prenom} {current_user.nom}"
    cree_par_id = tache.cree_par
    team_manager = None
    if not cree_par_id and tache.dossier and tache.dossier.equipe and tache.dossier.equipe.manager:
        team_manager = tache.dossier.equipe.manager
        cree_par_id = team_manager.id
    if cree_par_id and cree_par_id != current_user.id:
        notif = Notification(
            user_id=cree_par_id,
            tache_id=tache.id,
            message=f"{collab_nom} a changé le statut de \"{tache.titre}\" à \"{nouveau_statut.replace('_', ' ')}\"",
            type_notification='systeme'
        )
        db.session.add(notif)
        db.session.commit()
        # Email
        dest_user = User.query.get(cree_par_id)
        if dest_user and dest_user.email:
            try:
                from app.integrations.brevo import send_email_via_brevo_api
                sujet = f"Changement de statut : {tache.titre}"
                corps = f"Bonjour {dest_user.prenom},\n\n{collab_nom} a changé le statut de la tâche \"{tache.titre}\" à \"{nouveau_statut.replace('_', ' ')}\".\n\nCabinet JMH"
                envoye = send_email_via_brevo_api(to_email=dest_user.email, subject=sujet, body=corps)
                app.logger.info(f"Email statut change to {dest_user.email}: {'OK' if envoye else 'ECHEC'}")
            except Exception as e:
                app.logger.warning(f"Email statut change error: {e}")
    
    flash(f'Statut changé à "{nouveau_statut.replace("_", " ")}".', 'success')
    return redirect(url_for('taches'))

@app.route('/terminer_tache/<int:tache_id>', methods=['POST'])
@login_required
def terminer_tache(tache_id):
    """Marquer une tâche comme terminée."""
    tache = Tache.query.get_or_404(tache_id)
    
    # Vérifier les droits
    if current_user.role == 'membre' and tache.assigne_a != current_user.id:
        flash('Vous ne pouvez pas terminer cette tâche.', 'danger')
        return redirect(url_for('taches'))
    if tache.statut not in ('en_cours', 'a_faire'):
        flash('Cette tâche est déjà terminée.', 'warning')
        return redirect(url_for('taches'))
    
    tache.statut = 'terminee'
    tache.date_completion = datetime.utcnow()
    if not tache.date_prise_en_charge:
        tache.date_prise_en_charge = datetime.utcnow()
    db.session.commit()
    
    # Notifier le créateur (manager) + in-app
    collab_nom = f"{current_user.prenom} {current_user.nom}"
    cree_par_id = tache.cree_par
    team_manager = None
    if not cree_par_id and tache.dossier and tache.dossier.equipe and tache.dossier.equipe.manager:
        team_manager = tache.dossier.equipe.manager
        cree_par_id = team_manager.id
    if cree_par_id and cree_par_id != current_user.id:
        notif = Notification(
            user_id=cree_par_id,
            tache_id=tache.id,
            message=f"{collab_nom} a terminé : {tache.titre}",
            type_notification='completion'
        )
        db.session.add(notif)
        db.session.commit()
        # Envoyer email
        dest_user = User.query.get(cree_par_id)
        if dest_user and dest_user.email:
            try:
                if team_manager:
                    from app.integrations.brevo import send_email_via_brevo_api
                    send_email_via_brevo_api(
                        to_email=dest_user.email,
                        subject=f"Tâche terminée : {tache.titre}",
                        body=f"Bonjour {dest_user.prenom},\n\n{collab_nom} a terminé la tâche \"{tache.titre}\"."
                    )
                else:
                    from app.integrations.brevo import send_task_completed_email_brevo
                    send_task_completed_email_brevo(tache, collab_nom)
            except Exception as e:
                app.logger.warning(f"Send email failed: {e}")
    
    flash('Tâche marquée comme terminée.', 'success')
    return redirect(url_for('taches'))

@app.route('/upload_photo', methods=['POST'])
@app.route('/upload_photo/<int:user_id>', methods=['POST'])
@login_required
def upload_photo(user_id=None):
    """Upload photo de profil."""
    import os
    from werkzeug.utils import secure_filename
    
    target_user = current_user
    if user_id is not None:
        if current_user.role not in ('admin', 'manager'):
            return jsonify({'ok': False, 'message': 'Accès refusé.'}), 403
        target_user = User.query.get_or_404(user_id)
    
    if 'photo' not in request.files:
        return jsonify({'ok': False, 'message': 'Aucun fichier sélectionné.'}), 400
    
    file = request.files['photo']
    if file.filename == '':
        return jsonify({'ok': False, 'message': 'Aucun fichier sélectionné.'}), 400
    
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({'ok': False, 'message': 'Format non autorisé. Utilisez PNG, JPG, JPEG ou GIF.'}), 400
    
    file.seek(0, os.SEEK_END)
    size = file.tell()
    if size > 5 * 1024 * 1024:
        return jsonify({'ok': False, 'message': 'Fichier trop volumineux. Maximum 5MB.'}), 400
    file.seek(0)
    
    # Sauvegarder dans la base de données (permanent)
    target_user.photo_data = file.read()
    target_user.photo_mimetype = f"image/{ext}"
    target_user.photo_profil = None  # plus besoin du fichier disque
    db.session.commit()
    
    msg = f'Photo de profil mise à jour pour {target_user.prenom} {target_user.nom}.'
    return jsonify({'ok': True, 'message': msg})
    
    flash(msg, 'success')
    if user_id:
        return redirect(url_for('fiche_membre', user_id=user_id))
    return redirect(url_for('profil'))

@app.route('/user_photo/<int:user_id>')
def user_photo(user_id):
    """Servir la photo de profil depuis la base de données."""
    user = User.query.get_or_404(user_id)
    if not user.photo_data:
        return redirect(url_for('static', filename='img/default-avatar.png'))
    from flask import Response
    return Response(user.photo_data, mimetype=user.photo_mimetype or 'image/png')

# ==========================
# API Notifications
# ==========================
@app.route('/notification/test', methods=['POST'])
@login_required
def notification_test():
    """Test d'envoi de notification."""
    return jsonify({'ok': True})

def get_mail_config():
    """Retourne la configuration mail depuis les settings ou l'environnement."""
    from flask import current_app
    config = {}
    # Essayer les settings DB d'abord
    try:
        from app.models import AppSetting
        for key in ['MAIL_SERVER', 'MAIL_PORT', 'MAIL_USERNAME', 'MAIL_PASSWORD', 'MAIL_DEFAULT_SENDER']:
            setting = AppSetting.query.filter_by(cle=key).first()
            config[key] = setting.valeur.strip() if setting and setting.valeur else ''
    except Exception:
        pass
    # Fallback sur config Flask
    if not config.get('MAIL_SERVER'):
        config['MAIL_SERVER'] = current_app.config.get('MAIL_SERVER', '')
        config['MAIL_PORT'] = current_app.config.get('MAIL_PORT', '587')
        config['MAIL_USERNAME'] = current_app.config.get('MAIL_USERNAME', '')
        config['MAIL_PASSWORD'] = current_app.config.get('MAIL_PASSWORD', '')
        config['MAIL_DEFAULT_SENDER'] = current_app.config.get('MAIL_DEFAULT_SENDER', config.get('MAIL_USERNAME', ''))
    return config

@app.route('/api/notifications')
@login_required
def api_notifications():
    """Liste des notifications de l'utilisateur connecté."""
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.date_envoi.desc()).limit(50).all()
    return jsonify({
        'ok': True,
        'notifications': [{
            'id': n.id,
            'type': n.type_notification or 'info',
            'message': n.message,
            'lu': n.lu,
            'date': n.date_envoi.strftime('%d/%m/%Y %H:%M') if n.date_envoi else '',
            'tache_id': n.tache_id,
        } for n in notifs]
    })

@app.route('/api/notifications/mark-all-read', methods=['POST'])
@login_required
def api_notifications_mark_all_read():
    """Marquer toutes les notifications comme lues."""
    Notification.query.filter_by(user_id=current_user.id, lu=False).update({'lu': True})
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/notifications/<int:notif_id>/read', methods=['POST'])
@login_required
def api_notification_read(notif_id):
    """Marquer une notification comme lue."""
    notif = Notification.query.get_or_404(notif_id)
    if notif.user_id != current_user.id:
        return jsonify({'ok': False, 'message': 'Accès refusé'}), 403
    notif.lu = True
    db.session.commit()
    return jsonify({'ok': True})

# ==========================
# API Commentaires sur les tâches
# ==========================
@app.route('/api/commentaires/<int:tache_id>', methods=['GET', 'POST'])
@login_required
def api_commentaires(tache_id):
    """Lister et ajouter des commentaires sur une tâche."""
    tache = Tache.query.get_or_404(tache_id)
    
    if request.method == 'GET':
        comments = CommentaireTache.query.filter_by(tache_id=tache.id).order_by(CommentaireTache.date_creation).all()
        return jsonify({
            'ok': True,
            'commentaires': [{
                'id': c.id,
                'user_id': c.user_id,
                'user_nom': f"{c.user.prenom} {c.user.nom}",
                'message': c.message,
                'date': c.date_creation.strftime('%d/%m/%Y %H:%M') if c.date_creation else '',
            } for c in comments]
        })
    
    # POST: ajouter un commentaire
    data = request.get_json() or {}
    message = data.get('message', '').strip()
    if not message:
        return jsonify({'ok': False, 'message': 'Message requis'}), 400
    
    comment = CommentaireTache(
        tache_id=tache.id,
        user_id=current_user.id,
        message=message,
    )
    db.session.add(comment)
    
    # Créer notification pour l'assigné de la tâche
    if tache.assigne_a and tache.assigne_a != current_user.id:
        notif = Notification(
            user_id=tache.assigne_a,
            tache_id=tache.id,
            message=f"Nouveau commentaire sur \"{tache.titre}\" par {current_user.prenom} {current_user.nom}",
            type_notification='systeme'
        )
        db.session.add(notif)
    # Notifier aussi le créateur si différent
    if tache.cree_par and tache.cree_par != current_user.id and tache.cree_par != tache.assigne_a:
        notif2 = Notification(
            user_id=tache.cree_par,
            tache_id=tache.id,
            message=f"Nouveau commentaire sur \"{tache.titre}\" par {current_user.prenom} {current_user.nom}",
            type_notification='systeme'
        )
        db.session.add(notif2)
    
    db.session.commit()
    
    # Envoyer un email de notification aux personnes concernées
    comment_nom = f"{current_user.prenom} {current_user.nom}"
    comment_msg = f"Un nouveau commentaire a été ajouté sur la tâche \"{tache.titre}\" par {comment_nom} :\n\n\"{message}\""
    from app.integrations.brevo import send_email_via_brevo_api
    # À l'assigné de la tâche
    if tache.assigne_a and tache.assigne_a != current_user.id:
        assigne = User.query.get(tache.assigne_a)
        if assigne and assigne.email:
            try:
                send_email_via_brevo_api(
                    to_email=assigne.email,
                    subject=f"Commentaire sur : {tache.titre}",
                    body=f"Bonjour {assigne.prenom},\n\n{comment_msg}\n\nConsultez la tâche sur https://cabinet-team-manager.onrender.com/taches"
                )
            except Exception as e:
                app.logger.warning(f"Send comment email failed (assigne): {e}")
    # Au créateur de la tâche (si différent)
    if tache.cree_par and tache.cree_par != current_user.id and tache.cree_par != tache.assigne_a:
        createur = User.query.get(tache.cree_par)
        if createur and createur.email:
            try:
                send_email_via_brevo_api(
                    to_email=createur.email,
                    subject=f"Commentaire sur : {tache.titre}",
                    body=f"Bonjour {createur.prenom},\n\n{comment_msg}\n\nConsultez la tâche sur https://cabinet-team-manager.onrender.com/taches"
                )
            except Exception as e:
                app.logger.warning(f"Send comment email failed (createur): {e}")
    
    return jsonify({'ok': True, 'commentaire': {
        'id': comment.id,
        'user_id': comment.user_id,
        'user_nom': f"{current_user.prenom} {current_user.nom}",
        'message': comment.message,
        'date': comment.date_creation.strftime('%d/%m/%Y %H:%M') if comment.date_creation else '',
    }})

@app.route('/vue_tache/<int:tache_id>')
@login_required
def vue_tache(tache_id):
    """Vue détaillée d'une tâche avec commentaires."""
    tache = Tache.query.get_or_404(tache_id)
    commentaires = CommentaireTache.query.filter_by(tache_id=tache.id).order_by(CommentaireTache.date_creation).all()
    return render_template('vue_tache.html', tache=tache, commentaires=commentaires)

@app.route('/voir_taches_dossier/<int:dossier_id>')
@login_required
def voir_taches_dossier(dossier_id):
    # Rediriger vers la page des tâches avec le dossier pré-filtré
    return redirect(url_for('taches', dossier=dossier_id))

@app.route('/profil')
@login_required
def profil():
    return render_template('profil.html')

@app.route('/reset-admin', methods=['GET', 'POST'])
def reset_admin():
    if request.method == 'POST':
        reset_key = request.form.get('reset_key')
        new_password = request.form.get('new_password')
        if reset_key == 'cabinet-jmh-reset-2024':
            admin = User.query.filter_by(email='admin@cabinet-jmh.com').first()
            if admin:
                from werkzeug.security import generate_password_hash
                admin.password_hash = generate_password_hash(new_password)
                db.session.commit()
                flash('Mot de passe admin r\u00e9initialis\u00e9 avec succ\u00e8s.', 'success')
                return redirect(url_for('login'))
            else:
                flash('Compte admin introuvable.', 'danger')
        else:
            flash('Cl\u00e9 de r\u00e9initialisation invalide.', 'danger')
    return render_template('reset_admin.html')

@app.route('/admin/assign_photo/<email>')
@login_required
def admin_assign_photo(email):
    """Assigner une photo à un utilisateur par email (depuis static/uploads/)."""
    if current_user.role != 'admin':
        flash('Accès refusé.', 'danger')
        return redirect(url_for('membres'))
    photo = request.args.get('photo', '')
    if not photo:
        flash('Paramètre photo manquant. Utilisez ?photo=nom_fichier.png', 'warning')
        return redirect(url_for('membres'))
    user = User.query.filter_by(email=email).first()
    if not user:
        flash(f'Utilisateur {email} introuvable.', 'danger')
        return redirect(url_for('membres'))
    user.photo_profil = photo
    db.session.commit()
    flash(f'Photo {photo} assignée à {user.prenom} {user.nom}', 'success')
    return redirect(url_for('fiche_membre', user_id=user.id))

@app.route('/api/set_photo', methods=['POST'])
@login_required
def api_set_photo():
    """API admin pour assigner une photo à un utilisateur par email."""
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'message': 'Accès refusé'}), 403
    email = request.form.get('email') or (request.get_json() or {}).get('email')
    photo = request.form.get('photo') or (request.get_json() or {}).get('photo')
    if not email or not photo:
        return jsonify({'ok': False, 'message': 'email et photo requis'}), 400
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'ok': False, 'message': 'Utilisateur introuvable'}), 404
    user.photo_profil = photo
    db.session.commit()
    return jsonify({'ok': True, 'message': f'Photo {photo} assignée à {email}'})

@app.route('/admin_debug')
@login_required
def admin_debug():
    if current_user.role != 'admin':
        flash('Accès réservé aux administrateurs.', 'danger')
        return redirect(url_for('dossiers'))
    return render_template('admin_debug.html')

# ==========================
# Tableau de bord fiscal
# ==========================
@app.route('/fiscal')
@login_required
def fiscal():
    """Tableau de bord fiscal d\u00e9di\u00e9"""
    current_equipe = None
    all_equipes_for_switch = []
    membres = []

    if current_user.role == 'admin':
        equipe_id = session.get('current_equipe_id')
        if equipe_id:
            equipe = Equipe.query.get(equipe_id)
            current_equipe = equipe
            all_equipes_for_switch = Equipe.query.order_by(Equipe.nom).all()
            team_user_ids = [m.id for m in equipe.membres.all()] if equipe else []
            membres = User.query.filter(User.id.in_(team_user_ids), User.actif==True).all()
            all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_user_ids)).all()
        else:
            current_equipe = None
            all_equipes_for_switch = Equipe.query.order_by(Equipe.nom).all()
            membres = User.query.filter_by(actif=True).all()
            all_dossiers = Dossier.query.all()
    elif current_user.role == 'manager':
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        all_equipes_for_switch = mes_equipes
        current_equipe = None
        team_member_ids = [current_user.id]
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_member_ids)).all()
        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()
    else:
        mes_equipes = current_user.equipes.filter_by(actif=True).all() if hasattr(current_user, 'equipes') else []
        all_equipes_for_switch = mes_equipes
        current_equipe = None
        team_member_ids = [current_user.id]
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()
        all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_member_ids)).all()

    def _add_counts(item):
        """Ajoute les compteurs nb_a_faire, nb_terminee, a_retard et tax_tasks_visible à un item."""
        tasks = item.get('tax_tasks', [])
        now = date.today()
        horizon_3m = now + timedelta(days=95)
        
        # Visible tasks: only within 3 months horizon + past/terminated
        visible = [t for t in tasks if t.date_echeance and (t.date_echeance <= horizon_3m or t.statut in ('terminee', 'terminée'))]
        item['tax_tasks_visible'] = visible
        
        nb_a_faire = sum(1 for t in visible if t.statut == 'a_faire')
        nb_terminee = sum(1 for t in visible if t.statut in ('terminee', 'terminée'))
        a_retard = sum(1 for t in visible if t.statut not in ('terminee', 'terminée') and t.date_echeance and t.date_echeance < now)
        item['nb_a_faire'] = nb_a_faire
        item['nb_terminee'] = nb_terminee
        item['a_retard'] = a_retard
        return item
    
    dossier_data = []
    tva_dossiers = []
    ca3_dossiers = []
    ca12_dossiers = []
    is_dossiers = []
    cfe_dossiers = []
    
    for d in all_dossiers:
        tasks = Tache.query.filter(Tache.dossier_id == d.id).all()
        tax_tasks = [t for t in tasks if (
                     'TVA' in t.titre.upper() or 'CA3' in t.titre.upper() or 'CA12' in t.titre.upper() or
                      'IS' in t.titre.upper() or 'ACOMPTE' in t.titre.upper() or 'CFE' in t.titre.upper())]
        pending_tasks = [t for t in tax_tasks if t.statut != 'terminee']
        next_deadline = min([t.date_echeance for t in pending_tasks]) if pending_tasks else None
        if any(t.statut == 'a_faire' for t in tax_tasks):
            status = 'a_faire'
            status_label = 'À faire'
            status_class = 'text-danger'
        elif any(t.statut == 'en_cours' for t in tax_tasks):
            status = 'en_cours'
            status_label = 'En cours'
            status_class = 'text-warning'
        else:
            status = 'terminee'
            status_label = 'Terminé'
            status_class = 'text-success'
        
        item = {
            'dossier': d,
            'regime_fiscale': d.regime_fiscale,
            'has_cfe': d.has_cfe,
            'next_deadline': next_deadline,
            'status': status,
            'status_label': status_label,
            'status_class': status_class,
            'tax_tasks': tax_tasks
        }
        dossier_data.append(item)
        
        _add_counts(item)
        
        # TVA tasks (only TVA, CA3, CA12)
        tva_tasks = [t for t in tasks if 'TVA' in t.titre.upper() or 'CA3' in t.titre.upper() or 'CA12' in t.titre.upper()]
        if tva_tasks:
            tva_dossiers.append({**item, 'tax_tasks': tva_tasks})
        
        # CA3 tasks
        if d.regime_tva == 'ca3' or any('CA3' in t.titre.upper() for t in tasks):
            ca3_filtered = [t for t in tasks if ('TVA' in t.titre.upper() or 'CA3' in t.titre.upper()) and 'CA12' not in t.titre.upper()]
            ca3_dossiers.append({**item, 'tax_tasks': ca3_filtered})
        
        # CA12 tasks
        if d.regime_tva == 'ca12' or any('CA12' in t.titre.upper() for t in tasks):
            ca12_filtered = [t for t in tasks if 'CA12' in t.titre.upper()]
            ca12_dossiers.append({**item, 'tax_tasks': ca12_filtered})
        
        # IS tasks
        if d.regime_fiscale == 'IS' or any('IS' in t.titre.upper() or 'ACOMPTE' in t.titre.upper() for t in tasks):
            is_filtered = [t for t in tasks if 'IS' in t.titre.upper() or 'ACOMPTE' in t.titre.upper()]
            is_dossiers.append({**item, 'tax_tasks': is_filtered})
        
        # CFE tasks
        if d.has_cfe or any('CFE' in t.titre.upper() for t in tasks):
            cfe_filtered = [t for t in tasks if 'CFE' in t.titre.upper()]
            cfe_dossiers.append({**item, 'tax_tasks': cfe_filtered})
    
    return render_template('fiscal.html', dossier_data=dossier_data, 
        tva_dossiers=tva_dossiers, ca3_dossiers=ca3_dossiers, ca12_dossiers=ca12_dossiers,
        is_dossiers=is_dossiers, cfe_dossiers=cfe_dossiers,
        current_equipe=current_equipe,
        all_equipes_for_switch=all_equipes_for_switch, Tache=Tache, db=db,
        horizon_3m=date.today() + timedelta(days=95))


@app.route('/ajouter_dossier', methods=['POST'])
@login_required
def ajouter_dossier():
    if current_user.role not in ('admin', 'manager'):
        flash('Acc\u00e8s refus\u00e9.', 'danger')
        return redirect(url_for('dossiers'))
    try:
        numero_dossier = request.form.get('numero_dossier', '').strip()
        intitule = request.form.get('intitule', '').strip()
        collaborateur_id = request.form.get('collaborateur_id')
        equipe_id = request.form.get('equipe_id')
        regime_tva = request.form.get('regime_tva')
        frequence_tva = request.form.get('frequence_tva')
        date_limite_declaration = request.form.get('date_limite_declaration')
        date_acompte_1 = request.form.get('date_acompte_1')
        date_acompte_2 = request.form.get('date_acompte_2')
        regime_fiscale = request.form.get('regime_fiscale')
        has_cfe = ('has_cfe' in request.form)
        forme_juridique = (request.form.get('forme_juridique') or '').strip() or None
        secteur_activite = (request.form.get('secteur_activite') or '').strip() or None
        pennylane_api_token = (request.form.get('pennylane_api_token') or '').strip() or None

        if not numero_dossier or not intitule or not collaborateur_id or not equipe_id:
            flash('Veuillez remplir tous les champs obligatoires.', 'danger')
            return redirect(url_for('dossiers'))

        date_limite = None
        if date_limite_declaration:
            try:
                date_limite = datetime.strptime(date_limite_declaration, '%Y-%m-%d').date()
            except ValueError:
                flash('Format de date invalide.', 'danger')
                return redirect(url_for('dossiers'))

        def _parse_date(v):
            if not v:
                return None
            try:
                return datetime.strptime(v, '%Y-%m-%d').date()
            except ValueError:
                return None

        nouveau_dossier = Dossier(
            numero_dossier=numero_dossier,
            intitule=intitule,
            collaborateur_id=int(collaborateur_id),
            equipe_id=int(equipe_id),
            regime_tva=regime_tva if regime_tva else None,
            frequence_tva=frequence_tva if frequence_tva else None,
            date_limite_declaration=date_limite,
            date_acompte_1=_parse_date(date_acompte_1),
            date_acompte_2=_parse_date(date_acompte_2),
            regime_fiscale=regime_fiscale if regime_fiscale else None,
            has_cfe=has_cfe,
            forme_juridique=forme_juridique,
            secteur_activite=secteur_activite,
            pennylane_api_token=pennylane_api_token
        )
        db.session.add(nouveau_dossier)
        db.session.flush()

        # Planifier les imp\u00f4ts pour ce dossier
        from .tva_scheduler import planifier_impots_dossier
        planifier_impots_dossier(nouveau_dossier)

        db.session.commit()
        flash('Dossier cr\u00e9\u00e9 avec succ\u00e8s et les t\u00e2ches fiscales ont \u00e9t\u00e9 g\u00e9n\u00e9r\u00e9es.', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erreur lors de la création du dossier: {e}")
        flash(f'Erreur lors de la création du dossier: {str(e)}', 'danger')
    return redirect(url_for('dossiers'))

# ==========================
# Routes \u00e9quipes fonctionnelles
# ==========================
@app.route('/changer_manager_equipe', methods=['POST'])
@login_required
def changer_manager_equipe():
    if current_user.role != 'admin':
        flash('Acc\u00e8s refus\u00e9.', 'danger')
        return redirect(url_for('equipes'))
    equipe_id = request.form.get('equipe_id')
    manager_id = request.form.get('manager_id')
    if equipe_id and manager_id:
        equipe = Equipe.query.get(int(equipe_id))
        if equipe:
            equipe.manager_id = int(manager_id)
            db.session.commit()
            flash(f'Manager de l\'\u00e9quipe {equipe.nom} mis \u00e0 jour.', 'success')
    return redirect(url_for('equipes'))

@app.route('/configurer_email_equipe', methods=['GET', 'POST'])
@login_required
def configurer_email_equipe():
    flash('Fonctionnalit\u00e9 de configuration d\'email d\'\u00e9quipe non encore impl\u00e9ment\u00e9e.', 'info')
    return redirect(url_for('equipes'))

# ==========================
# Error handlers
# ==========================
def not_found(error):
    return render_template('error.html', code=404, message="Page non trouv\u00e9e."), 404

@app.route('/pennylane')
@login_required
def pennylane_page():
    """Page de configuration et statut de l'intégration Pennylane.
       Admin : configuration complète + vue globale.
       Manager : vue limitée aux dossiers de SES équipes (lecture seule)."""
    from app.integrations.pennylane import get_pennylane_token
    is_admin = current_user.role == 'admin'
    if not is_admin and current_user.role != 'manager':
        flash('Accès réservé aux administrateurs et managers.', 'danger')
        return redirect(url_for('dashboard'))

    # Scoping des dossiers : admin voit tout, manager voit les dossiers de ses équipes
    if is_admin:
        dossiers_pl = Dossier.query.order_by(Dossier.numero_dossier).all()
        equipes_list = Equipe.query.order_by(Equipe.nom).all()
    else:
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        equipe_ids = [eq.id for eq in mes_equipes]
        dossiers_pl = Dossier.query.filter(Dossier.equipe_id.in_(equipe_ids)).order_by(Dossier.numero_dossier).all()
        equipes_list = mes_equipes

    # Grouper les dossiers associés par équipe
    # Un dossier est "connecté" s'il a un customer_id OU un token API dédié
    dossiers_associes = [d for d in dossiers_pl if d.pennylane_customer_id or d.pennylane_api_token]
    dossiers_non_associes = [d for d in dossiers_pl if not (d.pennylane_customer_id or d.pennylane_api_token)]
    par_equipe = {}
    for d in dossiers_associes:
        nom_eq = d.equipe.nom if d.equipe else 'Sans équipe'
        par_equipe.setdefault(nom_eq, []).append(d)

    token = get_pennylane_token()
    configured = bool(token)
    test_result = None
    if configured and is_admin:
        try:
            from app.integrations.pennylane import test_connexion
            test_result = test_connexion()
        except Exception:
            test_result = {'ok': False, 'message': 'Erreur lors du test de connexion.'}
    return render_template('pennylane.html', configured=configured, test_result=test_result,
                           is_admin=is_admin,
                           dossiers_associes=dossiers_associes, dossiers_non_associes=dossiers_non_associes,
                           par_equipe=par_equipe, equipes_list=equipes_list,
                           total_dossiers=len(dossiers_pl),
                           token_masque=('••••' + token[-4:]) if configured and len(token) > 4 else ('••••' if configured else ''))


@app.route('/pennylane/config', methods=['POST'])
@login_required
def pennylane_config():
    """Sauvegarde le token Pennylane et teste la connexion."""
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'message': 'Accès réservé aux administrateurs.'}), 403
    token = (request.form.get('api_token') or '').strip()
    from app.integrations.pennylane import save_pennylane_token, test_connexion
    save_pennylane_token(token)
    result = test_connexion(token) if token else {'ok': False, 'message': 'Token effacé.'}
    return jsonify(result)


@app.route('/pennylane/sync', methods=['POST'])
@login_required
def pennylane_sync():
    """Lance la synchronisation des dossiers avec les clients Pennylane."""
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'message': 'Accès réservé aux administrateurs.'}), 403
    try:
        from app.integrations.pennylane import sync_dossiers_pennylane
        result = sync_dossiers_pennylane()
        return jsonify(result)
    except Exception as e:
        return jsonify({'ok': False, 'message': f'Erreur synchro: {str(e)}'})


@app.route('/pennylane/dossier/<int:dossier_id>')
@login_required
def pennylane_dossier(dossier_id):
    """Données Pennylane associées à un dossier (factures, écritures)."""
    dossier = Dossier.query.get_or_404(dossier_id)
    # Scoping par équipe/manager : chaque manager ne voit que les dossiers de SES équipes
    if current_user.role == 'admin':
        pass  # admin voit tout
    elif current_user.role == 'manager':
        mes_equipes_ids = [eq.id for eq in Equipe.query.filter_by(manager_id=current_user.id).all()]
        if dossier.equipe_id not in mes_equipes_ids:
            flash('Accès refusé : ce dossier ne fait pas partie de vos équipes.', 'danger')
            return redirect(url_for('dossiers'))
    else:
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dossiers'))
    try:
        from app.integrations.pennylane import get_dossier_pennylane_data
        data = get_dossier_pennylane_data(dossier)
    except Exception as e:
        import traceback
        app.logger.error(f'pennylane_dossier {dossier_id}: {e}\n{traceback.format_exc()}')
        data = {'ok': False, 'message': str(e), 'factures': [], 'factures_fournisseurs': [],
                'ecritures': [], 'transactions': [], 'source_token': None}

    # Fusionner les 3 natures en une seule liste pour le tableau unifié
    lignes = []
    # Indexer les PennylaneItem (type, api_id) -> db_id
    pl_items_db = {(it.item_type, it.item_id): it.id
                   for it in PennylaneItem.query.filter_by(dossier_id=dossier.id).all()}
    for f in data.get('factures', []):
        lignes.append({
            'nature': 'vente',
            'nature_label': 'Vente',
            'numero': f.get('numero') or '—',
            'date': (f.get('date') or '')[:10],
            'libelle': f.get('numero') or '—',
            'montant': f.get('montant_ttc'),
            'statut_fr': f.get('statut_fr') or '',
            'statut_traitement': f.get('statut_traitement') or 'a_traiter',
            'item_id': f.get('id'),
            'db_id': pl_items_db.get(('facture_vente', str(f.get('id') or ''))),
            'ajout_date': str(f.get('ajout_date') or ''),
            'nouveau': f.get('nouveau', False),
        })
    for f in data.get('factures_fournisseurs', []):
        lignes.append({
            'nature': 'achat',
            'nature_label': 'Achat',
            'numero': f.get('numero') or '—',
            'date': (f.get('date') or '')[:10],
            'libelle': f.get('numero') or '—',
            'montant': f.get('montant_ttc'),
            'statut_fr': f.get('statut_fr') or '',
            'statut_traitement': f.get('statut_traitement') or 'a_traiter',
            'item_id': f.get('id'),
            'db_id': pl_items_db.get(('facture_achat', str(f.get('id') or ''))),
            'ajout_date': str(f.get('ajout_date') or ''),
            'nouveau': f.get('nouveau', False),
        })
    for t in data.get('transactions', []):
        lignes.append({
            'nature': 'banque',
            'nature_label': 'Flux bancaire',
            'numero': t.get('libelle') or '—',
            'date': (t.get('date') or '')[:10],
            'libelle': t.get('libelle') or '—',
            'montant': t.get('montant'),
            'statut_fr': t.get('statut_fr') or '',
            'statut_traitement': t.get('statut_traitement') or 'a_traiter',
            'item_id': t.get('id'),
            'db_id': pl_items_db.get(('transaction', str(t.get('id') or ''))),
            'ajout_date': str(t.get('ajout_date') or ''),
            'nouveau': t.get('nouveau', False),
        })
    # Extrait l'exercice (année) de la date d'émission
    for l in lignes:
        try:
            y = (l['date'] or '')[:4]
            l['exercice'] = int(y) if y.isdigit() and 2000 <= int(y) <= 2100 else None
        except (ValueError, IndexError):
            l['exercice'] = None

    # Filtre par exercice (défaut : année en cours, comme Pennylane)
    try:
        exercice_filtre = int(request.args.get('exercice') or str(date.today().year))
    except (ValueError, TypeError):
        exercice_filtre = date.today().year
    lignes_filtrees = [l for l in lignes if l['exercice'] == exercice_filtre]

    # Tri : les plus récents en premier
    lignes_filtrees.sort(key=lambda x: (x['date'] or ''), reverse=True)

    # Filtre par nature côté serveur ('', 'vente', 'achat', 'banque') — compteurs TOUJOURS justes
    nature_filtre = request.args.get('nature') or ''
    if nature_filtre not in ('', 'vente', 'achat', 'banque'):
        nature_filtre = ''
    lignes_affichees = [l for l in lignes_filtrees if not nature_filtre or l['nature'] == nature_filtre]

    def _ftab(sf):
        """Mapping statut Pennylane -> onglet (identique au data-ftab du template)."""
        if sf == 'Archivé':
            return 'archive'
        if sf in ('Traité', 'Avoir', 'Annulé'):
            return 'traite'
        if sf == 'Prétraité':
            return 'pretraite'
        return 'a_traiter'

    data['lignes'] = lignes_affichees
    data['exercice_actif'] = exercice_filtre
    data['nature_actif'] = nature_filtre
    data['nb_total'] = len(lignes_filtrees)
    data['nb_ventes'] = sum(1 for l in lignes_filtrees if l['nature'] == 'vente')
    data['nb_achats'] = sum(1 for l in lignes_filtrees if l['nature'] == 'achat')
    data['nb_banque'] = sum(1 for l in lignes_filtrees if l['nature'] == 'banque')
    # Compteurs d'onglets : dérivés du statut PENNYLANE (statut_fr), même mapping que data-ftab
    data['cnt_toutes'] = len(lignes_affichees)
    data['cnt_a_traiter'] = sum(1 for l in lignes_affichees if _ftab(l['statut_fr']) == 'a_traiter')
    data['cnt_pretraite'] = sum(1 for l in lignes_affichees if _ftab(l['statut_fr']) == 'pretraite')
    data['cnt_traite'] = sum(1 for l in lignes_affichees if _ftab(l['statut_fr']) == 'traite')
    data['cnt_archive'] = sum(1 for l in lignes_affichees if _ftab(l['statut_fr']) == 'archive')
    # Compat : compteurs globaux (toutes natures)
    data['nb_a_traiter'] = sum(1 for l in lignes_filtrees if _ftab(l['statut_fr']) == 'a_traiter')
    data['nb_traite'] = sum(1 for l in lignes_filtrees if _ftab(l['statut_fr']) == 'traite')
    data['nb_pretraite'] = sum(1 for l in lignes_filtrees if _ftab(l['statut_fr']) == 'pretraite')
    data['nb_archive'] = sum(1 for l in lignes_filtrees if _ftab(l['statut_fr']) == 'archive')

    # JSON compact de toutes les lignes (rendu + filtres 100% client, zéro rechargement)
    data['lignes_json'] = json.dumps([{
        'n': l['nature'], 'f': _ftab(l['statut_fr']), 'sf': l['statut_fr'],
        'num': l['libelle'] or '—', 'd': (l['date'] or ''),
        'ad': (l['ajout_date'] or ''), 'm': l['montant'],
        'st': l['statut_traitement'] or 'a_traiter', 'id': l['db_id'],
        'nw': bool(l['nouveau']),
    } for l in lignes_filtrees], separators=(',', ':'), ensure_ascii=False)

    return render_template('pennylane_dossier.html', dossier=dossier, data=data)







@app.route('/pennylane/item/<int:item_db_id>/statut', methods=['POST'])
@login_required
def pennylane_item_statut(item_db_id):
    """Change le statut de traitement d'un item Pennylane (a_traiter / traite / ignore)."""
    from app.models import PennylaneItem
    item = PennylaneItem.query.get_or_404(item_db_id)
    dossier = Dossier.query.get_or_404(item.dossier_id)

    # Scoping : admin, manager de l'équipe du dossier, ou collaborateur du dossier
    if current_user.role != 'admin':
        mes_equipes_ids = [eq.id for eq in Equipe.query.filter_by(manager_id=current_user.id).all()]
        if item.dossier_id not in [d.id for d in Dossier.query.filter(
                Dossier.equipe_id.in_(mes_equipes_ids)).all()] and dossier.collaborateur_id != current_user.id:
            return jsonify({'ok': False, 'message': 'Accès refusé'}), 403

    statut = (request.json or {}).get('statut') if request.is_json else request.form.get('statut')
    if statut not in ('a_traiter', 'traite', 'ignore'):
        return jsonify({'ok': False, 'message': 'Statut invalide'}), 400

    item.statut = statut
    item.statut_par_id = current_user.id
    item.statut_date = datetime.utcnow()
    db.session.commit()
    try:
        from app.integrations.pennylane import invalidate_dossier_cache
        invalidate_dossier_cache(item.dossier_id)
    except Exception:
        pass
    return jsonify({'ok': True, 'statut': statut})


@app.route('/pennylane/items/statut_bulk', methods=['POST'])
@login_required
def pennylane_items_statut_bulk():
    """Change le statut de plusieurs items Pennylane en une fois."""
    from app.models import PennylaneItem
    payload = request.get_json(silent=True) or {}
    ids = payload.get('ids') or []
    statut = payload.get('statut')
    if not ids or statut not in ('a_traiter', 'traite', 'ignore'):
        return jsonify({'ok': False, 'message': 'Paramètres invalides'}), 400

    items = PennylaneItem.query.filter(PennylaneItem.id.in_(ids)).all()
    updated = 0
    for item in items:
        dossier = Dossier.query.get_or_404(item.dossier_id)
        # Scoping : admin, manager de l'équipe du dossier, ou collaborateur du dossier
        if current_user.role != 'admin':
            mes_equipes_ids = [eq.id for eq in Equipe.query.filter_by(manager_id=current_user.id).all()]
            dossiers_autorises = [d.id for d in Dossier.query.filter(
                Dossier.equipe_id.in_(mes_equipes_ids)).all()]
            if item.dossier_id not in dossiers_autorises and dossier.collaborateur_id != current_user.id:
                continue  # skip les items non autorisés
        item.statut = statut
        item.statut_par_id = current_user.id
        item.statut_date = datetime.utcnow()
        updated += 1
    db.session.commit()
    if updated:
        dossier_ids = {it.dossier_id for it in items}
        try:
            from app.integrations.pennylane import invalidate_dossier_cache
            for did in dossier_ids:
                invalidate_dossier_cache(did)
        except Exception:
            pass
    return jsonify({'ok': True, 'updated': updated})


@app.route('/pennylane/check/<int:dossier_id>', methods=['POST'])
@login_required
def pennylane_check(dossier_id):
    """Vérifie les nouveaux documents/transactions Pennylane d'un dossier (à la demande)."""
    dossier = Dossier.query.get_or_404(dossier_id)

    # Même scoping que pennylane_dossier
    if current_user.role != 'admin':
        mes_equipes_ids = [eq.id for eq in Equipe.query.filter_by(manager_id=current_user.id).all()]
        if dossier.equipe_id not in mes_equipes_ids and dossier.collaborateur_id != current_user.id:
            return jsonify({'ok': False, 'message': 'Accès refusé'}), 403

    from app.integrations.pennylane import get_dossier_pennylane_data
    data = get_dossier_pennylane_data(dossier, force_refresh=True)
    return jsonify({'ok': data.get('ok'),
                    'nouveaux': data.get('nouveaux', []),
                    'resume': data.get('resume_nouveaux', ''),
                    'message': data.get('message', '')})



# ==========================
# Error handlers
# ==========================
def not_found(error):
    return render_template('error.html', code=404, message="Page non trouvée."), 404

@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f"500 error: {error}")
    try:
        db.session.rollback()
    except Exception:
        pass
    return render_template('error.html', code=500, message="Une erreur interne est survenue. Nos équipes ont été notifiées."), 500
