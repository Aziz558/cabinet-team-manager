/* JMH ORBIT — base.html : blocs inline extraits (chargés avec defer).
   Généré depuis templates/base.html — NE PAS éditer à la main : modifier base.html
   puis relancer _extract_base_js.py. Le socle thème du <head> reste inline (anti-FOUC). */

/* ===== bloc extrait de base.html (ligne ~280) ===== */
    (function() {
        // Move flash toasts into the fixed toast container
        var container = document.getElementById('toastContainer');
        if (container) {
            document.querySelectorAll('.toast').forEach(function(t) {
                container.appendChild(t);
                // Auto-dismiss after 5 seconds
                setTimeout(function() {
                    var bsToast = bootstrap.Toast.getOrCreateInstance(t, {delay: 5000, animation: true});
                    bsToast.show();
                }, 100);
            });
        }
        // Concordance singulier/pluriel côté client : `'tâche' + orbitPl(n)`
        window.orbitPl = function(n, one, many) {
            n = Number(n) || 0;
            if (n === 1) { return one || ''; }
            return many === undefined ? 's' : many;
        };
        // Convenience function for non-flashed toasts
        window.showToast = function(message, category) {
            category = category || 'info';
            var cls = 'toast-info';
            if (category === 'success') cls = 'toast-success';
            if (category === 'danger') cls = 'toast-danger';
            if (category === 'warning') cls = 'toast-warning';
            var icon = 'bi-info-circle';
            if (category === 'success') icon = 'bi-check-circle';
            if (category === 'danger') icon = 'bi-x-circle';
            if (category === 'warning') icon = 'bi-exclamation-triangle';
            var html = '<div class="toast ' + cls + '" role="alert" style="min-width: 300px;">' +
                '<div class="toast-header d-flex align-items-center">' +
                '<i class="bi ' + icon + ' me-2"></i>' +
                '<strong class="me-auto">Cabinet JMH</strong>' +
                '<button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast" aria-label="Fermer"></button>' +
                '</div><div class="toast-body">' + message + '</div></div>';
            var wrapper = document.createElement('div');
            wrapper.innerHTML = html;
            var t = wrapper.firstElementChild;
            container.appendChild(t);
            var bsToast = bootstrap.Toast.getOrCreateInstance(t, {delay: 5000, animation: true});
            bsToast.show();
            setTimeout(function() { if (t.parentNode) t.parentNode.removeChild(t); }, 5500);
        };
    })();


    // Sidebar toggle
    (function() {
        var sidebarCol = document.getElementById('sidebarCol');
        var toggle = document.getElementById('sidebarToggle');
        var sidebar = sidebarCol ? sidebarCol.querySelector('.sidebar') : null;

        if (!sidebarCol || !sidebar || !toggle) return;

        var state = localStorage.getItem('sidebarState') || 'full';
        applySidebarState(state);

        function applySidebarState(s) {
            if (s === 'icons') {
                sidebarCol.style.width = '60px';
                sidebarCol.classList.add('sidebar-collapsed');
                sidebar.classList.add('sidebar-collapsed');
                // Hide text elements
                document.querySelectorAll('.sidebar-nav-item span, .sidebar-section-title, .sidebar-brand-text, .sidebar-user-info, .sidebar-subtitle').forEach(function(el) {
                    el.style.display = 'none';
                });
                document.querySelectorAll('.sidebar-nav-item').forEach(function(link) {
                    link.style.justifyContent = 'center';
                    link.style.padding = '0.55rem 0';
                });
                document.querySelectorAll('.sidebar-nav-item i').forEach(function(icon) {
                    icon.style.margin = '0';
                });
                document.querySelectorAll('.sidebar-nav-item.active').forEach(function(item) {
                    item.style.position = 'relative';
                });
                document.querySelectorAll('.sidebar-nav-item.active::before').forEach(function() {});
                toggle.innerHTML = '<i class="bi bi-caret-right"></i>';
            } else {
                sidebarCol.style.width = '240px';
                sidebarCol.classList.remove('sidebar-collapsed');
                sidebar.classList.remove('sidebar-collapsed');
                document.querySelectorAll('.sidebar-nav-item span, .sidebar-section-title, .sidebar-brand-text, .sidebar-user-info, .sidebar-subtitle').forEach(function(el) {
                    el.style.display = '';
                });
                document.querySelectorAll('.sidebar-nav-item').forEach(function(link) {
                    link.style.justifyContent = '';
                    link.style.padding = '';
                });
                document.querySelectorAll('.sidebar-nav-item i').forEach(function(icon) {
                    icon.style.margin = '';
                });
                toggle.innerHTML = '<i class="bi bi-list"></i>';
            }
        }

        toggle.addEventListener('click', function() {
            if (sidebarCol.style.width === '60px') {
                state = 'full';
            } else {
                state = 'icons';
            }
            localStorage.setItem('sidebarState', state);
            applySidebarState(state);
        });
    })();

