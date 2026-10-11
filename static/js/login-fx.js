/* ============================================================
   LOGIN FX — habillage spatial aléatoire du login
   - Étoiles filantes (CSS, par groupes de 3)
   - Satellite et astronaute en Three.js (canvas dédié) : éclairage,
     matériaux métalliques, reflets d'environnement, fondus
   Décor uniquement : pointer-events none, sous le formulaire.
   Créé seulement si la scène spatiale est active.
   ============================================================ */
(function () {
    'use strict';

    var html = document.documentElement;
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) { return; }

    // URL du Three local : passée par le template via data-three
    var threeScript = document.currentScript;
    var THREE_URL = (threeScript && threeScript.getAttribute('data-three')) || '/static/js/vendor/three.module.min.js';

    var layer = document.createElement('div');
    layer.className = 'login-fx';
    layer.setAttribute('aria-hidden', 'true');
    document.body.appendChild(layer);

    var canvas = document.createElement('canvas');
    canvas.className = 'login-fx-canvas';
    canvas.setAttribute('aria-hidden', 'true');
    layer.appendChild(canvas);

    var FOV = 45;
    var CAM_Z = 60;

    var THREE = null, renderer = null, scene = null, camera = null;
    var loading = null;
    var items = [], raf = 0, lastT = 0, running = false;

    function rnd(a, b) { return a + Math.random() * (b - a); }
    function smooth(x) { x = Math.max(0, Math.min(1, x)); return x * x * (3 - 2 * x); }

    /* Fondu entrée/sortie sur la durée de vie (p de 0 à 1). */
    function envelope(p) {
        if (p < 0.08) { return smooth(p / 0.08); }
        if (p > 0.92) { return smooth((1 - p) / 0.08); }
        return 1;
    }

    /* Demi-hauteur visible à la profondeur z (caméra en z = CAM_Z). */
    function halfHeightAt(z) { return Math.tan(FOV * Math.PI / 360) * (CAM_Z - z); }

    /* ---------- Étoiles filantes (CSS) : 3 par passage ---------- */
    function setVars(el, obj) {
        Object.keys(obj).forEach(function (k) { el.style.setProperty(k, obj[k]); });
    }

    function spawnShooting() {
        var w = window.innerWidth, h = window.innerHeight;
        var baseX = rnd(0, w * 0.7), baseY = rnd(0, h * 0.4);
        var ang = rnd(18, 32);
        var len = rnd(260, 380);
        for (var i = 0; i < 3; i++) {
            var el = document.createElement('div');
            el.className = 'login-fx-shooting';
            var x0 = baseX - i * rnd(34, 48), y0 = baseY - i * rnd(16, 22);
            var a = ang + rnd(-2, 2);
            var r = a * Math.PI / 180;
            setVars(el, {
                '--x0': x0 + 'px', '--y0': y0 + 'px',
                '--x1': (x0 + Math.cos(r) * len) + 'px', '--y1': (y0 + Math.sin(r) * len) + 'px',
                '--ang': a.toFixed(1) + 'deg',
                '--dur': rnd(1.1, 1.8).toFixed(2) + 's',
                '--tail': rnd(120, 170).toFixed(0) + 'px'
            });
            el.style.animationDelay = (i * 0.16).toFixed(2) + 's';
            layer.appendChild(el);
            setTimeout(function (node) { return function () { node.remove(); }; }(el), 2800);
        }
    }


    /* ---------- Three.js : chargement et environnement ---------- */
    function canvasTexture(w, h, draw) {
        var c = document.createElement('canvas');
        c.width = w; c.height = h;
        draw(c.getContext('2d'), w, h);
        var tex = new THREE.CanvasTexture(c);
        tex.colorSpace = THREE.SRGBColorSpace;
        return tex;
    }

    function resize() {
        if (!renderer) { return; }
        var w = window.innerWidth, h = window.innerHeight;
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
        renderer.setSize(w, h, false);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
    }

    /* Environnement procédural (ciel sombre, soleil, softbox) pour les reflets métalliques. */
    function buildEnvironment() {
        var tex = canvasTexture(512, 256, function (g, w, h) {
            var grd = g.createLinearGradient(0, 0, 0, h);
            grd.addColorStop(0, '#1b2750');
            grd.addColorStop(0.5, '#080b18');
            grd.addColorStop(1, '#2b2116');
            g.fillStyle = grd;
            g.fillRect(0, 0, w, h);
            g.fillStyle = '#fff3dc';
            g.beginPath(); g.arc(150, 80, 26, 0, Math.PI * 2); g.fill();
            g.fillStyle = 'rgba(170,200,255,0.8)';
            g.fillRect(330, 60, 70, 26);
        });
        tex.mapping = THREE.EquirectangularReflectionMapping;
        var pmrem = new THREE.PMREMGenerator(renderer);
        var env = pmrem.fromEquirectangular(tex).texture;
        pmrem.dispose();
        tex.dispose();
        return env;
    }

    /* Chargement unique et paresseux de Three.js. Échec = pas d'objets 3D,
       les étoiles filantes CSS continuent de fonctionner. */
    function loadThree() {
        if (!loading) {
            loading = import(THREE_URL).then(function (mod) {
                THREE = mod;
                renderer = new THREE.WebGLRenderer({
                    canvas: canvas,
                    alpha: true,
                    antialias: (window.devicePixelRatio || 1) < 1.5,
                    powerPreference: 'low-power'
                });
                renderer.setClearColor(0x000000, 0);
                renderer.outputColorSpace = THREE.SRGBColorSpace;
                renderer.toneMapping = THREE.ACESFilmicToneMapping;
                renderer.toneMappingExposure = 1.05;

                scene = new THREE.Scene();
                camera = new THREE.PerspectiveCamera(FOV, window.innerWidth / window.innerHeight, 0.1, 400);
                camera.position.set(0, 0, CAM_Z);

                scene.add(new THREE.AmbientLight(0xc4d4f0, 0.35));
                var sun = new THREE.DirectionalLight(0xfff1dc, 2.4);
                sun.position.set(-40, 30, 50);
                scene.add(sun);
                var rim = new THREE.DirectionalLight(0x5b8cff, 0.8);
                rim.position.set(50, -20, -30);
                scene.add(rim);
                scene.environment = buildEnvironment();

                resize();
                window.addEventListener('resize', resize);
            }).catch(function (err) {
                if (window.console && console.warn) { console.warn('[login-fx]', err); }
            });
        }
        return loading;
    }


    /* ---------- Matériaux, géométries et objets ---------- */
    function mat(color, rough, metal, extra) {
        var m = new THREE.MeshStandardMaterial({
            color: color, roughness: rough, metalness: metal,
            transparent: true, opacity: 0
        });
        if (extra) { Object.keys(extra).forEach(function (k) { m[k] = extra[k]; }); }
        return m;
    }

    function add(parent, geo, material, x, y, z) {
        var m = new THREE.Mesh(geo, material);
        m.position.set(x || 0, y || 0, z || 0);
        parent.add(m);
        return m;
    }

    /* Satellite : corps métallique, deux ailes solaires texturées, antenne parabolique. */
    function buildSatellite() {
        var root = new THREE.Group();
        var mats = [], geos = [];
        var bodyM = mat(0xdfe6f2, 0.32, 0.85); mats.push(bodyM);
        var goldM = mat(0xd8a24a, 0.35, 0.9); mats.push(goldM);
        var panelTex = canvasTexture(256, 128, function (g, w, h) {
            g.fillStyle = '#143a86'; g.fillRect(0, 0, w, h);
            g.strokeStyle = 'rgba(160,190,240,0.75)'; g.lineWidth = 2;
            for (var x = 0; x <= w; x += 32) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke(); }
            for (var y = 0; y <= h; y += 32) { g.beginPath(); g.moveTo(0, y); g.lineTo(w, y); g.stroke(); }
        });
        var panelM = mat(0xffffff, 0.4, 0.35, { map: panelTex }); mats.push(panelM);

        var bodyG = new THREE.BoxGeometry(2.2, 1.6, 1.6); geos.push(bodyG);
        add(root, bodyG, bodyM, 0, 0, 0);
        [-1, 1].forEach(function (s) {
            var boomG = new THREE.BoxGeometry(1.6, 0.12, 0.12); geos.push(boomG);
            add(root, boomG, goldM, s * 2.1, 0, 0);
            var panelG = new THREE.BoxGeometry(3.6, 0.05, 1.8); geos.push(panelG);
            var p = add(root, panelG, panelM, s * 3.9, 0, 0);
            p.rotation.x = 0.08;
        });
        var dishG = new THREE.SphereGeometry(0.9, 28, 14, 0, Math.PI * 2, 0, 0.85); geos.push(dishG);
        var d = add(root, dishG, bodyM, 0, 0.1, 1.05);
        d.rotation.x = Math.PI / 2;
        var antG = new THREE.CylinderGeometry(0.05, 0.05, 1.4, 8); geos.push(antG);
        add(root, antG, goldM, 0, 1.2, 0);
        root.scale.setScalar(2.4);
        return { group: root, mats: mats, geos: geos, texs: [panelTex] };
    }

    /* Astronaute : combinaison blanche, visière dorée réfléchissante, sac à dos,
       bras et jambes articulés, câble coupé qui pend du sac. */
    function buildAstronaut() {
        var root = new THREE.Group();
        var mats = [], geos = [];
        var suitM = mat(0xe9edf5, 0.6, 0.05); mats.push(suitM);
        var packM = mat(0x9aa4b6, 0.45, 0.4); mats.push(packM);
        var visorM = mat(0x2b1a08, 0.08, 1.0); mats.push(visorM);
        var cordM = mat(0xf2c14e, 0.5, 0.1); mats.push(cordM);
        function geo(g) { geos.push(g); return g; }

        add(root, geo(new THREE.CapsuleGeometry(1.1, 1.6, 6, 14)), suitM, 0, 0, 0);
        add(root, geo(new THREE.SphereGeometry(1.15, 28, 20)), suitM, 0, 2.3, 0);
        add(root, geo(new THREE.SphereGeometry(0.78, 24, 16, 0, Math.PI * 2, 0, Math.PI * 0.9)), visorM, 0, 2.3, 0.45);
        add(root, geo(new THREE.BoxGeometry(2.0, 2.5, 0.9)), packM, 0, 0.2, -1.2);

        var arms = [], legs = [];
        [-1, 1].forEach(function (s) {
            var arm = new THREE.Group();
            arm.position.set(s * 1.35, 1.2, 0);
            add(arm, geo(new THREE.CapsuleGeometry(0.34, 1.6, 4, 10)), suitM, 0, -1.0, 0);
            add(arm, geo(new THREE.SphereGeometry(0.42, 14, 10)), suitM, 0, -2.2, 0);
            root.add(arm);
            arms.push(arm);

            var leg = new THREE.Group();
            leg.position.set(s * 0.55, -1.7, 0);
            add(leg, geo(new THREE.CapsuleGeometry(0.4, 1.8, 4, 10)), suitM, 0, -1.2, 0);
            add(leg, geo(new THREE.BoxGeometry(0.7, 0.45, 1.0)), suitM, 0, -2.4, 0.2);
            root.add(leg);
            legs.push(leg);
        });

        /* Câble coupé : pivot sur le sac, pend et oscille. */
        var tether = new THREE.Group();
        tether.position.set(0.7, 1.4, -1.9);
        add(tether, geo(new THREE.CylinderGeometry(0.05, 0.05, 3.2, 6)), cordM, 0, -1.6, 0);
        add(tether, geo(new THREE.SphereGeometry(0.1, 8, 6)), cordM, 0, -3.2, 0);
        root.add(tether);

        root.scale.setScalar(2.2);
        return { group: root, mats: mats, geos: geos, texs: [], arms: arms, legs: legs, tether: tether };
    }

    /* Libère géométries, textures et matériaux à la fin de chaque passage. */
    function disposeItem(it) {
        scene.remove(it.group);
        it.geos.forEach(function (g) { g.dispose(); });
        it.texs.forEach(function (t) { t.dispose(); });
        it.mats.forEach(function (m) { m.dispose(); });
    }

    function setOpacity(mats, o) {
        for (var i = 0; i < mats.length; i++) { mats[i].opacity = o; }
    }

    /* ---------- Boucle de rendu : tourne seulement tant qu'un objet existe ---------- */
    function frame(now) {
        raf = 0;
        if (!renderer) { return; }
        var t = now / 1000;
        var dt = lastT ? Math.min(0.05, t - lastT) : 0;
        lastT = t;
        for (var i = items.length - 1; i >= 0; i--) {
            var it = items[i];
            var p = (now - it.t0) / it.dur;
            if (p >= 1) { disposeItem(it); items.splice(i, 1); continue; }
            it.update(p, t, dt);
            setOpacity(it.mats, envelope(p));
        }
        renderer.render(scene, camera);
        if (items.length) {
            raf = requestAnimationFrame(frame);
        } else {
            canvas.style.opacity = '0';
            lastT = 0;
        }
    }

    function kick() {
        canvas.style.opacity = '1';
        if (!raf) { raf = requestAnimationFrame(frame); }
    }


    /* ---------- Apparitions ---------- */
    function track(it, durMs) {
        it.t0 = performance.now();
        it.dur = durMs;
        items.push(it);
        kick();
    }

    /* Exécute fn une fois Three.js prêt (chargement unique). */
    function whenReady(fn) {
        if (scene) { fn(); return; }
        loadThree().then(function () { if (scene) { fn(); } });
    }

    /* Satellite : traverse la scène en profondeur, tumble lent, bords hors écran. */
    function spawnSatellite() {
        whenReady(function () {
            var z = rnd(-28, -8);
            var hh = halfHeightAt(z), hw = hh * camera.aspect;
            var fromLeft = Math.random() < 0.5;
            var sx = fromLeft ? -hw - 14 : hw + 14, ex = -sx;
            var sy = rnd(-hh * 0.1, hh * 0.7);
            var ey = sy + rnd(-hh * 0.25, hh * 0.25);
            var o = buildSatellite();
            o.group.position.set(sx, sy, z);
            scene.add(o.group);
            var phase = rnd(0, 6.28);
            o.update = function (p, t) {
                o.group.position.x = sx + (ex - sx) * p;
                o.group.position.y = sy + (ey - sy) * p + Math.sin(t * 0.5 + phase) * 0.3;
                o.group.rotation.y = 0.45 + 0.5 * Math.sin(t * 0.35 + phase);
                o.group.rotation.x = 0.25 + 0.15 * Math.sin(t * 0.5);
                o.group.rotation.z = -0.06 + 0.05 * Math.sin(t * 0.7);
            };
            track(o, rnd(28, 36) * 1000);
        });
    }

    /* Astronaute en dérive : bras et jambes qui bougent, câble coupé qui pend et oscille. */
    function spawnAstronaut() {
        whenReady(function () {
            var z = rnd(-12, -2);
            var hh = halfHeightAt(z), hw = hh * camera.aspect;
            var fromLeft = Math.random() < 0.5;
            var sx = fromLeft ? -hw - 10 : hw + 10, ex = -sx;
            var sy = rnd(-hh * 0.35, hh * 0.35);
            var ey = sy + rnd(-hh * 0.15, hh * 0.15);
            var rot0 = rnd(-0.4, 0.4), rot1 = rnd(-1.2, 1.2);
            var o = buildAstronaut();
            scene.add(o.group);
            var ph = rnd(0, 6.28);
            o.update = function (p, t) {
                var e = smooth(p);
                o.group.position.set(sx + (ex - sx) * e, sy + (ey - sy) * e + Math.sin(t * 0.9 + ph) * 0.5, z);
                o.group.rotation.z = rot0 + (rot1 - rot0) * e + 0.08 * Math.sin(t * 0.7 + ph);
                o.group.rotation.y = 0.6 * Math.sin(t * 0.4 + ph);
                o.group.rotation.x = 0.2 * Math.sin(t * 0.3 + ph);
                o.arms[0].rotation.z = -0.25 + 0.35 * Math.sin(t * 1.1 + ph);
                o.arms[1].rotation.z = 0.2 - 0.35 * Math.sin(t * 0.9 + ph + 1);
                o.legs[0].rotation.z = 0.15 * Math.sin(t * 0.8 + ph);
                o.legs[1].rotation.z = -0.15 * Math.sin(t * 0.8 + ph + 1.2);
                o.tether.rotation.z = 0.3 * Math.sin(t * 0.9 + ph);
                o.tether.rotation.x = 0.15 * Math.sin(t * 0.6 + ph);
            };
            track(o, rnd(40, 58) * 1000);
        });
    }

    /* Boucle aléatoire : étoiles filantes toutes les 4–9 s, satellite toutes
       les 18–30 s, astronaute toutes les 40–70 s. Rien ne se passe hors scène active. */
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
