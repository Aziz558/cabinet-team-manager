"""dossiers_gest — suppressions + CSV dossiers/equipes/taches (extrait de app/routes.py)."""
from flask import render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from . import app, db
from .models import User, Equipe, Dossier, Tache, Notification, CommentaireTache, SuggestionTache, PennylaneItem
from sqlalchemy import or_
import json
import os
import re  # sonde v11 (temporaire)
from datetime import date, datetime, timedelta
from .route_common import (prochaine_echeance_theorique, prochaine_echeance_par_nature,
                            _tache_accessible, _nettoyer_relations_dossier)

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
        _nettoyer_relations_dossier(dossier)
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
                _nettoyer_relations_dossier(dossier)
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
    """Telearcher un modele CSV complet pour l'import de dossiers (separeur point-virgule, BOM UTF-8 pour Excel)."""
    import csv, io

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        'numero_dossier', 'intitule', 'collaborateur_email', 'equipe_nom',
        'regime_tva', 'frequence_tva', 'date_limite_declaration',
        'date_acompte_1', 'date_acompte_2',
        'regime_fiscale', 'has_cfe', 'forme_juridique', 'secteur_activite',
        'honoraires_mensuel', 'pennylane_customer_id', 'pennylane_api_token', 'siren',
        'tva_intra', 'naf', 'effectif', 'categorie_entreprise', 'dirigeant', 'adresse_siege'
    ])
    # Exemple 1 : CA3 mensuel, IS, avec CFE + liaison Pennylane (infos entreprise completes)
    writer.writerow([
        'EXEMPLE-001', 'SAS Exemple Tech', 'collaborateur@cabinet-jmh.com', 'Equipe de Hamza',
        'ca3_mensuel', 'mensuelle', '2026-10-15',
        '', '',
        'IS', 'OUI', 'SAS', 'Services',
        '350', '1234567890', 'pl_o_xxxxxxxx', '552032534',
        'FR27552032534', '70.10Z', '10 000 et plus', 'GE', 'ANTOINE BERNARD DE SAINT AFFRIQUE — Directeur Général', '17 BLD HAUSSMANN 75009 PARIS'
    ])
    # Exemple 2 : CA3 trimestriel, IRPP, sans CFE
    writer.writerow([
        'EXEMPLE-002', 'EURL Exemple BTP', '', '',
        'ca3_trimestriel', 'trimestrielle', '2026-10-30',
        '', '',
        'IRPP', 'NON', 'EURL', 'BTP',
        '', '', '', '', '', '', '', '', '', ''
    ])
    # Exemple 3 : CA12 annuel (2 acomptes) + token uniquement (infos auto via SIREN si enrichissement coche)
    writer.writerow([
        'EXEMPLE-003', 'SCI Exemple Immobilier', '', '',
        'ca12', 'annuelle', '2027-05-15',
        '2026-07-15', '2026-12-15',
        'IS', 'OUI', 'SCI', 'Immobilier',
        '200', '', 'pl_o_yyyyyyyy', '', '', '', '', '', '', ''
    ])

    output.seek(0)
    from flask import Response
    return Response(
        '\ufeff' + output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=template_dossiers.csv'}
    )