/* ===== bloc extrait de base.html (ligne ~389) ===== */
// Applique l'icône + le logo du thème courant (socle défini dans <head>)
(function() {
    if (window.setOrbitTheme) { window.setOrbitTheme(window.ORBIT_THEME, false, true); }
})();

/* ===== bloc extrait de base.html (ligne ~395) ===== */
// Tiroir de navigation mobile (additif : n'affecte pas l'effondrement desktop)
(function() {
    var toggle = document.getElementById('sidebarToggle');
    if (!toggle) return;
    var body = document.body;
    var bd = document.createElement('div');
    bd.className = 'sidebar-backdrop';
    body.appendChild(bd);
    function mobile() { return window.matchMedia('(max-width: 767.98px)').matches; }
    function close() { body.classList.remove('sidebar-open'); }
    bd.addEventListener('click', close);
    toggle.addEventListener('click', function() { if (mobile()) body.classList.toggle('sidebar-open'); });
    document.querySelectorAll('#sidebarCol a').forEach(function(a) {
        a.addEventListener('click', function() { if (mobile()) close(); });
    });
    window.addEventListener('resize', function() { if (!mobile()) close(); });
    window.addEventListener('keydown', function(e) { if (e.key === 'Escape') close(); });
})();

/* ===== bloc extrait de base.html (ligne ~415) ===== */
// Select All checkboxes functionality
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.select-all-checkbox').forEach(function(selectAll) {
        selectAll.addEventListener('change', function() {
            var table = this.closest('table');
            if (!table) return;
            var checkboxes = table.querySelectorAll('.row-checkbox');
            checkboxes.forEach(function(cb) { cb.checked = selectAll.checked; });
        });
    });
    // Update select-all state when individual checkboxes change
    document.querySelectorAll('.row-checkbox').forEach(function(cb) {
        cb.addEventListener('change', function() {
            var table = this.closest('table');
            if (!table) return;
            var selectAll = table.querySelector('.select-all-checkbox');
            if (!selectAll) return;
            var all = table.querySelectorAll('.row-checkbox');
            var checked = table.querySelectorAll('.row-checkbox:checked');
            selectAll.checked = all.length > 0 && all.length === checked.length;
        });
    });
});

/* ===== bloc extrait de base.html (ligne ~440) ===== */
/* Menus deroulants filtres (avm-iconbar) en gestion manuelle : ferme a la
   selection, au 2e clic sur l'icone, au clic exterieur et a Echap. Remplace
   le dropdown Bootstrap (race Popper = menu qui reste ouvert). */
function closeAvmDropdowns() {
    document.querySelectorAll('.avm-iconbar .dropdown-menu.show').forEach(function(m) {
        m.classList.remove('show');
        var t = m.parentElement ? m.parentElement.querySelector('[aria-expanded]') : null;
        if (t) t.setAttribute('aria-expanded', 'false');
    });
}
function avmMenu(id, build) {
    var m = document.getElementById(id);
    if (!m) return;
    var wasOpen = m.classList.contains('show');
    closeAvmDropdowns();
    if (!wasOpen) {
        if (typeof build === 'function') build();
        m.classList.add('show');
    }
}
if (!window.__avmMenuBound) {
    window.__avmMenuBound = true;
    document.addEventListener('click', function(e) {
        if (!e.target || !e.target.closest || !e.target.closest('.avm-iconbar')) closeAvmDropdowns();
    }, true);
    document.addEventListener('keydown', function(e) { if (e.key === 'Escape') closeAvmDropdowns(); }, true);
}

