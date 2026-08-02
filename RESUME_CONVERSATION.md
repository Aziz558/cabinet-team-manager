# Resume de conversation — Cabinet Team Manager

## Etat actuel du projet
- Chemin: `C:\Users\LENOVO\cabinet_team_manager`
- Stack: Flask + SQLite + Flask-Login + Flask-Mail + Bootstrap 5
- Serveur local testé: `http://127.0.0.1:5000`
- Base de données: `instance/app.db`
- Premier manager créé: `aziz@cabinet.local` / `manager123`

## Structure
```
cabinet_team_manager/
├── app/
│   ├── __init__.py
│   ├── models.py
│   └── routes.py
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── register.html
│   ├── dashboard_manager.html
│   ├── dashboard_collaborateur.html
│   ├── membres.html
│   ├── fiche_membre.html
│   ├── dossiers.html
│   ├── taches.html
│   └── profil.html
├── static/
│   ├── css/style.css
│   ├── js/
│   └── uploads/
├── requirements.txt
├── render.yaml
├── wsgi.py
├── init_db.py
├── run_local.bat
└── .env.example
```

## Modeles de donnees
- `User`: email, password_hash, nom, prenom, photo_profil, role (manager/membre), poste, telephone, actif, date_arrivee
- `Dossier`: numero_dossier (unique), intitule, collaborateur_id, regime_tva (ca3/ca12/exonere), date_limite_declaration, date_creation, date_cloture
- `Tache`: titre, description, dossier_id, assigne_a, cree_par, priorite (haute/moyenne/basse), statut (a_faire/en_cours/terminee), date_echeance, date_prise_en_charge, date_completion
- `Notification`: user_id, tache_id, message, lu, type_notification, date_envoi
- `CommentaireTache`: tache_id, user_id, message, date_creation
- `Performance`: user_id, periode, date_debut, date_fin, dossiers_termines, taches_terminees, taches_en_retard, taux_respect_delai, score_performance, date_calcul

## Fonctionnalites implementees
### Auth
- Register: premier compte manager seulement
- Login/Logout avec Flask-Login
- Rôles: manager / membre

### Manager
- Dashboard: KPI membres actifs, dossiers, tâches retard, haute priorité
- Vue équipe: tableau collaborateurs + dossiers en cours / tâches à faire / en retard
- Tâches du jour / semaine
- CRUD membres: ajouter, modifier, désactiver (soft), fiche membre
- Upload photo profil
- CRUD dossiers: créer, modifier, assigner collaborateur, régime TVA, date limite déclaration
- Import CSV dossiers: format `numero_dossier,intitule,regime_tva,date_limite_declaration,collaborateur_email`
- Recherche dossiers par n°, intitulé, collaborateur, régime TVA
- CRUD tâches: créer avec multi-assignation, priorité, date échéance
- Notifications mail à l'assignation + notification au manager quand collaborateur prend en charge / termine

### Collaborateur
- Dashboard: mes dossiers, mes tâches à faire / en cours / terminées
- Prendre en charge une tâche (bouton "Prendre")
- Terminer une tâche (bouton "Terminer")
- Profil: modifier infos + mot de passe

## Point 1 corrigé
- Supprimé colonne "Statut" dans la vue dossiers
- Ajouté colonnes: Régime TVA (CA3/CA12/Exonéré), Date limite déclaration, Délai restant
- Ajouté barre de recherche temps réel
- Ajouté import CSV dossiers
- Modifié modèle Dossier: `regime_tva`, `date_limite_declaration` (remplace `date_limite` et `statut`)

## A faire / point 2 en attente
- Configurer Outlook SMTP dans `.env` pour les mails
- Déploiement Render
- Point 2 que l'utilisateur va préciser

## Comment relancer localement
Option A: double-clic sur `run_local.bat`
Option B: terminal dans `C:\Users\LENOVO\cabinet_team_manager`:
```
venv\Scripts\python.exe -c "from app import app; app.run(debug=True, port=5000, use_reloader=False)"
```
Puis ouvrir `http://127.0.0.1:5000`

## Données de test
- Manager: `aziz@cabinet.local` / `manager123`
- Aucun membre/dossier/tâche créé pour l'instant
