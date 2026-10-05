"""checklist — checklist des obligations fiscales (extrait de app/routes.py)."""
from flask import render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from . import app, db
from .models import User, Equipe, Dossier, Tache, Notification, CommentaireTache, SuggestionTache, PennylaneItem
from sqlalchemy import or_
import json
import os
import re  # sonde v11 (temporaire)
from datetime import date, datetime, timedelta

@app.route('/checklist')
@login_required
def checklist():
    """Workflow checklist métier (inspiré FollowApp) :
    étape 1 : type de tâches (fiscale/comptable/sociale/perso)
    étape 2 : fréquence (récurrentes / ponctuelles)
    étape 3 : choix de la taxe / obligation
    étape 4 : grille — Dénomination × Régime × Jour d'échéance × Compteur × 12 mois (symboles).
    Statuts : ChecklistEntry (manuel) > seed tâches deadlines (plan B par défaut, clé API Pennylane firm à venir)."""
    from app.models import ChecklistEntry

    def _nwd(d):
        """Report au lundi si week-end (même logique que tva_scheduler)."""
        from datetime import timedelta as _td
        if d.weekday() >= 5:
            d = d + _td(days=(7 - d.weekday()))
        return d

    annee = request.args.get('annee', type=int) or date.today().year
    etape = request.args.get('etape', 'type')
    taxe = request.args.get('taxe', '')
    type_sel = request.args.get('type', '')
    freq_sel = request.args.get('freq', '')

    TAXE_META = {
        'tva_mensuel':     {'label': 'TVA mensuelle (CA3)',       'type': 'fiscale',   'freq': 'recurrentes', 'icon': 'bi-calendar3'},
        'tva_trimestriel': {'label': 'TVA trimestrielle (CA3)',   'type': 'fiscale',   'freq': 'recurrentes', 'icon': 'bi-calendar-week'},
        'tva_ca12':        {'label': 'TVA annuelle (CA12)',       'type': 'fiscale',   'freq': 'recurrentes', 'icon': 'bi-calendar-range'},
        'is':              {'label': 'Impôt sur les Sociétés',    'type': 'fiscale',   'freq': 'ponctuelles', 'icon': 'bi-bank'},
        'cfe':             {'label': 'CFE',                       'type': 'fiscale',   'freq': 'ponctuelles', 'icon': 'bi-buildings'},
        'autres_fiscales': {'label': 'Autres obligations fiscales', 'type': 'fiscale', 'freq': 'ponctuelles', 'icon': 'bi-file-earmark-text'},
        'tenue':           {'label': 'Tenue comptable',           'type': 'comptable', 'freq': 'recurrentes', 'icon': 'bi-journal-check'},
        'divers':          {'label': 'Divers',                    'type': 'comptable', 'freq': 'ponctuelles', 'icon': 'bi-box-seam'},
        'paie':            {'label': 'Paie',                      'type': 'sociale',   'freq': 'recurrentes', 'icon': 'bi-people'},
        'perso':           {'label': 'Perso',                     'type': 'perso',     'freq': 'recurrentes', 'icon': 'bi-person'},
    }

    # Compat ascendante : déduire type/freq depuis la taxe si absents
    if taxe in TAXE_META:
        if not freq_sel:
            freq_sel = TAXE_META[taxe]['freq']
        if not type_sel:
            type_sel = TAXE_META[taxe]['type']

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
    dossiers_list = dossiers_q.order_by(Dossier.numero_dossier).all()

    def _filtre_dossiers(taxe_key):
        """Filtre les dossiers concernés par une obligation donnée."""
        out = []
        for d in dossiers_list:
            regime = (d.regime_tva or '').lower().strip()
            if taxe_key == 'tva_mensuel':
                keep = regime in ('ca3', 'mensuel', 'mensuelle')
            elif taxe_key == 'tva_trimestriel':
                keep = regime in ('trimestriel', 'trimestrielle')
            elif taxe_key == 'tva_ca12':
                keep = regime in ('annuel', 'ca12')
            elif taxe_key == 'is':
                keep = (d.regime_fiscale or '').upper() == 'IS'
            elif taxe_key == 'cfe':
                keep = bool(d.has_cfe)
            else:
                keep = True  # tenue / paie / autres / divers / perso
            if keep:
                out.append(d)
        return out

    # ===== ÉTAPE 3 : cartes taxes avec compteurs de dossiers =====
    taxes_dispo = []
    if etape == 'taxe' and type_sel and freq_sel:
        for k, v in TAXE_META.items():
            if v['type'] == type_sel and v['freq'] == freq_sel:
                taxes_dispo.append({'key': k, 'label': v['label'], 'icon': v['icon'],
                                    'nb': len(_filtre_dossiers(k))})

    # ===== ÉTAPE 4 : grille =====
    grille = []
    if etape == 'grille' and taxe in TAXE_META:
        dossiers_f = _filtre_dossiers(taxe)
        entries = ChecklistEntry.query.filter(
            ChecklistEntry.taxe == taxe,
            ChecklistEntry.annee == annee,
            ChecklistEntry.dossier_id.in_([d.id for d in dossiers_f])
        ).all()
        ent_by = {(e.dossier_id, e.mois, e.kind): e for e in entries}

        # --- Seed plan B : statuts depuis les tâches deadlines existantes ---
        # (par défaut tant que la clé API firm Pennylane n'est pas fournie ;
        #  les entrées manuelles ChecklistEntry restent prioritaires)
        def _taches_deadline(kws):
            from sqlalchemy import or_
            conds = []
            for kw in kws:
                conds.append(Tache.titre.ilike('%' + kw + '%'))
            return Tache.query.filter(
                Tache.dossier_id.in_([d.id for d in dossiers_f]),
                or_(*conds),
                ~Tache.titre.ilike('%Préparation%')
            ).all()

        def _periode_depuis_deadline(dt, freq):
            """Tâche deadline d'échéance dt -> période déclarée (année, mois).
            Mensuel : échéance 24/08 => déclaration de JUILLET (07) de la même année.
            Trimestriel : échéance 24/04 => CA3 du T1 (période janvier) ; 24/01/N+1 => T4/N."""
            y, m = dt.year, dt.month - 1
            if m == 0:
                y, m = y - 1, 12
            if freq == 'trimestriel':
                m = ((m - 1) // 3) * 3 + 1
            return y, m

        seed_map = {}  # (dossier_id, mois, kind) -> (declare, paye)
        if taxe in ('tva_mensuel', 'tva_trimestriel'):
            kw = 'Dépôt TVA mensuel' if taxe == 'tva_mensuel' else 'Dépôt TVA trimestriel'
            for t in _taches_deadline([kw]):
                if not (t.date_echeance and t.statut == 'terminee'):
                    continue
                if not (date(annee, 1, 1) <= t.date_echeance <= date(annee + 1, 1, 31)):
                    continue
                py, pm = _periode_depuis_deadline(
                    t.date_echeance, 'mensuel' if taxe == 'tva_mensuel' else 'trimestriel')
                if py == annee:
                    seed_map[(t.dossier_id, pm, 'depot')] = (True, False)
        elif taxe == 'tva_ca12':
            for t in _taches_deadline(['Acompte TVA annuel']):
                if t.date_echeance and t.date_echeance.year == annee and t.statut == 'terminee':
                    seed_map[(t.dossier_id, t.date_echeance.month, 'acompte')] = (True, True)
            for t in _taches_deadline(['Déclaration TVA annuelle']):
                if t.date_echeance and t.date_echeance.year == annee and t.statut == 'terminee':
                    seed_map[(t.dossier_id, t.date_echeance.month, 'declaration')] = (True, False)
        elif taxe == 'is':
            for t in _taches_deadline(['Acompte IS']):
                if t.date_echeance and t.date_echeance.year == annee and t.statut == 'terminee':
                    seed_map[(t.dossier_id, t.date_echeance.month, 'acompte')] = (True, True)
            for t in _taches_deadline(['Déclaration IS']):
                if t.date_echeance and t.date_echeance.year == annee and t.statut == 'terminee':
                    seed_map[(t.dossier_id, t.date_echeance.month, 'declaration')] = (True, False)
        elif taxe == 'cfe':
            for t in _taches_deadline(['CFE']):
                if t.date_echeance and t.date_echeance.year == annee and t.statut == 'terminee':
                    seed_map[(t.dossier_id, t.date_echeance.month, 'depot')] = (True, False)

        today = date.today()

        def _col(d, m, kind, oblig, jour_dt):
            e = ent_by.get((d.id, m, kind))
            declare = bool(e.declare) if e else False
            paye = bool(e.paye) if e else False
            if e is None and oblig and (d.id, m, kind) in seed_map:
                declare, paye = seed_map[(d.id, m, kind)]
            if not oblig:
                state = 'na'
            elif paye:
                state = 'solde'
            elif declare:
                state = 'declare'
            elif jour_dt and jour_dt < today:
                state = 'retard'
            else:
                state = 'venir'
            return {'mois': m, 'kind': kind, 'oblig': oblig,
                    'declare': declare, 'paye': paye, 'state': state,
                    'jour': jour_dt.day if jour_dt else 0,
                    'date_iso': jour_dt.isoformat() if jour_dt else ''}

        for d in dossiers_f:
            regime = (d.regime_tva or '').lower().strip()
            jour_lim = d.date_limite_declaration.day if d.date_limite_declaration else 15
            cols = []
            if taxe == 'tva_mensuel':
                # Colonne M = déclaration du mois M ; son échéance tombe le mois SUIVANT
                # (ex. déclaration de juillet 07 -> dépôt 24/08, report lundi si week-end)
                for m in range(1, 13):
                    ay, am = (annee, m + 1) if m < 12 else (annee + 1, 1)
                    try:
                        jdt = _nwd(date(ay, am, jour_lim))
                    except ValueError:
                        jdt = _nwd(date(ay, am, 15))
                    cols.append(_col(d, m, 'depot', True, jdt))
            elif taxe == 'tva_trimestriel':
                # Colonne M = 1er mois du TRIMESTRE déclaré ; échéance 3 mois plus tard
                # (ex. CA3 du T1 janv-mars -> dépôt 24/04 ; CA3 du T4 oct-déc -> dépôt 24/01/N+1)
                for m in range(1, 13):
                    if m in (1, 4, 7, 10):
                        ay, am = (annee, m + 3) if m <= 9 else (annee + 1, m - 9)
                        try:
                            jdt = _nwd(date(ay, am, jour_lim))
                        except ValueError:
                            jdt = _nwd(date(ay, am, 15))
                        cols.append(_col(d, m, 'depot', True, jdt))
                    else:
                        cols.append(_col(d, m, 'depot', False, None))
            elif taxe == 'tva_ca12':
                j1 = d.date_acompte_1.day if d.date_acompte_1 else jour_lim
                j2 = d.date_acompte_2.day if d.date_acompte_2 else jour_lim
                for m in range(1, 13):
                    if m == 7:
                        try:
                            jdt = _nwd(date(annee, m, j1))
                        except ValueError:
                            jdt = _nwd(date(annee, m, 15))
                        cols.append(_col(d, m, 'acompte', True, jdt))
                    elif m == 12:
                        try:
                            jdt = _nwd(date(annee, m, j2))
                        except ValueError:
                            jdt = _nwd(date(annee, m, 15))
                        cols.append(_col(d, m, 'acompte', True, jdt))
                    elif m == 5:
                        cols.append(_col(d, m, 'declaration', True, _nwd(date(annee, 5, 15))))
                    else:
                        cols.append(_col(d, m, 'na', False, None))
            elif taxe == 'is':
                if (d.regime_fiscale or '').upper() != 'IS':
                    continue
                for m in range(1, 13):
                    if m in (3, 6, 9, 12):
                        cols.append(_col(d, m, 'acompte', True, _nwd(date(annee, m, 15))))
                    elif m == 5:
                        cols.append(_col(d, m, 'declaration', True, _nwd(date(annee, 5, 15))))
                    else:
                        cols.append(_col(d, m, 'na', False, None))
            elif taxe == 'cfe':
                if not d.has_cfe:
                    continue
                for m in range(1, 13):
                    if m == 12:
                        cols.append(_col(d, m, 'depot', True, _nwd(date(annee, 12, 15))))
                    else:
                        cols.append(_col(d, m, 'na', False, None))
            else:
                # tenue / paie / autres / divers / perso : 1 échéance générique par mois
                for m in range(1, 13):
                    cols.append(_col(d, m, 'depot', True, date(annee, m, 1)))

            if cols:
                # Compteur prochaine échéance (J-x) : 1ère obligation future de l'année
                next_dl = None
                for c in cols:
                    if c['oblig'] and c['date_iso']:
                        yy, mm, dd = c['date_iso'].split('-')
                        dtc = date(int(yy), int(mm), int(dd))
                        if dtc >= today:
                            next_dl = dtc
                            break
                jours = (next_dl - today).days if next_dl else None
                collab = d.collaborateur
                initiales = ''
                if collab:
                    initiales = ((collab.prenom or '')[:1] + (collab.nom or '')[:1]).upper()
                grille.append({'dossier': d, 'regime': regime or '—', 'cols': cols,
                               'jours': jours, 'next_dl': next_dl, 'collab': collab,
                               'initiales': initiales})

    meta = TAXE_META.get(taxe)
    data = {'annee': annee, 'etape': etape, 'taxe': taxe, 'meta': meta, 'grille': grille,
            'type': type_sel, 'freq': freq_sel, 'taxes_dispo': taxes_dispo}

    # --- Statuts Pennylane (session web) pour affichage dans la grille TVA ---
    pl_last_sync = {}
    if taxe in ('tva_mensuel', 'tva_trimestriel'):
        from app.integrations.pennylane_web import statuts_pour_grille, get_last_sync, pill_class, pill_icon
        if grille:
            _pl_statuts = statuts_pour_grille([g['dossier'].id for g in grille], annee)
            for g in grille:
                for c in g['cols']:
                    st = _pl_statuts.get((g['dossier'].id, c['mois']))
                    if st:
                        c['pl_statut'] = st.statut
                        c['pl_statut_fr'] = st.statut_affiche
                        c['pl_deadline'] = st.deadline
                        c['pl_montant'] = st.montant
                        c['pl_sync'] = st.date_sync.strftime('%d/%m %H:%M') if st.date_sync else ''
                        c['pl_pill'] = pill_class(st.statut, st.statut_affiche)
                        c['pl_icon'] = pill_icon(st.statut, st.statut_affiche)
        pl_last_sync = get_last_sync()

    if request.args.get('format') == 'json':
        from flask import jsonify
        return jsonify({'annee': annee, 'taxe': taxe,
                        'grille': [{'id': g['dossier'].id, 'numero': g['dossier'].numero_dossier,
                                    'intitule': g['dossier'].intitule, 'regime': g['regime'],
                                    'jours': g['jours'], 'cols': g['cols']} for g in grille]})
    return render_template('checklist.html', data=data, annee=annee,
                           annees=sorted({date.today().year, date.today().year - 1, date.today().year - 2, date.today().year + 1}, reverse=True))


@app.route('/checklist/toggle', methods=['POST'])
@login_required
def checklist_toggle():
    """Change le statut d'une case de checklist.
    Accepte soit {field, value} (compat), soit {state: declare|solde|venir}."""
    from app.models import ChecklistEntry
    if current_user.role not in ('admin', 'manager'):
        return jsonify({'ok': False, 'error': 'acces refuse'}), 403
    payload = request.get_json(silent=True) or {}
    try:
        dossier_id = int(payload.get('dossier_id'))
        taxe = str(payload.get('taxe') or '')
        annee = int(payload.get('annee'))
        mois = int(payload.get('mois'))
        kind = str(payload.get('kind') or 'depot')
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'payload invalide'}), 400
    if taxe not in ('tva_mensuel', 'tva_trimestriel', 'tva_ca12', 'is', 'cfe', 'tenue', 'paie', 'autres_fiscales', 'divers', 'perso'):
        return jsonify({'ok': False, 'error': 'taxe inconnue'}), 400
    if not (1 <= mois <= 12):
        return jsonify({'ok': False, 'error': 'champ invalide'}), 400

    state = payload.get('state')
    if state is not None:
        if state == 'declare':
            declare, paye = True, False
        elif state == 'solde':
            declare, paye = True, True
        elif state in ('venir', 'retard', 'clear'):
            declare, paye = False, False
        else:
            return jsonify({'ok': False, 'error': 'state invalide'}), 400
    else:
        field = str(payload.get('field') or '')
        value = bool(payload.get('value'))
        if field not in ('declare', 'paye'):
            return jsonify({'ok': False, 'error': 'champ invalide'}), 400
        e0 = ChecklistEntry.query.filter_by(dossier_id=dossier_id, taxe=taxe, annee=annee,
                                            mois=mois, kind=kind).first()
        declare = (not e0.declare) if (field == 'declare' and e0) else (value if field == 'declare' else (e0.declare if e0 else False))
        paye = (not e0.paye) if (field == 'paye' and e0) else (value if field == 'paye' else (e0.paye if e0 else False))

    e = ChecklistEntry.query.filter_by(dossier_id=dossier_id, taxe=taxe, annee=annee,
                                       mois=mois, kind=kind).first()
    if not e:
        e = ChecklistEntry(dossier_id=dossier_id, taxe=taxe, annee=annee, mois=mois, kind=kind)
        db.session.add(e)
    if declare or paye:
        e.declare = declare
        e.paye = paye
    else:
        # tout désactivé -> supprimer la ligne (retour à l'état calculé : à venir / retard / seed)
        db.session.delete(e)
    e.pl_mode = False  # saisie manuelle : la prochaine synchro fera foi sur les périodes connues de PL
    e.updated_by_id = current_user.id
    e.date_modif = datetime.utcnow()
    db.session.commit()
    # LIAISON checklist -> taches : cocher la case termine la tache deadline
    # de la meme periode, la decocher la remet a faire.
    try:
        from .checklist_link import appliquer_case_a_taches
        if appliquer_case_a_taches(dossier_id, taxe, annee, mois, kind, declare or paye, paye):
            db.session.commit()
    except Exception as _lk_e:
        db.session.rollback()
        app.logger.warning(f"Liaison case->taches: {_lk_e}")
    return jsonify({'ok': True, 'declare': declare if (declare or paye) else False,
                    'paye': paye if (declare or paye) else False})


@app.route('/checklist/relink_all', methods=['POST'])
@login_required
def checklist_relink_all():
    """Backfill de la liaison Checklist <-> taches : applique l'etat de TOUTES les
    cases existantes (declarees ou non) sur les taches deadline correspondantes.
    Utile apres deploiement de la liaison ou pour resynchroniser manuellement."""
    if current_user.role not in ('admin', 'manager'):
        return jsonify({'ok': False, 'error': 'Accès refusé.'}), 403
    from .models import ChecklistEntry
    from .checklist_link import appliquer_case_a_taches
    n = 0
    for e in ChecklistEntry.query.all():
        n += appliquer_case_a_taches(e.dossier_id, e.taxe, e.annee, e.mois, e.kind,
                                     bool(e.declare or e.paye), bool(e.paye))
    db.session.commit()
    app.logger.info(f"checklist_relink_all: {n} tache(s) ajustee(s) par {current_user.email}")
    return jsonify({'ok': True, 'taches_ajustees': n})