/* ===== bloc extrait de base.html (ligne ~471) ===== */
// PWA: Service Worker registration
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js');
    // Tuer les enregistrements herites (ancien worker /static/sw.js, scope limite)
    navigator.serviceWorker.getRegistrations().then(function(regs) {
        regs.forEach(function(rg) {
            try {
                if (new URL(rg.scope).pathname !== '/') rg.unregister();
            } catch (e) {}
        });
    });
}
// PWA: Install prompt
var deferredPrompt;
window.addEventListener('beforeinstallprompt', function(e) {
    e.preventDefault();
    deferredPrompt = e;
    var btn = document.getElementById('installPwaBtn');
    if (btn) btn.style.display = 'inline-block';
});
document.addEventListener('click', function(e) {
    if (e.target && e.target.id === 'installPwaBtn' && deferredPrompt) {
        deferredPrompt.prompt();
        deferredPrompt.userChoice.then(function() { deferredPrompt = null; });
    }
});
// Sound notification on new notification
var lastNotifCount = parseInt(localStorage.getItem('notifCount') || '0');
// Request notification permission
if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
}

// Sons de notification (Web Audio API)
var NOTIF_SOUNDS = {
    'classic': { freq: 880, type: 'sine', bips: [[0, 0.3]] },
    'soft': { freq: 660, type: 'sine', bips: [[0, 0.25], [0.3, 0.4]] },
    'digital': { freq: 1000, type: 'square', bips: [[0, 0.12], [0.16, 0.12], [0.32, 0.2]] },
    'chime': { freq: 523, type: 'triangle', bips: [[0, 0.3], [0.28, 0.35], [0.56, 0.5]] },
    'alarm': { freq: 440, type: 'sawtooth', bips: [[0, 0.3], [0.35, 0.3], [0.7, 0.45]] }
};
function playNotificationSound() {
    var soundName = localStorage.getItem('notifSound') || 'classic';
    var s = NOTIF_SOUNDS[soundName] || NOTIF_SOUNDS['classic'];
    try {
        var ctx = new (window.AudioContext || window.webkitAudioContext)();
        s.bips.forEach(function(bip) {
            var osc = ctx.createOscillator();
            var gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.frequency.value = s.freq;
            osc.type = s.type;
            var start = ctx.currentTime + bip[0];
            var dur = bip[1];
            gain.gain.setValueAtTime(0.25, start);
            gain.gain.exponentialRampToValueAtTime(0.01, start + dur);
            osc.start(start);
            osc.stop(start + dur);
        });
    } catch(e) {}
}
function pollNotifs() {
    fetch('/notifications/non_lues').then(function(r) { return r.json(); }).then(function(data) {
        var count = data.count || 0;
        var badge = document.getElementById('notifBadge');
        if (badge) {
            badge.style.display = count > 0 ? 'inline-block' : 'none';
            badge.textContent = count > 99 ? '99+' : count;
        }
        if (count > lastNotifCount && count > 0) {
            if (localStorage.getItem('soundEnabled') !== 'false') {
                playNotificationSound();
            }
            // Toast in-app (style bienvenue / flash)
            if (window.showToast) {
                window.showToast('🔔 ' + (data.last_message || count + ' nouvelle(s) notification(s)'), 'info');
            }
            // Desktop notification
            if ('Notification' in window && Notification.permission === 'granted') {
                try {
                    var n = new Notification('Cabinet JMH', {
                        body: data.last_message || count + ' nouvelle(s) notification(s)',
                        icon: document.body.getAttribute('data-logo-orbit'),
                        tag: 'cabinet-jmh-notif',
                        silent: true
                    });
                    setTimeout(function() { n.close(); }, 5000);
                } catch(e) {}
            }
        }
        lastNotifCount = count;
        localStorage.setItem('notifCount', count);
    }).catch(function() {});
}
pollNotifs();
setInterval(pollNotifs, 30000);

