/* ============================================================
   ORBIT PREMIUM — micro-interactions studio (v1)
   Reveal au scroll, ripple boutons, tilt cartes, page transition.
   100% progressif : l'app reste identique si le script echoue.
   ============================================================ */
(function () {
    'use strict';
    var reduce = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

    /* 1) REVEAL AU SCROLL — apparition en cascade des blocs */
    function initReveal() {
        var targets = document.querySelectorAll('.card-premium, .stat-card, .task-card, .quick-actions, .today-band');
        if (!targets.length) { return; }
        if (reduce || !('IntersectionObserver' in window)) {
            Array.prototype.forEach.call(targets, function (el) { el.classList.add('orbit-revealed'); });
            return;
        }
        var io = new IntersectionObserver(function (entries) {
            entries.forEach(function (e) {
                if (e.isIntersecting) { var el = e.target; el.classList.add('orbit-revealed'); io.unobserve(el); setTimeout(function () { el.classList.remove('orbit-reveal', 'orbit-revealed'); el.style.transitionDelay = ''; }, 900); }
            });
        }, { rootMargin: '0px 0px -6% 0px', threshold: 0.08 });
        Array.prototype.forEach.call(targets, function (el, i) {
            el.classList.add('orbit-reveal');
            el.style.transitionDelay = (Math.min(i % 8, 6) * 45) + 'ms';
            io.observe(el);
        });
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

    /* 3) TILT 3D — cartes KPI legerement inclinees au survol */
    function initTilt() {
        if (reduce || window.matchMedia('(hover: none)').matches) { return; }
        var cards = document.querySelectorAll('.stat-card');
        Array.prototype.forEach.call(cards, function (card) {
            card.style.transformStyle = 'preserve-3d';
            card.addEventListener('pointermove', function (ev) {
                var r = card.getBoundingClientRect();
                var rx = ((ev.clientY - r.top) / r.height - 0.5) * -6;
                var ry = ((ev.clientX - r.left) / r.width - 0.5) * 6;
                card.style.transform = 'translateY(-2px) perspective(700px) rotateX(' + rx + 'deg) rotateY(' + ry + 'deg)';
            });
            card.addEventListener('pointerleave', function () { card.style.transform = ''; });
        });
    }

    /* 4) PAGE TRANSITION — fondu discret vers la page suivante */
    function initPageTransition() {
        if (reduce) { return; }
        document.addEventListener('click', function (ev) {
            var a = ev.target.closest('a[href]');
            if (!a || a.target === '_blank' || a.hasAttribute('download')) { return; }
            if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) { return; }
            var href = a.getAttribute('href');
            if (!href || href.charAt(0) === '#' || href.indexOf('javascript:') === 0) { return; }
            if (a.dataset.noTransition === '1' || a.closest('form, .modal, [data-bs-toggle]')) { return; }
            ev.preventDefault();
            document.documentElement.classList.add('orbit-leaving');
            setTimeout(function () { window.location.href = href; }, 160);
        }, { passive: false });
        window.addEventListener('pageshow', function (e) { document.documentElement.classList.remove('orbit-leaving'); });
    }

    /* 5) TOAST POSITION — centré en bas sur mobile (déjà stylé par CSS) */
    function initToastDock() {
        var style = document.createElement('style');
        style.textContent = [
            '            .orbit-reveal { opacity: 0; transform: translateY(14px); transition: opacity .6s cubic-bezier(.16,1,.3,1), transform .6s cubic-bezier(.16,1,.3,1); }',
            '            .orbit-reveal.orbit-revealed { opacity: 1; transform: none; }',
            '            .orbit-ripple { position: absolute; border-radius: 50%; background: currentColor; opacity: .18; transform: scale(0); animation: orbitRipple .6s cubic-bezier(.16,1,.3,1) forwards; pointer-events: none; }',
            '            @keyframes orbitRipple { to { transform: scale(2.4); opacity: 0; } }',
            '            html.orbit-leaving { opacity: 0; transition: opacity .16s ease; }',
            '            @media (prefers-reduced-motion: reduce) { .orbit-reveal { opacity: 1 !important; transform: none !important; } }',
        ].join('\\n');
        document.head.appendChild(style);
    }

    function init() {
        try { initToastDock(); initReveal(); initRipple(); initTilt(); initPageTransition(); }
        catch (e) { if (window.console && console.warn) { console.warn('[orbit-premium]', e); } }
    }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
})();
