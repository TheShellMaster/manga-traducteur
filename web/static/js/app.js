let currentSession = null;
let currentPageIndex = 0;
let pollInterval = null;
let viewMode = 'split'; // 'split', 'single', 'slider', or 'webtoon'
let zoomLevel = 100;
let fitWidthMode = false;
let isRtlMode = false; // Reading direction: false = LTR, true = RTL (Manga)
let translationStartTime = null;

// DOM Elements
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const folderInput = document.getElementById('folder-input');
const uploadSection = document.getElementById('upload-section');
const workspaceSection = document.getElementById('workspace-section');

const badgeFilename = document.getElementById('badge-filename');
const badgePages = document.getElementById('badge-pages');
const imgOriginal = document.getElementById('img-original');
const imgTranslated = document.getElementById('img-translated');
const colOriginal = document.getElementById('col-original');
const colTranslated = document.getElementById('col-translated');
const pageLoader = document.getElementById('page-loader');

const sliderCompareContainer = document.getElementById('slider-compare-container');
const sliderStage = document.getElementById('slider-stage');
const sliderImgOrig = document.getElementById('slider-img-orig');
const sliderImgTrans = document.getElementById('slider-img-trans');
const sliderHandle = document.getElementById('slider-handle');

const readerArea = document.getElementById('reader-area');
const readerStage = document.getElementById('reader-stage');
const btnPrev = document.getElementById('btn-prev-page');
const btnNext = document.getElementById('btn-next-page');
const stripCounter = document.getElementById('strip-counter');
const thumbnailStrip = document.getElementById('thumbnail-strip');

const btnStart = document.getElementById('btn-start-translation');
const btnRetranslatePage = document.getElementById('btn-retranslate-page');
const btnCancelTranslation = document.getElementById('btn-cancel-translation');
const btnDownload = document.getElementById('btn-download');
const lblDownload = document.getElementById('lbl-download');

const progressBanner = document.getElementById('progress-banner');
const progressTitle = document.getElementById('progress-title');
const progressStats = document.getElementById('progress-stats');
const progressEta = document.getElementById('progress-eta');
const progressLog = document.getElementById('progress-log');
const progressPercent = document.getElementById('progress-percent');
const progressFill = document.getElementById('progress-fill');

const viewSplit = document.getElementById('view-mode-split');
const viewSingle = document.getElementById('view-mode-single');
const viewSlider = document.getElementById('view-mode-slider');
const viewWebtoon = document.getElementById('view-mode-webtoon');
const webtoonScrollContainer = document.getElementById('webtoon-scroll-container');
const btnReadingDir = document.getElementById('btn-reading-dir');
const chkShowTranslated = document.getElementById('chk-show-translated');
const versionToggleWrap = document.getElementById('version-toggle-wrap');

// Settings modal elements
const btnOpenSettings = document.getElementById('btn-open-settings');
const btnCloseSettings = document.getElementById('btn-close-settings');
const settingsModal = document.getElementById('settings-modal');
const btnSaveSettings = document.getElementById('btn-save-settings');
const btnThemeToggle = document.getElementById('btn-theme-toggle');
const themeIcon = document.getElementById('theme-icon');