// Sound toggle
function toggleSound() {
    var current = localStorage.getItem('soundEnabled');
    var next = current === 'false' ? 'true' : 'false';
    localStorage.setItem('soundEnabled', next);
    var link = document.getElementById('soundToggleLink');
    if (link) {
        link.innerHTML = next !== 'false'
            ? '<i class="bi bi-volume-up me-2 text-tertiary"></i>Son activé'
            : '<i class="bi bi-volume-mute me-2 text-tertiary"></i>Son désactivé';
    }
}
(function() {
    var link = document.getElementById('soundToggleLink');
    if (link) {
        link.innerHTML = localStorage.getItem('soundEnabled') !== 'false'
            ? '<i class="bi bi-volume-up me-2 text-tertiary"></i>Son activé'
            : '<i class="bi bi-volume-mute me-2 text-tertiary"></i>Son désactivé';
    }
})();

// Sélecteur de son de notification
function changeNotifSound(value) {
    localStorage.setItem('notifSound', value);
    // Aperçu du son choisi
    if (localStorage.getItem('soundEnabled') !== 'false') {
        playNotificationSound();
    }
}
(function() {
    var sel = document.getElementById('notifSoundSelect');
    if (sel) {
        sel.value = localStorage.getItem('notifSound') || 'classic';
    }
})();

/* ===== bloc extrait de base.html (ligne ~607) ===== */
    (function() {
        var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

        /* 1) Les valeurs KPI montent de 0 a leur valeur reelle (texte final identique) */
        function countUp() {
            var nodes = document.querySelectorAll('.stat-card-value');
            for (var i = 0; i < nodes.length; i++) {
                (function(el) {
                    var raw = (el.textContent || '').trim();
                    if (!raw || el.getAttribute('data-counted')) { return; }
                    if (!/^-?\d+(?:[.,]\d+)?$/.test(raw)) { return; }   // valeur non numerique -> intacte
                    el.setAttribute('data-counted', '1');
                    if (reduce) { return; }
                    var hasDec = raw.indexOf(',') > -1 || raw.indexOf('.') > -1;
                    var dec = hasDec ? (raw.split(/[.,]/)[1] || '').length : 0;
                    var target = parseFloat(raw.replace(',', '.'));
                    if (isNaN(target)) { return; }
                    var dur = 650, t0 = null;
                    function step(ts) {
                        if (t0 === null) { t0 = ts; }
                        var p = Math.min(1, (ts - t0) / dur);
                        var eased = 1 - Math.pow(1 - p, 3);            // easeOutCubic
                        var v = target * eased;
                        el.textContent = dec ? v.toFixed(dec).replace('.', ',') : String(Math.round(v));
                        if (p < 1) { requestAnimationFrame(step); }
                        else { el.textContent = raw; }                 // valeur d'origine restauree
                    }
                    requestAnimationFrame(step);
                })(nodes[i]);
            }
        }
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', countUp);
        } else { countUp(); }

        /* 2) Barre superieure : se compacte des que la page defile */
        var topbar = document.querySelector('.app-topbar');
        if (topbar && !reduce) {
            var pending = false;
            var sync = function() {
                topbar.classList.toggle('is-compact', (window.pageYOffset || document.documentElement.scrollTop || 0) > 24);
                pending = false;
            };
            window.addEventListener('scroll', function() {
                if (!pending) { pending = true; requestAnimationFrame(sync); }
            }, { passive: true });
            sync();
        }
    })();

