(function () {
    'use strict';

    var fab = document.getElementById('assistantFab');
    var panel = document.getElementById('assistantPanel');
    var closeBtn = document.getElementById('assistantClose');
    var form = document.getElementById('assistantForm');
    var input = document.getElementById('assistantInput');
    var sendBtn = document.getElementById('assistantSend');
    var box = document.getElementById('assistantMessages');
    if (!fab || !panel || !form) return;

    var historique = [];
    var bienvenueAffichee = false;

    function ajouterMessage(classe, texte) {
        var div = document.createElement('div');
        div.className = 'ap-msg ' + classe;
        div.textContent = texte;  // textContent : jamais de HTML venant du LLM
        box.appendChild(div);
        box.scrollTop = box.scrollHeight;
        return div;
    }

    function ajouterIndicateurFrappe() {
        var d = document.createElement('div');
        d.className = 'ap-typing';
        d.innerHTML = '<i></i><i></i><i></i>';
        box.appendChild(d);
        box.scrollTop = box.scrollHeight;
        return d;
    }

    function masquerSuggestions() {
        var s = document.getElementById('assistantSugg');
        if (s) { s.classList.add('hidden'); }
    }

    function envoyerTexte(texte) {
        if (!input || !texte) return;
        input.value = texte;
        if (typeof form.requestSubmit === 'function') { form.requestSubmit(); }
        else { form.dispatchEvent(new Event('submit', {cancelable: true})); }
    }

    function ajouterBrouillon(brouillon) {
        var card = document.createElement('div');
        card.className = 'ap-draft';

        var to = document.createElement('div');
        to.className = 'ap-draft-to';
        to.textContent = 'Email à : ' + brouillon.to_nom;

        var subj = document.createElement('div');
        subj.className = 'ap-draft-subject';
        subj.textContent = 'Objet : ' + brouillon.subject;

        var body = document.createElement('div');
        body.className = 'ap-draft-body';
        body.textContent = brouillon.body;

        var actions = document.createElement('div');
        actions.className = 'ap-draft-actions';

        var ok = document.createElement('button');
        ok.type = 'button';
        ok.textContent = 'Confirmer l\u2019envoi';

        var annuler = document.createElement('button');
        annuler.type = 'button';
        annuler.className = 'secondary';
        annuler.textContent = 'Annuler';

        ok.addEventListener('click', function () {
            ok.disabled = true;
            annuler.disabled = true;
            fetch('/api/assistant/envoyer_email', {
                method: 'POST',
                credentials: 'same-origin',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    to_user_id: brouillon.to_user_id,
                    subject: brouillon.subject,
                    body: brouillon.body
                })
            }).then(function (r) { return r.json().then(function (j) { return {status: r.status, j: j}; }); })
              .then(function (res) {
                  if (res.j && res.j.ok) {
                      card.remove();
                      ajouterMessage('assistant', res.j.message || 'Email envoyé.');
                  } else {
                      ok.disabled = false;
                      annuler.disabled = false;
                      ajouterMessage('error', (res.j && res.j.error) || 'Échec de l\u2019envoi.');
                  }
              })
              .catch(function () {
                  ok.disabled = false;
                  annuler.disabled = false;
                  ajouterMessage('error', 'Erreur réseau pendant l\u2019envoi.');
              });
        });

        annuler.addEventListener('click', function () {
            card.remove();
            ajouterMessage('assistant', 'Envoi annulé.');
        });

        actions.appendChild(ok);
        actions.appendChild(annuler);
        card.appendChild(to);
        card.appendChild(subj);
        card.appendChild(body);
        card.appendChild(actions);
        box.appendChild(card);
        box.scrollTop = box.scrollHeight;
    }

    function ajouterRappel(rappel) {
        var card = document.createElement('div');
        card.className = 'ap-draft';

        var titre = document.createElement('div');
        titre.className = 'ap-draft-subject';
        titre.textContent = 'Nouveau rappel : ' + rappel.titre;

        var detail = document.createElement('div');
        detail.className = 'ap-draft-to';
        detail.textContent = 'Échéance le ' + rappel.date_echeance;

        var msg = document.createElement('div');
        msg.className = 'ap-draft-body';
        msg.textContent = rappel.message;

        var actions = document.createElement('div');
        actions.className = 'ap-draft-actions';

        var ok = document.createElement('button');
        ok.type = 'button';
        ok.textContent = 'Créer le rappel';

        var annuler = document.createElement('button');
        annuler.type = 'button';
        annuler.className = 'secondary';
        annuler.textContent = 'Annuler';

        ok.addEventListener('click', function () {
            ok.disabled = true;
            annuler.disabled = true;
            fetch('/api/assistant/creer_rappel', {
                method: 'POST',
                credentials: 'same-origin',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    titre: rappel.titre,
                    message: rappel.message,
                    date_echeance: rappel.date_echeance
                })
            }).then(function (r) { return r.json().then(function (j) { return {status: r.status, j: j}; }); })
              .then(function (res) {
                  if (res.j && res.j.ok) {
                      card.remove();
                      ajouterMessage('assistant', res.j.message || 'Rappel créé.');
                  } else {
                      ok.disabled = false;
                      annuler.disabled = false;
                      ajouterMessage('error', (res.j && res.j.error) || 'Rappel refusé.');
                  }
              })
              .catch(function () {
                  ok.disabled = false;
                  annuler.disabled = false;
                  ajouterMessage('error', 'Erreur réseau pendant la création du rappel.');
              });
        });

        annuler.addEventListener('click', function () {
            card.remove();
            ajouterMessage('assistant', 'Rappel annulé.');
        });

        actions.appendChild(ok);
        actions.appendChild(annuler);
        card.appendChild(titre);
        card.appendChild(detail);
        card.appendChild(msg);
        card.appendChild(actions);
        box.appendChild(card);
        box.scrollTop = box.scrollHeight;
    }

    function ajouterTache(tache) {
        var card = document.createElement('div');
        card.className = 'ap-draft';

        var titre = document.createElement('div');
        titre.className = 'ap-draft-subject';
        titre.textContent = 'Nouvelle tâche : ' + tache.titre;

        var detail = document.createElement('div');
        detail.className = 'ap-draft-to';
        detail.textContent = 'Assignée à ' + tache.assigne_nom + ' · échéance ' + tache.date_echeance + ' · priorité ' + tache.priorite;

        var desc = document.createElement('div');
        desc.className = 'ap-draft-body';
        desc.textContent = tache.description || '';

        var actions = document.createElement('div');
        actions.className = 'ap-draft-actions';

        var ok = document.createElement('button');
        ok.type = 'button';
        ok.textContent = 'Créer la tâche';

        var annuler = document.createElement('button');
        annuler.type = 'button';
        annuler.className = 'secondary';
        annuler.textContent = 'Annuler';

        ok.addEventListener('click', function () {
            ok.disabled = true;
            annuler.disabled = true;
            fetch('/api/assistant/creer_tache', {
                method: 'POST',
                credentials: 'same-origin',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    titre: tache.titre,
                    description: tache.description,
                    assigne_a_id: tache.assigne_a_id,
                    priorite: tache.priorite,
                    date_echeance: tache.date_echeance
                })
            }).then(function (r) { return r.json().then(function (j) { return {status: r.status, j: j}; }); })
              .then(function (res) {
                  if (res.j && res.j.ok) {
                      card.remove();
                      ajouterMessage('assistant', res.j.message || 'Tâche créée.');
                  } else {
                      ok.disabled = false;
                      annuler.disabled = false;
                      ajouterMessage('error', (res.j && res.j.error) || 'Création refusée.');
                  }
              })
              .catch(function () {
                  ok.disabled = false;
                  annuler.disabled = false;
                  ajouterMessage('error', 'Erreur réseau pendant la création.');
              });
        });

        annuler.addEventListener('click', function () {
            card.remove();
            ajouterMessage('assistant', 'Création annulée.');
        });

        actions.appendChild(ok);
        actions.appendChild(annuler);
        card.appendChild(titre);
        card.appendChild(detail);
        if (tache.description) card.appendChild(desc);
        card.appendChild(actions);
        box.appendChild(card);
        box.scrollTop = box.scrollHeight;
    }

    /* Carte générique pour les actions in-app (statut, suppression, étape onboarding).
       Même contrat que les autres cartes : confirmation explicite -> revalidation serveur. */
    function ajouterCarteAction(opts) {
        var card = document.createElement('div');
        card.className = 'ap-draft' + (opts.danger ? ' ap-draft-danger' : '');

        var titre = document.createElement('div');
        titre.className = 'ap-draft-subject';
        titre.textContent = opts.titre;

        var detail = document.createElement('div');
        detail.className = 'ap-draft-to';
        detail.textContent = opts.detail;

        card.appendChild(titre);
        card.appendChild(detail);
        if (opts.corps) {
            var corps = document.createElement('div');
            corps.className = 'ap-draft-body';
            corps.textContent = opts.corps;
            card.appendChild(corps);
        }

        var actions = document.createElement('div');
        actions.className = 'ap-draft-actions';

        var ok = document.createElement('button');
        ok.type = 'button';
        ok.textContent = opts.confirmLabel;

        var annuler = document.createElement('button');
        annuler.type = 'button';
        annuler.className = 'secondary';
        annuler.textContent = 'Annuler';

        ok.addEventListener('click', function () {
            ok.disabled = true;
            annuler.disabled = true;
            fetch(opts.endpoint, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(opts.payload)
            }).then(function (r) { return r.json().then(function (j) { return {status: r.status, j: j}; }); })
              .then(function (res) {
                  if (res.j && res.j.ok) {
                      card.remove();
                      ajouterMessage('assistant', res.j.message || 'Action effectuée.');
                  } else {
                      ok.disabled = false;
                      annuler.disabled = false;
                      ajouterMessage('error', (res.j && res.j.error) || 'Action refusée.');
                  }
              })
              .catch(function () {
                  ok.disabled = false;
                  annuler.disabled = false;
                  ajouterMessage('error', 'Erreur réseau pendant l\u2019action.');
              });
        });

        annuler.addEventListener('click', function () {
            card.remove();
            ajouterMessage('assistant', opts.annuleLabel || 'Action annulée.');
        });

        actions.appendChild(ok);
        actions.appendChild(annuler);
        card.appendChild(actions);
        box.appendChild(card);
        box.scrollTop = box.scrollHeight;
    }

    function ajouterCarteStatut(p) {
        ajouterCarteAction({
            titre: 'Changer le statut : ' + p.titre,
            detail: p.ancien_statut.replace(/_/g, ' ') + ' → ' + p.statut.replace(/_/g, ' '),
            confirmLabel: 'Confirmer le changement',
            endpoint: '/api/assistant/changer_statut',
            payload: {tache_id: p.tache_id, statut: p.statut},
            annuleLabel: 'Changement annulé.'
        });
    }

    function ajouterCarteStatutLot(p) {
        var titres = p.lignes.map(function (l) { return '• #' + l.id + ' ' + l.titre; });
        if (titres.length > 12) titres = titres.slice(0, 12).concat(['… et ' + (titres.length - 12) + ' autre(s)']);
        ajouterCarteAction({
            titre: 'Passer ' + p.nb + ' tâche(s) à « ' + p.statut.replace(/_/g, ' ') + ' »',
            detail: 'Changement en lot — chaque tâche garde ses effets habituels (checklist, notifications).',
            corps: titres.join(String.fromCharCode(10)),
            confirmLabel: 'Confirmer le lot',
            endpoint: '/api/assistant/statut_lot',
            payload: {tache_ids: p.tache_ids, statut: p.statut},
            annuleLabel: 'Lot annulé.'
        });
    }

    function ajouterCarteSuppression(p) {
        ajouterCarteAction({
            titre: 'Supprimer le dossier ' + p.numero,
            detail: p.intitule + ' · ' + p.nb_taches + ' tâche(s) liée(s)',
            corps: 'Action irréversible : le dossier et toutes ses données liées (tâches, checklist, notifications, éléments Pennylane) seront définitivement effacés.',
            confirmLabel: 'Supprimer définitivement',
            endpoint: '/api/assistant/supprimer_dossier',
            payload: {dossier_id: p.dossier_id},
            danger: true,
            annuleLabel: 'Suppression annulée.'
        });
    }

    function ajouterCarteOnbEtape(p) {
        ajouterCarteAction({
            titre: (p.fait ? 'Marquer faite : ' : 'Remettre à faire : ') + p.label,
            detail: p.nom_dossier + (p.deja_fait ? ' · déjà faite actuellement' : ''),
            corps: p.fait ? 'L\u2019étape sera datée du jour et l\u2019email configuré pour cette étape sera envoyé.' : 'La date de l\u2019étape sera effacée.',
            confirmLabel: p.fait ? 'Marquer l\u2019étape faite' : 'Remettre l\u2019étape à faire',
            endpoint: '/api/assistant/onb_etape',
            payload: {dossier_id: p.dossier_id, code: p.code, fait: p.fait},
            annuleLabel: 'Modification annulée.'
        });
    }

    // Résumé du matin : une fois par jour et par navigateur, sans appel LLM.
    function afficherResumeDuJour() {
        var cle = 'assistantResume:' + new Date().toISOString().slice(0, 10);
        try { if (localStorage.getItem(cle)) return; } catch (e) { /* navigation privée */ }
        fetch('/api/assistant/resume', {credentials: 'same-origin'})
            .then(function (r) { return r.json(); })
            .then(function (j) {
                if (!j || !j.ok || !j.resume) return;
                var r = j.resume;
                var lignes = [];
                lignes.push('Résumé du jour : ' + r.nb_du_jour + ' échéance(s) aujourd\u2019hui, '
                    + r.nb_demain + ' demain, ' + r.nb_en_retard + ' en retard.');
                r.en_retard.slice(0, 5).forEach(function (t) {
                    lignes.push('• En retard : ' + t.titre + ' (' + t.echeance + ')');
                });
                r.du_jour.slice(0, 5).forEach(function (t) {
                    lignes.push('• Aujourd\u2019hui : ' + t.titre);
                });
                ajouterMessage('assistant', lignes.join(String.fromCharCode(10)));
                try { localStorage.setItem(cle, '1'); } catch (e) { /* ignore */ }
            })
            .catch(function () { /* résumé facultatif : silencieux */ });
    }

    function ouvrir() {
        panel.classList.add('open');
        fab.classList.add('is-open');
        fab.setAttribute('aria-expanded', 'true');
        if (!bienvenueAffichee) {
            bienvenueAffichee = true;
            ajouterMessage('assistant', 'Bonjour, je suis ASTRO, votre assistant JMH Orbit. Je connais vos dossiers, vos échéances et le suivi des nouveaux dossiers. Je peux agir après votre confirmation (tâches, statuts, rappels, étapes) et je retiens ce que vous m\u2019apprenez : mémoire du cabinet partagée avec l\u2019équipe + votre mémoire personnelle. Que souhaitez-vous ?');
            afficherResumeDuJour();
        }
        input.focus();
    }

    function fermer() {
        panel.classList.remove('open');
        fab.classList.remove('is-open');
        fab.setAttribute('aria-expanded', 'false');
    }

    /* Entrée envoie, Maj+Entrée ajoute une ligne (textarea). */
    if (input) {
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                if (typeof form.requestSubmit === 'function') { form.requestSubmit(); }
                else { form.dispatchEvent(new Event('submit', {cancelable: true})); }
            }
        });
        input.addEventListener('input', function () {
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 96) + 'px';
        });
    }

    /* Suggestions de départ : un clic remplit et envoie. */
    var sugg = document.getElementById('assistantSugg');
    if (sugg) {
        sugg.addEventListener('click', function (e) {
            var b = e.target.closest('button[data-q]');
            if (b) { envoyerTexte(b.getAttribute('data-q')); }
        });
    }

    /* Diagnostic : dit pourquoi l'assistant ne répond pas (clé, modèle, panne). */
    var diag = document.getElementById('assistantDiag');
    if (diag) {
        diag.addEventListener('click', function () {
            diag.disabled = true;
            ajouterMessage('assistant', 'Diagnostic en cours...');
            fetch('/api/assistant/sante?probe=1', {credentials: 'same-origin'})
                .then(function (r) { return r.json(); })
                .then(function (j) {
                    var lignes = [j.etat || 'Etat inconnu.'];
                    (j.providers || []).forEach(function (p) {
                        lignes.push('- ' + p.fournisseur + ' (' + p.role + ') : '
                            + (p.configure ? 'cle OK' : 'non configure')
                            + (p.modele ? ' | modele ' + p.modele : '')
                            + (p.ok === true ? ' | repond' : (p.ok === false ? ' | NE REPOND PAS' : ''))
                            + (p.erreur ? ' | ' + p.erreur : ''));
                    });
                    ajouterMessage('assistant', lignes.join(String.fromCharCode(10)));
                })
                .catch(function () { ajouterMessage('error', 'Diagnostic impossible (reseau).'); })
                .then(function () { diag.disabled = false; });
        });
    }

    fab.addEventListener('click', function () {
        if (panel.classList.contains('open')) fermer(); else ouvrir();
    });
    closeBtn.addEventListener('click', fermer);

    form.addEventListener('submit', function (e) {
        e.preventDefault();
        var message = (input.value || '').trim();
        if (!message) return;
        input.value = '';
        ajouterMessage('user', message);
        sendBtn.disabled = true;
        var attente = ajouterMessage('assistant', '…');

        fetch('/api/assistant/message', {
            method: 'POST',
            credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({message: message, historique: historique})
        }).then(function (r) { return r.json().then(function (j) { return {status: r.status, j: j}; }); })
          .then(function (res) {
              attente.remove();
              if (res.j && res.j.ok) {
                  masquerSuggestions();
                  var reponse = res.j.reponse || '';
                  historique.push({role: 'user', content: message});
                  historique.push({role: 'assistant', content: reponse});
                  if (historique.length > 10) historique = historique.slice(-10);
                  ajouterMessage('assistant', reponse || '(réponse vide)');
                  if (res.j.brouillon) ajouterBrouillon(res.j.brouillon);
                  if (res.j.tache) ajouterTache(res.j.tache);
                  if (res.j.rappel) ajouterRappel(res.j.rappel);
                  if (res.j.statut) ajouterCarteStatut(res.j.statut);
                  if (res.j.statut_lot) ajouterCarteStatutLot(res.j.statut_lot);
                  if (res.j.suppression) ajouterCarteSuppression(res.j.suppression);
                  if (res.j.onb_etape) ajouterCarteOnbEtape(res.j.onb_etape);
                  // Apprentissage visible : ce que le LLM a réellement stocké (hors voie
                  // rapide, dont la réponse mentionne déjà la prise de note).
                  if (res.j.source !== 'regles' && res.j.memoires && res.j.memoires.length) {
                      res.j.memoires.forEach(function (m) {
                          if (m.info !== 'cree') return;
                          ajouterMessage('assistant', 'J\u2019ai retenu (' + (m.portee === 'cabinet' ? 'mémoire du cabinet, partagée' : 'mémoire personnelle') + ') : « ' + m.contenu + ' »');
                      });
                  }
              } else {
                  ajouterMessage('error', (res.j && res.j.error) || 'Erreur de l\u2019assistant.');
              }
          })
          .catch(function () {
              attente.remove();
              ajouterMessage('error', 'Erreur réseau. Réessayez.');
          })
          .then(function () { sendBtn.disabled = false; input.focus(); });
    });
})();
