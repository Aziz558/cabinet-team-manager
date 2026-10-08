/* ============================================================
   ORBIT DOCKING — scène spatiale 3D du login (V1)
   États : boot -> far -> approach -> docked (+ static, + warp)
   Progressif : si non armé, reduce, pas de WebGL, échec d'import
   Three ou fps < 35 -> on désarme proprement = login classique.
   ============================================================ */
(function () {
    'use strict';

    var html = document.documentElement;
    var body = document.body;
    var canvas = document.getElementById('orbitSpace');
    var planetBtn = document.getElementById('orbitPlanetBtn');
    var backBtn = document.getElementById('orbitBackBtn');
    var flashEl = document.getElementById('orbitFlash');
    var form = document.getElementById('loginForm');

    function disarm() {
        html.classList.remove('orbit-space-armed');
        html.classList.remove('orbit-space-active');
        if (body) {
            body.classList.remove('orbit-state-far');
            body.classList.remove('orbit-state-approach');
            body.classList.remove('orbit-state-docked');
            body.classList.remove('orbit-state-static');
        }
        if (canvas) { canvas.style.display = 'none'; }
        if (planetBtn) { planetBtn.hidden = true; }
        if (backBtn) { backBtn.hidden = true; }
    }

    /* Non armé (reduced-motion, pas de WebGL, ou inline head absent) :
       on ne touche à rien, le login classique s'affiche tel quel. */
    if (!html.classList.contains('orbit-space-armed')) { return; }
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) { disarm(); return; }
    if (!canvas || !planetBtn || !backBtn || !form) { disarm(); return; }

    // URL du Three local : passée par le template (url_for) via data-three,
    // repli sur le chemin statique si la page a été rendue sans attribut.
    var threeScript = document.currentScript;
    var THREE_URL = (threeScript && threeScript.getAttribute('data-three')) || '/static/js/vendor/three.module.min.js';
    var ALL_STATES = ['far', 'approach', 'docked', 'static'];
    var state = 'boot';

    function setState(next) {
        state = next;
        ALL_STATES.forEach(function (s) { body.classList.toggle('orbit-state-' + s, s === next); });
        planetBtn.hidden = (next !== 'far');
        backBtn.hidden = (next !== 'docked');
    }

    /* Import ESM de Three.js (fichier local, aucun CDN à l'exécution).
       Échec (réseau, parse) -> login classique, aucun dégât. */
    import(THREE_URL).then(function (mod) {
        try { boot(mod); } catch (e) { fail(e); }
    }).catch(function (err) { fail(err); });

    function fail(err) {
        if (window.console && console.warn) { console.warn('[orbit-space]', err); }
        dispose();
        disarm();
    }

    /* ---------- Scène ---------- */
    var THREE, renderer, scene, camera, clock;
    var starGeo, starLine, lineGeo;
    var planetGroup, jmhPlanet, moon, halo;
    var projV = null;
    var raf = 0, running = false;
    var cam = { z: 95, tx: 0, ty: 0 };
    var fly = null;
    var warp = 0, warpActive = false;
    var starBaseSpeed = 1.6;
    var fpsFrames = 0, fpsTime = 0, fpsChecked = false;
    var moonT = 0;
    var isMobile = window.matchMedia('(max-width: 991.98px)').matches;
    var FAR_Z = 95;
    var DOCK_Z = isMobile ? 36 : 30;

    function boot(mod) {
        THREE = mod;
        var dpr = Math.min(window.devicePixelRatio || 1, 1.75);
        renderer = new THREE.WebGLRenderer({
            canvas: canvas,
            antialias: dpr < 1.5,
            alpha: false,
            powerPreference: 'high-performance'
        });
        renderer.setPixelRatio(dpr);
        renderer.setSize(window.innerWidth, window.innerHeight, false);
        renderer.setClearColor(0x05060c, 1);

        scene = new THREE.Scene();
        scene.fog = new THREE.FogExp2(0x05060c, 0.0032);
        camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 700);
        camera.position.set(0, 0, FAR_Z);
        clock = new THREE.Clock();
        projV = new THREE.Vector3();

        buildLights();
        buildStars();
        buildNebula();
        buildPlanets();

        window.addEventListener('resize', onResize);
        bindEvents();

        // 1re frame rendue HORS-ligne avant d'activer (aucun écran noir)
        renderer.render(scene, camera);

        // Cinématique seulement si l'armement tient encore ; sinon la scène
        // reste en fond derrière le login classique (état static).
        var cinematic = html.classList.contains('orbit-space-armed');
        html.classList.remove('orbit-space-armed');
        html.classList.add('orbit-space-active');
        setState(cinematic ? 'far' : 'static');

        running = true;
        loop();
    }

    function glowTexture(inner, outer) {
        var c = document.createElement('canvas');
        c.width = c.height = 128;
        var g = c.getContext('2d');
        var rg = g.createRadialGradient(64, 64, 0, 64, 64, 64);
        rg.addColorStop(0, inner);
        rg.addColorStop(1, outer);
        g.fillStyle = rg;
        g.fillRect(0, 0, 128, 128);
        return new THREE.CanvasTexture(c);
    }

    function buildLights() {
        scene.add(new THREE.AmbientLight(0xbfd0e8, 0.55));
        var sun = new THREE.DirectionalLight(0xfff2df, 1.6);
        sun.position.set(40, 26, 60);
        scene.add(sun);
        var rim = new THREE.DirectionalLight(0x4477ff, 0.35);
        rim.position.set(-60, -20, -40);
        scene.add(rim);
    }

    function buildStars() {
        var count = isMobile ? 260 : 460;
        var pos = new Float32Array(count * 3);
        var colors = new Float32Array(count * 3);
        var palette = [[1, 1, 1], [0.72, 0.8, 1], [1, 0.82, 0.6]];
        for (var i = 0; i < count; i++) {
            pos[i * 3] = (Math.random() - 0.5) * 320;
            pos[i * 3 + 1] = (Math.random() - 0.5) * 200;
            pos[i * 3 + 2] = -240 + Math.random() * 300;   // -240 .. 60
            var c = palette[(Math.random() * 3) | 0];
            colors[i * 3] = c[0]; colors[i * 3 + 1] = c[1]; colors[i * 3 + 2] = c[2];
        }
        starGeo = new THREE.BufferGeometry();
        starGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
        starGeo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
        scene.add(new THREE.Points(starGeo, new THREE.PointsMaterial({
            size: isMobile ? 1.1 : 0.9,
            sizeAttenuation: true,
            vertexColors: true,
            transparent: true,
            opacity: 0.95,
            depthWrite: false
        })));

        // Traînées du warp : invisibles tant que warp === 0
        lineGeo = new THREE.BufferGeometry();
        lineGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(count * 6), 3));
        starLine = new THREE.LineSegments(lineGeo, new THREE.LineBasicMaterial({
            color: 0xbfd7ff, transparent: true, opacity: 0.85, depthWrite: false
        }));
        starLine.visible = false;
        scene.add(starLine);
    }

    function buildNebula() {
        var defs = [
            { p: [-90, 40, -200], s: 320, c: 'rgba(255,140,0,0.17)' },
            { p: [110, -50, -210], s: 360, c: 'rgba(47,111,237,0.16)' },
            { p: [10, 90, -220], s: 280, c: 'rgba(155,93,229,0.13)' }
        ];
        defs.forEach(function (d) {
            var sp = new THREE.Sprite(new THREE.SpriteMaterial({
                map: glowTexture(d.c, 'rgba(0,0,0,0)'),
                blending: THREE.AdditiveBlending,
                depthWrite: false,
                transparent: true
            }));
            sp.position.set(d.p[0], d.p[1], d.p[2]);
            sp.scale.set(d.s, d.s, 1);
            scene.add(sp);
        });
    }

    function planetTexture(base, dark, light, seed) {
        var c = document.createElement('canvas');
        c.width = 512; c.height = 256;
        var g = c.getContext('2d');
        var grad = g.createLinearGradient(0, 0, 0, 256);
        grad.addColorStop(0, light);
        grad.addColorStop(0.5, base);
        grad.addColorStop(1, dark);
        g.fillStyle = grad;
        g.fillRect(0, 0, 512, 256);
        var rnd = (function (s) {
            return function () { s = (s * 16807) % 2147483647; return (s - 1) / 2147483646; };
        })(seed);
        var b, y, h;
        for (b = 0; b < 16; b++) {                       // bandes atmosphériques
            g.fillStyle = (b % 2 ? 'rgba(255,255,255,' : 'rgba(0,0,0,') + (0.03 + rnd() * 0.06) + ')';
            y = rnd() * 256; h = 3 + rnd() * 16;
            g.fillRect(0, y, 512, h);
            if (y + h > 256) { g.fillRect(0, y - 256, 512, h); }
        }
        for (b = 0; b < 70; b++) {                       // taches / cratères
            g.fillStyle = (rnd() > 0.5 ? 'rgba(255,255,255,' : 'rgba(0,0,0,') + (0.04 + rnd() * 0.08) + ')';
            g.beginPath();
            g.arc(rnd() * 512, rnd() * 256, 2 + rnd() * 14, 0, Math.PI * 2);
            g.fill();
        }
        var tex = new THREE.CanvasTexture(c);
        if (THREE.SRGBColorSpace) { tex.colorSpace = THREE.SRGBColorSpace; }
        return tex;
    }

    function buildPlanets() {
        planetGroup = new THREE.Group();
        scene.add(planetGroup);

        // Planète JMH (orange signature) + anneau + halo + lune
        jmhPlanet = new THREE.Mesh(
            new THREE.SphereGeometry(6, 48, 48),
            new THREE.MeshStandardMaterial({ map: planetTexture('#ff8c00', '#8a3f00', '#ffb060', 7), roughness: 0.92, metalness: 0.02 })
        );
        planetGroup.add(jmhPlanet);

        var ring = new THREE.Mesh(
            new THREE.RingGeometry(8.6, 12.4, 72),
            new THREE.MeshBasicMaterial({ color: 0xffa149, transparent: true, opacity: 0.45, side: THREE.DoubleSide, depthWrite: false })
        );
        ring.rotation.x = -Math.PI / 2.35;
        ring.rotation.z = 0.28;
        planetGroup.add(ring);

        halo = new THREE.Sprite(new THREE.SpriteMaterial({
            map: glowTexture('rgba(255,150,40,0.5)', 'rgba(255,140,0,0)'),
            blending: THREE.AdditiveBlending,
            depthWrite: false,
            transparent: true
        }));
        halo.scale.set(32, 32, 1);
        halo.position.z = -2;
        planetGroup.add(halo);

        moon = new THREE.Mesh(
            new THREE.SphereGeometry(1.1, 24, 24),
            new THREE.MeshStandardMaterial({ color: 0x9aa3b2, roughness: 1 })
        );
        planetGroup.add(moon);

        // Planètes ambient lointaines
        var p1 = new THREE.Mesh(
            new THREE.SphereGeometry(5, 32, 32),
            new THREE.MeshStandardMaterial({ map: planetTexture('#4a6fa5', '#22354f', '#7fa3d0', 21), roughness: 1 })
        );
        p1.position.set(-75, 26, -150);
        var p2 = new THREE.Mesh(
            new THREE.SphereGeometry(9, 32, 32),
            new THREE.MeshStandardMaterial({ map: planetTexture('#2f7f6f', '#14403a', '#5cbfae', 33), roughness: 1 })
        );
        p2.position.set(90, -34, -190);
        planetGroup.add(p1);
        planetGroup.add(p2);
    }

    /* ---------- Chorégraphie caméra ---------- */
    function easeInOutCubic(p) {
        return p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
    }

    function startFly(z, tx, ty, dur, onDone) {
        fly = { t: 0, dur: dur, z0: cam.z, tx0: cam.tx, ty0: cam.ty, z1: z, tx1: tx, ty1: ty, onDone: onDone };
    }

    function dockTargets() {
        return isMobile ? { z: DOCK_Z, tx: 0, ty: -9 } : { z: DOCK_Z, tx: 12.5, ty: 0.5 };
    }

    function focusEmail() {
        var inp = form.querySelector('input[name="email"]');
        if (!inp) { return; }
        setTimeout(function () {
            try { inp.focus({ preventScroll: true }); } catch (e) { inp.focus(); }
        }, 700);
    }

    function approach() {
        if (state !== 'far') { return; }
        setState('approach');
        var d = dockTargets();
        startFly(d.z, d.tx, d.ty, isMobile ? 950 : 1350, function () {
            setState('docked');
            focusEmail();
        });
    }

    function retreat() {
        if (state !== 'docked') { return; }
        setState('approach');
        startFly(FAR_Z, 0, 0, 1100, function () { setState('far'); });
    }

    /* Positionne le bouton-planète sur la planète projetée (état far) */
    function syncPlanetButton() {
        if (state !== 'far') { return; }
        var w = window.innerWidth, h = window.innerHeight;
        projV.set(0, 0, 0).project(camera);
        if (projV.z > 1) { planetBtn.hidden = true; return; }
        if (planetBtn.hidden) { planetBtn.hidden = false; }
        var cx = (projV.x * 0.5 + 0.5) * w;
        var cy = (-projV.y * 0.5 + 0.5) * h;
        projV.set(0, 6.6, 0).project(camera);          // limite haute planète
        var ty = (-projV.y * 0.5 + 0.5) * h;
        var r = Math.max(64, Math.abs(cy - ty));
        planetBtn.style.width = planetBtn.style.height = (r * 2) + 'px';
        planetBtn.style.left = cx + 'px';
        planetBtn.style.top = cy + 'px';
    }

    function onResize() {
        if (!renderer) { return; }
        isMobile = window.matchMedia('(max-width: 991.98px)').matches;
        camera.aspect = window.innerWidth / window.innerHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(window.innerWidth, window.innerHeight, false);
        if (!running) { renderer.render(scene, camera); }
    }

    /* ---------- Boucle de rendu ---------- */
    function loop() {
        if (!running) { return; }
        raf = requestAnimationFrame(loop);
        var dt = Math.min(clock.getDelta(), 0.05);
        var t = clock.elapsedTime;

        // Garde-fou perf : si les 90 premières frames sont < 35 fps,
        // on bascule sur le login classique (aucune animation lourde).
        if (!fpsChecked) {
            fpsFrames++; fpsTime += dt;
            if (fpsFrames >= 90) {
                fpsChecked = true;
                if (fpsTime / fpsFrames > 1 / 35) { fail(new Error('fps < 35')); return; }
            }
        }

        // Vol caméra (approche / retour)
        if (fly) {
            fly.t += dt * 1000;
            var p = Math.min(1, fly.t / fly.dur);
            var e = easeInOutCubic(p);
            cam.z = fly.z0 + (fly.z1 - fly.z0) * e;
            cam.tx = fly.tx0 + (fly.tx1 - fly.tx0) * e;
            cam.ty = fly.ty0 + (fly.ty1 - fly.ty0) * e;
            if (p >= 1) { var done = fly.onDone; fly = null; if (done) { done(); } }
        }

        // Respiration douce à l'état far
        var breathe = (state === 'far' && !fly) ? 1 : 0;
        camera.position.set(
            Math.sin(t * 0.17) * 0.7 * breathe,
            Math.sin(t * 0.23) * 0.5 * breathe,
            cam.z + Math.sin(t * 0.3) * 1.3 * breathe
        );
        camera.lookAt(cam.tx, cam.ty, 0);

        // Warp (soumission du formulaire)
        if (warpActive && warp < 1) { warp = Math.min(1, warp + dt * 2.6); }
        var boost = fly ? 1 + Math.sin(Math.min(1, fly.t / fly.dur) * Math.PI) * 2.2 : 1;
        var move = (starBaseSpeed + warp * warp * 150) * boost * dt;

        // Étoiles : dérive vers l'avant + wrap (perspective du vaisseau)
        var arr = starGeo.attributes.position.array;
        var limit = camera.position.z + 8;
        for (var i = 2; i < arr.length; i += 3) {
            arr[i] += move;
            if (arr[i] > limit) { arr[i] -= 300; }
        }
        starGeo.attributes.position.needsUpdate = true;

        // Traînées + fov kick + planète qui défile derrière
        if (warp > 0.03) {
            var lp = lineGeo.attributes.position.array;
            var len = warp * warp * 26;
            for (var j = 0, k = 0; j < arr.length; j += 3, k += 6) {
                lp[k] = arr[j]; lp[k + 1] = arr[j + 1]; lp[k + 2] = arr[j + 2];
                lp[k + 3] = arr[j]; lp[k + 4] = arr[j + 1]; lp[k + 5] = arr[j + 2] - len;
            }
            lineGeo.attributes.position.needsUpdate = true;
            starLine.visible = true;
            camera.fov = 60 + warp * 12;
            camera.updateProjectionMatrix();
            planetGroup.position.z = warp * warp * 90;
        } else if (starLine.visible) {
            starLine.visible = false;
        }

        // Vie de la planète : rotation, lune, halo qui pulse
        if (jmhPlanet) { jmhPlanet.rotation.y += dt * 0.06; }
        if (moon) {
            moonT += dt * 0.45;
            moon.position.set(Math.cos(moonT) * 13.5, Math.sin(moonT * 0.6) * 2.6, Math.sin(moonT) * 13.5);
        }
        if (halo) { halo.material.opacity = 0.7 + Math.sin(t * 1.6) * 0.18; }

        syncPlanetButton();
        renderer.render(scene, camera);
    }

    /* ---------- Événements ---------- */
    function bindEvents() {
        planetBtn.addEventListener('click', approach);
        backBtn.addEventListener('click', retreat);

        document.addEventListener('keydown', function (ev) {
            if (ev.key !== 'Escape' || state !== 'docked') { return; }
            var tag = ((ev.target && ev.target.tagName) || '').toLowerCase();
            if (tag === 'input' || tag === 'textarea') { return; }  // tape = on ne vole pas le champ
            retreat();
        });

        form.addEventListener('submit', function () {
            if (state !== 'docked') { return; }
            warpActive = true;
            planetBtn.hidden = true;
            backBtn.hidden = true;
            if (flashEl) {
                flashEl.classList.remove('on');
                void flashEl.offsetWidth;                 // relance l'animation
                flashEl.classList.add('on');
            }
        });

        document.addEventListener('visibilitychange', function () {
            if (!renderer) { return; }
            if (document.hidden) {
                running = false;
                cancelAnimationFrame(raf);
            } else if (!running && html.classList.contains('orbit-space-active')) {
                running = true;
                clock.getDelta();                         // remise à zéro du delta
                loop();
            }
        });
    }

    function dispose() {
        running = false;
        cancelAnimationFrame(raf);
        window.removeEventListener('resize', onResize);
        try { if (renderer) { renderer.dispose(); } } catch (e) {}
        renderer = null;
    }
})();
