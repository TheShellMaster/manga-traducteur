/**
 * Manga Translator Studio — Dedicated Animations & Visual FX Engine
 * Features:
 *   - Slow-Motion Mouse-Following Physics Engine (lerp 0.035)
 *   - Background Vibration Grid & Parallax Manga SFX Badges
 *   - 3D Animated Manga Book with interactive cursor tracking
 *   - Hypnotic Reactive Patience Waves & Cyber-Scanner Laser FX
 *   - 3D Holographic Card Tilts & Glare
 *   - Silky Page Transitions & Button Ripples
 *   - Strict Reduced-Motion & Touch Ergonomics
 */

(function () {
    'use strict';

    if (window.__mangaAnimationsInitialized) {
        return;
    }
    window.__mangaAnimationsInitialized = true;

    // Accessibility & Hardware Detection
    const prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const isTouchDevice = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0) || (window.matchMedia && window.matchMedia('(pointer: coarse)').matches);

    // Physics Constants
    const LERP_PRIMARY = 0.035;   // Soft weightless feel
    const LERP_DEEP = 0.018;      // Secondary background lag
    const LERP_SFX = 0.028;       // Onomatopoeia floating lag

    let mouseX = window.innerWidth * 0.5;
    let mouseY = window.innerHeight * 0.5;
    let currentX = mouseX;
    let currentY = mouseY;
    let slowX = mouseX;
    let slowY = mouseY;
    let isRunning = false;
    let rafId = null;

    // DOM Elements Cache
    let ambientStage = null;
    let halo = null;
    let glyphs = [];
    let sfxBadges = [];
    let mangaBook = null;
    let pageLoader = null;
    let pulseBubble = null;
    let progressBanner = null;
    let dropZone = null;
    let uploadSection = null;
    let vibrationGrid = null;

    function initElements() {
        ambientStage = document.getElementById('slowmo-ambient-stage');
        halo = document.getElementById('slowmo-halo');
        glyphs = Array.from(document.querySelectorAll('.slowmo-glyph'));
        sfxBadges = Array.from(document.querySelectorAll('.manga-sfx-badge'));
        mangaBook = document.getElementById('manga-book-3d');
        pageLoader = document.getElementById('page-loader');
        pulseBubble = document.getElementById('slowmo-pulse-bubble');
        progressBanner = document.getElementById('progress-banner');
        dropZone = document.getElementById('drop-zone');
        uploadSection = document.getElementById('upload-section');
        vibrationGrid = document.getElementById('manga-vibration-grid');

        // Dynamically inject ripple canvas if not present
        if (pageLoader && !pageLoader.querySelector('.slowmo-ripple-canvas')) {
            const rippleCanvas = document.createElement('div');
            rippleCanvas.className = 'slowmo-ripple-canvas';
            rippleCanvas.innerHTML = `
                <div class="slowmo-ripple-ring"></div>
                <div class="slowmo-ripple-ring"></div>
                <div class="slowmo-ripple-ring"></div>
            `;
            if (pulseBubble) {
                pulseBubble.parentNode.insertBefore(rippleCanvas, pulseBubble);
            } else {
                pageLoader.appendChild(rippleCanvas);
            }
        }

        // Add subtle floating particles to the ambient stage if on desktop
        if (ambientStage && !isTouchDevice && !prefersReducedMotion) {
            setupFloatingParticles();
        }
    }

    function setupFloatingParticles() {
        const particleCount = 10;
        const container = document.createElement('div');
        container.className = 'slowmo-particle-container';

        for (let i = 0; i < particleCount; i++) {
            const p = document.createElement('div');
            p.className = 'slowmo-particle';
            const size = Math.floor(4 + Math.random() * 6);
            p.style.width = `${size}px`;
            p.style.height = `${size}px`;
            p.style.left = `${Math.random() * 95}%`;
            p.style.top = `${Math.random() * 95}%`;
            p.style.opacity = (0.2 + Math.random() * 0.4).toFixed(2);
            p.dataset.depth = (0.01 + Math.random() * 0.04).toFixed(3);
            p.dataset.speed = (0.5 + Math.random() * 1.5).toFixed(2);
            container.appendChild(p);
        }
        ambientStage.appendChild(container);
    }

    // Main Physics Animation Loop
    function physicsTick(timestamp) {
        if (!isRunning) return;

        // Smooth Lerp Calculations
        currentX += (mouseX - currentX) * LERP_PRIMARY;
        currentY += (mouseY - currentY) * LERP_PRIMARY;
        slowX += (mouseX - slowX) * LERP_DEEP;
        slowY += (mouseY - slowY) * LERP_DEEP;

        const winWidth = Math.max(1, window.innerWidth);
        const winHeight = Math.max(1, window.innerHeight);
        const normX = (currentX / winWidth) - 0.5;
        const normY = (currentY / winHeight) - 0.5;

        // 1. Smooth Halo Following
        if (halo && !isTouchDevice) {
            const haloOffsetX = currentX - 325;
            const haloOffsetY = currentY - 325;
            halo.style.transform = `translate3d(${haloOffsetX.toFixed(1)}px, ${haloOffsetY.toFixed(1)}px, 0)`;
        }

        // 2. Parallax Drift on Manga Glyphs, Onomatopoeias & Particles
        if (!isTouchDevice) {
            const centerX = winWidth * 0.5;
            const centerY = winHeight * 0.5;

            // Manga Glyphs
            glyphs.forEach((g, idx) => {
                const depth = parseFloat(g.dataset.depth || '0.05');
                const offsetX = (slowX - centerX) * depth * 8;
                const offsetY = (slowY - centerY) * depth * 8;
                const rot = (normX * 14) * (idx % 2 === 0 ? 1 : -1);
                g.style.transform = `translate3d(${offsetX.toFixed(1)}px, ${offsetY.toFixed(1)}px, 0) rotate(${rot.toFixed(1)}deg)`;
            });

            // Onomatopoeias (SFX) with 3D Parallax & slight tilt
            sfxBadges.forEach((sfx, idx) => {
                const depth = parseFloat(sfx.dataset.depth || '1.0');
                const offsetX = (slowX - centerX) * depth * 0.04;
                const offsetY = (slowY - centerY) * depth * 0.04;
                const rot = (normX * 8) + (idx === 0 ? -6 : idx === 1 ? 4 : 2);
                sfx.style.transform = `translate3d(${offsetX.toFixed(1)}px, ${offsetY.toFixed(1)}px, 0) rotate(${rot.toFixed(1)}deg)`;
            });

            // Ambient floating particles
            const particles = ambientStage ? ambientStage.querySelectorAll('.slowmo-particle') : [];
            particles.forEach((p, idx) => {
                const depth = parseFloat(p.dataset.depth || '0.02');
                const speed = parseFloat(p.dataset.speed || '1.0');
                const timeFactor = (timestamp * 0.001 * speed);
                const floatX = Math.sin(timeFactor + idx) * 12;
                const floatY = Math.cos(timeFactor + idx) * 12;
                const shiftX = (slowX - centerX) * depth * 15 + floatX;
                const shiftY = (slowY - centerY) * depth * 15 + floatY;
                p.style.transform = `translate3d(${shiftX.toFixed(1)}px, ${shiftY.toFixed(1)}px, 0)`;
            });
        }

        // 3. Manga Book 3D Interactive Reaction
        if (mangaBook && uploadSection && !uploadSection.classList.contains('hidden') && !isTouchDevice) {
            const bookTiltX = (24 - normY * 18).toFixed(1);
            const bookTiltY = (-20 + normX * 22).toFixed(1);
            mangaBook.style.transform = `rotateX(${bookTiltX}deg) rotateY(${bookTiltY}deg) rotateZ(3deg)`;
        }

        // 4. Hypnotic Patience Dynamics (Page Loader)
        if (pulseBubble && pageLoader && !pageLoader.classList.contains('hidden') && !isTouchDevice) {
            const pullX = normX * 26;
            const pullY = normY * 26;
            pulseBubble.style.transform = `translate3d(${pullX.toFixed(1)}px, ${pullY.toFixed(1)}px, 0)`;
        }

        // 5. 3D Magnetic Tilt on Drop Zone
        if (dropZone && uploadSection && !uploadSection.classList.contains('hidden') && !isTouchDevice) {
            const tiltX = (-normY * 4.5).toFixed(2);
            const tiltY = (normX * 4.5).toFixed(2);
            dropZone.style.transform = `perspective(1100px) rotateX(${tiltX}deg) rotateY(${tiltY}deg)`;
        }

        rafId = requestAnimationFrame(physicsTick);
    }

    // Event Listeners for User Interaction
    function setupInteractions() {
        if (prefersReducedMotion || isTouchDevice) {
            return;
        }

        window.addEventListener('mousemove', (e) => {
            mouseX = e.clientX;
            mouseY = e.clientY;

            // Update drop-zone sheen coordinates
            if (dropZone && uploadSection && !uploadSection.classList.contains('hidden')) {
                const rect = dropZone.getBoundingClientRect();
                const relX = ((e.clientX - rect.left) / Math.max(1, rect.width)) * 100;
                const relY = ((e.clientY - rect.top) / Math.max(1, rect.height)) * 100;
                dropZone.style.setProperty('--mouse-x', `${relX.toFixed(1)}%`);
                dropZone.style.setProperty('--mouse-y', `${relY.toFixed(1)}%`);
            }
        }, { passive: true });

        // Button Ripple Effect
        document.addEventListener('click', (e) => {
            const btn = e.target.closest('.btn');
            if (btn && !btn.disabled) {
                createButtonRipple(btn, e);
            }
        });

        // Manga Image Cross-Fade Interceptor
        setupImageTransitions();

        // Lifecycle: pause ticker when tab is backgrounded
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                isRunning = false;
                if (rafId) cancelAnimationFrame(rafId);
            } else {
                if (!isRunning && !prefersReducedMotion) {
                    isRunning = true;
                    rafId = requestAnimationFrame(physicsTick);
                }
            }
        });
    }

    function createButtonRipple(btn, event) {
        const rect = btn.getBoundingClientRect();
        const ripple = document.createElement('span');
        ripple.className = 'btn-ripple';
        const diameter = Math.max(rect.width, rect.height);
        const radius = diameter / 2;

        ripple.style.width = ripple.style.height = `${diameter}px`;
        ripple.style.left = `${event.clientX - rect.left - radius}px`;
        ripple.style.top = `${event.clientY - rect.top - radius}px`;

        btn.appendChild(ripple);
        ripple.addEventListener('animationend', () => ripple.remove(), { once: true });
    }

    function setupImageTransitions() {
        const imageIds = [
            'current-image',
            'img-original',
            'img-translated',
            'slider-image-before',
            'slider-image-after'
        ];

        imageIds.forEach((id) => {
            const img = document.getElementById(id);
            if (!img) return;

            img.addEventListener('load', () => {
                if (img.src && img.src.startsWith('data:image/gif')) return;
                img.classList.remove('manga-page-fade');
                void img.offsetWidth;
                img.classList.add('manga-page-fade');
            });
        });
    }

    // Public API
    window.MangaAnimations = {
        init: function () {
            initElements();
            if (!prefersReducedMotion) {
                isRunning = true;
                rafId = requestAnimationFrame(physicsTick);
            }
            setupInteractions();
        },
        triggerPageTransition: function (targetElement) {
            if (!targetElement) return;
            targetElement.classList.remove('manga-page-fade');
            void targetElement.offsetWidth;
            targetElement.classList.add('manga-page-fade');
        }
    };

    window.initSlowMotionMouseEngine = function () {
        window.MangaAnimations.init();
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            window.MangaAnimations.init();
        });
    } else {
        window.MangaAnimations.init();
    }
})();
