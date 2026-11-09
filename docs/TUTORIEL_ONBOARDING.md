# Tutoriel — Module « Suivi nouveaux dossiers » (JMH Orbit)

Ce module remplace le classeur `Suivi Nouveaux Doss CABINET JMH.xlsx`. Il suit
l'installation des nouveaux clients (Création / Reprise / Revision) et les
départs de clients, avec mails automatiques et import Excel.

> Accès : menu latéral **« Nouveaux dossiers »** (icône fusée) → `/onboarding`.
> Droits : **admin et manager** peuvent créer/modifier ; les autres rôles ont la
> lecture seule. La **suppression** est réservée à l'admin.

---

## 0. Préparation (admin, une seule fois)

Dans **Réglages > Notifications** :

1. **Destinataire mails de départ** (`ONBOARDING_MAIL_FACTURATION`) : l'adresse du
   service facturation qui recevra le mail « stop facturation + désactivation
   Pennylane » quand un client quitte le cabinet.
2. **Seuil de rappel** (`ONBOARDING_RAPPEL_JOURS`, défaut **7**) : nombre de jours
   sans mouvement à partir duquel un dossier est considéré « en attente » et
   peut être relancé via le bouton Rappels.
3. **Clé Brevo** (`BREVO_API_KEY`) : nécessaire pour que les mails partent
   réellement. Sans clé, chaque tentative est tracée en erreur dans le journal
   des mails du dossier (rien n'est perdu, mais rien n'est envoyé).

---

## 1. Exemple fil rouge

Tout au long du tutoriel, on suit un cas concret :

| Champ | Valeur |
|---|---|
| Nom du dossier | **BOULANGERIE DUPONT** |
| Client | Marie Dupont |
| Mail client | marie.dupont@example.com |
| Type | **Création** |
| EC / chef de mission | Aziz Benali |
| Établissement | Paris 11e |
| Honoraires | 4 800 € HT/an |
| Début mission | 01/12/2026 |
| Social | oui · PolyActe non |
| Collab. comptable / social / juridique | Sara / Yanis / Léa |

---

## 2. Vue d'ensemble (liste)

La page `/onboarding` comporte :

- **2 onglets** : « Nouveaux dossiers » et « Dossiers partis » (avec compteurs).
- **KPI** (onglet nouveaux) : en cours, terminés, en attente > seuil, total
  honoraires HT/an des dossiers en cours.
- **Filtres** : recherche texte (dossier ou client), type (Création / Reprise /
  Revision), établissement. Bouton **Filtrer**.
- **Tableau** : dossier + client, type, EC/chef de mission, **prochaine étape**,
  **attente** (jours, pastille rouge si ≥ seuil), **barre d'avancement** (x/y),
  **5 pastilles de phases** (vide / entamée / complète), bouton **Ouvrir**.
- En haut à droite : **Nouveau dossier**, **Importer Excel**, **Rappels**.

Les 5 phases du pipeline (identiques au fichier Excel) :

1. **Contractuel** — lettre de mission (+ déontologie/documents ancien EC pour les reprises)
2. **Juridique (création)** — statuts, dépôt K, juridique création, KBIS… (uniquement type Création)
3. **Installation** — dossier Pennylane, Inviter le client, RIB, imots.gouv, code impôts
4. **Facturation & mandats** — envoi LDM/facturation, mandats de prélèvement, So bank…
5. **Équipe** — mail d'identité des collaborateurs au client

Le pipeline s'adapte au type : **Création = 20 étapes**, **Reprise = 16**,
**Revision = 14** (les étapes « ancien EC » ne s'appliquent qu'aux reprises,
le volet juridique création uniquement aux créations).

---

## 3. Créer un dossier

1. Cliquer **Nouveau dossier** (bouton en haut à droite).
2. Remplir la fenêtre « Nouveau dossier à suivre » :
   - **Nom du dossier** * (obligatoire) : `BOULANGERIE DUPONT`
   - Nom du client : `Marie Dupont` · Mail : `marie.dupont@example.com` · Téléphone
   - Auteur (pré-rempli avec votre prénom), EC/chef de mission : `Aziz Benali`
   - Établissement : `Paris 11e` (suggestion automatique depuis les établissements existants)
   - **Type** : `Création`
   - Honoraires/an HT : `4800` · Date début mission : `01/12/2026`
   - Cases **PolyActe** / **Social** (cocher Social)
   - Collaborateurs comptable / social / juridique : `Sara`, `Yanis`, `Léa`
   - Commentaires (libre)
3. Cliquer **Créer le suivi**.

Résultat : le dossier est créé avec **son pipeline complet d'étapes** (toutes à
vide) et vous êtes redirigé vers sa fiche détail. Message : « Dossier
"BOULANGERIE DUPONT" créé avec son pipeline complet. »

---

## 4. Cocher les étapes (fiche détail)

En haut de la fiche :

