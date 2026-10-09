/* ============================================================
   ORBIT PREMIUM â€” micro-interactions studio (v2.2)
   Intro animee 1re page/session, ripple, prefetch, barre de
   progression, ancres fluides.
   RETIRES (feedback utilisateur) : fondu inter-pages (ecran noir)
   et tilt 3D (hover instable sur les bords des cartes).
   100% progressif : l'app reste identique si le script echoue.
   ============================================================ */
(function () {
    'use strict';
    var reduce = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

    /* 1) REVEAL â€” animee UNIQUEMENT a la premiere page de la session :
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
    
    /* 7) STELLAR CURSOR - SUPPRIME (assombrissement background) */
    function initStellarCursor() { /* retired */ }
    /* 2) RIPPLE â€” effet onde au clic sur les boutons */
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

    /* 3) TOAST POSITION â€” centrÃ© en bas sur mobile (dÃ©jÃ  stylÃ© par CSS) */
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
        try { initToastDock(); initReveal(); initRipple(); initPrefetch(); initProgress(); initSmoothAnchors(); }
        catch (e) { if (window.console && console.warn) { console.warn('[orbit-premium]', e); } }
    }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
})();