// Toast notification system
function showToast(message, type = 'info', duration = 4000) {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    const icon = { success: '✅', error: '❌', info: 'ℹ️', warning: '⚠️' }[type] || 'ℹ️';
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `<span>${icon}</span><span>${message}</span><button class="toast-close" aria-label="Fermer la notification" onclick="this.parentElement.classList.add('toast-out'); setTimeout(() => this.parentElement.remove(), 300)">×</button>`;
    container.appendChild(toast);
    setTimeout(() => {
        toast.classList.add('toast-out');
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

// Badge status helpers (including error status)
function getBadgeClass(status) {
    if (status === 'done') return 'badge-done';
    if (status === 'processing') return 'badge-proc';
    if (status === 'error') return 'badge-err';
    return 'badge-pend';
}

function getBadgeText(status, idx) {
    if (status === 'done') return '✓';
    if (status === 'processing') return '⚡';
    if (status === 'error') return '✗';
    return `${idx + 1}`;
}

function updateDownloadButtonLabel(fmt) {
    if (!lblDownload) return;
    const f = (fmt || 'cbz').toLowerCase();
    if (f === 'rar' || f === 'cbr') {
        lblDownload.textContent = 'Télécharger CBR/RAR';
    } else if (f === 'image') {
        lblDownload.textContent = 'Télécharger Image';
    } else {
        lblDownload.textContent = 'Télécharger CBZ';
    }
}

function getProviderOptionsPayload() {
    const provider = document.getElementById('cfg-provider').value;
    let apiKey = '';
    if (provider === 'gemini') {
        apiKey = document.getElementById('cfg-gemini-key').value.trim();
    } else if (provider === 'openrouter') {
        apiKey = document.getElementById('cfg-openrouter-key').value.trim();
    } else if (provider === 'custom') {
        apiKey = document.getElementById('cfg-custom-api-key').value.trim();
    }
    // Only send base_url and model if provider === 'custom'
    const baseUrl = provider === 'custom' ? document.getElementById('cfg-custom-base-url').value.trim() : '';
    const model = provider === 'custom' ? document.getElementById('cfg-custom-model').value.trim() : '';

    return {
        provider,
        api_key: apiKey,
        base_url: baseUrl,
        model: model,
        src_lang: document.getElementById('cfg-src-lang').value,
        tgt_lang: document.getElementById('cfg-tgt-lang').value,
        font_style: document.getElementById('cfg-font-style').value,
        fixed_font_size: parseInt(document.getElementById('cfg-font-size').value, 10) || 0,
        text_color: document.getElementById('cfg-text-color').value,
        mask_style: document.getElementById('cfg-mask-style').value,
    };
}

// Initial setup
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initDragAndDrop();
    initSettings();
    initNavigation();
    initViewModes();
    initSliderCompare();
    initZoomAndFullscreen();
    initSlowMotionMouseEngine();
});

// Theme Toggle (Light / Dark) stored in localStorage
function initTheme() {
    const saved = localStorage.getItem('manga_theme') || 'dark';
    applyTheme(saved);
    if (btnThemeToggle) {
        btnThemeToggle.addEventListener('click', () => {
            const current = document.body.classList.contains('light-theme') ? 'light' : 'dark';
            const next = current === 'dark' ? 'light' : 'dark';
            localStorage.setItem('manga_theme', next);
            applyTheme(next);
        });
    }
}

function applyTheme(theme) {
    if (theme === 'light') {
        document.body.classList.remove('dark-theme');
        document.body.classList.add('light-theme');
        if (themeIcon) themeIcon.textContent = '☀️';
    } else {
        document.body.classList.remove('light-theme');
        document.body.classList.add('dark-theme');
        if (themeIcon) themeIcon.textContent = '🌙';
    }
}

// Drag & Drop + File & Folder Uploads
function initDragAndDrop() {
    ['dragenter', 'dragover'].forEach(name => {
        dropZone.addEventListener(name, (e) => {
            e.preventDefault();
            dropZone.classList.add('dragover');
        });
    });

    dropZone.addEventListener('dragleave', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        const files = e.dataTransfer.files;
        if (files.length > 1) {
            handleFolderUpload(files);
        } else if (files.length === 1) {
            handleFileUpload(files[0]);
        }
    });

    bindUploadInputs();
}

function bindUploadInputs() {
    const fInput = document.getElementById('file-input');
    if (fInput) {
        fInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) handleFileUpload(e.target.files[0]);
        });
    }
    const dInput = document.getElementById('folder-input');
    if (dInput) {
        dInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) handleFolderUpload(e.target.files);
        });
    }
    const btnFiles = document.getElementById('btn-browse-files');
    if (btnFiles && fInput) {
        btnFiles.addEventListener('click', () => fInput.click());
    }
    const btnFolder = document.getElementById('btn-browse-folder');
    if (btnFolder && dInput) {
        btnFolder.addEventListener('click', () => dInput.click());
    }
}

function getDropZoneDefaultHTML() {
    return `
        <input type="file" id="file-input" accept=".cbz,.cbr,.rar,.zip,.png,.jpg,.jpeg,.webp" class="file-input-hidden">
        <input type="file" id="folder-input" webkitdirectory directory multiple class="file-input-hidden">
        <div class="drop-illustration"><div class="manga-icon-animated" aria-hidden="true">📖</div></div>
        <h2>Glissez-déposez votre Manga ici</h2>
        <p>Importez vos chapitres complets ou pages individuelles en un clic</p>
        <div class="upload-buttons-row">
            <button type="button" id="btn-browse-files" class="btn btn-primary btn-lg">📄 Parcourir un Fichier</button>
            <button type="button" id="btn-browse-folder" class="btn btn-secondary btn-lg">📁 Importer un Dossier</button>
        </div>
        <div class="format-cards">
            <div class="format-card"><span class="fmt-ext">CBZ / ZIP</span><span class="fmt-desc">Archive standard</span></div>
            <div class="format-card"><span class="fmt-ext">CBR / RAR</span><span class="fmt-desc">Extraction native</span></div>
            <div class="format-card"><span class="fmt-ext">DOSSIER</span><span class="fmt-desc">Chapitre complet</span></div>
            <div class="format-card"><span class="fmt-ext">PNG / JPG / WEBP</span><span class="fmt-desc">Page unitaire</span></div>
        </div>
        <div class="features-row">
            <span>⚡ Zéro modèle local (< 50 Mo RAM)</span>
            <span>🌐 Traduction Cloud Vision</span>
            <span>🔒 Restitution au format exact</span>
        </div>
    `;
}

function activateSessionWorkspace(data) {
    currentSession = data;
    currentPageIndex = 0;

    uploadSection.classList.add('hidden');
    workspaceSection.classList.remove('hidden');

    badgeFilename.textContent = data.filename;
    badgePages.textContent = `${data.total_pages} page${data.total_pages > 1 ? 's' : ''}`;
    updateDownloadButtonLabel(data.format);

    renderThumbnails();
    renderWebtoonPages();
    loadPage(0);
}