- **Barre de progression** en % (étapes faites / étapes applicables au type).
- **5 pastilles de phases** (survol = détail x/y par phase).
- **Prochaine étape** : la première étape non faite dans l'ordre du pipeline.
- **« Dernier mouvement : il y a N j »** : jours depuis la dernière étape datée
  (ou depuis le début de mission / la création si aucune étape datée).

Chaque phase est une carte listant ses étapes. Pour chaque étape, trois façons
de la marquer (comme dans le fichier Excel) :

| Saisie | Signification |
|---|---|
| Une **date** + **Appliquer** | Fait à cette date |
| Case **X** + **Appliquer** | Fait sans date (le « X » du classeur) |
| Bouton **Fait** | Fait aujourd'hui (raccourci) |
| Champ **Note…** | Commentaire libre attaché à l'étape |

- Une fois faite, l'étape affiche « Fait le jj/mm/aaaa · par Prénom »
  (**traçabilité** de qui a coché) et le bouton devient **Effacer** (avec
  confirmation) pour annuler le marqueur.
- **Appliquer** enregistre la date, la case X et la note saisies.

### Déroulé de l'exemple

1. Phase **Contractuel** : « Édition lettre de mission » → bouton **Fait**.
   Puis « Lettre de mission signée » → date `15/11/2026` + **Appliquer**.
   La barre passe à 2/20, prochaine étape : « Projet de statuts ».
2. Phase **Juridique (création)** : cocher au fil de l'eau Projet de statuts,
   Certificat de dépôt K, Juridique création, Retour juridique création signé,
   Statuts, KBIS. Exemple : « Certificat de dépôt K » → case **X** + note
   `dépôt greffe le 12/11` + **Appliquer** → « Fait (sans date) » + la note.
3. Phase **Installation** : Création dossier Pennylane, Inviter le client, RIB,
   Adhésion/Substitution imots.gouv, Code impôts.
4. Phase **Facturation & mandats** : voir §5 — l'étape « Envoi LDM / facturation »
   déclenche un mail automatique.
5. Phase **Équipe** : « Mail identité collaborateurs envoyé » → second mail auto.

---

## 5. Les mails automatiques au franchissement d'étapes

Deux étapes clés envoient un mail **au client** (adresse du champ « Mail » de la
fiche) dès qu'elles sont marquées faites :

1. **« Envoi LDM / facturation »** (phase 4) → mail « Lettre de mission &
   facturation » : confirme l'envoi de la LDM et des éléments de facturation,
   demande le retour signé.
2. **« Mail identité collaborateurs envoyé »** (phase 5) → mail « Vos
   interlocuteurs » : liste le collaborateur comptable, social (si Social coché)
   et juridique renseignés dans la fiche.

Un message flash confirme l'envoi (« Mail … envoyé au client ») ou signale
l'échec. Chaque envoi (réussi ou en erreur) est **journalisé** dans la carte
« Mails du suivi » de la fiche (20 derniers).

> Condition : le champ **Mail client** doit être renseigné, sinon aucun mail
> n'est tenté. Pensez à remplir les collaborateurs avant de cocher l'étape
> « identité », sinon le mail affiche « (à compléter) ».

## 6. Envoyer un mail manuellement

Carte **« Mails du suivi »** (colonne droite de la fiche) :

1. **Type de mail** : Déontologie (transmission de dossier), Lettre de mission &
   facturation, ou Identité des collaborateurs.
