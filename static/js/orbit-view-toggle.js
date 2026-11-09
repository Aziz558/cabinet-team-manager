/* JMH Orbit — bascule « Cartes / Tableau » pour les vues en cartes.
   Convention :
     conteneur  [data-view-scope="idPage"]
     boutons    [data-view-mode="cards|table"]
     panneaux   [data-view-pane="cards|table"] (attribut hidden géré ici)
   La préférence est mémorisée par page (localStorage) et un événement
   « orbit:viewchange » est émis pour que la page reconstruise son tableau. */
(function () {
  function apply(scope, mode) {
    scope.querySelectorAll('[data-view-pane]').forEach(function (pane) {
      pane.hidden = pane.getAttribute('data-view-pane') !== mode;
    });
    scope.querySelectorAll('[data-view-mode]').forEach(function (btn) {
      var on = btn.getAttribute('data-view-mode') === mode;
      btn.classList.toggle('active', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    scope.dispatchEvent(new CustomEvent('orbit:viewchange', { detail: { mode: mode } }));
  }

  function init(scope) {
    var id = scope.getAttribute('data-view-scope');
    var saved = null;
    try { saved = localStorage.getItem('orbit-view-' + id); } catch (e) {}
    apply(scope, saved === 'table' ? 'table' : 'cards');
  }

  /* Délégation au niveau document : les boutons peuvent vivre hors du
     conteneur (en-tête de page, barre de filtres…). */
  document.addEventListener('click', function (ev) {
    var btn = ev.target.closest('[data-view-mode]');
    if (!btn) { return; }
    /* Repli : le bouton peut être rendu par page_head AVANT le conteneur
       (une seule vue par page), on retombe sur le premier scope. */
    var scope = btn.closest('[data-view-scope]') || document.querySelector('[data-view-scope]');
    if (!scope) { return; }
    var mode = btn.getAttribute('data-view-mode');
    try { localStorage.setItem('orbit-view-' + scope.getAttribute('data-view-scope'), mode); } catch (e) {}
    apply(scope, mode);
  });

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-view-scope]').forEach(init);
  });
})();
