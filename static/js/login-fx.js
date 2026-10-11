/* ============================================================
   LOGIN FX - habillage spatial aleatoire du login
   - Etoiles filantes (CSS, par groupes de 3)
   - Planetes lointaines en Three.js (canvas dedie) : textures
     generees par procede, eclairage du soleil, reflets d'environnement
   Decor uniquement : pointer-events none, sous le formulaire.
   Cree seulement si la scene spatiale est active.
   ============================================================ */
(function () {
    'use strict';

    var html = document.documentElement;
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) { return; }

    // URL du Three local : passee par le template via data-three
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
    var items = [], raf = 0, lastT = 0;

    function rnd(a, b) { return a + Math.random() * (b - a); }
    function smooth(x) { x = Math.max(0, Math.min(1, x)); return x * x * (3 - 2 * x); }

    /* Fondu entree/sortie sur la duree de vie (p de 0 a 1). */
    function envelope(p) {
        if (p < 0.08) { return smooth(p / 0.08); }
        if (p > 0.92) { return smooth((1 - p) / 0.08); }
        return 1;
    }

    /* Demi-hauteur visible a la profondeur z (camera en z = CAM_Z). */
    function halfHeightAt(z) { return Math.tan(FOV * Math.PI / 360) * (CAM_Z - z); }

    /* ---------- Etoiles filantes (CSS) : 3 par passage ---------- */
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

    /* ---------- Three.js : environnement ---------- */
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

    /* Environnement procedural (ciel sombre, soleil, softbox) pour les reflets. */
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


    /* Chargement unique et paresseux de Three.js. Echec = pas d'objets 3D,
       les etoiles filantes CSS continuent de fonctionner. */
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

                scene.add(new THREE.AmbientLight(0xc4d4f0, 0.3));
                var sun = new THREE.DirectionalLight(0xfff1dc, 2.6);
                sun.position.set(-40, 30, 50);
                scene.add(sun);
                var rim = new THREE.DirectionalLight(0x5b8cff, 0.6);
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



    /* ---------- Materiaux et helpers ---------- */
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

    /* Bruit de valeur periodique en x (raccord gauche/droite de la texture). */
    function makeNoise(cols, rows) {
        var g = [];
        for (var i = 0; i < cols * rows; i++) { g.push(Math.random()); }
        return function (u, v) {
            var x = u * cols, y = v * (rows - 1);
            var x0 = Math.floor(x), y0 = Math.floor(y);
            var fx = smooth(x - x0), fy = smooth(y - y0);
            var ax = ((x0 % cols) + cols) % cols, bx = (ax + 1) % cols;
            var ay = Math.min(y0, rows - 1), by = Math.min(y0 + 1, rows - 1);
            var a = g[ay * cols + ax], b = g[ay * cols + bx];
            var c = g[by * cols + ax], d = g[by * cols + bx];
            return (a + (b - a) * fx) * (1 - fy) + (c + (d - c) * fx) * fy;
        };
    }

    /* Somme de quatre octaves de bruit (relief, nuages, cratères). */
    function makeFbm() {
        var layers = [makeNoise(4, 3), makeNoise(8, 5), makeNoise(16, 9), makeNoise(32, 17)];
        var weights = [0.5, 0.3, 0.13, 0.07];
        return function (u, v) {
            var s = 0;
            for (var i = 0; i < layers.length; i++) { s += weights[i] * layers[i](u, v); }
            return s;
        };
    }

    function mix(a, b, t) {
        t = Math.max(0, Math.min(1, t));
        return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
    }

    /* Couleur d'un texel : n = relief (0..1), v = latitude (0 haut, 1 bas). */
    function colorAt(kind, n, v) {
        var lat = Math.abs(v - 0.5) * 2;
        if (kind === 'earth') {
            if (lat > 0.9) { return [236, 242, 248]; }
            if (n > 0.52) { return mix([58, 112, 56], [128, 106, 64], (n - 0.52) * 4); }
            return mix([16, 58, 118], [38, 96, 156], n / 0.52);
        }
        if (kind === 'mars') {
            if (lat > 0.94) { return [228, 222, 214]; }
            if (n > 0.72) { return mix([120, 66, 40], [92, 50, 32], (n - 0.72) * 3); }
            return mix([164, 84, 46], [196, 118, 66], n);
        }
        if (kind === 'jupiter') {
            var band = Math.sin(v * Math.PI * 12 + (n - 0.5) * 2.5);
            return mix([150, 98, 62], [226, 190, 146], (band + 1) / 2 * 0.85 + n * 0.15);
        }
        if (kind === 'saturn') {
            var b2 = Math.sin(v * Math.PI * 9 + (n - 0.5) * 1.8);
            return mix([196, 166, 110], [240, 220, 170], (b2 + 1) / 2 * 0.8 + n * 0.2);
        }
        /* lune glacee */
        if (n > 0.7) { return mix([150, 152, 160], [110, 112, 122], (n - 0.7) * 3); }
        return mix([196, 204, 216], [160, 168, 180], n);
    }

    /* Peint la surface d'une planete (texture equirectangulaire). */
    function paintPlanet(g, w, h, kind) {
        var fbm = makeFbm();
        var img = g.createImageData(w, h);
        var d = img.data;
        for (var y = 0; y < h; y++) {
            var v = y / (h - 1);
            for (var x = 0; x < w; x++) {
                var n = Math.max(0, Math.min(1, (fbm(x / w, v) - 0.5) * 2.4 + 0.5));
                var c = colorAt(kind, n, v);
                var k = (y * w + x) * 4;
                d[k] = c[0]; d[k + 1] = c[1]; d[k + 2] = c[2]; d[k + 3] = 255;
            }
        }
        g.putImageData(img, 0, 0);
    }



    /* Anneaux : texture radiale, UV planaires de RingGeometry (rayon interne 161 px). */
    function ringTexture() {
        return canvasTexture(512, 512, function (g) {
            g.clearRect(0, 0, 512, 512);
            for (var rr = 161; rr < 256; rr++) {
                var a = 0.25 + 0.4 * Math.abs(Math.sin(rr * 0.23) * Math.sin(rr * 0.071));
                if (rr > 196 && rr < 202) { a = 0.04; }
                g.strokeStyle = 'rgba(222,200,160,' + a.toFixed(3) + ')';
                g.lineWidth = 1.2;
                g.beginPath(); g.arc(256, 256, rr, 0, Math.PI * 2); g.stroke();
            }
        });
    }

    var KINDS = {
        earth:   { halo: 0x3d7fe0, ring: false },
        mars:    { halo: 0xc8643a, ring: false },
        jupiter: { halo: 0xd9a46a, ring: false },
        saturn:  { halo: 0xe6cf98, ring: true },
        ice:     { halo: 0x9fb4d0, ring: false }
    };

    /* Planete de rayon 1 (mise a l'echelle ensuite) : surface, halo, anneaux eventuels. */
    function buildPlanet(kind) {
        var cfg = KINDS[kind];
        var root = new THREE.Group();
        var mats = [], geos = [], texs = [];
        function geo(g) { geos.push(g); return g; }

        var bodyTex = canvasTexture(512, 256, function (g, w, h) { paintPlanet(g, w, h, kind); });
        texs.push(bodyTex);
        var bodyM = mat(0xffffff, 0.9, 0.0, { map: bodyTex });
        mats.push(bodyM);
        add(root, geo(new THREE.SphereGeometry(1, 64, 48)), bodyM, 0, 0, 0);

        /* Halo : coque un peu plus grande, seules ses faces arriere sont visibles (liseret). */
        var haloM = mat(0x000000, 1, 0, { side: THREE.BackSide });
        haloM.emissive.setHex(cfg.halo);
        haloM.emissiveIntensity = 0.12;
        mats.push(haloM);
        add(root, geo(new THREE.SphereGeometry(1.04, 48, 32)), haloM, 0, 0, 0);

        if (cfg.ring) {
            var ringTex = ringTexture();
            texs.push(ringTex);
            var ringM = mat(0xffffff, 0.7, 0, { map: ringTex, side: THREE.DoubleSide });
            mats.push(ringM);
            var ring = add(root, geo(new THREE.RingGeometry(1.45, 2.3, 128)), ringM, 0, 0, 0);
            ring.rotation.x = Math.PI / 2;
        }

        root.rotation.z = rnd(0.2, 0.45);
        return { group: root, mats: mats, geos: geos, texs: texs };
    }

    /* Libere geometries, textures et materiaux a la fin de chaque passage. */
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
        lastT = t;
        for (var i = items.length - 1; i >= 0; i--) {
            var it = items[i];
            var p = (now - it.t0) / it.dur;
            if (p >= 1) { disposeItem(it); items.splice(i, 1); continue; }
            it.update(p, t);
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

    /* Execute fn une fois Three.js pret (chargement unique). */
    function whenReady(fn) {
        if (scene) { fn(); return; }
        loadThree().then(function () { if (scene) { fn(); } });
    }

    /* Planete lointaine : profondeur -160 a -110, petite, dérive lente et rotation. */
    function spawnPlanet() {
        whenReady(function () {
            var kinds = ['earth', 'mars', 'jupiter', 'saturn', 'ice'];
            var kind = kinds[Math.floor(Math.random() * kinds.length)];
            var z = rnd(-160, -110);
            var hh = halfHeightAt(z), hw = hh * camera.aspect;
            var r = rnd(4.5, 7.5) * (kind === 'saturn' ? 1.1 : 1);
            var side = Math.random() < 0.5 ? -1 : 1;
            var x0 = side * rnd(hw * 0.35, hw * 0.8);
            var y0 = rnd(-hh * 0.45, hh * 0.45);
            var dx = -side * rnd(hw * 0.08, hw * 0.2);
            var dy = rnd(-hh * 0.08, hh * 0.08);
            var spin = rnd(0.03, 0.08) * (Math.random() < 0.5 ? -1 : 1);
            var ph = rnd(0, 6.28);
            var o = buildPlanet(kind);
            o.group.scale.setScalar(r);
            o.group.position.set(x0, y0, z);
            scene.add(o.group);
            o.update = function (p, t) {
                o.group.position.x = x0 + dx * p;
                o.group.position.y = y0 + dy * p + Math.sin(t * 0.05 + ph) * 0.4;
                o.group.rotation.y = t * spin;
            };
            track(o, rnd(50, 70) * 1000);
        });
    }

    /* Boucle aleatoire : etoiles filantes toutes les 4-9 s, planete toutes
       les 25-45 s. Rien ne se passe hors scene active. */
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
    schedule(spawnPlanet, 25, 45, 8);
})();
