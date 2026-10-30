/**
 * Manga Translator Studio — Dedicated Animations & Visual FX Engine
 * Authors: Antigravity UI/UX Specialist
 * Features:
 *   - Slow-Motion Mouse-Following Physics Engine (lerp 0.035)
 *   - Ambient Halo & 3D Parallax Manga Glyphs
 *   - Hypnotic Reactive Patience Waves during translation
 *   - 3D Magnetic Card Tilts & Glare
 *   - Silky Page Transitions & Button Ripples
 *   - Strict Reduced-Motion & Touch Ergonomics
 */

(function () {
    'use strict';

    // Prevent duplicate initialization
    if (window.__mangaAnimationsInitialized) {
        return;
    }
    window.__mangaAnimationsInitialized = true;

    // Accessibility check
    const prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const isTouchDevice = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0) || (window.matchMedia && window.matchMedia('(pointer: coarse)').matches);

    // State & Physics Constants
    const LERP_PRIMARY = 0.035;   // Soft weightless feel
    const LERP_DEEP = 0.018;      // Deeper secondary lag
    const LERP_FAST = 0.065;      // For responsive magnetic items

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
    let pageLoader = null;
    let pulseBubble = null;
    let progressBanner = null;
    let dropZone = null;
    let uploadSection = null;

    function initElements() {
        ambientStage = document.getElementById('slowmo-ambient-stage');
        halo = document.getElementById('slowmo-halo');
        glyphs = Array.from(document.querySelectorAll('.slowmo-glyph'));
        pageLoader = document.getElementById('page-loader');
        pulseBubble = document.getElementById('slowmo-pulse-bubble');
        progressBanner = document.getElementById('progress-banner');
        dropZone = document.getElementById('drop-zone');
        uploadSection = document.getElementById('upload-section');

        // Dynamically inject hypnotic ripple canvas into pageLoader if not already present
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
        const particleCount = 8;
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
            const haloOffsetX = currentX - 300;
            const haloOffsetY = currentY - 300;
            halo.style.transform = `translate3d(${haloOffsetX.toFixed(1)}px, ${haloOffsetY.toFixed(1)}px, 0)`;
        }

        // 2. Parallax Drift on Manga Glyphs & Particles
        if (glyphs.length > 0 && !isTouchDevice) {
            const centerX = winWidth * 0.5;
            const centerY = winHeight * 0.5;
            
            glyphs.forEach((g, idx) => {
                const depth = parseFloat(g.dataset.depth || '0.05');
                const offsetX = (slowX - centerX) * depth * 8;
                const offsetY = (slowY - centerY) * depth * 8;
                const rot = (normX * 14) * (idx % 2 === 0 ? 1 : -1);
                g.style.transform = `translate3d(${offsetX.toFixed(1)}px, ${offsetY.toFixed(1)}px, 0) rotate(${rot.toFixed(1)}deg)`;
            });

            // Particles floating drift
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

        // 3. Hypnotic Patience Dynamics (Page Loader & Banner)
        const isTranslating = (pageLoader && !pageLoader.classList.contains('hidden')) ||
                              (progressBanner && !progressBanner.classList.contains('hidden'));

        if (pulseBubble && pageLoader && !pageLoader.classList.contains('hidden') && !isTouchDevice) {
            const pullX = normX * 24;
            const pullY = normY * 24;
            pulseBubble.style.transform = `translate3d(${pullX.toFixed(1)}px, ${pullY.toFixed(1)}px, 0)`;
        }

        // 4. Subtle 3D Magnetic Tilt on Drop Zone
        if (dropZone && uploadSection && !uploadSection.classList.contains('hidden') && !isTouchDevice) {
            const tiltX = (-normY * 4.2).toFixed(2);
            const tiltY = (normX * 4.2).toFixed(2);
            dropZone.style.transform = `perspective(1100px) rotateX(${tiltX}deg) rotateY(${tiltY}deg)`;
        }

        rafId = requestAnimationFrame(physicsTick);
    }

    // Event Listeners for Mouse Tracking
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

        // Magnetic Thumbnails
        document.addEventListener('mouseover', (e) => {
            const thumb = e.target.closest('.thumbnail-item');
            if (thumb && !isTouchDevice) {
                thumb.style.willChange = 'transform, box-shadow';
            }
        });

        // Button Ripple Effect
        document.addEventListener('click', (e) => {
            const btn = e.target.closest('.btn');
            if (btn && !btn.disabled) {
                createButtonRipple(btn, e);
            }
        });

        // Manga Image Cross-Fade Interceptor
        setupImageTransitions();

        // Page Visibility Lifecycle: pause ticker when backgrounded to save 100% CPU/GPU
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
                // Ignore transparent data URIs
                if (img.src && img.src.startsWith('data:image/gif')) return;
                img.classList.remove('manga-page-fade');
                // Trigger reflow to restart CSS animation smoothly
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

    // Override global initSlowMotionMouseEngine so app.js calls this seamlessly
    window.initSlowMotionMouseEngine = function () {
        window.MangaAnimations.init();
    };

    // Auto-bootstrap on DOMContentLoaded
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            window.MangaAnimations.init();
        });
    } else {
        window.MangaAnimations.init();
    }
})();
