/**
 * Manga Translator Studio — Dedicated Animations & Visual FX Engine
 * Features:
 *   - Slow-Motion Mouse-Following Physics Engine (lerp 0.035)
 *   - Le Portail Holographique de Scanlation (Interactive Live Manga Before / After)
 *   - Cyber-Scan Neon Laser Blade with dynamic reveal
 *   - Background Vibration Grid & Parallax Manga SFX Badges
 *   - Hypnotic Reactive Patience Waves & Page Transitions
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
    const LERP_LASER = 0.045;     // Smooth laser tracking

    let mouseX = window.innerWidth * 0.5;
    let mouseY = window.innerHeight * 0.5;
    let currentX = mouseX;
    let currentY = mouseY;
    let slowX = mouseX;
    let slowY = mouseY;
    let isRunning = false;
    let rafId = null;

    // Laser Blade Position Tracking (15% to 85%)
    let laserTargetPos = 50;
    let laserCurrentPos = 50;
    let isMouseOverPortal = false;

    // DOM Elements Cache
    let ambientStage = null;
    let halo = null;
    let glyphs = [];
    let sfxBadges = [];
    let mangaPortal = null;
    let portalFrame = null;
    let portalSfxLeft = null;
    let portalSfxRight = null;
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
        mangaPortal = document.getElementById('manga-portal-hero');
        portalFrame = document.getElementById('portal-page-frame');
        portalSfxLeft = document.getElementById('portal-sfx-left');
        portalSfxRight = document.getElementById('portal-sfx-right');
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

        // Add subtle floating particles on desktop
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
            const size = Math.floor(3 + Math.random() * 5);
            p.style.width = `${size}px`;
            p.style.height = `${size}px`;
            p.style.left = `${Math.random() * 95}%`;
            p.style.top = `${Math.random() * 95}%`;
            p.style.opacity = (0.15 + Math.random() * 0.35).toFixed(2);
            p.dataset.depth = (0.01 + Math.random() * 0.03).toFixed(3);
            p.dataset.speed = (0.4 + Math.random() * 1.2).toFixed(2);
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
            const haloOffsetX = currentX - 290;
            const haloOffsetY = currentY - 290;
            halo.style.transform = `translate3d(${haloOffsetX.toFixed(1)}px, ${haloOffsetY.toFixed(1)}px, 0)`;
        }

        // 2. Parallax Drift on Manga Glyphs & Badges
        if (!isTouchDevice) {
            const centerX = winWidth * 0.5;
            const centerY = winHeight * 0.5;

            glyphs.forEach((g, idx) => {
                const depth = parseFloat(g.dataset.depth || '0.04');
                const offsetX = (slowX - centerX) * depth * 6;
                const offsetY = (slowY - centerY) * depth * 6;
                const rot = (normX * 10) * (idx % 2 === 0 ? 1 : -1);
                g.style.transform = `translate3d(${offsetX.toFixed(1)}px, ${offsetY.toFixed(1)}px, 0) rotate(${rot.toFixed(1)}deg)`;
            });

            sfxBadges.forEach((sfx, idx) => {
                const depth = parseFloat(sfx.dataset.depth || '1.0');
                const offsetX = (slowX - centerX) * depth * 0.03;
                const offsetY = (slowY - centerY) * depth * 0.03;
                const rot = (normX * 6) + (idx === 0 ? -6 : idx === 1 ? 4 : 2);
                sfx.style.transform = `translate3d(${offsetX.toFixed(1)}px, ${offsetY.toFixed(1)}px, 0) rotate(${rot.toFixed(1)}deg)`;
            });
        }

        // 3. Manga Portal Hero & Cyber-Scan Laser
        if (mangaPortal && uploadSection && !uploadSection.classList.contains('hidden') && !isTouchDevice) {
            // If mouse is not actively over portal, gently float laser with a sine wave
            if (!isMouseOverPortal) {
                laserTargetPos = 50 + Math.sin(timestamp * 0.0016) * 22;
            }

            // Lerp laser blade position smoothly
            laserCurrentPos += (laserTargetPos - laserCurrentPos) * LERP_LASER;
            mangaPortal.style.setProperty('--laser-pos', `${laserCurrentPos.toFixed(1)}%`);

            // 3D Portal Tilt
            const portalTiltX = (10 - normY * 14).toFixed(1);
            const portalTiltY = (-6 + normX * 16).toFixed(1);
            mangaPortal.style.transform = `perspective(1200px) rotateX(${portalTiltX}deg) rotateY(${portalTiltY}deg)`;

            // Floating Onomatopoeias reaction
            if (portalSfxLeft && portalSfxRight) {
                const sfxSpread = Math.abs(normX) * 12;
                portalSfxLeft.style.transform = `translate3d(${(-sfxSpread).toFixed(1)}px, 0, 0) rotate(-12deg)`;
                portalSfxRight.style.transform = `translate3d(${(sfxSpread).toFixed(1)}px, 0, 0) rotate(10deg)`;
            }
        }

        // 4. Hypnotic Patience Dynamics (Page Loader)
        if (pulseBubble && pageLoader && !pageLoader.classList.contains('hidden') && !isTouchDevice) {
            const pullX = normX * 20;
            const pullY = normY * 20;
            pulseBubble.style.transform = `translate3d(${pullX.toFixed(1)}px, ${pullY.toFixed(1)}px, 0)`;
        }

        // 5. Subtle Magnetic Tilt on Drop Zone
        if (dropZone && uploadSection && !uploadSection.classList.contains('hidden') && !isTouchDevice) {
            const tiltX = (-normY * 3.5).toFixed(2);
            const tiltY = (normX * 3.5).toFixed(2);
            dropZone.style.transform = `perspective(1200px) rotateX(${tiltX}deg) rotateY(${tiltY}deg)`;
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

            // Track cursor over dropZone to position the Cyber-Scan laser
            if (dropZone && uploadSection && !uploadSection.classList.contains('hidden')) {
                const rect = dropZone.getBoundingClientRect();
                const isInside = (
                    e.clientX >= rect.left && e.clientX <= rect.right &&
                    e.clientY >= rect.top && e.clientY <= rect.bottom
                );

                if (isInside) {
                    isMouseOverPortal = true;
                    const relX = ((e.clientX - rect.left) / Math.max(1, rect.width)) * 100;
                    // Clamp between 15% and 85% for aesthetically pleasing margins
                    laserTargetPos = Math.max(15, Math.min(85, relX));
                } else {
                    isMouseOverPortal = false;
                }
            }
        }, { passive: true });

        // Image Transitions
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
