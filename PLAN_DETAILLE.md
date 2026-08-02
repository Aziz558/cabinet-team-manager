# Cabinet Team Manager — Plan détaillé page par page

## 0. Rôle et principes
- Cible : cabinet comptable, usage quotidien.
- Public : manager + collaborateurs.
- Langue : français.
- Stack : Flask / SQLite / Bootstrap 5 / Flask-Login / Flask-Mail.
- Intégrations cibles : PennyLane, Outlook, Teams, Microsoft To Do, OpenRouter.
- Principe UX : moins de clics, vue du jour d’abord, automation quand c’est possible.

---

## 1. Pages / vues

### 1.1 Login
- **Objectif** : connexion sécurisée.
- **Contenu** : email + mot de passe + case mémo “se souvenir de moi”.
- **Règles** :
  - redirection automatique si déjà connecté
  - message flash pour erreur
  - possibilité de demander un accès / contacter le manager
- **Intégrations** : aucune pour l’instant.

### 1.2 Register
- **Objectif** : créer le premier manager.
- **Règles** :
  - accessible uniquement si aucun manager n’existe
  - fermé ensuite
- **Évolutions possibles** :
  - invitation par email
  - choix du rôle lors de l’invitation

---

### 1.3 Dashboard Manager
- **Objectif** : pilotage global en 30 secondes.
- **KPIs** :
  - membres actifs
  - dossiers en cours
  - tâches en retard
  - tâches haute priorité non commencées
- **Blocs** :
  - Tâches du jour
  - Tâches de la semaine
  - Alertes : retards, deadlines déclarations proches
  - Activité récente
- **Actions rapides** :
  - créer tâche
  - créer dossier
  - importer CSV
- **Intégrations** :
  - suggestions automatiques depuis PennyLane / mails / Teams
  - indicateurs de charge par collaborateur

---

### 1.4 Dashboard Collaborateur
- **Objectif** : savoir exactement quoi faire en arrivant.
- **Contenu prioritaire** :
  - Mes tâches du jour
  - Mes tâches en cours
  - Mes tâches à faire
  - Mes dossiers assignés
  - Rappels : deadlines, échéances fiscales
- **Actions rapides** :
  - prendre en charge
  - terminer
  - ajouter un commentaire
  - demander de l’aide

---

### 1.5 Membres (manager)
- **Objectif** : gérer l’équipe.
- **Liste** :
  - nom, prénom, poste, email, statut actif/inactif
  - indicateurs synthétiques : dossiers en cours, retards, charge
- **Actions** :
  - ajouter membre
  - modifier infos
  - réinitialiser mot de passe
  - activer / désactiver
  - accéder à la fiche membre
- **Fiche membre** :
  - profil complet
  - historique tâches
  - taux de respect délais
  - performance récente
  - photo de profil

---

### 1.6 Dossiers
- **Objectif** : suivre les dossiers clients et leurs deadlines fiscales.
- **Liste** :
  - recherche par numéro, intitulé, collaborateur, régime TVA
  - colonnes : numéro, intitulé, collaborateur, régime TVA, date limite déclaration, délai restant
  - tri + pagination si nécessaire
- **Création / modification** :
  - numéro, intitulé, collaborateur, régime TVA, date limite
- **Intégrations** :
  - import CSV
  - PennyLane : import automatique des dossiers clients
  - rappels automatiques avant échéances

---

### 1.7 Tâches
- **Objectif** : affecter, exécuter, suivre.
- **Liste manager** :
  - vue globale
  - filtres : statut, priorité, dossier, collaborateur, date
  - tri par échéance / priorité
- **Liste collaborateur** :
  - mes tâches uniquement
  - colonnes : titre, dossier, priorité, échéance, jours restants, statut
- **Création tâche** :
  - titre, description
  - dossier lié
  - multi-assignation
  - priorité
  - date d’échéance
  - rappel automatique
- **Actions** :
  - prendre en charge
  - terminer
  - commenter
