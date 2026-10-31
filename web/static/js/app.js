/* Manga Translator Studio - interface */
(() => {
  "use strict";

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const LANGS = [
    ["Japanese", "Japonais"], ["Korean", "Coréen"], ["Chinese", "Chinois"], ["English", "Anglais"],
    ["French", "Français"], ["Spanish", "Espagnol"], ["German", "Allemand"], ["Italian", "Italien"],
    ["Portuguese", "Portugais"], ["Russian", "Russe"], ["Arabic", "Arabe"], ["Vietnamese", "Vietnamien"],
    ["Thai", "Thaï"], ["Indonesian", "Indonésien"],
  ];

  const PROVIDERS = [
    { id: "gemini", name: "Google Gemini", desc: "Gratuit pour un usage personnel. Idéal pour débuter.", color: "#4f7cff", letter: "G", rec: true, keyUrl: "https://aistudio.google.com/apikey" },
    { id: "openrouter", name: "OpenRouter", desc: "Accès à de nombreux modèles, dont certains gratuits.", color: "#7c5cff", letter: "O", keyUrl: "https://openrouter.ai/keys" },
    { id: "groq", name: "Groq", desc: "Très rapide. Sert aussi à rendre les phrases plus naturelles.", color: "#f55036", letter: "Q", keyUrl: "https://console.groq.com/keys" },
    { id: "openai", name: "OpenAI", desc: "Service payant, très bonne qualité.", color: "#10a37f", letter: "A", keyUrl: "https://platform.openai.com/api-keys" },
    { id: "mistral", name: "Mistral AI", desc: "Service européen, payant.", color: "#ff7000", letter: "M", keyUrl: "https://console.mistral.ai/api-keys" },
    { id: "nvidia", name: "NVIDIA", desc: "Modèles hébergés par NVIDIA.", color: "#76b900", letter: "N", keyUrl: "https://build.nvidia.com" },
    { id: "custom", name: "Service personnalisé", desc: "Pour utilisateurs avancés : toute adresse compatible.", color: "#5b6275", letter: "+", custom: true },
  ];
  const providerName = (id) => (PROVIDERS.find((p) => p.id === id) || {}).name || id;

  const state = {
    settings: {},
    sid: null,
    pages: [],
    total: 0,
    cur: 0,
    mode: "translated",
    follow: true,
    status: "idle",
    poll: null,
    ver: {},          // cache-busting per page
    animated: new Set(),
    anim: null,       // page index being animated
    detectShown: null,
    dirty: false,
    sliderPct: 50,
    curStep: null,
  };

  /* ---------------- API ---------------- */
  async function api(path, opts = {}) {
    const init = { ...opts };
    if (opts.json !== undefined) {
      init.method = init.method || "POST";
      init.headers = { "Content-Type": "application/json" };
      init.body = JSON.stringify(opts.json);
    }
    const r = await fetch(path, init);
    let data = null;
    try { data = await r.json(); } catch { /* ignore */ }
    if (!r.ok) throw new Error((data && data.detail) || `Erreur ${r.status}`);
    return data;
  }

  /* ---------------- Toasts ---------------- */
  function toast(msg, type = "") {
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.textContent = msg;
    $("#toasts").appendChild(el);
    const kill = () => { el.classList.add("out"); setTimeout(() => el.remove(), 320); };
    setTimeout(kill, type === "err" ? 6000 : 3500);
    el.addEventListener("click", kill);
  }

  /* ---------------- Navigation ---------------- */
  function moveIndicator() {
    const a = $(".tab.active"), ind = $("#tab-indicator");
    if (!a) return;
    ind.style.width = a.offsetWidth + "px";
    ind.style.transform = `translateX(${a.offsetLeft - 4}px)`;
  }
  function go(view) {
    $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.nav === view));
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
    moveIndicator();
    if (view === "library") loadLibrary();
    history.replaceState(null, "", `#${view}`);
  }

  /* ---------------- Settings ---------------- */
  function fillLangs(sel, value) {
    sel.innerHTML = LANGS.map(([v, l]) => `<option value="${v}">${l}</option>`).join("");
    sel.value = value;
  }

  async function loadSettings() {
    try {
      state.settings = await api("/api/settings");
    } catch (e) {
      toast("Impossible de charger les paramètres.", "err");
      return;
    }
    const s = state.settings;
    fillLangs($("#src-lang"), s.src_lang || "Japanese");
    fillLangs($("#tgt-lang"), s.tgt_lang || "French");
    fillLangs($("#set-src"), s.src_lang || "Japanese");
    fillLangs($("#set-tgt"), s.tgt_lang || "French");
    setChoice("#font-choices", s.font_style || "bold");
    setChoice("#mask-choices", s.mask_style || "smart");
    $("#text-color").value = s.text_color || "#000000";
    const fixed = Number(s.fixed_font_size) || 0;
    setSizeMode(fixed > 0 ? "fixed" : "auto", fixed || 20);
    renderEngineSummary();
    renderProviders();
  }

  function engineReady() {
    const s = state.settings;
    if (!s) return false;
    if (s.provider && s.provider !== "auto") {
      return Boolean(s.configured?.[s.provider] || s.provider === "custom");
    }
    // Mode "auto" : prêt si AU MOINS UN fournisseur est configuré dans l'environnement !
    return Object.entries(s.configured || {}).some(([k, v]) => v && k !== "custom");
  }

  function getActiveEngineLabel() {
    const s = state.settings;
    if (s.provider && s.provider !== "auto") {
      return `${providerName(s.provider)}${s.selected_model ? ` (${s.selected_model})` : ""}`;
    }
    const ready = PROVIDERS.filter((p) => !p.custom && s.configured?.[p.id]).map((p) => p.name);
    if (ready.length) return `Auto (${ready.join(", ")})`;
    return "Aucun service configuré";
  }

  function renderEngineSummary() {
    const s = state.settings;
    const ok = engineReady();
    const box = $("#current-engine");
    if (box) {
      box.className = "current-engine" + (ok ? " ok" : "");
      box.innerHTML = ok
        ? `<span class="dot"></span><div>Service actif : <b>${esc(getActiveEngineLabel())}</b><br><small class="muted">Prêt pour la traduction automatique</small></div>`
        : `<span class="dot"></span><div><b>Aucun service configuré</b><br><small class="muted">Choisissez un service ci-dessous pour commencer.</small></div>`;
    }
    const hint = $("#engine-hint");
    if (hint) {
      hint.innerHTML = ok
        ? `Service d'IA : <span class="pill">${esc(getActiveEngineLabel())}</span>`
        : `<span class="pill warn">Aucun service de traduction connecté</span><button class="btn ghost sm" id="hint-setup">Configurer</button>`;
      const b = $("#hint-setup");
      if (b) b.onclick = () => openSettings("engine");
    }
    renderApiStatus();
    renderStudioModelPicker();
  }

  function renderApiStatus() {
    const s = state.settings;
    const cfg = s.configured || {};
    const configuredList = PROVIDERS.filter((p) => !p.custom && !!cfg[p.id]);

    // Topbar badges: show only configured APIs with green checkmarks
    const top = $("#top-api-status");
    if (top) {
      if (configuredList.length > 0) {
        top.innerHTML = configuredList.map((p) => {
          return `<button type="button" class="api-pill ok" data-p="${p.id}" title="${p.name} : Clé connectée et active">${p.name} ✓</button>`;
        }).join("");
      } else {
        top.innerHTML = `<button type="button" class="api-pill missing" title="Configurer une clé d'API">⚙️ Configurer API</button>`;
      }
      top.querySelectorAll(".api-pill").forEach((btn) => {
        btn.onclick = () => {
          openSettings("engine");
          if (btn.dataset.p) {
            setTimeout(() => {
              const card = $(`.prov[data-p="${btn.dataset.p}"]`);
              if (card) {
                $$(".prov").forEach((c) => c.classList.remove("open"));
                card.classList.add("open");
                $("[data-f=key]", card)?.focus();
              }
            }, 150);
          }
        };
      });
    }

    // Home empty state pills: show only configured APIs, or a setup prompt if none
    const homePills = $("#home-api-pills");
    if (homePills) {
      if (configuredList.length > 0) {
        homePills.innerHTML = configuredList.map((p) => {
          return `<button type="button" class="api-pill ok" data-p="${p.id}" title="${p.name} : Prêt à traduire">${p.name} ✓</button>`;
        }).join("");
      } else {
        homePills.innerHTML = `<button type="button" class="api-pill missing" title="Configurer un service d'IA">⚙️ Aucun service connecté — Cliquez pour configurer</button>`;
      }
      homePills.querySelectorAll(".api-pill").forEach((btn) => {
        btn.onclick = () => {
          openSettings("engine");
          if (btn.dataset.p) {
            setTimeout(() => {
              const card = $(`.prov[data-p="${btn.dataset.p}"]`);
              if (card) {
                $$(".prov").forEach((c) => c.classList.remove("open"));
                card.classList.add("open");
                $("[data-f=key]", card)?.focus();
              }
            }, 150);
          }
        };
      });
    }
  }

  function renderStudioModelPicker() {
    const sel = $("#studio-provider-select");
    if (!sel) return;
    const s = state.settings;
    const cfg = s.configured || {};
    const options = [];

    const isAutoActive = !s.provider || s.provider === "auto";
    options.push(`<option value="auto"${isAutoActive ? " selected" : ""}>⚡ Mode Auto (Repli automatique)</option>`);

    PROVIDERS.forEach((p) => {
      if (cfg[p.id] || p.custom) {
        const presetModels = s.presets?.[p.id]?.models || [];
        if (presetModels.length) {
          options.push(`<optgroup label="${p.name}">`);
          presetModels.forEach((m) => {
            const val = `${p.id}:${m.id}`;
            const selAttr = (s.provider === p.id && s.selected_model === m.id) ? " selected" : "";
            options.push(`<option value="${esc(val)}"${selAttr}>${esc(m.label || m.id)}</option>`);
          });
          options.push(`</optgroup>`);
        } else if (p.custom && s.custom_model) {
          const val = `custom:${s.custom_model}`;
          const selAttr = (s.provider === "custom") ? " selected" : "";
          options.push(`<option value="${esc(val)}"${selAttr}>${p.name} : ${esc(s.custom_model)}</option>`);
        }
      }
    });

    options.push(`<option value="__config__">⚙️ Gérer les clés d'API...</option>`);
    sel.innerHTML = options.join("");

    sel.onchange = async () => {
      const v = sel.value;
      if (v === "__config__") {
        openSettings("engine");
        renderStudioModelPicker();
        return;
      }
      if (v === "auto") {
        state.settings.provider = "auto";
        state.settings.selected_model = "";
        await api("/api/settings", { json: { default_provider: "auto", selected_model: "" } });
        toast("Mode automatique activé.", "ok");
      } else {
        const [prov, mod] = v.split(":");
        state.settings.provider = prov;
        state.settings.selected_model = mod;
        await api("/api/settings", { json: { default_provider: prov, selected_model: mod } });
        toast(`${providerName(prov)} (${mod}) sélectionné.`, "ok");
      }
      renderEngineSummary();
    };
  }

  function renderProviders() {
    const s = state.settings;
    $("#providers").innerHTML = PROVIDERS.map((p) => {
      const has = !!s.configured?.[p.id];
      const active = s.provider === p.id && engineReady();
      const presetModels = s.presets?.[p.id]?.models || [];
      const hasPreset = has && presetModels.length > 0;
      return `
      <div class="prov${active ? " selected" : ""}" data-p="${p.id}">
        <button class="prov-head" data-toggle>
          <span class="prov-logo" style="background:${p.color}">${p.letter}</span>
          <span class="prov-title"><b>${p.name}</b><small>${p.desc}</small></span>
          ${active ? '<span class="tag ok">Actif</span>' : has ? '<span class="tag ok">Clé enregistrée</span>' : p.rec ? '<span class="tag rec">Recommandé</span>' : ""}
        </button>
        <div class="prov-body"><div><div class="prov-inner">
          ${p.custom ? `
          <div class="step"><b>0</b><div>
            <label class="small">Adresse du service</label>
            <input type="url" data-f="base" placeholder="https://exemple.com/v1" value="${esc(s.custom_base_url || "")}">
          </div></div>` : ""}
          <div class="step${has ? " done" : ""}" data-step="1"><b>1</b><div>
            <label class="small">Clé d'accès ${p.keyUrl ? `<a href="${p.keyUrl}" target="_blank" rel="noopener">Obtenir une clé</a>` : ""}</label>
            <div class="row">
              <input type="password" data-f="key" autocomplete="off" placeholder="${has ? "Clé déjà enregistrée - laisser vide pour la garder" : "Collez votre clé ici"}">
              <button class="btn ghost sm" data-act="connect">Connecter</button>
            </div>
          </div></div>
          <div class="step${hasPreset ? "" : " locked"}" data-step="2"><b>2</b><div>
            <label class="small">Modèle</label>
            <select data-f="model">
              ${hasPreset ? presetModels.map((m) => `<option value="${esc(m.id)}"${m.id === s.selected_model ? " selected" : ""}>${esc(m.label || m.id)}</option>`).join("") : "<option>Connectez d'abord votre clé</option>"}
            </select>
            <small data-f="count">${hasPreset ? `${presetModels.length} modèles disponibles.` : ""}</small>
          </div></div>
          <div class="step${hasPreset ? "" : " locked"}" data-step="3"><b>3</b><div>
            <div class="row"><button class="btn primary sm" data-act="use">Vérifier et utiliser</button><span class="test-result" data-f="result"></span></div>
          </div></div>
        </div></div></div>
      </div>`;
    }).join("");
  }

  async function providerAction(card, act) {
    const pid = card.dataset.p;
    const key = $("[data-f=key]", card).value.trim();
    const base = $("[data-f=base]", card)?.value.trim() || "";
    const s1 = $("[data-step='1']", card), s2 = $("[data-step='2']", card), s3 = $("[data-step='3']", card);
    const result = $("[data-f=result]", card);

    if (act === "connect") {
      if (!key && !state.settings.configured?.[pid] && pid !== "custom") { toast("Collez d'abord votre clé.", "err"); return; }
      if (pid === "custom" && !base) { toast("Indiquez l'adresse du service.", "err"); return; }
      const btn = $("[data-act=connect]", card);
      btn.disabled = true; btn.textContent = "Connexion...";
      try {
        const d = await api("/api/models/fetch", { json: { provider: pid, api_key: key, base_url: base } });
        if (d.warning) throw new Error("Clé refusée ou service injoignable.");
        let models = (d.models || []).filter((m) => !/(tts|embedding|embed|image-gen|imagen|audio|live|aqa|whisper|guard)/i.test(m.id));
        if (!models.length) throw new Error("Aucun modèle compatible trouvé.");
        models.sort((a, b) => (b.is_free ? 1 : 0) - (a.is_free ? 1 : 0));
        const sel = $("[data-f=model]", card);
        sel.innerHTML = models.map((m) => `<option value="${esc(m.id)}">${esc(cleanLabel(m))}</option>`).join("");
        if (state.settings.provider === pid && models.some((m) => m.id === state.settings.selected_model)) sel.value = state.settings.selected_model;
        $("[data-f=count]", card).textContent = `${models.length} modèles disponibles${models.some((m) => m.is_free) ? ", gratuits en premier" : ""}.`;
        s1.classList.add("done"); s2.classList.remove("locked"); s3.classList.remove("locked");
        result.textContent = ""; result.className = "test-result";
      } catch (e) {
        toast(e.message, "err");
      } finally {
        btn.disabled = false; btn.textContent = "Connecter";
      }
    }

    if (act === "use") {
      const model = $("[data-f=model]", card).value;
      const btn = $("[data-act=use]", card);
      btn.disabled = true; result.className = "test-result"; result.textContent = "Vérification...";
      try {
        const t = await api("/api/models/test", { json: { provider: pid, model, api_key: key, base_url: base } });
        if (!t.ok) throw new Error(t.error || "Le modèle ne répond pas.");
        const payload = { default_provider: pid, selected_model: model };
        if (key) payload[`${pid}_api_key`] = key;
        if (pid === "custom") { payload.custom_base_url = base; payload.custom_model = model; }
        await api("/api/settings", { json: payload });
        result.className = "test-result ok"; result.textContent = `Fonctionne (${t.latency_ms} ms)`;
        s3.classList.add("done");
        toast(`${providerName(pid)} est prêt.`, "ok");
        await loadSettings();
        const again = $(`.prov[data-p="${pid}"]`);
        if (again) again.classList.add("open");
      } catch (e) {
        result.className = "test-result err"; result.textContent = e.message;
      } finally {
        btn.disabled = false;
      }
    }
  }

  function cleanLabel(m) {
    let l = String(m.label || m.id).replace(/\s*\((Gratuit|gratuit|Groq LPU)\)\s*/g, " ").trim();
    if (l.length > 70) l = l.slice(0, 67) + "...";
    return m.is_free ? `${l}  -  gratuit` : l;
  }

  function setChoice(sel, v) { $$(`${sel} button`).forEach((b) => b.classList.toggle("active", b.dataset.v === v)); }
  function getChoice(sel) { return $(`${sel} button.active`)?.dataset.v; }
  function setSizeMode(mode, val) {
    $$("#size-mode button").forEach((b) => b.classList.toggle("active", b.dataset.v === mode));
    const r = $("#font-size");
    r.disabled = mode === "auto";
    if (val) r.value = val;
    $("#font-size-out").textContent = mode === "auto" ? "Auto" : `${r.value} px`;
  }

  function lookOptions() {
    const fixed = $("#size-mode button.active").dataset.v === "fixed";
    return {
      font_style: getChoice("#font-choices") || "bold",
      mask_style: getChoice("#mask-choices") || "smart",
      text_color: $("#text-color").value,
      fixed_font_size: fixed ? Number($("#font-size").value) : 0,
    };
  }

  async function saveSettings() {
    const payload = { ...lookOptions(), src_lang: $("#set-src").value, tgt_lang: $("#set-tgt").value };
    try {
      await api("/api/settings", { json: payload });
      $("#src-lang").value = payload.src_lang;
      $("#tgt-lang").value = payload.tgt_lang;
      Object.assign(state.settings, payload);
      $("#save-state").textContent = "Enregistré";
      setTimeout(() => ($("#save-state").textContent = ""), 2000);
      closeModal($("#settings"));
    } catch (e) { toast(e.message, "err"); }
  }

  function openSettings(tab) {
    if (tab) switchSettingsTab(tab);
    openModal($("#settings"));
  }
  function switchSettingsTab(t) {
    $$("#settings-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.stab === t));
    $$(".stab").forEach((s) => s.classList.toggle("active", s.id === `stab-${t}`));
  }
  function openModal(m) { m.classList.add("open"); m.setAttribute("aria-hidden", "false"); }
  function closeModal(m) { m.classList.remove("open"); m.setAttribute("aria-hidden", "true"); }

  /* ---------------- Upload ---------------- */
  async function upload(files, isFolder) {
    if (!files || !files.length) return;
    const fd = new FormData();
    if (isFolder) [...files].forEach((f) => fd.append("files", f, f.webkitRelativePath || f.name));
    else fd.append("file", files[0]);
    const drop = $("#drop-zone");
    drop.querySelector("h1").textContent = "Ouverture du chapitre...";
    try {
      const d = await api(isFolder ? "/api/upload_folder" : "/api/upload", { method: "POST", body: fd });
      openSession(d);
    } catch (e) {
      toast(e.message, "err");
    } finally {
      drop.querySelector("h1").textContent = "Déposez un chapitre ici";
    }
  }

  async function uploadDropped(dt) {
    const items = [...(dt.items || [])];
    const entry = items[0]?.webkitGetAsEntry?.();
    if (entry && entry.isDirectory) {
      const files = [];
      const walk = (ent, path) => new Promise((res) => {
        if (ent.isFile) ent.file((f) => { Object.defineProperty(f, "webkitRelativePath", { value: path + f.name }); files.push(f); res(); });
        else {
          const reader = ent.createReader(); const all = [];
          const readBatch = () => reader.readEntries(async (batch) => {
            if (!batch.length) { for (const e of all) await walk(e, path + ent.name + "/"); res(); }
            else { all.push(...batch); readBatch(); }
          });
          readBatch();
        }
      });
      await walk(entry, "");
      return upload(files, true);
    }
    return upload(dt.files, false);
  }

  /* ---------------- Session ---------------- */
  function openSession(d) {
    stopPolling();
    Object.assign(state, { sid: d.session_id, pages: d.pages, total: d.total_pages, cur: 0, status: "ready", ver: {}, animated: new Set(), anim: null, detectShown: null });
    $("#file-name").textContent = d.filename;
    $("#file-pages").textContent = `${d.total_pages} page${d.total_pages > 1 ? "s" : ""}`;
    $("#empty-state").classList.add("hidden");
    $("#studio").classList.remove("hidden");
    $("#progress").classList.add("hidden");
    $("#btn-download").classList.add("hidden");
    $("#btn-cancel").classList.add("hidden");
    $("#btn-translate").classList.remove("hidden");
    $("#btn-translate").disabled = false;
    $("#btn-translate").textContent = "Traduire";
    $("#live-badge").classList.add("hidden");
    renderThumbs();
    showPage(0);
  }

  function resetToEmpty() {
    if (state.status === "translating" && !confirm("Une traduction est en cours. Abandonner ?")) return;
    if (state.status === "translating") cancel();
    stopPolling();
    state.sid = null;
    $("#studio").classList.add("hidden");
    $("#empty-state").classList.remove("hidden");
  }

  const imgUrl = (i, v) => `/api/image/${state.sid}/${v}/${i}?v=${state.ver[i] || 0}`;

  function stateBadgeHTML(p, i) {
    const s = p.status;
    let label = "En attente";
    if (s === "processing") {
      if (state.cur === i && (state.curStep === "write" || state.curStep === "clean")) {
        label = "Lettrage ✍️";
      } else {
        label = "Analyse ⚡";
      }
    } else if (s === "done") {
      label = "Traduit ✓";
    } else if (s === "error") {
      label = "Erreur ✕";
    }
    return `<span class="state-pill ${s}" title="${esc(label)}">${label}</span>`;
  }

  function pageStatusLabel(page) {
    return ({ pending: "En attente", processing: "En cours", done: "Traduite", error: "En erreur" })[page?.status] || "Original";
  }

  function renderThumbs() {
    $("#page-list").innerHTML = state.pages.map((p, i) => `
      <button class="thumb ${p.status}${i === state.cur ? " active" : ""}" data-i="${i}" style="animation-delay:${Math.min(i, 20) * 25}ms" aria-label="Page ${i + 1} — ${pageStatusLabel(p)}"${i === state.cur ? ' aria-current="page"' : ""}>
        <img loading="lazy" src="${imgUrl(i, p.status === "done" ? "translated" : "original")}" alt="">
        <span class="num">${i + 1}</span>
        ${stateBadgeHTML(p, i)}
      </button>`).join("");
  }

  function updateThumb(i) {
    const el = $(`.thumb[data-i="${i}"]`);
    if (!el) return;
    const p = state.pages[i];
    el.className = `thumb ${p.status}${i === state.cur ? " active" : ""}`;
    el.setAttribute("aria-label", `Page ${i + 1} — ${pageStatusLabel(p)}`);
    if (i === state.cur) el.setAttribute("aria-current", "page"); else el.removeAttribute("aria-current");
    const pill = el.querySelector(".state-pill");
    if (pill) {
      pill.outerHTML = stateBadgeHTML(p, i);
    }
    if (p.status === "done" && !el.dataset.tr) {
      el.dataset.tr = "1";
      el.querySelector("img").src = imgUrl(i, "translated");
    }
  }

  function setActiveThumb() {
    $$(".thumb").forEach((t) => {
      const active = Number(t.dataset.i) === state.cur;
      t.classList.toggle("active", active);
      if (active) t.setAttribute("aria-current", "page"); else t.removeAttribute("aria-current");
    });
    const a = $(".thumb.active");
    if (a) a.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
    $("#btn-prev").disabled = state.cur <= 0;
    $("#btn-next").disabled = state.cur >= state.total - 1;
  }

  function updatePageIndicator() {
    const p = state.pages[state.cur];
    const modeLabel = state.anim === state.cur ? "Traduction en cours"
      : state.mode === "slider" && p?.status === "done" ? "Original / traduit"
      : state.mode === "translated" && p?.status === "done" ? "Traduction affichée" : "Original affiché";
    $("#page-indicator").textContent = `Page ${state.cur + 1} sur ${state.total} · ${modeLabel} · ${pageStatusLabel(p)}`;
    $("#img-base").alt = `Page ${state.cur + 1} — ${modeLabel.toLowerCase()}`;
    $("#img-top").alt = state.mode === "slider" ? "Version traduite, superposée à l’original" : "Original affiché temporairement";
  }

  function loadImg(img, src) {
    return new Promise((res) => {
      if (img.getAttribute("src") === src && img.complete) return res();
      img.onload = img.onerror = () => res();
      img.src = src;
    });
  }

  function updateSliderVisual() {
    const img = $("#img-base");
    const top = $("#img-top");
    const divider = $("#slider-divider");
    if (!divider || !top || !img) return;
    if (state.mode !== "slider" || state.pages[state.cur]?.status !== "done") {
      divider.classList.remove("on");
      top.classList.remove("slider-active");
      top.style.clipPath = "";
      return;
    }
    const pct = Math.max(0, Math.min(100, state.sliderPct));
    top.classList.add("slider-active");
    top.style.clipPath = `inset(0 calc(100% - ${pct}%) 0 0)`;
    divider.classList.add("on");
    const x = img.offsetLeft + (img.offsetWidth * (pct / 100));
    divider.style.transform = `translate3d(${x}px, 0, 0)`;
  }

  async function showPage(i, { keepOverlay = false } = {}) {
    if (i < 0 || i >= state.total) return;
    state.cur = i;
    const p = state.pages[i];
    const base = $("#img-base");
    const top = $("#img-top");
    const divider = $("#slider-divider");

    base.classList.add("loading");
    if (!keepOverlay) { clearOverlay(); setStep(null); }

    if (state.mode === "slider" && p.status === "done") {
      // Slider comparator mode: base = original, top = translated with clip-path
      await Promise.all([
        loadImg(base, imgUrl(i, "original")),
        loadImg(top, imgUrl(i, "translated"))
      ]);
      top.classList.add("slider-active");
      if (divider) divider.classList.add("on");
      updateSliderVisual();
    } else {
      if (top) {
        top.classList.remove("slider-active");
        top.style.clipPath = "";
        top.classList.remove("show");
      }
      if (divider) divider.classList.remove("on");
      const v = state.mode === "translated" && p.status === "done" ? "translated" : "original";
      await loadImg(base, imgUrl(i, v));
      if (v === "translated") {
        base.classList.remove("page-reveal");
        void base.offsetWidth;
        base.classList.add("page-reveal");
      }
    }

    base.classList.remove("loading");
    syncOverlay();
    updatePageIndicator();
    $("#scanline").classList.toggle("on", p.status === "processing" && state.anim !== i);
    setActiveThumb();
    renderBubbles();
  }

  function syncOverlay() {
    const img = $("#img-base"), ov = $("#overlay");
    Object.assign(ov.style, { left: img.offsetLeft + "px", top: img.offsetTop + "px", width: img.offsetWidth + "px", height: img.offsetHeight + "px" });
    const sc = $("#scanline");
    Object.assign(sc.style, { left: img.offsetLeft + "px", width: img.offsetWidth + "px" });
    if (state.mode === "slider") updateSliderVisual();
  }

  function clearOverlay() { const ov = $("#overlay"); ov.innerHTML = ""; ov.classList.remove("fade"); }

  function drawBoxes(blocks) {
    const ov = $("#overlay");
    ov.classList.remove("fade");
    ov.innerHTML = blocks.map((b, n) => {
      const [x0, y0, x1, y1] = b.box;
      return `<div class="box" data-n="${n + 1}" style="left:${x0 / 10}%;top:${y0 / 10}%;width:${(x1 - x0) / 10}%;height:${(y1 - y0) / 10}%;animation-delay:${n * 90}ms"></div>`;
    }).join("");
  }

  function setStep(s) {
    state.curStep = s;
    const bar = $("#stage-step");
    const order = ["detect", "clean", "write"];
    bar.classList.toggle("on", !!s);
    $$("span", bar).forEach((el) => {
      const k = order.indexOf(el.dataset.s), c = order.indexOf(s);
      el.classList.toggle("active", el.dataset.s === s);
      el.classList.toggle("past", c > k);
    });
    if (state.cur !== null && state.pages[state.cur]?.status === "processing") {
      updateThumb(state.cur);
    }
  }

  function renderBubbles() {
    const p = state.pages[state.cur];
    const list = $("#bubble-list");
    const head = $(".panel-head");
    let retry = $("#btn-retry");
    if (!retry) {
      retry = document.createElement("button");
      retry.id = "btn-retry"; retry.className = "btn ghost sm"; retry.textContent = "Retraduire la page";
      retry.onclick = retranslatePage;
      head.insertBefore(retry, $("#btn-apply-edits"));
    }
    retry.classList.toggle("hidden", !(p && (p.status === "done" || p.status === "error")) || state.status === "translating");
    state.dirty = false;
    $("#btn-apply-edits").classList.add("hidden");
    if (!p || !p.blocks || !p.blocks.length) {
      const msg = p?.status === "processing" ? "Lecture de la page en cours..." : p?.status === "error" ? "Cette page n'a pas pu être traduite. " + esc(p.error || "") : p?.status === "done" ? "Aucun texte détecté sur cette page." : "Les textes détectés apparaîtront ici.";
      list.innerHTML = `<p class="muted small">${msg}</p>`;
      return;
    }
    list.innerHTML = p.blocks.map((b, n) => `
      <div class="bubble" data-n="${n}" style="animation-delay:${n * 40}ms">
        <div class="orig"><b>${n + 1}</b><span>${esc(b.original || b.ja)}</span></div>
        <textarea rows="2" data-n="${n}">${esc(b.translation || b.fr)}</textarea>
      </div>`).join("");
  }

  async function applyEdits() {
    const p = state.pages[state.cur];
    const blocks = p.blocks.map((b, n) => ({ ...b, translation: $(`textarea[data-n="${n}"]`).value, fr: $(`textarea[data-n="${n}"]`).value }));
    const btn = $("#btn-apply-edits");
    btn.disabled = true;
    try {
      const d = await api(`/api/rerender/${state.sid}/${state.cur}`, { json: { blocks, ...lookOptions() } });
      p.blocks = d.blocks;
      state.ver[state.cur] = (state.ver[state.cur] || 0) + 1;
      $(`.thumb[data-i="${state.cur}"]`)?.removeAttribute("data-tr");
      updateThumb(state.cur);
      state.mode = "translated"; syncModeButtons();
      await showPage(state.cur);
      toast("Page mise à jour.", "ok");
    } catch (e) { toast(e.message, "err"); }
    finally { btn.disabled = false; }
  }

  async function retranslatePage() {
    const i = state.cur, p = state.pages[i];
    if (!engineReady()) { toast("Connectez d'abord un service de traduction.", "err"); openSettings("engine"); return; }
    p.status = "processing"; p.blocks = []; updateThumb(i); renderBubbles();
    $("#scanline").classList.add("on"); setStep("detect");
    try {
      const d = await api(`/api/translate/page/${state.sid}/${i}`, { json: translateOptions() });
      p.status = d.status; p.blocks = d.blocks || []; p.error = d.error;
      state.ver[i] = (state.ver[i] || 0) + 1;
      $(`.thumb[data-i="${i}"]`)?.removeAttribute("data-tr");
      updateThumb(i);
      if (d.status === "done") await playReveal(i); else { setStep(null); await showPage(i); toast("La page n'a pas pu être traduite.", "err"); }
    } catch (e) { toast(e.message, "err"); p.status = "error"; updateThumb(i); showPage(i); }
  }

  /* ---------------- Translation ---------------- */
  function translateOptions() {
    const s = state.settings;
    return {
      provider: s.provider, model: s.selected_model,
      base_url: s.provider === "custom" ? s.custom_base_url : undefined,
      src_lang: $("#src-lang").value, tgt_lang: $("#tgt-lang").value,
      ...lookOptions(),
    };
  }

  async function startTranslation() {
    if (!engineReady()) {
      toast("Connectez d'abord un service de traduction.", "err");
      openSettings("engine");
      return;
    }
    if ($("#src-lang").value === $("#tgt-lang").value) { toast("Choisissez deux langues différentes.", "err"); return; }
    try {
      await api("/api/translate/start", { json: { session_id: state.sid, ...translateOptions() } });
    } catch (e) { toast(e.message, "err"); return; }
    state.status = "translating";
    state.animated = new Set(); state.anim = null; state.detectShown = null;
    state.pages.forEach((p) => { if (p.status !== "done") p.status = "pending"; });
    $("#btn-translate").classList.add("hidden");
    $("#btn-cancel").classList.remove("hidden");
    $("#btn-download").classList.add("hidden");
    $("#progress").classList.remove("hidden", "done");
    $("#live-badge").classList.remove("hidden");
    $("#progress-fill").style.width = "0%";
    $("#progress-track").setAttribute("aria-valuenow", "0");
    $("#progress-label").textContent = "Démarrage de la traduction";
    $("#progress-count").textContent = `0 / ${state.total} traduites`;
    renderBubbles();
    state.poll = setInterval(pollStatus, 700);
    pollStatus();
  }

  async function cancel() {
    try { await api(`/api/translate/cancel/${state.sid}`, { method: "POST" }); } catch { /* ignore */ }
  }

  function stopPolling() { if (state.poll) clearInterval(state.poll); state.poll = null; }

  async function pollStatus() {
    if (!state.sid) return stopPolling();
    let d;
    try { d = await api(`/api/status/${state.sid}`); } catch { return; }
    const prev = state.pages;
    state.pages = d.pages;
    const translated = d.pages.filter((p) => p.status === "done").length;
    const errors = d.pages.filter((p) => p.status === "error").length;
    $("#progress-fill").style.width = `${d.progress_percent}%`;
    if (state.anim !== state.cur) updatePageIndicator();
    $("#progress-track").setAttribute("aria-valuenow", String(d.progress_percent));
    $("#progress-count").textContent = `${translated} / ${d.total_pages} traduites${errors ? ` · ${errors} en erreur` : ""}`;
    const proc = d.pages.findIndex((p) => p.status === "processing");
    const next = d.pages.findIndex((p) => p.status === "pending");
    $("#progress-label").textContent = proc >= 0 ? `Traduction de la page ${proc + 1} sur ${d.total_pages}` : next >= 0 ? `À suivre : page ${next + 1} sur ${d.total_pages}` : "Traduction";
    d.pages.forEach((p, i) => { if (!prev[i] || prev[i].status !== p.status) updateThumb(i); });

    // keep the viewed page panel fresh when not animating it
    if (state.anim !== state.cur && prev[state.cur]?.status !== d.pages[state.cur].status && !state.follow) showPage(state.cur);

    if (state.follow) driveLive(prev);

    if (["finished", "cancelled"].includes(d.status)) {
      stopPolling();
      state.status = d.status;
      $("#btn-cancel").classList.add("hidden");
      $("#btn-translate").classList.remove("hidden");
      $("#btn-translate").textContent = "Traduire à nouveau";
      $("#live-badge").classList.add("hidden");
      $("#progress").classList.add("done");
      $("#scanline").classList.remove("on");
      if (d.status === "finished") {
        $("#progress-label").textContent = d.errors_count ? `Terminé, ${d.errors_count} page(s) en erreur` : "Traduction terminée";
        const dl = $("#btn-download");
        dl.href = `/api/download/${state.sid}`;
        dl.classList.remove("hidden");
        toast(d.errors_count ? `Terminé avec ${d.errors_count} page(s) en erreur.` : "Chapitre traduit.", d.errors_count ? "err" : "ok");
      } else {
        $("#progress-label").textContent = "Traduction arrêtée";
      }
      if (state.anim === null) showPage(state.cur);
    }
  }

  /* ---------------- Live view ---------------- */
  function driveLive(prev) {
    if (state.anim !== null) return;
    // 1. pages that just finished and haven't been revealed (most recent first, skip backlog)
    const fresh = state.pages
      .map((p, i) => ({ p, i }))
      .filter(({ p, i }) => p.status === "done" && !state.animated.has(i) && prev[i] && prev[i].status !== "done");
    if (fresh.length) {
      fresh.slice(0, -1).forEach(({ i }) => state.animated.add(i));
      const target = fresh[fresh.length - 1].i;
      playReveal(target);
      return;
    }
    // 2. otherwise show the page being processed with the scanning effect
    const proc = state.pages.findIndex((p) => p.status === "processing");
    if (proc >= 0 && state.detectShown !== proc) {
      state.detectShown = proc;
      state.mode = "translated"; syncModeButtons();
      showPage(proc).then(() => { if (state.anim === null) setStep("detect"); });
    }
  }

  async function playReveal(i) {
    state.anim = i;
    state.animated.add(i);
    const p = state.pages[i];
    const blocks = p.blocks || [];
    const base = $("#img-base"), top = $("#img-top");
    state.cur = i;
    setActiveThumb();
    updatePageIndicator();
    await loadImg(base, imgUrl(i, "original"));
    top.classList.remove("show");
    syncOverlay();
    // 1. detected bubbles
    setStep("detect");
    $("#scanline").classList.add("on");
    await sleep(500);
    $("#scanline").classList.remove("on");
    drawBoxes(blocks);
    renderBubbles();
    await sleep(700 + blocks.length * 90);
    // 2. erase
    setStep("clean");
    const cleanUrl = `/api/image/${state.sid}/clean/${i}?v=${state.ver[i] || 0}`;
    await loadImg(top, cleanUrl);
    $$(".box").forEach((b, n) => setTimeout(() => b.classList.add("erase"), n * 70));
    await sleep(500 + blocks.length * 70);
    top.classList.add("show");
    await sleep(500);
    $$(".box").forEach((b) => b.classList.remove("erase"));
    // 3. rewrite
    setStep("write");
    const boxes = $$(".box");
    for (let n = 0; n < boxes.length; n++) {
      const b = boxes[n];
      b.classList.add("write");
      const txt = document.createElement("div");
      txt.className = "txt";
      const h = b.getBoundingClientRect().height;
      txt.style.fontSize = Math.max(8, Math.min(16, h / 5)) + "px";
      b.appendChild(txt);
      typeText(txt, blocks[n].translation || blocks[n].fr || "");
      await sleep(Math.min(260, 1400 / Math.max(1, boxes.length)));
    }
    await sleep(800);
    // 4. final image
    await loadImg(top, imgUrl(i, "translated"));
    $("#overlay").classList.add("fade");
    await sleep(600);
    await loadImg(base, imgUrl(i, "translated"));
    base.classList.remove("page-reveal");
    void base.offsetWidth;
    base.classList.add("page-reveal");
    top.classList.remove("show");
    clearOverlay();
    setStep(null);
    state.anim = null;
    state.detectShown = null;
    if (state.status !== "translating" || !state.follow) renderBubbles();
  }

  function typeText(el, text) {
    let k = 0;
    const step = Math.max(1, Math.ceil(text.length / 18));
    const t = setInterval(() => {
      k += step; el.textContent = text.slice(0, k);
      if (k >= text.length) clearInterval(t);
    }, 30);
    setTimeout(() => clearInterval(t), 3000);
  }

  function syncModeButtons() { $$("#view-mode button").forEach((b) => b.classList.toggle("active", b.dataset.mode === state.mode)); }

  /* ---------------- Library ---------------- */
  async function loadLibrary() {
    const box = $("#library-list");
    try {
      const d = await api("/api/library");
      if (!d.library.length) { box.innerHTML = `<div class="empty-note">Aucun chapitre traduit pour le moment.</div>`; return; }
      box.innerHTML = d.library.map((it, n) => `
        <div class="lib-item" style="animation-delay:${n * 30}ms">
          <span class="ext">${esc(it.format)}</span>
          <div class="meta"><b title="${esc(it.filename)}">${esc(it.filename)}</b><small>${esc(it.date)} - ${it.size_mb} Mo</small></div>
          <a class="icon-btn" href="${it.download_url}" title="Télécharger" aria-label="Télécharger"><svg><use href="#i-down"/></svg></a>
        </div>`).join("");
    } catch { box.innerHTML = `<div class="empty-note">Bibliothèque indisponible.</div>`; }
  }

  /* ---------------- Quit ---------------- */
  async function quitApp() {
    closeModal($("#quit-modal"));
    try { await fetch("/api/system/shutdown", { method: "POST" }); } catch { /* ignore */ }
    $("#closed-screen").classList.remove("hidden");
    setTimeout(() => window.close(), 400);
  }

  /* ---------------- Events ---------------- */
  function bind() {
    $$("[data-nav]").forEach((b) => b.addEventListener("click", (e) => { e.preventDefault(); go(b.dataset.nav); }));
    window.addEventListener("resize", () => { moveIndicator(); syncOverlay(); });

    // drop zone
    const drop = $("#drop-zone");
    ["dragenter", "dragover"].forEach((ev) => document.addEventListener(ev, (e) => { e.preventDefault(); if (!state.sid) drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach((ev) => document.addEventListener(ev, (e) => { e.preventDefault(); if (ev === "drop" || !e.relatedTarget) drop.classList.remove("over"); }));
    document.addEventListener("drop", (e) => { if (!state.sid || $("#view-translate").classList.contains("active")) { if (e.dataTransfer?.files?.length) { if (state.sid && state.status === "translating") return; go("translate"); uploadDropped(e.dataTransfer); } } });
    $("#btn-pick-file").onclick = (e) => { e.stopPropagation(); $("#file-input").click(); };
    $("#btn-pick-folder").onclick = (e) => { e.stopPropagation(); $("#folder-input").click(); };
    drop.addEventListener("click", () => $("#file-input").click());
    drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#file-input").click(); } });
    $("#file-input").onchange = (e) => { upload(e.target.files, false); e.target.value = ""; };
    $("#folder-input").onchange = (e) => { upload(e.target.files, true); e.target.value = ""; };

    // studio
    $("#btn-translate").onclick = startTranslation;
    $("#btn-cancel").onclick = cancel;
    $("#btn-new").onclick = resetToEmpty;
    $("#btn-swap-lang").onclick = () => { const a = $("#src-lang"), b = $("#tgt-lang"); [a.value, b.value] = [b.value, a.value]; };
    $("#page-list").addEventListener("click", (e) => {
      const t = e.target.closest(".thumb"); if (!t) return;
      if (state.status === "translating") { state.follow = false; $("#follow-live").checked = false; }
      if (state.anim === null) showPage(Number(t.dataset.i));
    });
    $("#btn-prev").onclick = () => navPage(-1);
    $("#btn-next").onclick = () => navPage(1);
    $("#follow-live").onchange = (e) => { state.follow = e.target.checked; state.detectShown = null; };
    $$("#view-mode button").forEach((b) => b.onclick = () => {
      state.mode = b.dataset.mode;
      syncModeButtons();
      if (state.anim === null) showPage(state.cur);
    });

    // hold to compare & reactive slider drag
    const canvas = $("#canvas");
    let holdT = null, startX = 0, isDraggingSlider = false;

    function setSliderFromPointer(e) {
      const img = $("#img-base");
      const rect = img.getBoundingClientRect();
      if (rect.width <= 0) return;
      const relX = e.clientX - rect.left;
      state.sliderPct = Math.max(0, Math.min(100, (relX / rect.width) * 100));
      updateSliderVisual();
    }

    canvas.addEventListener("pointerdown", (e) => {
      startX = e.clientX;
      if (state.anim !== null) return;
      if (state.mode === "slider" && state.pages[state.cur]?.status === "done") {
        isDraggingSlider = true;
        setSliderFromPointer(e);
        return;
      }
      if (state.pages[state.cur]?.status !== "done" || state.mode !== "translated") return;
      holdT = setTimeout(async () => {
        const top = $("#img-top");
        await loadImg(top, imgUrl(state.cur, "original"));
        top.classList.add("show");
      }, 180);
    });

    canvas.addEventListener("pointermove", (e) => {
      if (isDraggingSlider) {
        setSliderFromPointer(e);
      }
    });

    const release = (e) => {
      clearTimeout(holdT);
      if (isDraggingSlider) {
        isDraggingSlider = false;
        return;
      }
      if (state.anim === null && state.mode !== "slider") $("#img-top").classList.remove("show");
      if (e && e.type === "pointerup" && Math.abs(e.clientX - startX) > 60 && state.mode !== "slider") {
        navPage(e.clientX < startX ? 1 : -1);
      }
    };
    ["pointerup", "pointerleave", "pointercancel"].forEach((ev) => canvas.addEventListener(ev, release));

    $("#bubble-list").addEventListener("input", () => { state.dirty = true; $("#btn-apply-edits").classList.remove("hidden"); });
    $("#bubble-list").addEventListener("mouseover", (e) => {
      const b = e.target.closest(".bubble");
      $$(".bubble").forEach((x) => x.classList.toggle("hl", x === b));
    });
    $("#btn-apply-edits").onclick = applyEdits;

    document.addEventListener("keydown", (e) => {
      if (/input|textarea|select/i.test(document.activeElement.tagName)) return;
      if (e.key === "Escape") $$(".modal.open").forEach(closeModal);
      if (!state.sid || !$("#view-translate").classList.contains("active")) return;
      if (e.key === "ArrowRight") navPage(1);
      if (e.key === "ArrowLeft") navPage(-1);
    });

    // settings
    $("#btn-settings").onclick = () => openSettings();
    $$("[data-close]").forEach((el) => el.addEventListener("click", () => closeModal(el.closest(".modal"))));
    $$("#settings-tabs button").forEach((b) => b.onclick = () => switchSettingsTab(b.dataset.stab));
    $("#providers").addEventListener("click", (e) => {
      const card = e.target.closest(".prov"); if (!card) return;
      if (e.target.closest("[data-toggle]")) {
        const open = !card.classList.contains("open");
        $$(".prov").forEach((c) => c.classList.remove("open"));
        card.classList.toggle("open", open);
        if (open) setTimeout(() => $("[data-f=key]", card)?.focus(), 200);
      }
      const act = e.target.closest("[data-act]");
      if (act) providerAction(card, act.dataset.act);
    });
    $("#providers").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target.matches("[data-f=key]")) providerAction(e.target.closest(".prov"), "connect");
    });
    $$("#font-choices button").forEach((b) => b.onclick = () => setChoice("#font-choices", b.dataset.v));
    $$("#mask-choices button").forEach((b) => b.onclick = () => setChoice("#mask-choices", b.dataset.v));
    $$("#size-mode button").forEach((b) => b.onclick = () => setSizeMode(b.dataset.v));
    $("#font-size").oninput = () => setSizeMode("fixed");
    $("#btn-save-settings").onclick = saveSettings;

    // quit
    $("#btn-quit").onclick = () => openModal($("#quit-modal"));
    $("#btn-quit-confirm").onclick = quitApp;

    // guide scrollspy
    const gv = $("#view-guide");
    gv.addEventListener("scroll", () => {
      let cur = null;
      $$(".guide-body section").forEach((s) => { if (s.getBoundingClientRect().top < 140) cur = s.id; });
      if (cur) $$("#guide-nav a").forEach((a) => a.classList.toggle("active", a.getAttribute("href") === `#${cur}`));
    });
    $$("#guide-nav a").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); $(a.getAttribute("href")).scrollIntoView({ behavior: "smooth" }); }));
  }

  function navPage(d) {
    if (!state.sid || state.anim !== null) return;
    const n = state.cur + d;
    if (n < 0 || n >= state.total) return;
    if (state.status === "translating") { state.follow = false; $("#follow-live").checked = false; }
    showPage(n);
  }

  /* ---------------- Boot ---------------- */
  function initTheme() {
    const theme = localStorage.getItem("mts_theme") || "light";
    applyTheme(theme);
    const btn = $("#btn-theme");
    if (btn) {
      btn.onclick = () => {
        const cur = document.documentElement.getAttribute("data-theme") || "light";
        const next = cur === "light" ? "dark" : "light";
        applyTheme(next);
        localStorage.setItem("mts_theme", next);
        toast(next === "light" ? "Thème clair activé" : "Thème sombre activé", "ok");
      };
    }
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    const icon = $("#theme-icon");
    if (icon) icon.textContent = theme === "light" ? "🌙" : "☀️";
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "light" ? "#f8fafc" : "#0c0d12");
  }

  function heartbeat() { fetch("/api/system/heartbeat", { method: "POST" }).catch(() => {}); }

  initTheme();
  bind();
  loadSettings();
  const start = (location.hash || "#translate").slice(1);
  go(["translate", "library", "guide"].includes(start) ? start : "translate");
  requestAnimationFrame(moveIndicator);
  heartbeat();
  setInterval(heartbeat, 10000);
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/static/sw.js").catch(() => {});
})();
