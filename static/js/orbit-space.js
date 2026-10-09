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
    var coinGroup, spinGroup, orbitRing, halo, envRT;
    var minis = [];
    var hoverT = 0;        // 0..1 survol de la médaille (halo chaud)
    var spinKick = 0;      // impulsion de rotation au clic
    var projV = null;
    var raf = 0, running = false;
    var cam = { z: 95, tx: 0, ty: 0 };
    var fly = null;
    var warp = 0, warpActive = false;
    var starBaseSpeed = 1.6;
    var fpsFrames = 0, fpsTime = 0, fpsChecked = false;
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
        buildCoin();

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

    /* ---------- Médaille JMH (jeton 3D détaillé) ---------- */
    function bumpFromCanvas(src) {
        var c = document.createElement('canvas');
        c.width = src.width; c.height = src.height;
        var g = c.getContext('2d');
        g.drawImage(src, 0, 0);
        var img = g.getImageData(0, 0, c.width, c.height);
        var d = img.data;
        for (var i = 0; i < d.length; i += 4) {
            var lum = d[i] * 0.3 + d[i + 1] * 0.59 + d[i + 2] * 0.11;
            d[i] = d[i + 1] = d[i + 2] = lum;
        }
        g.putImageData(img, 0, 0);
        return c;
    }

    function arcText(g, text, cx, cy, radius, a0, a1, font, fill, mode) {
        g.save();
        g.font = font; g.fillStyle = fill;
        g.textAlign = 'center'; g.textBaseline = 'middle';
        var n = text.length;
        var step = (a1 - a0) / ((n - 1) || 1);
        for (var i = 0; i < n; i++) {
            var a = a0 + step * i;
            g.save();
            g.translate(cx + Math.cos(a) * radius, cy + Math.sin(a) * radius);
            g.rotate(mode === 'top' ? a + Math.PI / 2 : a - Math.PI / 2);
            g.fillText(text[i], 0, 0);
            g.restore();
        }
        g.restore();
    }

    function buildEnv() {
        var c = document.createElement('canvas');
        c.width = 512; c.height = 256;
        var g = c.getContext('2d');
        var grad = g.createLinearGradient(0, 0, 0, 256);
        grad.addColorStop(0, '#2b3654');
        grad.addColorStop(0.5, '#0a0d14');
        grad.addColorStop(1, '#05060a');
        g.fillStyle = grad;
        g.fillRect(0, 0, 512, 256);
        function blob(x, y, r, col) {
            var rg = g.createRadialGradient(x, y, 0, x, y, r);
            rg.addColorStop(0, col); rg.addColorStop(1, 'rgba(0,0,0,0)');
            g.fillStyle = rg; g.fillRect(0, 0, 512, 256);
        }
        blob(120, 58, 130, 'rgba(255,244,218,0.95)');   // soleil chaud
        blob(392, 96, 150, 'rgba(120,160,255,0.5)');    // rebond bleu
        blob(258, 224, 170, 'rgba(255,140,0,0.32)');    // reflet orange
        var tex = new THREE.CanvasTexture(c);
        tex.mapping = THREE.EquirectangularReflectionMapping;
        if (THREE.SRGBColorSpace) { tex.colorSpace = THREE.SRGBColorSpace; }
        var pmrem = new THREE.PMREMGenerator(renderer);
        envRT = pmrem.fromEquirectangular(tex);
        scene.environment = envRT.texture;
        tex.dispose();
        pmrem.dispose();
    }

    function coinFaceTexture(reverse) {
        var S = 1024;
        var c = document.createElement('canvas');
        c.width = c.height = S;
        var g = c.getContext('2d');
        if (reverse) { g.translate(S, 0); g.scale(-1, 1); }   // face arrière miroir -> pré-compensation
        var cx = S / 2, cy = S / 2;

        // Fond or brossé
        var base = g.createRadialGradient(cx * 0.78, cy * 0.66, 40, cx, cy, 540);
        base.addColorStop(0, '#ffe9b8');
        base.addColorStop(0.55, '#e8b44e');
        base.addColorStop(1, '#b8801f');
        g.fillStyle = base;
        g.fillRect(0, 0, S, S);

        // Brossé concentrique (micro-relief optique)
        for (var r = 70; r < 520; r += 15) {
            g.beginPath(); g.arc(cx, cy, r, 0, 2 * Math.PI);
            g.strokeStyle = (r % 30 ? 'rgba(255,255,255,0.03)' : 'rgba(90,55,0,0.045)');
            g.lineWidth = 1.3; g.stroke();
        }

        // Couronne saillante (bord relevé)
        g.beginPath(); g.arc(cx, cy, 496, 0, 2 * Math.PI);
        g.lineWidth = 30; g.strokeStyle = 'rgba(255,244,214,0.9)'; g.stroke();
        g.beginPath(); g.arc(cx, cy, 478, 0, 2 * Math.PI);
        g.lineWidth = 5; g.strokeStyle = 'rgba(110,70,8,0.55)'; g.stroke();

        // Grenetis (perles du pourtour)
        var beads = 132;
        for (var b = 0; b < beads; b++) {
            var ab = (b / beads) * 2 * Math.PI;
            g.beginPath();
            g.arc(cx + Math.cos(ab) * 452, cy + Math.sin(ab) * 452, 4.6, 0, 2 * Math.PI);
            g.fillStyle = 'rgba(255,246,218,0.95)'; g.fill();
        }

        g.beginPath(); g.arc(cx, cy, 424, 0, 2 * Math.PI);
        g.lineWidth = 3; g.strokeStyle = 'rgba(130,85,15,0.5)'; g.stroke();

        g.textAlign = 'center'; g.textBaseline = 'middle';
        if (!reverse) {
            // Avers : monogramme JMH sur orbes
            g.save(); g.translate(cx, cy - 8); g.rotate(-0.32);
            g.strokeStyle = 'rgba(255,246,220,0.7)'; g.lineWidth = 4;
            g.beginPath(); g.ellipse(0, 0, 252, 96, 0, 0, 2 * Math.PI); g.stroke();
            g.strokeStyle = 'rgba(255,246,220,0.3)'; g.lineWidth = 2;
            g.beginPath(); g.ellipse(0, 0, 188, 188, 0, 0, 2 * Math.PI); g.stroke();
            g.restore();

            arcText(g, '* CABINET JMH *', cx, cy, 382, Math.PI * 1.22, Math.PI * 1.78, 'bold 46px Georgia, serif', 'rgba(122,74,8,0.92)', 'top');
            arcText(g, 'ORBIT - EXCELLENCE', cx, cy, 382, Math.PI * 0.80, Math.PI * 0.20, 'bold 40px Georgia, serif', 'rgba(122,74,8,0.9)', 'bottom');

            g.font = 'bold 214px Georgia, serif';
            g.fillStyle = 'rgba(255,248,225,0.85)'; g.fillText('JMH', cx, cy + 6);
            g.fillStyle = 'rgba(122,74,8,0.94)';    g.fillText('JMH', cx, cy);
            g.font = 'bold 46px Georgia, serif';
            g.fillStyle = 'rgba(255,248,225,0.8)';  g.fillText('2026', cx, cy + 152);
            g.fillStyle = 'rgba(122,74,8,0.9)';     g.fillText('2026', cx, cy + 150);
        } else {
            // Revers : emblème orbite
            arcText(g, '* JMH ORBIT *', cx, cy, 382, Math.PI * 1.22, Math.PI * 1.78, 'bold 46px Georgia, serif', 'rgba(122,74,8,0.92)', 'top');
            arcText(g, 'GESTION & COMPTABILITE', cx, cy, 382, Math.PI * 0.82, Math.PI * 0.18, 'bold 38px Georgia, serif', 'rgba(122,74,8,0.9)', 'bottom');

            g.save(); g.translate(cx, cy - 20);
            g.strokeStyle = 'rgba(255,246,220,0.9)'; g.lineWidth = 7;
            g.beginPath(); g.arc(0, 0, 74, 0, 2 * Math.PI); g.stroke();
            g.save(); g.rotate(-0.48);
            g.lineWidth = 5; g.strokeStyle = 'rgba(255,246,220,0.75)';
            g.beginPath(); g.ellipse(0, 0, 128, 46, 0, 0, 2 * Math.PI); g.stroke();
            g.restore();
            g.fillStyle = 'rgba(255,214,120,0.98)';
            g.beginPath(); g.arc(0, 0, 30, 0, 2 * Math.PI); g.fill();
            g.restore();

            g.font = 'bold 58px Georgia, serif';
            g.fillStyle = 'rgba(255,248,225,0.85)'; g.fillText('ORBIT', cx, cy + 132);
            g.fillStyle = 'rgba(122,74,8,0.92)';    g.fillText('ORBIT', cx, cy + 130);
        }

        var tex = new THREE.CanvasTexture(c);
        if (THREE.SRGBColorSpace) { tex.colorSpace = THREE.SRGBColorSpace; }
        var bump = new THREE.CanvasTexture(bumpFromCanvas(c));
        return { map: tex, bump: bump };
    }

    function coinEdgeTexture() {
        var W = 1024, H = 64;
        var c = document.createElement('canvas');
        c.width = W; c.height = H;
        var g = c.getContext('2d');
        var grad = g.createLinearGradient(0, 0, 0, H);
        grad.addColorStop(0, '#8a5c14');
        grad.addColorStop(0.5, '#f0cd7e');
        grad.addColorStop(1, '#8a5c14');
        g.fillStyle = grad;
        g.fillRect(0, 0, W, H);
        var reeds = 150;
        for (var i = 0; i < reeds; i++) {
            g.fillStyle = (i % 2 ? 'rgba(60,42,6,0.85)' : 'rgba(255,244,214,0.75)');
            g.fillRect((i / reeds) * W, 0, (W / reeds) * 0.55, H);
        }
        var tex = new THREE.CanvasTexture(c);
        if (THREE.SRGBColorSpace) { tex.colorSpace = THREE.SRGBColorSpace; }
        var bump = new THREE.CanvasTexture(bumpFromCanvas(c));
        return { map: tex, bump: bump };
    }

    function buildCoin() {
        buildEnv();

        coinGroup = new THREE.Group();
        scene.add(coinGroup);

        var tilt = new THREE.Group();
        tilt.rotation.x = -0.22;
        tilt.rotation.z = 0.06;
        coinGroup.add(tilt);

        spinGroup = new THREE.Group();
        tilt.add(spinGroup);

        var R = 6.2, TH = 0.62, SEG = 128;
        var top = coinFaceTexture(false);
        var bot = coinFaceTexture(true);
        var edg = coinEdgeTexture();

        var sideMat = new THREE.MeshStandardMaterial({ map: edg.map, bumpMap: edg.bump, bumpScale: 0.5, metalness: 0.95, roughness: 0.42, envMapIntensity: 1.0 });
        var topMat  = new THREE.MeshStandardMaterial({ map: top.map, bumpMap: top.bump, bumpScale: 0.6, metalness: 0.90, roughness: 0.33, envMapIntensity: 1.2 });
        var botMat  = new THREE.MeshStandardMaterial({ map: bot.map, bumpMap: bot.bump, bumpScale: 0.6, metalness: 0.90, roughness: 0.33, envMapIntensity: 1.2 });

        var cyl = new THREE.Mesh(new THREE.CylinderGeometry(R, R, TH, SEG, 1, false), [sideMat, topMat, botMat]);
        cyl.rotation.x = Math.PI / 2;          // faces vers la caméra
        spinGroup.add(cyl);

        // Grain de bord poli (léger relief sur la tranche)
        var bead = new THREE.Mesh(new THREE.TorusGeometry(R + 0.02, 0.09, 10, SEG),
            new THREE.MeshStandardMaterial({ color: 0xd9a441, metalness: 0.98, roughness: 0.26, envMapIntensity: 1.25 }));
        bead.rotation.x = Math.PI / 2;
        spinGroup.add(bead);

        // Anneau d'orbite (signature JMH Orbit)
        orbitRing = new THREE.Mesh(new THREE.TorusGeometry(9.6, 0.055, 8, 160),
            new THREE.MeshBasicMaterial({ color: 0xffb24d, transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending, depthWrite: false }));
        orbitRing.rotation.x = Math.PI / 2.4;
        tilt.add(orbitRing);

        // Halo chaud derrière la médaille
        halo = new THREE.Sprite(new THREE.SpriteMaterial({
            map: glowTexture('rgba(255,168,60,0.5)', 'rgba(255,140,0,0)'),
            blending: THREE.AdditiveBlending, depthWrite: false, transparent: true
        }));
        halo.scale.set(34, 34, 1);
        halo.position.z = -2.5;
        tilt.add(halo);

        // Mini-médailles en orbite (remplace la lune)
        var miniMat = new THREE.MeshStandardMaterial({ color: 0xe8b44e, metalness: 0.95, roughness: 0.3, envMapIntensity: 1.1 });
        var defs = [
            { r: 11.5, sp: 0.50, inc: 0.42, s: 0.95, ph: 0.0 },
            { r: 13.6, sp: -0.36, inc: -0.30, s: 0.70, ph: 2.1 },
            { r: 9.8, sp: 0.62, inc: 0.85, s: 0.55, ph: 4.0 }
        ];
        if (isMobile) { defs = defs.slice(0, 2); }
        defs.forEach(function (d) {
            var m = new THREE.Mesh(new THREE.CylinderGeometry(d.s, d.s, d.s * 0.15, 48), miniMat);
            m.rotation.x = Math.PI / 2;
            tilt.add(m);
            minis.push({ mesh: m, r: d.r, sp: d.sp, inc: d.inc, ph: d.ph, a: Math.random() * 6.28 });
        });

        // Éclairage dédié : éclat spéculaire chaud
        var spark = new THREE.PointLight(0xffd9a0, 40, 70, 2);
        spark.position.set(9, 9, 15);
        scene.add(spark);
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
            coinGroup.position.z = warp * warp * 90;
        } else if (starLine.visible) {
            starLine.visible = false;
        }

        // Vie de la médaille : rotation, mini-médailles en orbite, halo qui pulse
        if (spinGroup) { spinGroup.rotation.y += dt * (0.5 + spinKick * 6); }
        if (spinKick > 0) { spinKick = Math.max(0, spinKick - dt * 2.2); }  // impulsion amortie
        if (orbitRing) { orbitRing.rotation.z += dt * 0.25; }
        for (var mi = 0; mi < minis.length; mi++) {
            var mm = minis[mi];
            mm.a += dt * mm.sp;
            var x = Math.cos(mm.a + mm.ph) * mm.r;
            var z = Math.sin(mm.a + mm.ph) * mm.r;
            mm.mesh.position.set(x, Math.sin(mm.a * 1.3) * mm.inc * 2, z);
        }
        if (halo) {
            // halo de base + éclat chaud au survol (hoverT lissé)
            var hover = hoverT; // déjà 0/1 ; lissage optionnel évité pour rester léger
            halo.material.opacity = 0.7 + Math.sin(t * 1.6) * 0.18 + hover * 0.35;
            var hs = 34 + hover * 6;
            halo.scale.set(hs, hs, 1);
        }

        syncPlanetButton();
        renderer.render(scene, camera);
    }

    /* ---------- Événements ---------- */
    function bindEvents() {
        planetBtn.addEventListener('click', approach);
        backBtn.addEventListener('click', retreat);

        // Micro-interactions médaille : halo chaud au survol, impulsion au clic
        planetBtn.addEventListener('pointerover', function () { hoverT = 1; });
        planetBtn.addEventListener('pointerout', function () { hoverT = 0; });
        planetBtn.addEventListener('pointerdown', function () { spinKick = 1; });

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