@app.route('/importer_csv', methods=['POST'])
@login_required
def importer_csv():
    """Importer des dossiers depuis un CSV au format du template complet
    (fiscalite, equipe, collaborateur, acomptes CA12, clefs API Pennylane)."""
    import csv, io, re, unicodedata

    def _key(s):
        """minuscule, sans accents ni punctuation — pour comparer en-tetes et libelles."""
        s = unicodedata.normalize('NFKD', str(s or ''))
        s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
        return re.sub(r'[^a-z0-9]', '', s)

    # en-tetes accepts (normalises) -> champ canonique
    ALIAS = {
        'numerodossier': 'numero_dossier', 'numero': 'numero_dossier',
        'intitule': 'intitule', 'raisosociale': 'intitule', 'client': 'intitule', 'nom': 'intitule',
        'collaborateuremail': 'collaborateur_email', 'email': 'collaborateur_email',
        'collaborateur': 'collaborateur_nom', 'prenomnom': 'collaborateur_nom',
        'equipe': 'equipe_nom', 'equipenom': 'equipe_nom',
        'regimetva': 'regime_tva', 'tva': 'regime_tva',
        'frequencetva': 'frequence_tva', 'frequence': 'frequence_tva',
        'datelimitedeclaration': 'date_limite_declaration', 'datelimite': 'date_limite_declaration',
        'dateacompte1': 'date_acompte_1', 'acompte1': 'date_acompte_1',
        'dateacompte2': 'date_acompte_2', 'acompte2': 'date_acompte_2',
        'regimefiscale': 'regime_fiscale', 'regimefiscal': 'regime_fiscale',
        'hascfe': 'has_cfe', 'cfe': 'has_cfe',
        'formejuridique': 'forme_juridique', 'forme': 'forme_juridique',
        'secteuractivite': 'secteur_activite', 'secteur': 'secteur_activite',
        'honorairesmensuel': 'honoraires_mensuel', 'honoraires': 'honoraires_mensuel',
        'pennylanecustomerid': 'pennylane_customer_id', 'customerid': 'pennylane_customer_id',
        'idclient': 'pennylane_customer_id', 'pennylaneid': 'pennylane_customer_id',
        'pennylaneapitoken': 'pennylane_api_token', 'apitoken': 'pennylane_api_token',
        'token': 'pennylane_api_token', 'cleapi': 'pennylane_api_token',
        'siren': 'siren', 'numsiren': 'siren',
        'tvaintracommunautaire': 'tva_intra', 'tvaintra': 'tva_intra', 'numerotva': 'tva_intra',
        'naf': 'naf_code', 'codenaf': 'naf_code', 'ape': 'naf_code', 'codeape': 'naf_code',
        'effectif': 'effectif_label', 'trancheeffectif': 'effectif_label',
        'categorieentreprise': 'categorie_entreprise', 'categorie': 'categorie_entreprise',
        'dirigeant': 'dirigeant',
        'adressesiege': 'adresse_siege', 'adresse': 'adresse_siege',
    }

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
    enrichir_siren = 'enrichir_siren' in request.form

    # Decodage tolerant (Excel FR = cp1252, template = utf-8 avec BOM)
    content = None
    for enc in ('utf-8-sig', 'utf-8', 'cp1252', 'ISO-8859-1'):
        try:
            content = file.read().decode(enc)
            break
        except UnicodeDecodeError:
            file.seek(0)
            continue
    if content is None or not content.strip():
        flash('Fichier CSV vide ou illisible.', 'danger')
        return redirect(url_for('dossiers'))

    # Separateur : premier caractere le plus frequent sur la ligne d'en-tetes
    first_line = content.splitlines()[0]
    delim = max((';', ',', '\t'), key=first_line.count)
    reader = csv.DictReader(io.StringIO(content), delimiter=delim)
    if not reader.fieldnames:
        flash('CSV sans ligne d\'en-têtes. Téléchargez le template depuis cette fenêtre.', 'danger')
        return redirect(url_for('dossiers'))

    canon = {}
    for h in reader.fieldnames:
        canon[h] = ALIAS.get(_key(h), _key(h))

    def _cell(row, name):
        return str(row.get(name) or '').strip()

    def _parse_date(v):
        if not v:
            return None
        v = v.strip().replace('-', '/')
        for fmt in ('%Y/%m/%d', '%d/%m/%Y', '%d/%m/%y'):
            try:
                return datetime.strptime(v, fmt).date()
            except ValueError:
                continue
        return 'INVALID'

    def _norm_regime_tva(v, f):
        """CA3/CA12/mensuel/trimestriel/annuel/exonere -> (regime, frequence) du formulaire."""
        s, fq = _key(v), _key(f)
        if not s and not fq:
            return None, None
        if 'exonere' in s or s in ('non', 'aucun', 'ni'):
            return 'exonere', None
        if 'ca12' in s or 'annuel' in s:
            return 'annuel', 'annuelle'
        if 'trimestriel' in s:
            return 'trimestriel', 'trimestrielle'
        if 'mensuel' in s:
            return 'mensuel', 'mensuelle'
        # 'CA3' seul ou valeur inconnue : la frequence decide (sinon mensuel, comme le scheduler)
        if 'trimestrielle' in fq:
            return 'trimestriel', 'trimestrielle'
        if 'annuelle' in fq:
            return 'annuel', 'annuelle'
        if 'mensuelle' in fq:
            return 'mensuel', 'mensuelle'
        return 'mensuel', 'mensuelle'

    def _norm_regime_fiscal(v):
        s = _key(v).upper()
        if not s:
            return None
        if 'IRPP' in s or s == 'IR':
            return 'IRPP'
        if s == 'IS' or 'SOCIETE' in s or 'SOCIETES' in s:
            return 'IS'
        return str(v).strip().upper()[:10]

    def _norm_bool(v):
        return _key(v) in ('oui', 'true', '1', 'yes', 'on', 'vrai', 'x', 'o')

    def _norm_float(v):
        v = str(v or '').replace('€', '').replace(' ', '').replace(',', '.')
        try:
            return float(v) if v else None
        except ValueError:
            return None

    success_count = 0
    task_total = 0
    error_count = 0
    example_skipped = 0
    errors = []
    avertissements = []
    seen = set()

    for row in reader:
        row_num = reader.line_num
        try:
            r = {}
            for h, v in row.items():
                if h is None:
                    continue
                r[canon[h]] = v

            numero = _cell(r, 'numero_dossier')
            intitule = _cell(r, 'intitule')
            # ignorer les lignes d'exemple du template si l'utilisateur les laisse
            if numero.upper().startswith('EXEMPLE'):
                example_skipped += 1
                continue
            if not numero or not intitule:
                error_count += 1
                errors.append(f'ligne {row_num} : numéro ou intitulé manquant')
                continue
            if numero in seen:
                error_count += 1
                errors.append(f'ligne {row_num} : dossier {numero} en double dans le fichier')
                continue
            if Dossier.query.filter_by(numero_dossier=numero).first():
                error_count += 1
                errors.append(f'ligne {row_num} : dossier {numero} existe déjà dans l\'app')
                continue
            seen.add(numero)

            # Collaborateur : email (colonne email) ou prenom+nom (colonne collaborateur)
            collab = None
            email_v = _cell(r, 'collaborateur_email')
            nom_v = _cell(r, 'collaborateur_nom')
            if email_v and '@' not in email_v and not nom_v:
                nom_v, email_v = email_v, ''  # tolerance : nom saisi dans la colonne email
            if email_v:
                collab = User.query.filter(db.func.lower(User.email) == email_v.lower()).first()
                if not collab:
                    error_count += 1
                    errors.append(f'ligne {row_num} : email collaborateur « {email_v} » introuvable dans l\'app')
                    continue
            elif nom_v:
                target = _key(nom_v)
                for u in User.query.all():
                    if target in (_key((u.prenom or '') + ' ' + (u.nom or '')),
                                  _key((u.nom or '') + ' ' + (u.prenom or ''))):
                        collab = u
                        break
                if not collab:
                    error_count += 1
                    errors.append(f'ligne {row_num} : collaborateur « {nom_v} » introuvable (mettez prenom nom, ou utilisez la colonne email)')
                    continue
            else:
                error_count += 1
                errors.append(f'ligne {row_num} ({numero}) : collaborateur manquant (email ou prenom nom)')
                continue

            # Equipe par nom, insensible aux accents
            equipe_nom = _cell(r, 'equipe_nom')
            equipe = None
            if equipe_nom:
                target = _key(equipe_nom)
                for e in Equipe.query.all():
                    if _key(e.nom) == target:
                        equipe = e
                        break
                if not equipe:
                    error_count += 1
                    errors.append(f'ligne {row_num} : équipe « {equipe_nom} » introuvable (vérifiez l\'orthographe exacte)')
                    continue
            else:
                error_count += 1
                errors.append(f'ligne {row_num} ({numero}) : équipe manquante')
                continue

            regime_fiscale = _norm_regime_fiscal(_cell(r, 'regime_fiscale'))
            if not regime_fiscale:
                error_count += 1
                errors.append(f'ligne {row_num} ({numero}) : régime fiscal manquant (IS ou IRPP)')
                continue

            regime_tva, frequence_tva = _norm_regime_tva(_cell(r, 'regime_tva'), _cell(r, 'frequence_tva'))

            date_limite = _parse_date(_cell(r, 'date_limite_declaration'))
            if date_limite == 'INVALID':
                error_count += 1
                errors.append(f'ligne {row_num} ({numero}) : date limite illisible « {_cell(r, "date_limite_declaration")} » (format AAAA-MM-JJ ou JJ/MM/AAAA)')
                continue
            d_a1 = _parse_date(_cell(r, 'date_acompte_1'))
            d_a2 = _parse_date(_cell(r, 'date_acompte_2'))
            if d_a1 == 'INVALID' or d_a2 == 'INVALID':
                error_count += 1
                errors.append(f'ligne {row_num} ({numero}) : date d\'acompte illisible (format AAAA-MM-JJ ou JJ/MM/AAAA)')
                continue

            dossier = Dossier(
                numero_dossier=numero,
                intitule=intitule,
                collaborateur_id=collab.id,
                equipe_id=equipe.id,
                regime_tva=regime_tva,
                frequence_tva=frequence_tva or (regime_tva.replace('mensuel', 'mensuelle').replace('trimestriel', 'trimestrielle').replace('annuel', 'annuelle') if regime_tva and regime_tva != 'exonere' else None),
                date_limite_declaration=date_limite,
                date_acompte_1=None if d_a1 == 'INVALID' else d_a1,
                date_acompte_2=None if d_a2 == 'INVALID' else d_a2,
                regime_fiscale=regime_fiscale,
                has_cfe=_norm_bool(_cell(r, 'has_cfe')),
                forme_juridique=_cell(r, 'forme_juridique') or None,
                secteur_activite=_cell(r, 'secteur_activite') or None,
                siren=(re.sub(r'\D', '', _cell(r, 'siren')) or None),
                tva_intra=(_cell(r, 'tva_intra') or '').strip() or None,
                naf_code=(_cell(r, 'naf_code') or '').strip() or None,
                effectif_label=(_cell(r, 'effectif_label') or '').strip() or None,
                categorie_entreprise=(_cell(r, 'categorie_entreprise') or '').strip() or None,
                dirigeant=(_cell(r, 'dirigeant') or '').strip() or None,
                adresse_siege=(_cell(r, 'adresse_siege') or '').strip() or None,
                honoraires_mensuel=_norm_float(_cell(r, 'honoraires_mensuel')),
                pennylane_customer_id=_cell(r, 'pennylane_customer_id') or None,
                pennylane_api_token=_cell(r, 'pennylane_api_token') or None,
            )
            if not dossier.date_limite_declaration and regime_tva and regime_tva != 'exonere':
                avertissements.append(f'{numero} : pas de date limite TVA, échéances au 15 du mois par défaut du scheduler')
            db.session.add(dossier)
            db.session.flush()

            # Enrichissement SIREN a l'import (cases vides seulement, sans ecraser le CSV)
            if enrichir_siren and dossier.siren:
                from .siren_service import apply_siren_to_dossier
                if len(dossier.siren) == 9:
                    ok, err = apply_siren_to_dossier(dossier, dossier.siren, overwrite=False)
                    if not ok:
                        avertissements.append(f'{numero} : enrichissement SIREN échoué ({err})')

            if creer_taches:
                from app.tva_scheduler import planifier_impots_dossier
                try:
                    planifier_impots_dossier(dossier)
                    task_total += dossier.taches.count()
                except Exception as e:
                    app.logger.warning(f'Erreur planification pour {numero}: {e}')
                    avertissements.append(f'{numero} : dossier créé mais planification des tâches en échec ({e})')

            success_count += 1
        except Exception as e:
            error_count += 1
            errors.append(f'ligne {row_num}: {str(e)}')

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f'Erreur lors de l\'enregistrement: {str(e)}', 'danger')
        return redirect(url_for('dossiers'))

    msg = f'Import terminé : {success_count} dossier(s) créé(s)'
    if creer_taches:
        msg += f' et {task_total} tâche(s) fiscale(s) générée(s)'
    msg += '.'
    if example_skipped:
        msg += f' ({example_skipped} ligne(s) d\'exemple du template ignorée(s).)'
    if avertissements:
        msg += ' ⚠ ' + ' · '.join(avertissements[:6])
    if error_count > 0:
        msg += f' {error_count} ligne(s) refusée(s) → ' + ' | '.join(errors[:15])
        flash(msg, 'warning' if success_count > 0 else 'danger')
    else:
        flash(msg, 'success')

    return redirect(url_for('dossiers'))

@app.route('/supprimer_equipe/<int:equipe_id>')
@login_required
def supprimer_equipe(equipe_id):
    """Supprime une equipe (admin) : detache membres et dossiers au prealable."""
    if current_user.role != 'admin':
        flash('Acc\u00e8s refus\u00e9.', 'danger')
        return redirect(url_for('equipes'))
    equipe = Equipe.query.get_or_404(equipe_id)
    try:
        nom = equipe.nom
        # Detacher les membres (equipe_id -> None)
        User.query.filter_by(equipe_id=equipe.id).update({User.equipe_id: None})
        # Detacher les dossiers
        Dossier.query.filter_by(equipe_id=equipe.id).update({Dossier.equipe_id: None})
        db.session.delete(equipe)
        db.session.commit()
        flash(f'\u00c9quipe \u00ab {nom} \u00bb supprim\u00e9e. Les membres et dossiers ont \u00e9t\u00e9 d\u00e9tach\u00e9s.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erreur lors de la suppression de l\u2019\u00e9quipe: {str(e)}', 'danger')
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