/* ===== bloc extrait de base.html (ligne ~664) ===== */
    (function() {
        // Detects and adds mobile-specific enhancements
        var isMobile = () => {
            return (window.innerWidth <= 991.98) || 
                   ('ontouchstart' in window) ||
                   (navigator.maxTouchPoints > 0) ||
                   (navigator.msMaxTouchPoints > 0);
        };
        
        if (isMobile()) {
            document.documentElement.classList.add('mobile-device');
            
            // Enhanced touch feedback
            var style = document.createElement('style');
            style.textContent = `
                .mobile-device {
                    /* Improve touch targets */
                    --touch-min-height: 44px;
                    --touch-min-width: 44px;
                }
                
                .mobile-device .btn, 
                .mobile-device button, 
                .mobile-device a.touch-target {
                    position: relative;
                    min-height: var(--touch-min-height);
                    min-width: var(--touch-min-width);
                    -webkit-tap-highlight-color: transparent;
                    touch-action: manipulation;
                }
                
                .mobile-device .btn:active,
                .mobile-device button:active,
                .mobile-device a.touch-target:active {
                    transform: scale(0.92);
                    opacity: 0.8;
                }
                
                /* Improve mobile scrolling */
                .mobile-device body {
                    -webkit-overflow-scrolling: touch;
                    overscroll-behavior: contain;
                }
                
                /* Prevent zoom on input focus (iOS) */
                .mobile-device input[type="text"],
                .mobile-device input[type="email"],
                .mobile-device input[type="password"],
                .mobile-device select,
                .mobile-device textarea {
                    font-size: 16px !important;
                    border-radius: 8px;
                    padding: 12px 14px;
                    -webkit-appearance: none;
                    appearance: none;
                }
                
                /* Mobile drawer improvements */
                .mobile-device .orbit-drawer,
                .mobile-device .orbit-palette {
                    transition: transform 0.3s cubic-bezier(.4, 0, .2, 1);
                }
                
                /* Hide desktop-only elements on mobile */
                .mobile-device .desktop-only {
                    display: none !important;
                }
                
                /* Show mobile-only elements on mobile */
                .mobile-device .mobile-only {
                    display: block !important;
                }
            `;
            document.head.appendChild(style);
            
            // Initialize mobile enhancements
            setTimeout(function() {
                var app = document.querySelector('.app-container');
                if (app) {
                    // Add mobile class for CSS targeting
                    app.classList.add('mobile-optimized');
                }
                
                // Double-tap : géré proprement par touch-action: manipulation (orbit-system.css)
                
                // Improve mobile viewport handling
                var viewport = document.querySelector('meta[name="viewport"]');
                if (viewport && !viewport.content.includes('interactive-widget')) {
                    viewport.setAttribute('content',
                        'width=device-width, initial-scale=1.0');
                }
            }, 100);
        }
    })();

/* ===== bloc extrait de base.html (ligne ~760) ===== */
    // Barre de progression de navigation : retour visuel immédiat entre deux pages.
    (function () {
        var bar = document.getElementById('orbitProgress');
        if (!bar) { return; }
        var timer = null;
        function start() {
            clearTimeout(timer);
            bar.classList.remove('is-done');
            bar.classList.add('is-on');
        }
        function done() {
            if (!bar.classList.contains('is-on')) { return; }
            bar.classList.remove('is-on');
            bar.classList.add('is-done');
            timer = setTimeout(function () { bar.classList.remove('is-done'); }, 600);
        }
        document.addEventListener('click', function (e) {
            var a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
            if (!a) { return; }
            if (a.target && a.target !== '_self') { return; }
            if (a.hasAttribute('download')) { return; }
            var href = a.getAttribute('href') || '';
            if (!href || href.charAt(0) === '#') { return; }
            if (a.origin && a.origin !== window.location.origin) { return; }
            if (/^(mailto:|tel:|javascript:)/i.test(href)) { return; }
            start();
        }, true);
        document.addEventListener('submit', function (e) {
            if (e.target && e.target.target && e.target.target !== '_self') { return; }
            start();
        }, true);
        window.addEventListener('pageshow', done);
        window.addEventListener('load', done);
    })();
