/* ============================================================
   LOGIN FX — spawn aléatoire d'étoiles filantes, satellites
   et astronaute, uniquement quand la scène spatiale est active.
   Décor : aucun clic capté, se nettoie tout seul.
   ============================================================ */
(function () {
    'use strict';

    var html = document.documentElement;
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) { return; }

    var layer = document.createElement('div');
    layer.className = 'login-fx';
    layer.setAttribute('aria-hidden', 'true');
    document.body.appendChild(layer);

    function rnd(a, b) { return a + Math.random() * (b - a); }
    function pick(arr) { return arr[Math.floor(Math.random() * arr.length)]; }
    function vw() { return window.innerWidth; }
    function vh() { return window.innerHeight; }

    /* Trajectoires : départ et arrivée hors écran pour éviter les apparitions visibles. */
    function edgeRoute() {
        var w = vw(), h = vh();
        var side = pick(['left', 'right', 'top']);
        if (side === 'left') { return { x0: -80, y0: rnd(0, h), x1: w + 80, y1: rnd(0, h) }; }
        if (side === 'right') { return { x0: w + 80, y0: rnd(0, h), x1: -80, y1: rnd(0, h) }; }
        return { x0: rnd(0, w), y0: -60, x1: rnd(0, w), y1: h + 60 };
    }

    function setVars(el, obj) {
        Object.keys(obj).forEach(function (k) { el.style.setProperty(k, obj[k]); });
    }

    function spawnShooting() {
        var el = document.createElement('div');
        el.className = 'login-fx-shooting';
        var w = vw(), h = vh();
        var x0 = rnd(0, w * 0.8), y0 = rnd(0, h * 0.5);
        var len = rnd(260, 420);
        var ang = rnd(18, 34);
        var rad = ang * Math.PI / 180;
        setVars(el, {
            '--x0': x0 + 'px', '--y0': y0 + 'px',
            '--x1': (x0 + Math.cos(rad) * len) + 'px', '--y1': (y0 + Math.sin(rad) * len) + 'px',
            '--ang': ang + 'deg', '--dur': rnd(0.9, 1.7).toFixed(2) + 's'
        });
        layer.appendChild(el);
        setTimeout(function () { el.remove(); }, 2200);
    }

    function spawnSatellite() {
        var el = document.createElement('div');
        el.className = 'login-fx-sat';
        el.innerHTML = '<span class="sat-panel l"></span><span class="sat-body"></span>' +
                       '<span class="sat-panel r"></span><span class="sat-blink"></span>';
        var r = edgeRoute();
        var dur = rnd(26, 40);
        setVars(el, { '--x0': r.x0 + 'px', '--y0': r.y0 + 'px', '--x1': r.x1 + 'px', '--y1': r.y1 + 'px', '--dur': dur.toFixed(1) + 's' });
        layer.appendChild(el);
        setTimeout(function () { el.remove(); }, dur * 1000 + 200);
    }

    function spawnAstronaut() {
        var el = document.createElement('div');
        el.className = 'login-fx-astro';
        el.innerHTML = '<span class="astro-tether"></span>' +
                       '<span class="astro-arm l"></span><span class="astro-arm r"></span>' +
                       '<span class="astro-body"></span><span class="astro-helmet"></span>' +
                       '<span class="astro-visor"></span>';
        var w = vw(), h = vh();
        var x0 = rnd(-60, w * 0.25), y0 = rnd(h * 0.2, h * 0.8);
        var dur = rnd(40, 58);
        setVars(el, {
            '--x0': x0 + 'px', '--y0': y0 + 'px',
            '--x1': (w * rnd(0.7, 1) + 80) + 'px', '--y1': (y0 + rnd(-h * 0.25, h * 0.25)) + 'px',
            '--rot0': rnd(-25, 25).toFixed(0) + 'deg', '--rot1': rnd(-60, 60).toFixed(0) + 'deg',
            '--dur': dur.toFixed(1) + 's'
        });
        layer.appendChild(el);
        setTimeout(function () { el.remove(); }, dur * 1000 + 200);
    }

    /* Boucle aléatoire : une étoile filante toutes les 4–9 s, un satellite
       toutes les 18–30 s, un astronaute toutes les 40–70 s. */
    function schedule(fn, minS, maxS, firstS) {
        function next(delay) {
            setTimeout(function () {
                if (html.classList.contains('orbit-space-active') && !document.hidden) { fn(); }
                next(rnd(minS, maxS) * 1000);
            }, delay);
        }
        next(firstS * 1000);
    }

    schedule(spawnShooting, 4, 9, 2.5);
    schedule(spawnSatellite, 18, 30, 6);
    schedule(spawnAstronaut, 40, 70, 14);
})();