async function handleFileUpload(file) {
    const formData = new FormData();
    formData.append('file', file);

    dropZone.innerHTML = `
        <div class="spinner-manga" style="margin: 0 auto 16px auto; width: 40px; height: 40px;"></div>
        <h2>Décompression et indexation de ${file.name}...</h2>
        <p>Veuillez patienter quelques instants</p>
    `;

    try {
        const res = await fetch('/api/upload', {
            method: 'POST',
            body: formData,
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Erreur de chargement");
        }

        const data = await res.json();
        activateSessionWorkspace(data);
        showToast(`Manga "${data.filename}" chargé (${data.total_pages} pages)`, 'success');
    } catch (e) {
        dropZone.innerHTML = getDropZoneDefaultHTML();
        bindUploadInputs();
        showToast("Erreur lors de l'envoi : " + e.message, 'error');
    }
}

async function handleFolderUpload(fileList) {
    const formData = new FormData();
    for (let i = 0; i < fileList.length; i++) {
        const f = fileList[i];
        const relPath = f.webkitRelativePath || f.name;
        formData.append('files', f, relPath);
    }

    dropZone.innerHTML = `
        <div class="spinner-manga" style="margin: 0 auto 16px auto; width: 40px; height: 40px;"></div>
        <h2>Importation du dossier (${fileList.length} fichiers)...</h2>
        <p>Tri naturel et extraction des pages</p>
    `;

    try {
        const res = await fetch('/api/upload_folder', {
            method: 'POST',
            body: formData,
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Erreur de chargement du dossier");
        }

        const data = await res.json();
        activateSessionWorkspace(data);
        showToast(`Dossier "${data.filename}" importé (${data.total_pages} pages)`, 'success');
    } catch (e) {
        dropZone.innerHTML = getDropZoneDefaultHTML();
        bindUploadInputs();
        showToast("Erreur lors de l'import du dossier : " + e.message, 'error');
    }
}

// Navigation & Reader
function initNavigation() {
    btnPrev.addEventListener('click', () => {
        if (currentPageIndex > 0) loadPage(currentPageIndex - 1);
    });

    btnNext.addEventListener('click', () => {
        if (currentSession && currentPageIndex < currentSession.total_pages - 1) {
            loadPage(currentPageIndex + 1);
        }
    });

    document.addEventListener('keydown', (e) => {
        if (workspaceSection.classList.contains('hidden')) return;
        const tag = (e.target && e.target.tagName) ? e.target.tagName.toLowerCase() : '';
        if (tag === 'input' || tag === 'select' || tag === 'textarea') return;

        if (e.key === 'ArrowLeft') {
            isRtlMode ? btnNext.click() : btnPrev.click();
        } else if (e.key === 'ArrowRight') {
            isRtlMode ? btnPrev.click() : btnNext.click();
        } else if (e.key === '1') viewSplit.click();
        else if (e.key === '2') viewSingle.click();
        else if (e.key === '3' && viewSlider) viewSlider.click();
        else if (e.key === '4' && viewWebtoon) viewWebtoon.click();
        else if ((e.key === 'r' || e.key === 'R') && btnReadingDir) btnReadingDir.click();
        else if (e.key === 'f' || e.key === 'F') toggleFullscreen();
    });

    if (btnReadingDir) {
        btnReadingDir.addEventListener('click', () => {
            isRtlMode = !isRtlMode;
            btnReadingDir.textContent = isRtlMode ? '🇯🇵 RTL ←' : '🌍 LTR →';
            btnReadingDir.classList.toggle('active', isRtlMode);
            if (readerStage) readerStage.classList.toggle('rtl-mode', isRtlMode);
            showToast(
                isRtlMode
                    ? 'Sens de lecture Manga activé (Droite → Gauche)'
                    : 'Sens de lecture Occidental activé (Gauche → Droite)',
                'info',
                2500
            );
        });
    }

    // Reset button (Nouveau manga)
    const btnNewManga = document.getElementById('btn-new-manga');
    if (btnNewManga) {
        btnNewManga.addEventListener('click', () => {
            if (pollInterval) clearInterval(pollInterval);
            currentSession = null;
            currentPageIndex = 0;
            uploadSection.classList.remove('hidden');
            workspaceSection.classList.add('hidden');
            progressBanner.classList.add('hidden');
            btnStart.classList.remove('hidden');
            btnDownload.classList.add('hidden');
            dropZone.innerHTML = getDropZoneDefaultHTML();
            bindUploadInputs();
            showToast('Prêt pour un nouveau manga !', 'info');
        });
    }

    // Retranslate current page button
    if (btnRetranslatePage) {
        btnRetranslatePage.addEventListener('click', async () => {
            if (!currentSession) return;
            const idx = currentPageIndex;
            btnRetranslatePage.disabled = true;
            pageLoader.classList.remove('hidden');
            showToast(`Retraduction de la page ${idx + 1} lancée...`, 'info');

            try {
                const opts = getProviderOptionsPayload();
                const res = await fetch(`/api/translate/page/${currentSession.session_id}/${idx}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(opts),
                });
                const data = await res.json();
                if (!res.ok || data.status === 'error') {
                    currentSession.pages[idx].status = 'error';
                    updateThumbnailBadge(idx, 'error');
                    showToast(`Échec page ${idx + 1} : ${data.error || 'Erreur API'}`, 'error');
                } else {
                    currentSession.pages[idx].status = 'done';
                    currentSession.pages[idx].blocks = data.blocks || [];
                    updateThumbnailBadge(idx, 'done');
                    showToast(`Page ${idx + 1} retraduite (${data.blocks_count} bulles)`, 'success');
                }
                loadPage(idx);
            } catch (err) {
                showToast(`Erreur retraduction : ${err.message}`, 'error');
            } finally {
                pageLoader.classList.add('hidden');
                btnRetranslatePage.disabled = false;
            }
        });
    }

    // Live Bubble Editor controls
    const btnToggleBubbles = document.getElementById('btn-toggle-bubbles');
    const btnCloseBubbles = document.getElementById('btn-close-bubbles');
    const btnApplyBubbles = document.getElementById('btn-apply-bubbles');
    const bubblePanel = document.getElementById('bubble-editor-panel');

    if (btnToggleBubbles && bubblePanel) {
        btnToggleBubbles.addEventListener('click', () => {
            bubblePanel.classList.toggle('hidden');
            if (!bubblePanel.classList.contains('hidden')) {
                renderBubbleEditor(currentPageIndex);
            }
        });
    }
    if (btnCloseBubbles && bubblePanel) {
        btnCloseBubbles.addEventListener('click', () => {
            bubblePanel.classList.add('hidden');
        });
    }
    if (btnApplyBubbles) {
        btnApplyBubbles.addEventListener('click', async () => {
            if (!currentSession) return;
            const page = currentSession.pages[currentPageIndex];
            const blocks = (page && page.blocks) ? page.blocks : [];
            if (!blocks.length) {
                showToast("Aucune bulle à mettre à jour sur cette page", "info");
                return;
            }
            const updatedBlocks = blocks.map((b, i) => {
                const ta = document.getElementById(`bubble-edit-ta-${i}`);
                const newText = ta ? ta.value.trim() : (b.fr || b.translation || '');
                return {
                    ...b,
                    fr: newText,
                    translation: newText,
                };
            });
            btnApplyBubbles.disabled = true;
            try {
                const opts = getProviderOptionsPayload();
                const res = await fetch(`/api/rerender/${currentSession.session_id}/${currentPageIndex}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        blocks: updatedBlocks,
                        font_style: opts.font_style,
                        fixed_font_size: opts.fixed_font_size,
                        text_color: opts.text_color,
                        mask_style: opts.mask_style,
                    }),
                });
                const data = await res.json();
                if (res.ok && data.status === 'done') {
                    currentSession.pages[currentPageIndex].blocks = data.blocks || updatedBlocks;
                    const freshUrl = `/api/image/${currentSession.session_id}/translated/${currentPageIndex}?t=${Date.now()}`;
                    imgTranslated.src = freshUrl;
                    if (sliderImgTrans) sliderImgTrans.src = freshUrl;
                    showToast(`Bulles appliquées en ${data.elapsed_ms || '<50'} ms ✓`, 'success');
                } else {
                    showToast("Erreur lors du rendu des bulles", "error");
                }
            } catch (err) {
                showToast("Erreur réseau : " + err.message, "error");
            } finally {
                btnApplyBubbles.disabled = false;
            }
        });
    }

    // Cancel translation button
    if (btnCancelTranslation) {
        btnCancelTranslation.addEventListener('click', async () => {
            if (!currentSession) return;
            try {
                await fetch(`/api/translate/cancel/${currentSession.session_id}`, { method: 'POST' });
                if (pollInterval) clearInterval(pollInterval);
                progressTitle.textContent = "Traduction annulée";
                btnStart.classList.remove('hidden');
                showToast("Traduction annulée", 'warning');
            } catch (err) {
                showToast("Erreur lors de l'annulation", 'error');
            }
        });
    }
}

