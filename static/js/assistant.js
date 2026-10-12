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

    function ouvrir() {
        panel.classList.add('open');
        if (!bienvenueAffichee) {
            bienvenueAffichee = true;
            ajouterMessage('assistant', 'Bonjour, je peux vous rappeler vos tâches en retard, vos prochaines échéances, vos analyses, ou préparer un email. Que souhaitez-vous ?');
        }
        input.focus();
    }

    function fermer() {
        panel.classList.remove('open');
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
                  var reponse = res.j.reponse || '';
                  historique.push({role: 'user', content: message});
                  historique.push({role: 'assistant', content: reponse});
                  if (historique.length > 10) historique = historique.slice(-10);
                  ajouterMessage('assistant', reponse || '(réponse vide)');
                  if (res.j.brouillon) ajouterBrouillon(res.j.brouillon);
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
