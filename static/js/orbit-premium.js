/* ============================================================
   ORBIT PREMIUM — micro-interactions studio (v2.1)
   Intro animee 1re page/session, ripple, prefetch, barre de
   progression, ancres fluides.
   RETIRES (feedback utilisateur) : fondu inter-pages (ecran noir)
   et tilt 3D (hover instable sur les bords des cartes).
   100% progressif : l'app reste identique si le script echoue.
   ============================================================ */
(function () {
    'use strict';
    var reduce = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

    /* 1) REVEAL — animee UNIQUEMENT a la premiere page de la session :
       les naviguations suivantes s'affichent instantanement (aucun effet). */
    function initReveal() {
        var targets = document.querySelectorAll('.card-premium, .stat-card, .task-card, .quick-actions, .today-band');
        if (!targets.length) { return; }
        var intro = false;
        try { intro = !sessionStorage.getItem('orbitIntro'); if (intro) { sessionStorage.setItem('orbitIntro', '1'); } } catch (e) { intro = false; }
        if (reduce || !intro || !('IntersectionObserver' in window)) { return; }
        var io = new IntersectionObserver(function (entries) {
            entries.forEach(function (e) {
                if (e.isIntersecting) { var el = e.target; el.classList.add('orbit-revealed'); io.unobserve(el); setTimeout(function () { el.classList.remove('orbit-reveal', 'orbit-revealed'); el.style.transitionDelay = ''; }, 700); }
            });
        }, { rootMargin: '0px 0px -4% 0px', threshold: 0.06 });
        Array.prototype.forEach.call(targets, function (el, i) {
            el.classList.add('orbit-reveal');
            el.style.transitionDelay = (Math.min(i % 6, 5) * 30) + 'ms';
            io.observe(el);
        });
    }
    
    /* 7) STELLAR CURSOR — légère traîne de particules au curseur sur les éléments interactifs */
    function initStellarCursor() {
        if (reduce) return;
        var canvas = document.createElement('canvas');
        canvas.className = 'orbit-stellar-canvas';
        canvas.style.cssText = 'position:fixed;pointer-events:none;top:0;left:0;width:100%;height:100%;z-index:9999';
        document.body.appendChild(canvas);
        var ctx = canvas.getContext('2d'), w, h, pts = [], max = 3, lx = 0, ly = 0, mx = 0, my = 0, over = false, lt = 0, fps = 60, fpsTimeout;
        function rsz() { w = window.innerWidth; h = window.innerHeight; canvas.width = w * dpr; canvas.height = h * dpr; ctx.scale(dpr, dpr); }
        var dpr = window.devicePixelRatio;
        function intEl(el) { if (!el) return false; var tags = ['BUTTON','A','INPUT','SELECT','TEXTAREA']; if (tags.indexOf(el.tagName) !== -1) return true; var s = getComputedStyle(el); return s.cursor === 'pointer' || el.closest('.btn-premium,.qa-btn,.btn-login,.card-premium,.stat-card,.task-card,.kpi-chip,.badge,.sidebar-nav-item,.orbit-tool-btn,.avm-panel-chip,.theme-choice,.orbit-drawer-btn,.orbit-drawer-close,.orbit-fav-btn,.orbit-search-btn,.orbit-logo,.orbit-palette,.orbit-help,.orbit-theme') !== null; }
        function onm(e) { mx = e.clientX; my = e.clientY; over = false; var t = e.target; while (t && t !== document.body) { if (intEl(t)) { over = true; break; } t = t.parentElement; } }
        function rend(t) { if (!lt) lt = t; var d = t - lt; if (fpsTimeout) clearTimeout(fpsTimeout); fps = 1000/(d||16); fpsTimeout = setTimeout(()=>fps=60,1000); if (fps < 35) { ctx.clearRect(0,0,w,h); lt = t; requestAnimationFrame(rend); return; } lt = t; ctx.fillStyle = 'rgba(0,0,0,0.01)'; ctx.fillRect(0,0,w,h); if (over && pts.length < max) { var ox = (Math.random()-0.5)*2, oy = (Math.random()-0.5)*2; pts.push({x:mx+ox,y:my+oy,a:0.8,s:1+Math.random()*1.5}); } for (var i = pts.length-1; i >= 0; i--) { var p = pts[i]; p.a -= 0.02; if (p.a <= 0) { pts.splice(i,1); continue; } ctx.beginPath(); ctx.arc(p.x,p.y,p.s,0,Math.PI*2); ctx.fillStyle = 'rgba(255,140,0,'+p.a+')'; ctx.fill(); } requestAnimationFrame(rend); }
        rsz(); window.addEventListener('resize',rsz); window.addEventListener('orientationchange',rsz); document.addEventListener('mousemove',onm); requestAnimationFrame(rend);
    }
    /* 2) RIPPLE — effet onde au clic sur les boutons */
    function initRipple() {
        if (reduce) { return; }
        document.addEventListener('pointerdown', function (ev) {
            var btn = ev.target.closest('.btn-premium, .qa-btn, .btn-login');
            if (!btn || btn.disabled) { return; }
            var rect = btn.getBoundingClientRect();
            var d = Math.max(rect.width, rect.height);
            var span = document.createElement('span');
            span.className = 'orbit-ripple';
            span.style.width = span.style.height = d + 'px';
            span.style.left = (ev.clientX - rect.left - d / 2) + 'px';
            span.style.top = (ev.clientY - rect.top - d / 2) + 'px';
            btn.appendChild(span);
            setTimeout(function () { if (span.parentNode) { span.parentNode.removeChild(span); } }, 650);
        }, { passive: true });
    }

    /* 3) TOAST POSITION — centré en bas sur mobile (déjà stylé par CSS) */
    function initToastDock() {
        var style = document.createElement('style');
        style.textContent = [
            '            .orbit-reveal { opacity: 0; transform: translateY(10px); transition: opacity .3s cubic-bezier(.16,1,.3,1), transform .3s cubic-bezier(.16,1,.3,1); }',
            '            .orbit-reveal.orbit-revealed { opacity: 1; transform: none; }',
            '            .orbit-ripple { position: absolute; border-radius: 50%; background: currentColor; opacity: .18; transform: scale(0); animation: orbitRipple .6s cubic-bezier(.16,1,.3,1) forwards; pointer-events: none; }',
            '            @keyframes orbitRipple { to { transform: scale(2.4); opacity: 0; } }',
            '            @media (prefers-reduced-motion: reduce) { .orbit-reveal { opacity: 1 !important; transform: none !important; } }',
        ].join('\n');
        document.head.appendChild(style);
    }

    function initPrefetch() {
        var seen = {};
        function add(href) { if (!href || seen[href] || href.indexOf('/') !== 0) return; seen[href]=1; var l=document.createElement('link'); l.rel='prefetch'; l.href=href; document.head.appendChild(l); }
        document.addEventListener('mouseover', function(ev){ var a=ev.target.closest('a[href]'); if(a) add(a.getAttribute('href')); }, {passive:true});
        document.addEventListener('focusin', function(ev){ var a=ev.target.closest('a[href]'); if(a) add(a.getAttribute('href')); });
    }
    function initProgress() {
        var bar=document.createElement('div'); bar.className='orbit-progress'; bar.setAttribute('aria-hidden','true'); document.body.appendChild(bar);
        document.addEventListener('click', function(ev){ var a=ev.target.closest('a[href]'); if(!a || a.target==='_blank') return; var h=a.getAttribute('href'); if(!h||h.charAt(0)==='#'||h.indexOf('javascript:')===0) return; bar.style.width='42%'; bar.classList.add('is-on'); }, {passive:true});
        window.addEventListener('beforeunload', function(){ bar.style.width='100%'; });
        window.addEventListener('pageshow', function(){ bar.style.width='0'; bar.classList.remove('is-on'); });
    }
    function initSmoothAnchors() {
        if (reduce) return;
        document.addEventListener('click', function(ev){ var a=ev.target.closest('a[href^=\"#\"]'); if(!a) return; var id=a.getAttribute('href'); if(id.length<2) return; var t=document.querySelector(id); if(!t) return; ev.preventDefault(); t.scrollIntoView({behavior:'smooth', block:'start'}); history.pushState(null,'',id); });
    }

    function init() {
        try { initToastDock(); initReveal(); initRipple(); initPrefetch(); initProgress(); initSmoothAnchors(); initStellarCursor(); }
        catch (e) { if (window.console && console.warn) { console.warn('[orbit-premium]', e); } }
    }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
})();