function updateThumbnailBadge(idx, status) {
    const b = document.getElementById(`badge-st-${idx}`);
    if (b) {
        b.className = `thumb-badge ${getBadgeClass(status)}`;
        b.textContent = getBadgeText(status, idx);
    }
}

function preloadNextPage(index) {
    if (!currentSession || index + 1 >= currentSession.total_pages) return;
    const nextIdx = index + 1;
    const preOrig = new Image();
    preOrig.src = `/api/image/${currentSession.session_id}/original/${nextIdx}`;
    if (currentSession.pages[nextIdx].status === 'done') {
        const preTrans = new Image();
        preTrans.src = `/api/image/${currentSession.session_id}/translated/${nextIdx}`;
    }
}

function loadPage(index) {
    if (!currentSession) return;
    currentPageIndex = index;
    stripCounter.textContent = `${index + 1} / ${currentSession.total_pages}`;

    if (btnPrev) btnPrev.disabled = (index <= 0);
    if (btnNext) btnNext.disabled = (index >= currentSession.total_pages - 1);

    // Subtle transition effect
    if (readerStage) {
        readerStage.classList.add('page-fade');
        setTimeout(() => readerStage.classList.remove('page-fade'), 150);
    }

    document.querySelectorAll('.thumb-item').forEach((el, idx) => {
        el.classList.toggle('active', idx === index);
    });

    const origUrl = `/api/image/${currentSession.session_id}/original/${index}`;
    const transUrl = `/api/image/${currentSession.session_id}/translated/${index}?t=${Date.now()}`;

    imgOriginal.src = origUrl;
    if (sliderImgOrig) sliderImgOrig.src = origUrl;

    const pageStatus = currentSession.pages[index].status;
    if (pageStatus === 'done') {
        pageLoader.classList.add('hidden');
        imgTranslated.src = transUrl;
        if (sliderImgTrans) sliderImgTrans.src = transUrl;
    } else if (pageStatus === 'processing') {
        pageLoader.classList.remove('hidden');
        imgTranslated.src = origUrl;
        if (sliderImgTrans) sliderImgTrans.src = origUrl;
    } else {
        pageLoader.classList.add('hidden');
        imgTranslated.src = origUrl;
        if (sliderImgTrans) sliderImgTrans.src = origUrl;
    }

    const activeThumb = document.getElementById(`thumb-${index}`);
    if (activeThumb) {
        activeThumb.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
    }

    renderBubbleEditor(index);
    preloadNextPage(index);
}