2. **Destinataire** : pré-rempli avec le mail client ; modifiable (ex. l'adresse
   de l'ancien expert-comptable pour le mail de déontologie).
3. **Corps personnalisé** : laisser vide = modèle standard du cabinet ; sinon
   votre texte remplace le modèle.
4. Cliquer **Envoyer**.

Le mail de déontologie type indique la reprise du dossier par le Cabinet JMH à
compter de la date de début mission et demande la transmission des pièces.

Le journal sous le formulaire affiche : type → destinataire, date/heure, et
l'erreur éventuelle (icône rouge).

---

## 7. Modifier la fiche, terminer, rouvrir, supprimer

- **Modifier** (bouton crayon, carte « Fiche dossier ») : même formulaire qu'à la
  création. **Changer le type ajoute les étapes manquantes** du nouveau pipeline
  (les étapes déjà cochées sont conservées).
- **Marquer terminé** (en-tête) : bascule le statut en « Terminé » (badge vert,
  sort des KPI « en cours »). Le bouton devient **Réouvrir** pour repasser en cours.
- **Supprimer** (icône poubelle, **admin uniquement**, avec confirmation) :
  supprime le suivi, son pipeline et son journal de mails.

---

## 8. Rappels des étapes bloquées

Bouton **Rappels** (en haut de la liste) :

1. Orbit sélectionne les dossiers **en cours** dont la prochaine étape est en
   attente depuis **≥ seuil** jours (défaut 7, réglable).
2. Pour chacun, il cherche l'**EC/chef de mission** parmi les utilisateurs
   actifs (correspondance de nom) :
   - trouvé → mail de rappel à cet utilisateur **+ notification dans l'app** ;
   - pas trouvé → mail aux **admins** actifs.
3. Le mail type : « Dossier X : l'étape "…" est en attente depuis N jours.
   Merci de la traiter dans Orbit. »
4. Un flash résume : « N dossier(s) bloqué(s) depuis 7 j — M mail(s) envoyé(s). »

Dans la liste, ces dossiers ont une pastille d'attente **rouge** et le KPI
« en attente > 7 j » les compte.

---

## 9. Import Excel (reprendre une liste existante)

Bouton **Importer Excel** → page en 2 cartes :

### 9.1 Télécharger le modèle

**Télécharger le modèle .xlsx** fournit `Modele_Suivi_Nouveaux_Dossiers_JMH.xlsx` :
- feuille « SUIVI NOUVEAUX DOSSIERS » avec les **39 colonnes du cabinet**
  (en-têtes ligne 7, colonne A = « N° »), dont « Création dossier Pennylane »
  (l'ancien « Création Doss ACD ») ;
- feuille **LEGENDE** (types, règles OUI/NON, dates, X).

### 9.2 Préparer la liste

- Une ligne par dossier ; **NOM DOSSIER obligatoire**.
- Type : Création / Reprise / Revision (le pipeline s'adapte à l'import).
- PolyActe / Social : OUI ou NON.
- Cellules d'étapes :
  - une **date** (jj/mm/aaaa) = fait à cette date ;
  - **X** = fait sans date ;
  - un **texte libre** = fait sans date + ce texte devient la note de l'étape ;
  - vide = pas fait.
- Honoraires : valeur numérique (sinon ignorés et signalés).

### 9.3 Importer

1. Choisir le fichier `.xlsx` puis cliquer **Importer**.
2. Règles de lecture automatique :
   - feuille dont le nom contient « suivi » (hors « partis »), sinon la 1re ;
   - ligne d'en-têtes détectée dans les 20 premières lignes (colonne A = « N° ») ;
   - en-têtes tolérants (accents/casse/espaces), « Création Doss ACD » accepté
     et converti vers Pennylane ;
   - jusqu'à 2 500 lignes.
3. Rapport final : « X dossier(s) importé(s), Y ligne(s) ignorée(s) » + les
   anomalies (nom vide, honoraires non numériques…).

> L'import **crée** des dossiers : il ne fusionne pas avec l'existant. Évitez de
> réimporter deux fois la même liste (doublons).

---

## 10. Onglet « Dossiers partis »

Quand un client quitte le cabinet :

1. Onglet **Dossiers partis** → **Nouveau départ**.
2. Remplir : nom du dossier *, client, mail, téléphone, EC/chef de mission,
   établissement, collaborateur en charge, **cause du départ** (Résiliation,
   Radiation…), **date de départ**, commentaires.
3. Trois jalons de sortie (dates) :
   - **Mail déontologie reçu** ;
   - **Documents envoyés** (à l'ancien/confrère ou au client) ;
   - **Mail facturation**.
4. **Enregistrer**.

**Automatisme clé** : dès qu'une date est saisie dans **« Mail facturation »**,
Orbit envoie automatiquement au destinataire configuré
(`ONBOARDING_MAIL_FACTURATION`) le mail : « Le client X quitte le cabinet
(départ le …). Merci de stopper la facturation à compter de cette date et de
désactiver le dossier Pennylane. » Si le destinataire n'est pas configuré, un
avertissement s'affiche.

Dans le tableau des partis : KPI (total, départs du mois), cause, date de départ
et **3 pastilles de sortie** (enveloppe / colis / cash) qui s'allument quand
chaque jalon est daté (survol = date). Bouton **Éditer** pour mettre à jour ;
**Supprimer** (admin, avec confirmation) dans la fenêtre d'édition.

---

## 11. Récapitulatif des automatismes

| Déclencheur | Effet |
|---|---|
| Étape « Envoi LDM / facturation » cochée | Mail LDM & facturation au client |
| Étape « Mail identité collaborateurs » cochée | Mail interlocuteurs au client |
| Date « Mail facturation » saisie sur un départ | Mail stop facturation + désactivation Pennylane au service facturation |
| Bouton Rappels | Mails + notifications in-app pour les dossiers bloqués ≥ seuil |
| Création / changement de type | Pipeline d'étapes adapté (20 / 16 / 14 étapes) |

Chaque étape cochée garde **qui** l'a faite ; chaque mail (succès ou échec) est
**journalisé** avec destinataire, sujet, date et erreur éventuelle.

## 12. Checklist de prise en main

- [ ] Configurer Brevo + destinataire facturation + seuil de rappel (Réglages)
- [ ] Créer un premier dossier test et cocher une étape de chaque façon (date, X, Fait)
- [ ] Vérifier le mail auto « Envoi LDM / facturation » et le journal des mails
- [ ] Tester le bouton Rappels sur un dossier sans mouvement
- [ ] Télécharger le modèle, importer 2-3 lignes, vérifier le rapport
- [ ] Enregistrer un départ avec date « Mail facturation » et vérifier le mail