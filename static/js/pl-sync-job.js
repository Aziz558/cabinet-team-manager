/* Synchro TVA Pennylane en arrière-plan.
 *
 * Le serveur répond immédiatement (202) puis l'UI interroge
 * /checklist/pl_sync_status toutes les 2 s. Évite les « Unexpected end of
 * JSON input » quand le proxy coupe une requête qui dure plusieurs minutes.
 * Aucune valeur de cookie ne transite ici.
 */
(function () {
    'use strict';

    /* Une réponse vide ou non-JSON doit produire un message lisible, pas une
       exception « Unexpected end of JSON input » sans contexte. */
    function jsonOuErreur(r) {
        return r.text().then(function (txt) {
            if (!txt || !txt.trim()) {
                throw new Error('Réponse vide du serveur (HTTP ' + r.status +
                    ') : la requête a été coupée. Relance la vérification.');
            }
            try {
                return JSON.parse(txt);
            } catch (e) {
                throw new Error('Réponse illisible du serveur (HTTP ' + r.status + ') : ' +
                    txt.slice(0, 80));
            }
        });
    }

    function attendre(onTick, onFin) {
        var tours = 0;
        function poll() {
            fetch('/checklist/pl_sync_status', { cache: 'no-store' })
                .then(jsonOuErreur)
                .then(function (s) {
                    if (s.running) {
                        tours++;
                        if (tours > 180) {
                            onFin({ ok: false,
                                message: 'La synchro dépasse 6 minutes. Consulte le bandeau ' +
                                         '« Dernier passage » sur la page Intégration.' });
                            return;
                        }
                        if (onTick) { onTick(s); }
                        setTimeout(poll, 2000);
                        return;
                    }
                    onFin(s.resultat || {
                        ok: false,
                        message: s.message || 'Aucun bilan disponible — relance la vérification.'
                    });
                })
                .catch(function (e) {
                    /* Un polling raté (instance qui se réveille) ne doit pas
                       abandonner : on réessaie quelques fois. */
                    tours++;
                    if (tours > 180) {
                        onFin({ ok: false, message: 'Suivi interrompu : ' + e.message });
                        return;
                    }
                    setTimeout(poll, 3000);
                });
        }
        poll();
    }

    /* url : endpoint qui démarre le job. onTick(progression), onFin(bilan). */
    function lancer(url, onTick, onFin) {
        return fetch(url, { method: 'POST' })
            .then(jsonOuErreur)
            .then(function (d) {
                if (d.en_cours) { attendre(onTick, onFin); return; }
                onFin(d);   // réponse directe (ex. session non configurée)
            });
    }

    window.plSyncJob = { lancer: lancer, jsonOuErreur: jsonOuErreur };
})();