function renderBubbleEditor(index) {
    const countLbl = document.getElementById('lbl-bubbles-count');
    const listEl = document.getElementById('bubble-editor-list');
    if (!currentSession || !currentSession.pages[index]) {
        if (countLbl) countLbl.textContent = '0';
        return;
    }
    const blocks = currentSession.pages[index].blocks || [];
    if (countLbl) countLbl.textContent = String(blocks.length);
    if (!listEl) return;

    if (!blocks.length) {
        listEl.innerHTML = '<p class="box-hint">Aucune bulle détectée sur cette page pour le moment.</p>';
        return;
    }

    listEl.innerHTML = blocks.map((b, i) => {
        const orig = (b.ja || b.original || '').replace(/</g, '&lt;');
        const trans = (b.fr || b.translation || '').replace(/</g, '&lt;');
        return `
            <div class="bubble-edit-item">
                <div class="bubble-edit-meta">#${i + 1} <span class="bubble-orig-text">${orig}</span></div>
                <textarea id="bubble-edit-ta-${i}" class="form-input bubble-edit-ta" rows="2">${trans}</textarea>
            </div>
        `;
    }).join('');
}

function renderThumbnails() {
    thumbnailStrip.innerHTML = '';
    currentSession.pages.forEach((p, idx) => {
        const div = document.createElement('div');
        div.className = `thumb-item ${idx === currentPageIndex ? 'active' : ''}`;
        div.id = `thumb-${idx}`;

        const statusClass = getBadgeClass(p.status);
        const statusText = getBadgeText(p.status, idx);

        div.innerHTML = `
            <img src="/api/image/${currentSession.session_id}/original/${idx}" loading="lazy" alt="Miniature page ${idx + 1}">
            <span class="thumb-badge ${statusClass}" id="badge-st-${idx}">${statusText}</span>
        `;

        div.addEventListener('click', () => loadPage(idx));
        thumbnailStrip.appendChild(div);
    });
}

function renderWebtoonPages() {
    if (!webtoonScrollContainer || !currentSession) return;
    webtoonScrollContainer.innerHTML = '';
    currentSession.pages.forEach((p, idx) => {
        const img = document.createElement('img');
        img.className = 'webtoon-page-img';
        img.id = `webtoon-img-${idx}`;
        img.loading = 'lazy';
        img.alt = `Page ${idx + 1}`;
        const isDone = p.status === 'done';
        img.src = isDone
            ? `/api/image/${currentSession.session_id}/translated/${idx}?t=${Date.now()}`
            : `/api/image/${currentSession.session_id}/original/${idx}`;
        img.addEventListener('click', () => {
            currentPageIndex = idx;
            stripCounter.textContent = `${idx + 1} / ${currentSession.total_pages}`;
        });
        webtoonScrollContainer.appendChild(img);
    });
}

// View Modes (Split vs Single vs Slider vs Webtoon)
function initViewModes() {
    function clearActiveViewModes() {
        viewSplit.classList.remove('active');
        viewSingle.classList.remove('active');
        if (viewSlider) viewSlider.classList.remove('active');
        if (viewWebtoon) viewWebtoon.classList.remove('active');
        versionToggleWrap.classList.add('hidden');
        if (sliderCompareContainer) sliderCompareContainer.classList.add('hidden');
        if (webtoonScrollContainer) webtoonScrollContainer.classList.add('hidden');
    }

    viewSplit.addEventListener('click', () => {
        viewMode = 'split';
        clearActiveViewModes();
        viewSplit.classList.add('active');

        colOriginal.style.display = 'flex';
        colOriginal.style.maxWidth = '50%';
        colTranslated.style.display = 'flex';
        colTranslated.style.maxWidth = '50%';
    });

    viewSingle.addEventListener('click', () => {
        viewMode = 'single';
        clearActiveViewModes();
        viewSingle.classList.add('active');
        versionToggleWrap.classList.remove('hidden');

        updateSingleView();
    });

    if (viewSlider) {
        viewSlider.addEventListener('click', () => {
            viewMode = 'slider';
            clearActiveViewModes();
            viewSlider.classList.add('active');

            colOriginal.style.display = 'none';
            colTranslated.style.display = 'none';
            if (sliderCompareContainer) sliderCompareContainer.classList.remove('hidden');
        });
    }

    if (viewWebtoon) {
        viewWebtoon.addEventListener('click', () => {
            viewMode = 'webtoon';
            clearActiveViewModes();
            viewWebtoon.classList.add('active');

            colOriginal.style.display = 'none';
            colTranslated.style.display = 'none';
            if (webtoonScrollContainer) {
                webtoonScrollContainer.classList.remove('hidden');
                renderWebtoonPages();
            }
        });
    }

    chkShowTranslated.addEventListener('change', () => {
        if (viewMode === 'single') updateSingleView();
    });
}

