/* ============================================================
   ORBIT WORKSPACE — Phase 4 (façon Pennylane)
   Panneau latéral, palette ⇧K, navigation clavier, favoris,
   densité, sidebar redimensionnable, dates relatives, aide.
   100 % déclaratif : piloté par les attributs data-orbit-*.
   ============================================================ */
(function () {
    'use strict';

    var doc = document;
    var reduce = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    var store = {
        get: function (k, d) { try { var v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
        set: function (k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
    };
    function esc(s) {
        return String(s === null || s === undefined ? '' : s).replace(/&/g, '&amp;')
            .replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    function mk(tag, cls, html) {
        var n = doc.createElement(tag);
        if (cls) { n.className = cls; }
        if (html !== undefined) { n.innerHTML = html; }
        return n;
    }
    var LABELS = {
        collaborateur: 'Collaborateur', equipe: 'Équipe', regime: 'Régime TVA',
        echeance: 'Échéance(s)', delai: 'Délai', tva: 'Tâches TVA', reste: 'Tâches restantes',
        siren: 'SIREN', naf: 'Code NAF', forme: 'Forme', secteur: 'Secteur',
        priorite: 'Priorité', statut: 'Statut', assigne: 'Assigné à',
        dossier: 'Dossier', nature: 'Nature', description: 'Description'
    };
    function label(key) {
        var k = String(key).toLowerCase();
        return LABELS[k] || (k.charAt(0).toUpperCase() + k.slice(1).replace(/_/g, ' '));
    }

    /* ============================================================
       1) PANNEAU LATÉRAL — le détail s'ouvre sans quitter la liste
       ============================================================ */
    var drawer = null, drawerBackdrop = null, lastFocus = null;

    function ensureDrawer() {
        if (drawer) { return; }
        drawerBackdrop = mk('div', 'orbit-drawer-backdrop');
        drawerBackdrop.addEventListener('click', closeDrawer);
        drawer = mk('aside', 'orbit-drawer');
        drawer.setAttribute('role', 'dialog');
        drawer.setAttribute('aria-modal', 'true');
        drawer.innerHTML =
            '<div class="orbit-drawer-head"><div>' +
            '<span class="orbit-drawer-badge" data-role="kind"></span>' +
            '<div class="orbit-drawer-title" data-role="title"></div>' +
            '<div class="orbit-drawer-sub" data-role="sub"></div></div>' +
            '<button type="button" class="orbit-drawer-close" data-role="close" aria-label="Fermer">&times;</button></div>' +
            '<div class="orbit-drawer-body" data-role="body"></div>' +
            '<div class="orbit-drawer-foot" data-role="foot"></div>';
        doc.body.appendChild(drawerBackdrop);
        doc.body.appendChild(drawer);
        drawer.querySelector('[data-role="close"]').addEventListener('click', closeDrawer);
    }
    function fieldsOf(target) {
        var out = [], attrs = target.attributes, P = 'data-orbit-f-';
        for (var i = 0; i < attrs.length; i++) {
            var a = attrs[i];
            if (a.name.indexOf(P) === 0 && a.value !== '') { out.push([label(a.name.slice(P.length)), a.value]); }
        }
        return out;
    }
    function actionsOf(target) {
        var raw = target.getAttribute('data-orbit-actions');
        if (!raw) { return []; }
        try { var a = JSON.parse(raw); return a && a.length ? a : []; } catch (e) { return []; }
    }
    function openDrawer(target) {
        ensureDrawer();
        lastFocus = target;
        drawer.querySelector('[data-role="kind"]').textContent = target.getAttribute('data-orbit-kind') || 'Détail';
        drawer.querySelector('[data-role="title"]').textContent = target.getAttribute('data-orbit-title') || '—';
        drawer.querySelector('[data-role="sub"]').textContent = target.getAttribute('data-orbit-sub') || '';
        var body = drawer.querySelector('[data-role="body"]');
        body.innerHTML = '';
        var fields = fieldsOf(target);
        if (!fields.length) { body.appendChild(mk('p', 'orbit-palette-empty', 'Aucune information supplémentaire.')); }
        fields.forEach(function (f) {
            var row = mk('div', 'orbit-drawer-row');
            row.appendChild(mk('div', 'orbit-drawer-label', esc(f[0])));
            row.appendChild(mk('div', 'orbit-drawer-value', esc(f[1])));
            body.appendChild(row);
        });
        var foot = drawer.querySelector('[data-role="foot"]');
        foot.innerHTML = '';
        actionsOf(target).forEach(function (a) {
            var btn = mk('a', 'orbit-drawer-btn' + (a[2] === 'primary' ? ' is-primary' : ''),
                (a[3] ? '<i class="bi ' + a[3] + '"></i>' : '') + esc(a[0]));
            btn.href = a[1] || '#';
            if (a[1] && a[1].indexOf('js:') === 0) {
                btn.addEventListener('click', function (ev) {
                    ev.preventDefault(); closeDrawer();
                    try { (new Function(a[1].slice(3)))(); } catch (e) {}
                });
            }
            foot.appendChild(btn);
        });
        foot.style.display = foot.children.length ? '' : 'none';
        drawer.classList.add('is-open');
        drawerBackdrop.classList.add('is-open');
        doc.body.classList.add('orbit-drawer-open');
        if (!reduce) {
            window.setTimeout(function () {
                var c = drawer.querySelector('[data-role="close"]');
                if (c) { c.focus(); }
            }, 140);
        }
    }
    function closeDrawer() {
        if (!drawer) { return; }
        drawer.classList.remove('is-open');
        drawerBackdrop.classList.remove('is-open');
        doc.body.classList.remove('orbit-drawer-open');
        if (lastFocus && lastFocus.focus) {
            try { lastFocus.focus({ preventScroll: true }); } catch (e) { try { lastFocus.focus(); } catch (e2) {} }
        }
        lastFocus = null;
    }

    /* ============================================================
       2) NAVIGATION CLAVIER DANS LES LISTES (↑ ↓ ⇧ Entrée Espace)
       ============================================================ */
    function navList() {
        return Array.prototype.slice.call(doc.querySelectorAll('[data-orbit-nav]'))
            .filter(function (n) { return n.offsetParent !== null; });
    }
    function paintCursor(list, idx) {
        list.forEach(function (n) { n.classList.remove('orbit-cursor'); });
        if (idx < 0 || idx >= list.length) { return; }
        var n = list[idx];
        n.classList.add('orbit-cursor');
        try { n.focus({ preventScroll: true }); } catch (e) { n.focus(); }
        var r = n.getBoundingClientRect();
        if (r.top < 90 || r.bottom > (window.innerHeight - 40)) {
            n.scrollIntoView({ block: 'nearest', behavior: reduce ? 'auto' : 'smooth' });
        }
    }
    function toggleSelect(n) {
        var box = n.querySelector('input[type="checkbox"]');
        if (box) { box.click(); n.classList.toggle('orbit-selected', box.checked); }
        else { n.classList.toggle('orbit-selected'); }
    }
    function moveCursor(delta, extend) {
        var list = navList();
        if (!list.length) { return; }
        var idx = -1;
        list.forEach(function (n, i) { if (n.classList.contains('orbit-cursor')) { idx = i; } });
        if (extend && idx >= 0) {
            var step = delta > 0 ? 1 : -1;
            for (var k = idx; k !== idx + delta * 0; k += step) {
                if (k < 0 || k >= list.length) { break; }
                list[k].classList.add('orbit-selected');
                var target = k;
            }
            if (typeof target === 'number') { paintCursor(list, target); }
            return;
        }
        var next = idx < 0 ? (delta > 0 ? 0 : list.length - 1) : Math.min(list.length - 1, Math.max(0, idx + delta));
        paintCursor(list, next);
    }
    function openCursorDetail() {
        var cur = doc.querySelector('[data-orbit-nav].orbit-cursor');
        if (cur) { openDrawer(cur); }
    }
    function closeCursor() {
        var list = navList();
        list.forEach(function (n) { n.classList.remove('orbit-cursor'); });
    }

    /* ============================================================
       3) PALETTE DE COMMANDES ⇧K (pages + lignes + actions)
       ============================================================ */
    var pal = null, palBackdrop = null, palInput = null, palResults = null;
    var palItems = [], palSel = 0;

    function ensurePalette() {
        if (pal) { return; }
        palBackdrop = mk('div', 'orbit-palette-backdrop');
        palBackdrop.addEventListener('click', closePalette);
        pal = mk('div', 'orbit-palette');
        pal.innerHTML = '<input class="orbit-palette-input" type="text" placeholder="Rechercher un dossier, une tâche, une page…" autocomplete="off" spellcheck="false">' +
            '<div class="orbit-palette-results"></div>' +
            '<div class="orbit-palette-hint"><kbd class="orbit-kbd">&#8593;</kbd><kbd class="orbit-kbd">&#8595;</kbd> naviguer &middot; <kbd class="orbit-kbd">Entr&eacute;e</kbd> ouvrir &middot; <kbd class="orbit-kbd">&Eacute;chap</kbd> fermer</div>';
        palInput = pal.querySelector('.orbit-palette-input');
        palResults = pal.querySelector('.orbit-palette-results');
        palInput.addEventListener('input', function () { renderPalette(palInput.value); });
        palInput.addEventListener('keydown', function (ev) {
            if (ev.key === 'ArrowDown') { ev.preventDefault(); movePalette(1); }
            else if (ev.key === 'ArrowUp') { ev.preventDefault(); movePalette(-1); }
            else if (ev.key === 'Enter') { ev.preventDefault(); runPalette(palSel); }
            else if (ev.key === 'Escape') { ev.preventDefault(); closePalette(); }
        });
        doc.body.appendChild(palBackdrop);
        doc.body.appendChild(pal);
    }
    function norm(s) {
        var t = String(s === null || s === undefined ? '' : s).toLowerCase();
        try { return t.normalize('NFD').replace(/[\u0300-\u036f]/g, ''); } catch (e) { return t; }
    }
    function palettePages() {
        var out = [], seen = {};
        var links = doc.querySelectorAll('.sidebar-nav-item[href], .app-topbar a[href]');
        Array.prototype.forEach.call(links, function (a) {
            var href = a.getAttribute('href');
            if (!href || href.charAt(0) === '#' || seen[href]) { return; }
            seen[href] = 1;
            var ic = a.querySelector('i');
            out.push({
                group: 'Navigation', icon: (ic && ic.className) || 'bi bi-dot',
                label: (a.textContent || '').trim().slice(0, 60) || href, sub: href,
                run: (function (h) { return function () { window.location.href = h; }; })(href)
            });
        });
        return out;
    }
    function paletteItems() {
        var out = [];
        Array.prototype.forEach.call(doc.querySelectorAll('[data-orbit-nav][data-orbit-title]'), function (n) {
            out.push({
                group: n.getAttribute('data-orbit-kind') || 'Résultats', icon: 'bi bi-file-earmark-text',
                label: n.getAttribute('data-orbit-title'),
                sub: n.getAttribute('data-orbit-sub') || '',
                run: (function (el) { return function () { openDrawer(el); }; })(n)
            });
        });
        return out;
    }
    function paletteCommands() {
        return [
            { group: 'Actions', icon: 'bi bi-moon-stars', label: 'Changer de thème (clair / sombre)', sub: 't', run: function () { if (window.toggleTheme) { window.toggleTheme(); } } },
            { group: 'Actions', icon: 'bi bi-arrows-angle-contract', label: 'Basculer la densité d’affichage', sub: 'd', run: toggleDensity },
            { group: 'Actions', icon: 'bi bi-card-list', label: 'Guide des raccourcis clavier', sub: '?', run: toggleHelp }
        ];
    }
    function renderPalette(q) {
        var needle = norm(q).trim();
        var pool = palettePages().concat(paletteItems()).concat(paletteCommands());
        var recents = store.get('orbitRecents', []);
        if (needle) {
            pool = pool.filter(function (it) {
                return norm(it.label).indexOf(needle) > -1 || norm(it.sub).indexOf(needle) > -1;
            });
        }
        pool.sort(function (a, b) {
            var ra = recents.indexOf(a.label), rb = recents.indexOf(b.label);
            return (ra === -1 ? 99 : ra) - (rb === -1 ? 99 : rb);
        });
        palItems = pool.slice(0, needle ? 24 : 30);
        palResults.innerHTML = '';
        if (!palItems.length) {
            palResults.appendChild(mk('div', 'orbit-palette-empty', 'Aucun résultat pour « ' + esc(q) + ' »'));
            return;
        }
        var lastGroup = null;
        palItems.forEach(function (it, i) {
            if (it.group !== lastGroup) {
                lastGroup = it.group;
                palResults.appendChild(mk('div', 'orbit-palette-group', esc(lastGroup)));
            }
            var b = mk('button', 'orbit-palette-item' + (i === 0 ? ' is-active' : ''));
            b.type = 'button';
            b.innerHTML = '<i class="' + esc(it.icon) + '"></i><span>' + esc(it.label) + '</span>' +
                (it.sub ? '<span class="orbit-palette-sub">' + esc(it.sub) + '</span>' : '');
            b.addEventListener('click', (function (k) { return function () { runPalette(k); }; })(i));
            b.addEventListener('mousemove', (function (k) { return function () { setPaletteSel(k); }; })(i));
            palResults.appendChild(b);
        });
        palSel = 0;
    }
    function setPaletteSel(i) {
        var nodes = palResults.querySelectorAll('.orbit-palette-item');
        if (!nodes.length) { return; }
        palSel = Math.max(0, Math.min(nodes.length - 1, i));
        Array.prototype.forEach.call(nodes, function (n, k) { n.classList.toggle('is-active', k === palSel); });
        var act = nodes[palSel];
        if (act && act.scrollIntoView) { act.scrollIntoView({ block: 'nearest' }); }
    }
    function movePalette(d) { setPaletteSel(palSel + d); }
    function runPalette(i) {
        var it = palItems[i];
        if (!it) { return; }
        var recents = store.get('orbitRecents', []).filter(function (x) { return x !== it.label; });
        recents.unshift(it.label);
        store.set('orbitRecents', recents.slice(0, 8));
        closePalette();
        try { it.run(); } catch (e) {}
    }
    function openPalette() {
        ensurePalette();
        palInput.value = '';
        renderPalette('');
        palBackdrop.classList.add('is-open');
        pal.classList.add('is-open');
        window.setTimeout(function () { palInput.focus(); }, reduce ? 0 : 40);
    }
    function closePalette() {
        if (!pal) { return; }
        pal.classList.remove('is-open');
        palBackdrop.classList.remove('is-open');
    }

    /* ============================================================
       4) FAVORIS — étoile + épinglés en tête (comme Pennylane)
       ============================================================ */
    function favs() { return store.get('orbitFavs', {}); }
    function isFav(kind, id) { return (favs()[kind] || []).indexOf(String(id)) > -1; }
    function toggleFav(kind, id) {
        var all = favs(), list = all[kind] || [], s = String(id), i = list.indexOf(s);
        if (i > -1) { list.splice(i, 1); } else { list.push(s); }
        all[kind] = list;
        store.set('orbitFavs', all);
        return i === -1;
    }
    function injectFavButtons() {
        var nodes = doc.querySelectorAll('[data-orbit-nav][data-orbit-id]');
        Array.prototype.forEach.call(nodes, function (n) {
            if (n.querySelector('.orbit-fav-btn')) { return; }
            var kind = n.getAttribute('data-orbit-kind') || 'item';
            var id = n.getAttribute('data-orbit-id');
            var slot = n.querySelector('[data-orbit-fav-slot]') || (n.tagName === 'TR' ? n.querySelector('td') : null);
            if (!slot) { return; }
            var b = mk('button', 'orbit-fav-btn', '<i class="bi bi-star"></i>');
            b.type = 'button';
            b.addEventListener('click', function (ev) { ev.stopPropagation(); toggleFav(kind, id); paintFavs(); sortFavs(); });
            slot.insertBefore(b, slot.firstChild);
        });
        paintFavs();
    }
    function paintFavs() {
        var nodes = doc.querySelectorAll('[data-orbit-nav][data-orbit-id]');
        Array.prototype.forEach.call(nodes, function (n) {
            var kind = n.getAttribute('data-orbit-kind') || 'item';
            var on = isFav(kind, n.getAttribute('data-orbit-id'));
            var b = n.querySelector('.orbit-fav-btn');
            if (b) {
                b.classList.toggle('is-on', on);
                b.innerHTML = '<i class="bi ' + (on ? 'bi-star-fill' : 'bi-star') + '"></i>';
            }
            n.classList.toggle('orbit-fav', on);
        });
    }
    function sortFavs() {
        var groups = {};
        Array.prototype.forEach.call(doc.querySelectorAll('[data-orbit-nav][data-orbit-id]'), function (n) {
            var key = n.getAttribute('data-orbit-kind') || 'item';
            (groups[key] = groups[key] || []).push(n);
        });
        Object.keys(groups).forEach(function (key) {
            var list = groups[key], parent = list[0] && list[0].parentNode;
            if (!parent || list.length < 2) { return; }
            var ordered = list.slice().sort(function (a, b) {
                var fa = isFav(key, a.getAttribute('data-orbit-id')) ? 0 : 1;
                var fb = isFav(key, b.getAttribute('data-orbit-id')) ? 0 : 1;
                if (fa !== fb) { return fa - fb; }
                return (a.compareDocumentPosition(b) & 4) ? -1 : 1;
            });
            ordered.forEach(function (n) { parent.appendChild(n); });
        });
    }

    /* ---------- 5) DENSITÉ, SIDEBAR REDIMENSIONNABLE, DATES RELATIVES ---------- */
    function toggleDensity(force) {
        var on = force !== undefined ? !!force : !doc.documentElement.classList.contains('orbit-compact');
        doc.documentElement.classList.toggle('orbit-compact', on);
        store.set('orbitCompact', on);
        Array.prototype.forEach.call(doc.querySelectorAll('[data-orbit-density]'), function (b) {
            b.classList.toggle('is-active', on);
        });
    }
    function initResizer() {
        var col = doc.getElementById('sidebarCol');
        if (!col) { return; }
        var saved = store.get('orbitSidebarWidth', 0);
        if (saved) { col.style.width = saved + 'px'; }
        var handle = mk('div', 'orbit-resizer');
        handle.title = 'Glisser pour redimensionner';
        col.appendChild(handle);
        var dragging = false;
        handle.addEventListener('mousedown', function (ev) {
            ev.preventDefault(); dragging = true;
            handle.classList.add('is-dragging');
            doc.body.classList.add('orbit-resizing');
        });
        handle.addEventListener('dblclick', function () { col.style.width = ''; store.set('orbitSidebarWidth', 0); });
        doc.addEventListener('mousemove', function (ev) {
            if (!dragging) { return; }
            col.style.width = Math.min(420, Math.max(170, ev.clientX - col.getBoundingClientRect().left)) + 'px';
        });
        doc.addEventListener('mouseup', function () {
            if (!dragging) { return; }
            dragging = false;
            handle.classList.remove('is-dragging');
            doc.body.classList.remove('orbit-resizing');
            store.set('orbitSidebarWidth', parseInt(col.style.width, 10) || 0);
        });
    }
    function humanWhen(iso) {
        var d = new Date(iso + 'T00:00:00');
        if (isNaN(d.getTime())) { return ''; }
        var days = Math.round((d - new Date(new Date().toDateString())) / 86400000);
        if (days === 0) { return "aujourd'hui"; }
        if (days === 1) { return 'demain'; }
        if (days === -1) { return 'hier'; }
        return days > 0 ? ('dans ' + days + ' j') : ('il y a ' + Math.abs(days) + ' j');
    }
    function initRelativeDates() {
        Array.prototype.forEach.call(doc.querySelectorAll('td'), function (td) {
            if (td.querySelector('.orbit-rel')) { return; }
            var m = (td.textContent || '').trim().match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
            if (!m) { return; }
            var when = humanWhen(m[3] + '-' + m[2] + '-' + m[1]);
            if (!when) { return; }
            var s = mk('span', 'orbit-rel', esc(when));
            if (/il y a/.test(when)) { s.classList.add('is-late'); }
            td.appendChild(doc.createTextNode(' '));
            td.appendChild(s);
        });
    }

    /* ---------- 6) BARRE D'OUTILS : compteur, filtres actifs ---------- */
    function initToolbar() {
        var bar = doc.querySelector('[data-orbit-toolbar]');
        if (!bar) { return; }
        var countEl = bar.querySelector('[data-orbit-count]');
        var chipsEl = bar.querySelector('[data-orbit-chips]');
        var unit = bar.getAttribute('data-orbit-unit') || 'élément(s)';
        var timer = null;
        function refresh() {
            if (countEl) {
                var n = 0;
                Array.prototype.forEach.call(doc.querySelectorAll('[data-orbit-nav]'), function (el) {
                    if (el.offsetParent !== null) { n++; }
                });
                countEl.innerHTML = '<strong>' + n + '</strong> ' + esc(unit);
            }
            if (chipsEl) {
                chipsEl.innerHTML = '';
                var chips = [];
                if (typeof window.orbitChips === 'function') {
                    try { chips = window.orbitChips() || []; } catch (e) { chips = []; }
                }
                chips.forEach(function (c) {
                    if (!c || !c.on || !c.label) { return; }
                    var chip = mk('span', 'orbit-chip is-active', esc(c.label));
                    var x = mk('button', '', '&times;');
                    x.type = 'button';
                    x.title = 'Retirer ce filtre';
                    x.addEventListener('click', function () { try { (new Function(c.clear))(); } catch (e) {} });
                    chip.appendChild(x);
                    chipsEl.appendChild(chip);
                });
                Array.prototype.forEach.call(doc.querySelectorAll('[data-orbit-chip-src]'), function (a) {
                    var on = a.classList.contains('is-active') || a.classList.contains('active') || a.classList.contains('on');
                    if (!on) { return; }
                    var chip = mk('span', 'orbit-chip is-active', esc(a.getAttribute('data-orbit-chip-src') || ''));
                    var x = mk('button', '', '&times;');
                    x.type = 'button';
                    x.title = 'Retirer ce filtre';
                    x.addEventListener('click', function () { a.click(); });
                    chip.appendChild(x);
                    chipsEl.appendChild(chip);
                });
            }
        }
        function schedule() { if (timer) { clearTimeout(timer); } timer = setTimeout(refresh, 140); }
        doc.addEventListener('click', schedule);
        doc.addEventListener('input', schedule);
        if (window.MutationObserver) { new MutationObserver(schedule).observe(bar, { childList: true, subtree: true }); }
        refresh();
    }

    /* ---------- 7) GUIDE DES RACCOURCIS ---------- */
    var help = null, helpBackdrop = null;
    var SHORTCUTS = [
        ['Recherche rapide', ['Ctrl', 'K']],
        ['Ligne / carte précédente', ['↑']],
        ['Ligne / carte suivante', ['↓']],
        ['Étendre la sélection', ['⇧', '↓']],
        ['Ouvrir le détail', ['→', 'Entrée']],
        ['Fermer le panneau', ['←', 'Échap']],
        ['Sélectionner', ['Espace']],
        ['Densité compacte / confort', ['d']],
        ['Thème clair / sombre', ['t']],
        ['Ce guide', ['?']]
    ];
    function ensureHelp() {
        if (help) { return; }
        helpBackdrop = mk('div', 'orbit-palette-backdrop');
        helpBackdrop.addEventListener('click', closeHelp);
        help = mk('div', 'orbit-help');
        var grid = SHORTCUTS.map(function (s) {
            return '<div class="orbit-help-row"><span>' + esc(s[0]) + '</span><span class="orbit-help-keys">' +
                s[1].map(function (k) { return '<kbd class="orbit-kbd">' + esc(k) + '</kbd>'; }).join('') + '</span></div>';
        }).join('');
        help.innerHTML = '<div class="orbit-help-head"><h3>Raccourcis clavier</h3>' +
            '<button type="button" class="orbit-drawer-close" style="margin-left:auto" data-close>&times;</button></div>' +
            '<div class="orbit-help-grid">' + grid + '</div>';
        help.querySelector('[data-close]').addEventListener('click', closeHelp);
        doc.body.appendChild(helpBackdrop);
        doc.body.appendChild(help);
    }
    function openHelp() { ensureHelp(); helpBackdrop.classList.add('is-open'); help.classList.add('is-open'); }
    function closeHelp() { if (!help) { return; } help.classList.remove('is-open'); helpBackdrop.classList.remove('is-open'); }
    function toggleHelp() { if (help && help.classList.contains('is-open')) { closeHelp(); } else { openHelp(); } }
    function togglePalette() { if (pal && pal.classList.contains('is-open')) { closePalette(); } else { openPalette(); } }

    /* ---------- 9) LOGO ORBIT INTERACTIF ----------
       Clavier (Entrée/Espace) + explosion de particules au clic.
       L'ouverture de la palette passe par [data-orbit-open-palette]
       (déjà géré dans le gestionnaire de clic global). */
    function initOrbitLogo() {
        Array.prototype.forEach.call(doc.querySelectorAll('.orbit-logo'), function (logo) {
            if (logo.dataset.orbitLogoInit) { return; }
            logo.dataset.orbitLogoInit = '1';
            logo.addEventListener('keydown', function (ev) {
                if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); openPalette(); }
            });
            logo.addEventListener('click', function () { logoBurst(logo); });
        });
    }
    function logoBurst(logo) {
        if (reduce) { return; }
        try {
            for (var i = 0; i < 10; i++) {
                (function (k) {
                    var p = doc.createElement('span');
                    p.className = 'orbit-logo-burst';
                    logo.appendChild(p);
                    var ang = (k / 10) * Math.PI * 2 + Math.random() * 0.4;
                    var dist = 22 + Math.random() * 20;
                    var dx = Math.cos(ang) * dist, dy = Math.sin(ang) * dist;
                    p.animate([
                        { transform: 'translate(-50%,-50%) scale(1)', opacity: 1 },
                        { transform: 'translate(calc(-50% + ' + dx + 'px), calc(-50% + ' + dy + 'px)) scale(0.2)', opacity: 0 }
                    ], { duration: 480 + Math.random() * 220, easing: 'cubic-bezier(.16,1,.3,1)' })
                    .onfinish = function () { if (p.parentNode) { p.parentNode.removeChild(p); } };
                })(i);
            }
        } catch (e) {}
    }

    /* ---------- 8) RACCOURCIS GLOBAUX + INITIALISATION ---------- */
    function isTyping(el) {
        if (!el) { return false; }
        var t = (el.tagName || '').toLowerCase();
        return t === 'input' || t === 'textarea' || t === 'select' || !!el.isContentEditable;
    }
    doc.addEventListener('keydown', function (ev) {
        var k = ev.key;
        if ((ev.ctrlKey || ev.metaKey) && (k === 'k' || k === 'K')) { ev.preventDefault(); togglePalette(); return; }
        if (k === 'Escape') {
            if (pal && pal.classList.contains('is-open')) { closePalette(); return; }
            if (help && help.classList.contains('is-open')) { closeHelp(); return; }
            if (drawer && drawer.classList.contains('is-open')) { closeDrawer(); return; }
            closeCursor();
            return;
        }
        if (k === '?') { ev.preventDefault(); toggleHelp(); return; }
        if (isTyping(ev.target) || ev.ctrlKey || ev.metaKey || ev.altKey) { return; }
        if (k === 'ArrowDown') { ev.preventDefault(); moveCursor(1, ev.shiftKey); }
        else if (k === 'ArrowUp') { ev.preventDefault(); moveCursor(-1, ev.shiftKey); }
        else if (k === 'ArrowRight' || k === 'Enter') {
            if (doc.querySelector('[data-orbit-nav].orbit-cursor')) { ev.preventDefault(); openCursorDetail(); }
        } else if (k === 'ArrowLeft') {
            if (drawer && drawer.classList.contains('is-open')) { ev.preventDefault(); closeDrawer(); }
        } else if (k === ' ') {
            var cur = doc.querySelector('[data-orbit-nav].orbit-cursor');
            if (cur) { ev.preventDefault(); toggleSelect(cur); }
        } else if (k === 'd' || k === 'D') { toggleDensity(); }
        else if (k === 't' || k === 'T') { if (window.toggleTheme) { window.toggleTheme(); } }
    });

    doc.addEventListener('click', function (ev) {
        if (ev.target.closest('[data-orbit-open-palette]')) { ev.preventDefault(); openPalette(); return; }
        var nav = ev.target.closest('[data-orbit-nav]');
        if (!nav) { return; }
        if (ev.target.closest('a, button, input, select, textarea, form, .dropdown, label')) { return; }
        ev.preventDefault();
        openDrawer(nav);
    });

    function init() {
        toggleDensity(!!store.get('orbitCompact', false));
        initResizer();
        injectFavButtons();
        sortFavs();
        initRelativeDates();
        initToolbar();
        initOrbitLogo();
        window.orbitWorkspace = {
            openPalette: openPalette, openDrawer: openDrawer,
            toggleDensity: toggleDensity, toggleHelp: toggleHelp
        };
    }
    if (doc.readyState === 'loading') { doc.addEventListener('DOMContentLoaded', init); } else { init(); }
})();
