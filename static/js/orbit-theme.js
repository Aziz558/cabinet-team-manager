/* JMH Orbit — socle thème unique.
   Chargé de façon synchrone dans <head> de toutes les pages (app + auth) pour
   appliquer le thème avant le premier rendu (aucun flash). Une seule source :
   corriger ici corrige partout. */
(function () {
  var KEY = 'theme';
  function read() {
    var t = null;
    try { t = localStorage.getItem(KEY); } catch (e) {}
    if (!t) { t = document.documentElement.getAttribute('data-theme') || 'dark'; }
    return (t === 'light' || t === 'dark') ? t : 'dark';
  }
  function persist(t) {
    try {
      localStorage.setItem(KEY, t);
      document.cookie = KEY + '=' + t + ';path=/;max-age=31536000;SameSite=Lax';
    } catch (e) {}
  }
  function paint(t) {
    var root = document.documentElement;
    root.setAttribute('data-theme', t);
    // Bootstrap 5.3 doit suivre le même mode, sinon ses composants (dropdowns,
    // inputs, close buttons) restent en clair sur fond sombre.
    root.setAttribute('data-bs-theme', t);
    window.ORBIT_THEME = t;
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) { meta.setAttribute('content', t === 'light' ? '#E5E0DA' : '#101010'); }
    var icon = document.getElementById('themeIcon');
    if (icon) { icon.className = t === 'light' ? 'bi bi-moon-fill' : 'bi bi-sun-fill'; }
    var auth = document.getElementById('authThemeToggle');
    if (auth) { auth.innerHTML = '<i class="bi ' + (t === 'light' ? 'bi-moon-stars-fill' : 'bi-sun-fill') + '"></i>'; }
    document.querySelectorAll('[data-theme-choice]').forEach(function (el) {
      el.classList.toggle('active', el.getAttribute('data-theme-choice') === t);
    });
    window.dispatchEvent(new CustomEvent('orbit:theme', { detail: t }));
  }

  var initial = read();
  persist(initial);
  paint(initial);

  window.setOrbitTheme = function (theme, persistIt, instant) {
    theme = (theme === 'light' || theme === 'dark') ? theme : 'dark';
    if (persistIt !== false) { persist(theme); }
    var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced || instant === true || !window.ORBIT_THEME_READY) { paint(theme); return; }
    var veil = document.getElementById('orbitThemeVeil');
    if (!veil) {
      veil = document.createElement('div');
      veil.id = 'orbitThemeVeil';
      veil.className = 'orbit-theme-veil';
      document.body.appendChild(veil);
    }
    veil.style.background = theme === 'light' ? '#E5E0DA' : '#101010';
    veil.classList.remove('orbit-theme-veil--out');
    void veil.offsetWidth;
    veil.classList.add('orbit-theme-veil--out');
    if (document.startViewTransition) { document.startViewTransition(function () { paint(theme); }); }
    else { paint(theme); }
  };
  window.toggleTheme = function () {
    window.setOrbitTheme(window.ORBIT_THEME === 'light' ? 'dark' : 'light', true);
  };
  window.addEventListener('load', function () { window.ORBIT_THEME_READY = true; });
})();