function updateSingleView() {
    const showTrans = chkShowTranslated.checked;
    if (showTrans) {
        colOriginal.style.display = 'none';
        colTranslated.style.display = 'flex';
        colTranslated.style.maxWidth = '100%';
    } else {
        colOriginal.style.display = 'flex';
        colOriginal.style.maxWidth = '100%';
        colTranslated.style.display = 'none';
    }
}

// Interactive Slider Compare Logic
function initSliderCompare() {
    if (!sliderStage || !sliderHandle) return;
    let isDragging = false;

    function updateSliderPos(clientX) {
        const rect = sliderStage.getBoundingClientRect();
        if (rect.width <= 0) return;
        let pct = ((clientX - rect.left) / rect.width) * 100;
        pct = Math.max(0, Math.min(100, pct));
        sliderStage.style.setProperty('--slider-pos', `${pct}%`);
        sliderHandle.setAttribute('aria-valuenow', Math.round(pct));
    }

    sliderHandle.addEventListener('mousedown', (e) => {
        e.preventDefault();
        isDragging = true;
    });
    sliderStage.addEventListener('mousedown', (e) => {
        isDragging = true;
        updateSliderPos(e.clientX);
    });
    window.addEventListener('mousemove', (e) => {
        if (isDragging) updateSliderPos(e.clientX);
    });
    window.addEventListener('mouseup', () => {
        isDragging = false;
    });

    sliderStage.addEventListener('touchstart', (e) => {
        if (e.touches.length > 0) updateSliderPos(e.touches[0].clientX);
    }, { passive: true });
    sliderStage.addEventListener('touchmove', (e) => {
        if (e.touches.length > 0) updateSliderPos(e.touches[0].clientX);
    }, { passive: true });
}

// Zoom & Fullscreen Controls
function initZoomAndFullscreen() {
    const btnZoomIn = document.getElementById('btn-zoom-in');
    const btnZoomOut = document.getElementById('btn-zoom-out');
    const btnZoomFit = document.getElementById('btn-zoom-fit');
    const btnFullscreen = document.getElementById('btn-fullscreen');
    const lblZoom = document.getElementById('lbl-zoom-level');

    function applyZoom() {
        if (lblZoom) lblZoom.textContent = `${zoomLevel}%`;
        const scale = zoomLevel / 100;
        [imgOriginal, imgTranslated].forEach(img => {
            if (img) img.style.transform = `scale(${scale})`;
        });
    }

    if (btnZoomIn) {
        btnZoomIn.addEventListener('click', () => {
            zoomLevel = Math.min(250, zoomLevel + 15);
            applyZoom();
        });
    }
    if (btnZoomOut) {
        btnZoomOut.addEventListener('click', () => {
            zoomLevel = Math.max(50, zoomLevel - 15);
            applyZoom();
        });
    }
    if (btnZoomFit) {
        btnZoomFit.addEventListener('click', () => {
            fitWidthMode = !fitWidthMode;
            zoomLevel = 100;
            applyZoom();
            if (readerStage) readerStage.classList.toggle('fit-width', fitWidthMode);
            btnZoomFit.textContent = fitWidthMode ? 'Hauteur' : 'Ajuster';
        });
    }
    if (readerArea) {
        readerArea.addEventListener('wheel', (e) => {
            if (e.ctrlKey || e.metaKey) {
                e.preventDefault();
                zoomLevel = e.deltaY < 0 ? Math.min(250, zoomLevel + 10) : Math.max(50, zoomLevel - 10);
                applyZoom();
            }
        }, { passive: false });
    }
    if (btnFullscreen) {
        btnFullscreen.addEventListener('click', toggleFullscreen);
    }
}

function toggleFullscreen() {
    const target = readerArea || document.documentElement;
    if (!document.fullscreenElement) {
        if (target.requestFullscreen) target.requestFullscreen();
    } else {
        if (document.exitFullscreen) document.exitFullscreen();
    }
}

// Translation Trigger & Progress Polling
btnStart.addEventListener('click', async () => {
    if (!currentSession) return;

    btnStart.classList.add('hidden');
    progressBanner.classList.remove('hidden');
    translationStartTime = Date.now();

    const options = {
        session_id: currentSession.session_id,
        ...getProviderOptionsPayload(),
    };

    try {
        await fetch('/api/translate/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(options),
        });

        startPolling();
    } catch (e) {
        showToast("Erreur de lancement : " + e.message, 'error');
        btnStart.classList.remove('hidden');
        progressBanner.classList.add('hidden');
    }
});