- **Intégrations** :
  - Microsoft To Do : création automatique
  - Teams : notification
  - Outlook : mail d’assignation
  - suggestions issues de mails / Teams / PennyLane

---

### 1.8 Notifications
- **Objectif** : centraliser les alertes utiles.
- **Vue** :
  - liste notifications non lues
  - historique limité
  - types : assignation, prise en charge, completion, système
- **Comportement** :
  - marquage automatique comme lu à l’ouverture
  - badge dans la navbar
- **Intégrations** :
  - Teams
  - Outlook

---

### 1.9 Profil
- **Objectif** : gérer ses informations.
- **Contenu** :
  - nom, prénom, poste, téléphone
  - modification mot de passe
  - photo de profil

---

### 1.10 Admin / Settings (à venir)
- **Objectif** : configuration avancée pour le manager.
- **Contenu prévu** :
  - intégrations API
  - règles d’automatisation
  - modèles de tâches récurrentes
  - sécurité / sauvegarde

---

## 2. Fonctionnalités transversales

### 2.1 Vue “Mes tâches du jour”
- Affichage prioritaire pour chaque collaborateur.
- Tâches dues aujourd’hui + rappels du jour.
- Statut visuel : à faire / en cours / en retard.

### 2.2 Tâches récurrentes
- Journalières, hebdomadaires, mensuelles.
- Basées sur des règles métier.
- Génération automatique selon calendrier.

### 2.3 Rappels et échéances
- Notifications avant deadline.
- Escalade possible si retard.

### 2.4 Recherche globale
- Tâches, dossiers, membres.

### 2.5 Import / export
- CSV dossiers.
- Export Excel / PDF à venir.

---

## 3. Intégrations et automation

### 3.1 PennyLane
- Lecture API :
  - clients / dossiers
  - échéances fiscales
  - factures / dépenses récentes
- Génération de tâches suggérées :
  - “Déclaration CA3 client X”
  - “Vérifier dépense client Y”

### 3.2 Outlook
- Réception / analyse mails reçus :
  - détection de demandes client
  - suggestions de tâches
- Envoi notifications :
  - assignation
  - rappels
  - résumés

### 3.3 Microsoft Teams
- Lecture conversations d’équipe :
  - détection d’actions à faire
  - suggestions de tâches
- Notifications sortantes :
  - assignation
  - rappels
  - mises à jour

### 3.4 Microsoft To Do
- Création / mise à jour / complétion des tâches personnelles.

### 3.5 OpenRouter LLM
- Classification des messages/mails en catégories exploitables.
- Suggestion d’affectation selon charge et compétences.
- Résumé d’activité.
- Aide à la priorisation.

---

## 4. Flux principaux

### 4.1 Flux manager
1. Ouvrir dashboard
2. Voir alertes et tâches du jour
3. Créer / assigner tâche
4. Suivre avancement
5. Valider / clôturer

### 4.2 Flux collaborateur
1. Ouvrir app
2. Voir tâches du jour
3. Prendre en charge / avancer
4. Terminer + commenter
5. Recevoir notifications

### 4.3 Flux automation
1. Scanner PennyLane / Outlook / Teams
2. LLM extrait actions
3. Créer tâches suggérées
4. Manager valide / ajuste
5. Exécution + suivi

---

## 5. Règles métier principales
- Un dossier a une deadline fiscale.
- Une tâche appartient à un dossier ou est indépendante.
- Une tâche a un échéance, une priorité, un statut.
- Notification systématique à l’assignation.
- Une tâche en retard est visible immédiatement.
- Un membre inactif n’apparaît plus dans les assignations.

---

## 6. Priorisation réaliste
1. Stabiliser l’existant
2. Vue “tâches du jour”
3. Automatisations simples :
   - rappels échéances
   - suggestions depuis PennyLane
4. Puis Outlook / Teams / To Do si les clés API sont fournies
5. LLM en dernier, pour classification et suggestions

---

## 7. Prochaines étapes proposées
- Valider ce plan
- Choisir la première fonctionnalité à implémenter
- Définir les formats d’intégration avec PennyLane et Microsoft
