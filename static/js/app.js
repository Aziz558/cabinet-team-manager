/**
 * Cabinet JMH — Premium Animations & UX
 * GSAP-powered scroll animations, floating cards, micro-interactions
 */

(function () {
  'use strict';

  // ─── Wait for DOM ──────────────────────────────────────────────
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  function init() {
    // Only run GSAP if the library loaded
    if (typeof gsap === 'undefined') return;

    registerScrollTrigger();
    animateCards();
    animateFadeIns();
    animateStats();
    animateNavbar();
    animateTooltips();
    initParticles();
    initMagneticButtons();
    initTypewriter();
    smoothScroll();
  }

  // ─── Register ScrollTrigger plugin ─────────────────────────────
  function registerScrollTrigger() {
    if (typeof ScrollTrigger !== 'undefined') {
      gsap.registerPlugin(ScrollTrigger);
    }
  }

  // ─── Floating Card Effect (Équipe only) ──────────────────────
  function animateCards() {
    // Floating parallax cards on scroll — ONLY inside .equipe-cards-container
    gsap.utils.toArray('.equipe-cards-container .card-premium').forEach(function (card, i) {
      // Skip if already has a data attribute
      if (card.hasAttribute('data-animated')) return;
      card.setAttribute('data-animated', 'true');

      // Floating entrance on scroll
      if (typeof ScrollTrigger !== 'undefined') {
        var direction = i % 2 === 0 ? -30 : 30;
        gsap.fromTo(
          card,
          {
            y: 60 + direction,
            opacity: 0,
            scale: 0.95,
            rotateX: i % 2 === 0 ? 3 : -3,
          },
          {
            y: 0,
            opacity: 1,
            scale: 1,
            rotateX: 0,
            duration: 0.8,
            ease: 'power3.out',
            scrollTrigger: {
              trigger: card,
              start: 'top 85%',
              toggleActions: 'play none none reverse',
            },
          }
        );
      }

      // 3D Tilt on hover (floating card effect)
      card.addEventListener('mousemove', function (e) {
        var rect = card.getBoundingClientRect();
        var x = e.clientX - rect.left;
        var y = e.clientY - rect.top;
        var centerX = rect.width / 2;
        var centerY = rect.height / 2;
        var rotateX = (y - centerY) / 20;
        var rotateY = (centerX - x) / 20;

        gsap.to(card, {
          rotateX: rotateX,
          rotateY: rotateY,
          scale: 1.02,
          boxShadow: '0 20px 60px rgba(255,140,0,0.25)',
          duration: 0.4,
          ease: 'power2.out',
          overwrite: 'auto',
        });
      });

      card.addEventListener('mouseleave', function () {
        gsap.to(card, {
          rotateX: 0,
          rotateY: 0,
          scale: 1,
          boxShadow: 'var(--shadow-md)',
          duration: 0.5,
          ease: 'elastic.out(1, 0.4)',
          overwrite: 'auto',
        });
      });
    });
  }

  // ─── Fade-in stagger animations ────────────────────────────────
  function animateFadeIns() {
    gsap.utils.toArray('.animate-fade-in-up').forEach(function (el) {
      if (el.hasAttribute('data-animated-fade')) return;
      el.setAttribute('data-animated-fade', 'true');

      var delay = 0;
      if (el.classList.contains('stagger-1')) delay = 0.1;
      else if (el.classList.contains('stagger-2')) delay = 0.2;
      else if (el.classList.contains('stagger-3')) delay = 0.3;
      else if (el.classList.contains('stagger-4')) delay = 0.4;

      if (typeof ScrollTrigger !== 'undefined') {
        gsap.fromTo(
          el,
          { y: 40, opacity: 0 },
          {
            y: 0,
            opacity: 1,
            duration: 0.7,
            delay: delay,
            ease: 'power3.out',
            scrollTrigger: {
              trigger: el,
              start: 'top 88%',
              toggleActions: 'play none none reverse',
            },
          }
        );
      } else {
        // Fallback: simple reveal
        el.style.opacity = '0';
        el.style.transform = 'translateY(40px)';
        requestAnimationFrame(function () {
          el.style.transition = 'opacity 0.7s ease, transform 0.7s ease';
          el.style.opacity = '1';
          el.style.transform = 'translateY(0)';
        });
      }
    });
  }

  // ─── Stat counters animation ───────────────────────────────────
  function animateStats() {
    gsap.utils.toArray('.stat-card-value').forEach(function (el) {
      if (el.hasAttribute('data-counted')) return;
      el.setAttribute('data-counted', 'true');

      var target = parseInt(el.textContent.trim()) || 0;
      if (target === 0) return;

      if (typeof ScrollTrigger !== 'undefined') {
        ScrollTrigger.create({
          trigger: el,
          start: 'top 90%',
          onEnter: function () {
            gsap.fromTo(
              el,
              { textContent: 0 },
              {
                textContent: target,
                duration: 1.5,
                ease: 'power2.out',
                snap: { textContent: 1 },
                onUpdate: function () {
                  el.textContent = Math.round(parseFloat(el.textContent));
                },
              }
            );
          },
        });
      }
    });
  }

  // ─── Navbar animation on scroll ────────────────────────────────
  function animateNavbar() {
    var header = document.querySelector('.app-topbar');
    if (!header) return;

    var lastScroll = 0;
    window.addEventListener('scroll', function () {
      var currentScroll = window.pageYOffset || document.documentElement.scrollTop;

      // Hide/show on scroll direction
      if (currentScroll > 80) {
        if (currentScroll > lastScroll) {
          gsap.to(header, { y: -header.offsetHeight, duration: 0.3, ease: 'power2.in' });
        } else {
          gsap.to(header, { y: 0, duration: 0.3, ease: 'power2.out' });
        }
        header.classList.add('topbar-scrolled');
      } else {
        header.classList.remove('topbar-scrolled');
        gsap.to(header, { y: 0, duration: 0.2 });
      }
      lastScroll = currentScroll;
    });
  }

  // ─── Tooltip micro-interactions ───────────────────────────────
  function animateTooltips() {
    gsap.utils.toArray('[data-tooltip]').forEach(function (el) {
      el.addEventListener('mouseenter', function () {
        var tooltip = el.querySelector('.tooltip-inner') || el.nextElementSibling;
        if (tooltip && tooltip.classList.contains('tooltip-inner')) {
          gsap.fromTo(tooltip, { opacity: 0, y: 5 }, { opacity: 1, y: 0, duration: 0.2 });
        }
      });
    });
  }

  // ─── Floating particles effect (ambient) ──────────────────────
  function initParticles() {
    var container = document.querySelector('.particles-container');
    if (!container) {
      // Auto-create a subtle ambient particle layer on the body
      container = document.createElement('div');
      container.className = 'particles-container';
      container.style.cssText =
        'position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0;overflow:hidden;';
      document.body.appendChild(container);
    }

    var particleCount = 20;
    for (var i = 0; i < particleCount; i++) {
      var particle = document.createElement('div');
      var size = Math.random() * 4 + 2;
      particle.style.cssText =
        'position:absolute;width:' +
        size +
        'px;height:' +
        size +
        'px;background:rgba(255,140,0,' +
        (Math.random() * 0.15 + 0.05) +
        ');border-radius:50%;top:' +
        Math.random() * 100 +
        '%;left:' +
        Math.random() * 100 +
        '%;';
      container.appendChild(particle);

      gsap.to(particle, {
        y: -(Math.random() * 200 + 100),
        x: Math.random() * 100 - 50,
        opacity: 0,
        duration: Math.random() * 8 + 6,
        repeat: -1,
        delay: Math.random() * 5,
        ease: 'power1.out',
        onRepeat: function () {
          gsap.set(this.targets()[0], {
            y: 0,
            x: 0,
            opacity: Math.random() * 0.15 + 0.05,
            top: Math.random() * 100 + '%',
            left: Math.random() * 100 + '%',
          });
        },
      });
    }
  }

  // ─── Magnetic button effect ───────────────────────────────────
  function initMagneticButtons() {
    gsap.utils.toArray('.btn-premium').forEach(function (btn) {
      btn.addEventListener('mousemove', function (e) {
        var rect = btn.getBoundingClientRect();
        var x = e.clientX - rect.left - rect.width / 2;
        var y = e.clientY - rect.top - rect.height / 2;
        gsap.to(btn, {
          x: x * 0.15,
          y: y * 0.15,
          duration: 0.3,
          ease: 'power2.out',
          overwrite: 'auto',
        });
      });
      btn.addEventListener('mouseleave', function () {
        gsap.to(btn, {
          x: 0,
          y: 0,
          duration: 0.5,
          ease: 'elastic.out(1, 0.3)',
          overwrite: 'auto',
        });
      });
    });
  }

  // ─── Typewriter effect for headings ──────────────────────────
  function initTypewriter() {
    gsap.utils.toArray('.typewriter').forEach(function (el) {
      var text = el.textContent;
      el.textContent = '';
      el.style.visibility = 'visible';
      var chars = text.split('');
      var tl = gsap.timeline({ defaults: { duration: 0.03, ease: 'none' } });
      chars.forEach(function (char, i) {
        tl.to(
          {},
          {
            onComplete: function () {
              el.textContent += char;
            },
          }
        );
      });
    });
  }

  // ─── Smooth scroll for anchor links ──────────────────────────
  function smoothScroll() {
    document.querySelectorAll('a[href^="#"]').forEach(function (a) {
      a.addEventListener('click', function (e) {
        var target = document.querySelector(this.getAttribute('href'));
        if (target) {
          e.preventDefault();
          gsap.to(window, {
            scrollTo: { y: target, offsetY: 80 },
            duration: 0.8,
            ease: 'power3.inOut',
          });
        }
      });
    });
  }

  // ─── Re-run on page changes (Turbolinks/htmx compatibility) ──
  window.reinitAnimations = function () {
    if (typeof gsap === 'undefined') return;
    ScrollTrigger && ScrollTrigger.refresh();
    animateCards();
    animateFadeIns();
    animateStats();
  };

  // ─── Expose GSAP for debug ───────────────────────────────────
  window.gsap = gsap;

  console.log('Cabinet JMH — Premium animations loaded');
})();