function startPolling() {
    if (pollInterval) clearInterval(pollInterval);

    pollInterval = setInterval(async () => {
        if (!currentSession) return;

        try {
            const res = await fetch(`/api/status/${currentSession.session_id}`);
            const data = await res.json();

            progressPercent.textContent = `${data.progress_percent}%`;
            progressFill.style.width = `${data.progress_percent}%`;
            progressLog.textContent = data.current_log;

            let doneCount = 0;
            let errCount = 0;

            data.pages.forEach((p, idx) => {
                const prevStatus = currentSession.pages[idx].status;
                currentSession.pages[idx].status = p.status;
                if (p.blocks) {
                    currentSession.pages[idx].blocks = p.blocks;
                }
                if (p.status === 'done') {
                    doneCount++;
                    const webtoonImg = document.getElementById(`webtoon-img-${idx}`);
                    if (webtoonImg && prevStatus !== 'done') {
                        webtoonImg.src = `/api/image/${currentSession.session_id}/translated/${idx}?t=${Date.now()}`;
                    }
                }
                if (p.status === 'error') errCount++;
                updateThumbnailBadge(idx, p.status);
                if (idx === currentPageIndex && prevStatus !== p.status) {
                    renderBubbleEditor(currentPageIndex);
                }
            });

            if (progressStats) {
                progressStats.textContent = `✓ ${doneCount} traduite${doneCount > 1 ? 's' : ''} · ✗ ${errCount} erreur${errCount > 1 ? 's' : ''}`;
            }

            const completed = doneCount + errCount;
            if (progressEta && translationStartTime && completed > 0 && data.total_pages > completed) {
                const elapsedSec = (Date.now() - translationStartTime) / 1000;
                const avgSecPerPage = elapsedSec / completed;
                const remSec = Math.max(1, Math.round(avgSecPerPage * (data.total_pages - completed)));
                progressEta.textContent = `Temps restant estimé : ~${remSec}s`;
            } else if (progressEta && data.status === 'finished') {
                progressEta.textContent = 'Terminé';
            }

            if (currentSession.pages[currentPageIndex].status === 'done') {
                pageLoader.classList.add('hidden');
                const freshUrl = `/api/image/${currentSession.session_id}/translated/${currentPageIndex}?t=${Date.now()}`;
                imgTranslated.src = freshUrl;
                if (sliderImgTrans) sliderImgTrans.src = freshUrl;
            }

            if (data.status === 'finished' || data.status === 'cancelled') {
                clearInterval(pollInterval);
                progressTitle.textContent = data.status === 'finished' ? "Traduction terminée !" : "Traduction annulée";
                if (btnCancelTranslation) btnCancelTranslation.classList.add('hidden');
                btnDownload.classList.remove('hidden');
                btnDownload.onclick = () => {
                    window.location.href = `/api/download/${currentSession.session_id}`;
                };
            }
        } catch (e) {
            console.error("Erreur de suivi :", e);
        }
    }, 1500);
}

function updateApiStatusPills(d) {
    const setPill = (id, label, hasKey) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = `${label} ${hasKey ? '✓' : '—'}`;
        el.className = `status-pill ${hasKey ? 'pill-ok' : 'pill-missing'}`;
    };
    setPill('pill-gemini', 'Gemini', Boolean(d.gemini_api_key && d.gemini_api_key.trim()));
    setPill('pill-openrouter', 'OpenRouter', Boolean(d.openrouter_api_key && d.openrouter_api_key.trim()));
    setPill('pill-groq', 'Groq', Boolean(d.groq_api_key && d.groq_api_key.trim()));
}

// Settings modal logic
function initSettings() {
    btnOpenSettings.addEventListener('click', async () => {
        await fetchSettings();
        settingsModal.classList.remove('hidden');
    });

    btnCloseSettings.addEventListener('click', () => {
        settingsModal.classList.add('hidden');
    });

    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(btn.dataset.tab).classList.add('active');
        });
    });

    // Provider visibility toggle
    const cfgProvider = document.getElementById('cfg-provider');
    function updateProviderBoxes() {
        const v = cfgProvider.value;
        const boxGemini = document.getElementById('box-gemini');
        const boxOpenRouter = document.getElementById('box-openrouter');
        const boxCustom = document.getElementById('box-custom');
        if (boxGemini) boxGemini.style.display = (v === 'auto' || v === 'gemini') ? 'block' : 'none';
        if (boxOpenRouter) boxOpenRouter.style.display = (v === 'auto' || v === 'openrouter') ? 'block' : 'none';
        if (boxCustom) boxCustom.style.display = (v === 'custom') ? 'block' : 'none';
    }
    cfgProvider.addEventListener('change', updateProviderBoxes);
    updateProviderBoxes();

    const range = document.getElementById('cfg-font-size');
    const lbl = document.getElementById('lbl-font-size');
    range.addEventListener('input', () => {
        lbl.textContent = range.value == 0 ? "Auto-Fit (Adaptation automatique)" : `${range.value} px`;
    });

    btnSaveSettings.addEventListener('click', async () => {
        const payload = {
            gemini_api_key: document.getElementById('cfg-gemini-key').value,
            openrouter_api_key: document.getElementById('cfg-openrouter-key').value,
            groq_api_key: document.getElementById('cfg-groq-key').value,
            custom_base_url: document.getElementById('cfg-custom-base-url').value,
            custom_api_key: document.getElementById('cfg-custom-api-key').value,
            custom_model: document.getElementById('cfg-custom-model').value,
            default_provider: document.getElementById('cfg-provider').value,
            src_lang: document.getElementById('cfg-src-lang').value,
            tgt_lang: document.getElementById('cfg-tgt-lang').value,
            font_style: document.getElementById('cfg-font-style').value,
            fixed_font_size: parseInt(document.getElementById('cfg-font-size').value, 10) || 0,
            text_color: document.getElementById('cfg-text-color').value,
            mask_style: document.getElementById('cfg-mask-style').value,
        };

        const res = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (res.ok) {
            settingsModal.classList.add('hidden');
            updateApiStatusPills(payload);
            showToast("Paramètres enregistrés ✓", 'success');
        }
    });

    fetchSettings();
}

async function fetchSettings() {
    try {
        const res = await fetch('/api/settings');
        const d = await res.json();
        document.getElementById('cfg-gemini-key').value = d.gemini_api_key || '';
        document.getElementById('cfg-openrouter-key').value = d.openrouter_api_key || '';
        document.getElementById('cfg-groq-key').value = d.groq_api_key || '';
        document.getElementById('cfg-custom-base-url').value = d.custom_base_url || '';
        document.getElementById('cfg-custom-api-key').value = d.custom_api_key || '';
        document.getElementById('cfg-custom-model').value = d.custom_model || '';
        document.getElementById('cfg-provider').value = d.provider || 'auto';
        document.getElementById('cfg-src-lang').value = d.src_lang || 'Japanese';
        document.getElementById('cfg-tgt-lang').value = d.tgt_lang || 'French';
        document.getElementById('cfg-font-style').value = d.font_style || 'bold';
        document.getElementById('cfg-font-size').value = d.fixed_font_size || 0;
        document.getElementById('lbl-font-size').textContent = (d.fixed_font_size || 0) == 0 ? "Auto-Fit (Adaptation automatique)" : `${d.fixed_font_size} px`;
        document.getElementById('cfg-text-color').value = d.text_color || '#000000';
        document.getElementById('cfg-mask-style').value = d.mask_style || 'smart';

        updateApiStatusPills(d);

        const cfgProvider = document.getElementById('cfg-provider');
        if (cfgProvider) {
            const v = cfgProvider.value;
            const boxGemini = document.getElementById('box-gemini');
            const boxOpenRouter = document.getElementById('box-openrouter');
            const boxCustom = document.getElementById('box-custom');
            if (boxGemini) boxGemini.style.display = (v === 'auto' || v === 'gemini') ? 'block' : 'none';
            if (boxOpenRouter) boxOpenRouter.style.display = (v === 'auto' || v === 'openrouter') ? 'block' : 'none';
            if (boxCustom) boxCustom.style.display = (v === 'custom') ? 'block' : 'none';
        }
    } catch (e) {
        console.error("Erreur chargement settings:", e);
    }
}

// Slow-Motion Mouse-Following Physics Engine (T12)
function initSlowMotionMouseEngine() {
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        return;
    }

    const halo = document.getElementById('slowmo-halo');
    const glyphs = Array.from(document.querySelectorAll('.slowmo-glyph'));
    const pulseBubble = document.getElementById('slowmo-pulse-bubble');

    let targetX = window.innerWidth * 0.5;
    let targetY = window.innerHeight * 0.5;
    let currentX = targetX;
    let currentY = targetY;
    let slowX = targetX;
    let slowY = targetY;

    // Silky slow-motion interpolation factors
    const LERP_PRIMARY = 0.035;
    const LERP_DEEP = 0.018;

    window.addEventListener('mousemove', (e) => {
        targetX = e.clientX;
        targetY = e.clientY;
    }, { passive: true });

    function animateSlowMo() {
        currentX += (targetX - currentX) * LERP_PRIMARY;
        currentY += (targetY - currentY) * LERP_PRIMARY;
        slowX += (targetX - slowX) * LERP_DEEP;
        slowY += (targetY - slowY) * LERP_DEEP;

        const normX = (currentX / Math.max(1, window.innerWidth)) - 0.5;
        const normY = (currentY / Math.max(1, window.innerHeight)) - 0.5;

        if (halo) {
            halo.style.transform = `translate3d(${currentX - 260}px, ${currentY - 260}px, 0)`;
        }

        glyphs.forEach((g, idx) => {
            const depth = parseFloat(g.dataset.depth || '0.03');
            const offsetX = (slowX - window.innerWidth * 0.5) * depth * 12;
            const offsetY = (slowY - window.innerHeight * 0.5) * depth * 12;
            const rot = (normX * 18) * (idx % 2 === 0 ? 1 : -1);
            g.style.transform = `translate3d(${offsetX.toFixed(1)}px, ${offsetY.toFixed(1)}px, 0) rotate(${rot.toFixed(1)}deg)`;
        });

        // Interactive patience animation when pageLoader is visible
        if (pulseBubble && pageLoader && !pageLoader.classList.contains('hidden')) {
            const pullX = normX * 26;
            const pullY = normY * 26;
            pulseBubble.style.transform = `translate3d(${pullX.toFixed(1)}px, ${pullY.toFixed(1)}px, 0)`;
        }

        // Subtle 3D magnetic tilt on dropZone while upload section is visible
        if (dropZone && uploadSection && !uploadSection.classList.contains('hidden')) {
            const tiltX = (-normY * 4.5).toFixed(2);
            const tiltY = (normX * 4.5).toFixed(2);
            dropZone.style.transform = `perspective(1100px) rotateX(${tiltX}deg) rotateY(${tiltY}deg)`;
        }

        requestAnimationFrame(animateSlowMo);
    }

    requestAnimationFrame(animateSlowMo);
}
