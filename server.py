import asyncio
import concurrent.futures
import gc
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

from app.config import load_env, save_env_key, PROVIDER_PRESETS, USER_DIR
from app.archives import ArchiveHandler, ArchiveItem
from app.cloud_vision import CloudVisionClient
from app.typesetter import render_manga_page
from app.groq_refine import refine_translations_with_groq


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_env()
    yield


app = FastAPI(title="Manga Translator Web Studio", version="2.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "web" / "static"
TEMPLATES_DIR = BASE_DIR / "web" / "templates"
DATA_DIR = USER_DIR / "data"
SESSIONS_DIR = DATA_DIR / "sessions"
OUTPUT_DIR = DATA_DIR / "output"
CACHE_DIR = DATA_DIR / "cache"

for d in (STATIC_DIR, TEMPLATES_DIR, DATA_DIR, SESSIONS_DIR, OUTPUT_DIR, CACHE_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# In-memory session tracking
sessions: Dict[str, Dict[str, Any]] = {}
HISTORY_FILE = USER_DIR / "history" / "sessions.json"


def _record_session_history(session: Dict[str, Any], model_name: str = "Cloud Vision"):
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        history = []
        if HISTORY_FILE.exists():
            try:
                history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            except Exception:
                history = []

        history = [h for h in history if h.get("session_id") != session.get("session_id")]
        history.insert(0, {
            "session_id": session["session_id"],
            "filename": session.get("filename", "Manga"),
            "format": session.get("fmt", "cbz"),
            "total_pages": session.get("total_pages", 0),
            "date": time.strftime("%Y-%m-%d %H:%M"),
            "model": model_name,
            "download_url": f"/api/download/{session['session_id']}",
        })
        HISTORY_FILE.write_text(json.dumps(history[:50], indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print("Erreur enregistrement historique:", e)


@app.get("/api/history")
def get_translation_history():
    if not HISTORY_FILE.exists():
        return {"history": []}
    try:
        items = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return {"history": items}
    except Exception:
        return {"history": []}


def _get_image_cache_key(img_bytes: bytes, tgt_lang: str) -> str:
    h = hashlib.sha256(img_bytes).hexdigest()
    return f"{h}_{tgt_lang.lower().strip()}"


def _load_cached_page_blocks(img_bytes: bytes, tgt_lang: str) -> Optional[Tuple[List[Dict[str, Any]], str]]:
    key = _get_image_cache_key(img_bytes, tgt_lang)
    cache_file = CACHE_DIR / f"{key}.json"
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            blocks = data.get("blocks", [])
            model = data.get("model", "Cache")
            return blocks, f"{model} (cache)"
        except Exception:
            return None
    return None


def _save_cached_page_blocks(img_bytes: bytes, tgt_lang: str, blocks: List[Dict[str, Any]], model_name: str):
    try:
        key = _get_image_cache_key(img_bytes, tgt_lang)
        cache_file = CACHE_DIR / f"{key}.json"
        data = {
            "key": key,
            "tgt_lang": tgt_lang,
            "model": model_name,
            "timestamp": time.time(),
            "blocks": blocks,
        }
        cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print("[Cache] Erreur écriture cache:", e)


def _invalidate_cached_page_blocks(img_bytes: bytes, tgt_lang: str):
    """Invalidates disk cache for a specific page image and target language."""
    try:
        key = _get_image_cache_key(img_bytes, tgt_lang)
        cache_file = CACHE_DIR / f"{key}.json"
        if cache_file.exists():
            cache_file.unlink()
    except Exception as e:
        print("[Cache] Erreur invalidation cache:", e)


@app.get("/api/library")
def get_library():
    """
    Returns the permanent catalog of translated mangas stored in data/output/
    with metadata, file size in MB, date, and download link.
    """
    items = []
    if OUTPUT_DIR.exists():
        for p in sorted(OUTPUT_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if p.is_file() and p.suffix.lower() in (".cbz", ".cbr", ".zip", ".jpg", ".png", ".webp"):
                stat = p.stat()
                size_mb = round(stat.st_size / (1024 * 1024), 2)
                mtime_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime))
                items.append({
                    "filename": p.name,
                    "format": p.suffix.lower().lstrip("."),
                    "size_mb": size_mb,
                    "date": mtime_str,
                    "download_url": f"/api/library/download/{p.name}",
                })
    return {"library": items, "count": len(items)}


@app.get("/api/library/download/{filename}")
def download_from_library(filename: str):
    """Safely serves a translated archive from data/output with path-traversal prevention."""
    safe_name = Path(filename).name
    target_file = (OUTPUT_DIR / safe_name).resolve()
    if not target_file.is_relative_to(OUTPUT_DIR.resolve()) or not target_file.exists():
        raise HTTPException(status_code=404, detail="Manga introuvable dans la bibliothèque permanente.")
    return FileResponse(target_file, filename=safe_name, media_type="application/octet-stream")


@app.get("/api/system/check_update")
async def check_system_update():
    """
    Compares the local git commit hash with the remote repository on GitHub (TheShellMaster/manga-traducteur).
    """
    import subprocess
    import httpx

    current_commit = "unknown"
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(BASE_DIR),
        )
        if res.returncode == 0:
            current_commit = res.stdout.strip()
    except Exception:
        pass

    latest_commit = current_commit
    up_to_date = True
    remote_repo = "TheShellMaster/manga-traducteur"

    try:
        res_git = subprocess.run(
            ["git", "ls-remote", "--heads", "origin", "main"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(BASE_DIR),
            timeout=3,
        )
        if res_git.returncode == 0 and res_git.stdout:
            remote_full = res_git.stdout.split()[0].strip()
            latest_commit = remote_full[:7]
            up_to_date = (current_commit == latest_commit)
    except Exception:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"https://api.github.com/repos/{remote_repo}/commits/main")
                if r.status_code == 200:
                    latest_commit = r.json().get("sha", "")[:7]
                    up_to_date = (current_commit == latest_commit)
        except Exception:
            pass

    return {
        "status": "ok",
        "current_commit": current_commit,
        "latest_commit": latest_commit,
        "up_to_date": up_to_date,
        "version": "2.1.0",
        "remote_repo": remote_repo,
    }


@app.post("/api/system/shutdown")
def shutdown_system_server():
    """
    Arrête proprement le serveur local Manga Translator Studio.
    Accessible depuis l'interface Web (PC & Mobile/Android) ou via script.
    """
    import os
    import signal
    import threading
    import time

    def _delayed_exit():
        # En mode test unitaire pytest, ne pas couper le runner
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        time.sleep(0.5)
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        except Exception:
            pass

    threading.Thread(target=_delayed_exit, daemon=True).start()
    return {
        "status": "ok",
        "message": "Le serveur Manga Translator Studio est en cours d'extinction propre."
    }


_last_heartbeat = {"t": 0.0}


@app.post("/api/system/heartbeat")
def system_heartbeat():
    """Called periodically by the UI. In desktop mode (MTS_AUTO_EXIT=1), the server
    stops by itself when no window has been open for a while."""
    _last_heartbeat["t"] = time.time()
    return {"status": "ok"}


def _auto_exit_watchdog():
    import signal
    grace = float(os.environ.get("MTS_AUTO_EXIT_DELAY", "40"))
    start = time.time()
    while True:
        time.sleep(5)
        last = _last_heartbeat["t"]
        busy = any(s.get("status") == "translating" for s in sessions.values())
        ref = last or start
        limit = grace if last else 180
        if not busy and time.time() - ref > limit:
            print("[System] Plus aucune fenêtre ouverte : arrêt du serveur.")
            os.kill(os.getpid(), signal.SIGTERM)
            return


if os.environ.get("MTS_AUTO_EXIT") == "1":
    threading.Thread(target=_auto_exit_watchdog, daemon=True).start()


@app.post("/api/models/test")
async def test_provider_model(payload: Dict[str, Any]):
    """Real minimal inference call to verify that a key + model actually work."""
    import httpx

    provider = str(payload.get("provider") or "").lower()
    model = str(payload.get("model") or "").strip()
    load_env()
    api_key = str(payload.get("api_key") or "").strip() or os.environ.get(f"{provider.upper()}_API_KEY", "")
    base_url = str(payload.get("base_url") or "").strip()
    if not model:
        return {"ok": False, "error": "Aucun modèle sélectionné."}
    if not api_key and provider != "custom":
        return {"ok": False, "error": "Clé API manquante."}
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if provider == "gemini":
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                resp = await client.post(url, json={"contents": [{"parts": [{"text": "Reply with: OK"}]}]})
            else:
                url_base = base_url or PROVIDER_PRESETS.get(provider, {}).get("base_url") or ""
                if not url_base:
                    return {"ok": False, "error": "Adresse du service manquante."}
                headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
                resp = await client.post(
                    url_base.rstrip("/") + "/chat/completions",
                    headers=headers,
                    json={"model": model, "max_tokens": 5, "messages": [{"role": "user", "content": "Reply with: OK"}]},
                )
        ms = round((time.perf_counter() - t0) * 1000)
        if resp.status_code == 200:
            return {"ok": True, "latency_ms": ms}
        detail = resp.text[:200]
        try:
            j = resp.json()
            detail = (j.get("error") or {}).get("message") if isinstance(j.get("error"), dict) else (j.get("error") or detail)
        except Exception:
            pass
        return {"ok": False, "error": f"HTTP {resp.status_code} : {detail}"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


@app.get("/api/session/{session_id}")
def get_session_data(session_id: str):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session en mémoire expirée")
    return {
        "session_id": session_id,
        "filename": session["filename"],
        "format": session["fmt"],
        "total_pages": session["total_pages"],
        "pages": session["pages"],
        "status": session["status"],
    }


@app.get("/", response_class=HTMLResponse)
def index():
    html_file = TEMPLATES_DIR / "index.html"
    if html_file.exists():
        return html_file.read_text(encoding="utf-8")
    return "<h1>Interface introuvable</h1>"


@app.get("/api/settings")
def get_settings():
    load_env()
    return {
        "gemini_api_key": os.environ.get("GEMINI_API_KEY", ""),
        "openrouter_api_key": os.environ.get("OPENROUTER_API_KEY", ""),
        "groq_api_key": os.environ.get("GROQ_API_KEY", ""),
        "openai_api_key": os.environ.get("OPENAI_API_KEY", ""),
        "mistral_api_key": os.environ.get("MISTRAL_API_KEY", ""),
        "nvidia_api_key": os.environ.get("NVIDIA_API_KEY", ""),
        "custom_base_url": os.environ.get("CUSTOM_BASE_URL", "https://openrouter.ai/api/v1"),
        "custom_api_key": os.environ.get("CUSTOM_API_KEY", ""),
        "custom_model": os.environ.get("CUSTOM_MODEL", "nvidia/nemotron-3.5-super-vl:free"),
        "provider": os.environ.get("DEFAULT_PROVIDER", "auto"),
        "selected_model": os.environ.get("SELECTED_MODEL", ""),
        "src_lang": os.environ.get("SRC_LANG", "Japanese"),
        "tgt_lang": os.environ.get("TGT_LANG", "French"),
        "font_style": os.environ.get("FONT_STYLE", "bold"),
        "fixed_font_size": int(os.environ.get("FIXED_FONT_SIZE", 0)),
        "text_color": os.environ.get("TEXT_COLOR", "#000000"),
        "mask_style": os.environ.get("MASK_STYLE", "smart"),
        "presets": PROVIDER_PRESETS,
        "configured": {
            p: bool(os.environ.get(f"{p.upper()}_API_KEY"))
            for p in ("gemini", "openrouter", "groq", "openai", "mistral", "nvidia", "ollama", "custom")
        },
    }


@app.post("/api/settings")
async def save_settings(data: Dict[str, Any]):
    for k, v in data.items():
        if v is not None:
            save_env_key(k.upper(), str(v))
    return {"status": "ok", "message": "Paramètres sauvegardés avec succès"}


@app.post("/api/models/fetch")
async def fetch_provider_models_api(payload: Dict[str, Any]):
    """
    Live real model discovery from official API endpoints.
    Receives { provider, api_key, base_url } and returns live model list directly from the provider.
    Zero manual URL or model name typing required by the user.
    """
    import httpx

    provider = str(payload.get("provider") or "gemini").lower()
    load_env()
    api_key = str(payload.get("api_key") or "").strip()
    if not api_key:
        api_key = (
            os.environ.get(f"{provider.upper()}_API_KEY")
            or os.environ.get("GEMINI_API_KEY" if provider == "gemini" else "OPENROUTER_API_KEY")
            or ""
        )

    base_url = str(payload.get("base_url") or "").strip()

    models_list = []

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            if provider == "gemini":
                if not api_key:
                    # Provide official verified presets if no key yet
                    preset_models = PROVIDER_PRESETS.get("gemini", {}).get("models", [])
                    return {"status": "ok", "provider": provider, "models": preset_models}
                url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
                resp = await client.get(url)
                if resp.status_code == 200:
                    d = resp.json()
                    for m in d.get("models", []):
                        m_id = m.get("name", "").replace("models/", "")
                        methods = m.get("supportedGenerationMethods", [])
                        if "generateContent" in methods and any(tag in m_id for tag in ("flash", "pro", "gemini")):
                            label = m.get("displayName") or m_id
                            models_list.append({"id": m_id, "label": f"{label} ({m_id})", "is_free": "flash" in m_id})
                else:
                    preset_models = PROVIDER_PRESETS.get("gemini", {}).get("models", [])
                    return {"status": "ok", "provider": provider, "models": preset_models, "warning": f"API Gemini HTTP {resp.status_code}"}

            elif provider == "openrouter":
                headers = {"User-Agent": "Mozilla/5.0"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"
                resp = await client.get("https://openrouter.ai/api/v1/models", headers=headers)
                if resp.status_code == 200:
                    d = resp.json()
                    free_list = []
                    paid_list = []
                    for m in d.get("data", []):
                        mid = m.get("id", "")
                        arch = m.get("architecture") or {}
                        in_mod = arch.get("input_modalities") or []
                        mod = arch.get("modality") or ""
                        has_img = "image" in in_mod or "image" in mod or "vision" in mid.lower() or "vl" in mid.lower()
                        is_free = mid.endswith(":free")
                        if has_img:
                            name = m.get("name") or mid
                            if is_free:
                                free_list.append({"id": mid, "label": f"{name} (gratuit)", "is_free": True})
                            elif any(k in mid for k in ("gpt-4o", "claude-3.5", "qwen", "gemini", "llama-3.2", "mistral")):
                                paid_list.append({"id": mid, "label": f"{name}", "is_free": False})
                    # Prioritize free vision models at the top
                    models_list = free_list + paid_list
                else:
                    models_list = PROVIDER_PRESETS.get("openrouter", {}).get("models", [])

            elif provider == "openai":
                headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
                resp = await client.get("https://api.openai.com/v1/models", headers=headers)
                if resp.status_code == 200:
                    d = resp.json()
                    for m in d.get("data", []):
                        mid = m.get("id", "")
                        if "gpt-4o" in mid or "o1" in mid or "gpt-4-turbo" in mid:
                            models_list.append({"id": mid, "label": mid, "is_free": False})
                    models_list.sort(key=lambda x: x["id"])
                else:
                    models_list = PROVIDER_PRESETS.get("openai", {}).get("models", [])

            elif provider == "groq":
                headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
                resp = await client.get("https://api.groq.com/openai/v1/models", headers=headers)
                if resp.status_code == 200:
                    d = resp.json()
                    for m in d.get("data", []):
                        mid = m.get("id", "")
                        models_list.append({"id": mid, "label": f"{mid} (Groq LPU)", "is_free": True})
                else:
                    models_list = PROVIDER_PRESETS.get("groq", {}).get("models", [])

            elif provider == "mistral":
                headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
                resp = await client.get("https://api.mistral.ai/v1/models", headers=headers)
                if resp.status_code == 200:
                    d = resp.json()
                    for m in d.get("data", []):
                        mid = m.get("id", "")
                        if "pixtral" in mid or "large" in mid or "vision" in mid:
                            models_list.append({"id": mid, "label": mid, "is_free": False})
                else:
                    models_list = PROVIDER_PRESETS.get("mistral", {}).get("models", [])

            elif provider == "nvidia":
                headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
                resp = await client.get("https://integrate.api.nvidia.com/v1/models", headers=headers)
                if resp.status_code == 200:
                    d = resp.json()
                    for m in d.get("data", []):
                        mid = m.get("id", "")
                        if "vision" in mid or "vl" in mid or "embed" not in mid:
                            models_list.append({"id": mid, "label": mid, "is_free": False})
                else:
                    models_list = PROVIDER_PRESETS.get("nvidia", {}).get("models", [])

            elif provider == "ollama":
                target_url = (base_url or "https://ollama.com/v1").rstrip("/") + "/models"
                headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
                resp = await client.get(target_url, headers=headers)
                if resp.status_code == 200:
                    d = resp.json()
                    for m in d.get("data", []):
                        mid = m.get("id", "")
                        models_list.append({"id": mid, "label": f"{mid} (Ollama)", "is_free": False})
                else:
                    models_list = PROVIDER_PRESETS.get("ollama", {}).get("models", [])

            else:
                # Custom or Ollama local/cloud endpoint
                target_url = (base_url or "http://localhost:11434/v1").rstrip("/") + "/models"
                headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
                resp = await client.get(target_url, headers=headers)
                if resp.status_code == 200:
                    d = resp.json()
                    for m in d.get("data", []):
                        mid = m.get("id", "")
                        models_list.append({"id": mid, "label": mid, "is_free": False})

    except Exception as e:
        preset_models = PROVIDER_PRESETS.get(provider, {}).get("models", [])
        return {"status": "ok", "provider": provider, "models": preset_models, "warning": str(e)}

    if not models_list:
        models_list = PROVIDER_PRESETS.get(provider, {}).get("models", [])

    return {"status": "ok", "provider": provider, "models": models_list}


def _init_session_from_path(session_id: str, session_dir: Path, input_path: Path, display_name: str) -> Dict[str, Any]:
    extract_dir = session_dir / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)
    fmt, items = ArchiveHandler.extract(input_path, extract_dir)
    # Secondary defense: ensure all items exclude macOS AppleDouble, resource forks, and junk
    items = [it for it in items if not ArchiveHandler.is_ignored_entry(it.relative_name)]
    image_items = [it for it in items if it.is_image]

    if not image_items:
        shutil.rmtree(session_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="Aucune image trouvée dans le fichier ou dossier fourni.")

    pages_info = []
    pages_dir = session_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    valid_image_items = []
    for it in image_items:
        try:
            img = it.get_image()
        except Exception:
            # Skip unidentifiable or corrupt entries without HTTP 500
            continue
        orig_name = f"page_{len(pages_info):03d}_orig.jpg"
        w, h = img.width, img.height
        img.convert("RGB").save(pages_dir / orig_name, format="JPEG", quality=85)
        img.close()
        pages_info.append({
            "index": len(pages_info),
            "relative_name": it.relative_name,
            "status": "pending",
            "width": w,
            "height": h,
            "blocks_count": 0,
            "blocks": [],
        })
        valid_image_items.append(it)
    image_items = valid_image_items

    if not image_items:
        shutil.rmtree(session_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="Aucune image valide trouvée dans le fichier ou dossier fourni.")
    gc.collect()

    sessions[session_id] = {
        "session_id": session_id,
        "filename": display_name,
        "fmt": fmt,
        "input_file": str(input_path),
        "session_dir": str(session_dir),
        "items": items,
        "image_items": image_items,
        "pages": pages_info,
        "total_pages": len(pages_info),
        "current_page": 0,
        "status": "ready",
        "cancelled": False,
        "progress_percent": 0,
        "current_log": "Archive chargée et prête pour la traduction.",
        "translated_images": {},
    }

    return {
        "session_id": session_id,
        "filename": display_name,
        "format": fmt,
        "total_pages": len(pages_info),
        "pages": pages_info,
    }


@app.post("/api/upload")
async def upload_manga(file: UploadFile = File(...)):
    if file.size is not None and file.size == 0:
        raise HTTPException(status_code=400, detail="Le fichier téléversé est vide (0 octet).")

    session_id = str(uuid.uuid4())[:8]
    session_dir = SESSIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(file.filename or "manga.cbz").name
    input_file = session_dir / safe_name
    with open(input_file, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    if input_file.stat().st_size == 0:
        shutil.rmtree(session_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="Le fichier téléversé est vide (0 octet).")

    try:
        return _init_session_from_path(session_id, session_dir, input_file, safe_name)
    except HTTPException:
        raise
    except ValueError as ve:
        shutil.rmtree(session_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        shutil.rmtree(session_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Erreur d'extraction : {str(e)}")


@app.post("/api/upload_folder")
async def upload_folder(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="Aucun fichier reçu pour le dossier.")

    session_id = str(uuid.uuid4())[:8]
    session_dir = SESSIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    first_raw = (files[0].filename or "dossier_manga").replace("\\", "/")
    parts = [p for p in first_raw.split("/") if p and p not in (".", "..")]
    folder_name = parts[0] if len(parts) > 1 else "dossier_manga"

    input_folder = (session_dir / folder_name).resolve()
    input_folder.mkdir(parents=True, exist_ok=True)

    for f in files:
        raw_name = (f.filename or "").replace("\\", "/")
        rel_parts = [p for p in raw_name.split("/") if p and p not in (".", "..")]
        if not rel_parts:
            continue
        if len(rel_parts) > 1 and rel_parts[0] == folder_name:
            rel_path = Path(*rel_parts[1:])
        else:
            rel_path = Path(*rel_parts)
        dest = (input_folder / rel_path).resolve()
        if not dest.is_relative_to(input_folder):
            shutil.rmtree(session_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=f"Sécurité : Détection d'évasion de chemin : {raw_name}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as buffer:
            shutil.copyfileobj(f.file, buffer)

    try:
        return _init_session_from_path(session_id, session_dir, input_folder, folder_name)
    except HTTPException:
        raise
    except ValueError as ve:
        shutil.rmtree(session_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        shutil.rmtree(session_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Erreur d'extraction du dossier : {str(e)}")


def _serialize_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    serialized = []
    for b in blocks:
        box = b.get("box", (0, 0, 100, 100))
        serialized.append({
            "box": [float(v) for v in box],
            "type": str(b.get("type") or "speech"),
            "original": str(b.get("original") or b.get("ja") or ""),
            "translation": str(b.get("fr") or b.get("translation") or ""),
            "ja": str(b.get("ja") or b.get("original") or ""),
            "fr": str(b.get("fr") or b.get("translation") or ""),
        })
    return serialized


def _translate_single_page(
    session: Dict[str, Any],
    idx: int,
    client: CloudVisionClient,
    tgt_lang: str,
    font_style: str,
    fixed_font_size: int,
    text_color: str,
    mask_style: str,
    context_history: Optional[List[Dict[str, str]]] = None,
    force_refresh: bool = False,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    session_dir = Path(session["session_dir"])
    pages_dir = session_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    item = session["image_items"][idx]
    total = session["total_pages"]

    page = session["pages"][idx]
    page["status"] = "processing"
    page["stage"] = "detect"
    page["blocks"] = []
    img = item.get_image()

    raw_img_bytes = None
    if item.raw_bytes:
        raw_img_bytes = item.raw_bytes
    elif item.source_path and item.source_path.exists():
        try:
            raw_img_bytes = item.source_path.read_bytes()
        except Exception:
            raw_img_bytes = None
    if not raw_img_bytes:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        raw_img_bytes = buf.getvalue()

    try:
        if force_refresh:
            _invalidate_cached_page_blocks(raw_img_bytes, tgt_lang)
            cached = None
        else:
            cached = _load_cached_page_blocks(raw_img_bytes, tgt_lang)

        if cached is not None:
            blocks, model_name = cached
            is_cached = True
        else:
            is_cached = False
            blocks, model_name = client.detect_and_translate(
                img,
                max_side=1600,
                context_history=context_history,
            )
            opts = options or {}
            if opts.get("groq_refine") or opts.get("groq_api_key") or opts.get("provider") == "groq":
                refine_translations_with_groq(
                    blocks,
                    groq_api_key=opts.get("groq_api_key"),
                    target_lang=tgt_lang,
                    context_history=context_history,
                )
            _save_cached_page_blocks(raw_img_bytes, tgt_lang, blocks, model_name)

        # Live view: expose detected bubbles, then the cleaned page, before final typesetting
        page["blocks"] = _serialize_blocks(blocks)
        page["blocks_count"] = len(page["blocks"])
        page["stage"] = "clean"
        cleaned = render_manga_page(img=img.copy(), blocks=blocks, mask_style=mask_style, mask_only=True)
        cleaned.convert("RGB").save(pages_dir / f"page_{idx:03d}_clean.jpg", format="JPEG", quality=85)
        cleaned.close()
        page["stage"] = "write"

        rendered = render_manga_page(
            img=img,
            blocks=blocks,
            font_style=font_style,
            fixed_font_size=fixed_font_size,
            text_color=text_color,
            mask_style=mask_style,
        )
        trans_filename = f"page_{idx:03d}_trans.jpg"
        trans_path = pages_dir / trans_filename
        rendered.convert("RGB").save(trans_path, format="JPEG", quality=90)
        rendered.close()
        img.close()
        session["translated_images"][item.relative_name] = trans_path

        ser_blocks = _serialize_blocks(blocks)
        session["pages"][idx]["status"] = "done"
        session["pages"][idx]["stage"] = "done"
        session["pages"][idx]["blocks_count"] = len(ser_blocks)
        session["pages"][idx]["blocks"] = ser_blocks
        session["current_log"] = f"Page {idx + 1}/{total} terminée ({len(ser_blocks)} bulles via {model_name}{' - cache' if is_cached else ''})"
        gc.collect()
        return {"status": "done", "blocks_count": len(ser_blocks), "blocks": ser_blocks, "model": model_name}
    except Exception as e:
        fallback_filename = f"page_{idx:03d}_trans.jpg"
        fallback_path = pages_dir / fallback_filename
        img.convert("RGB").save(fallback_path, format="JPEG", quality=90)
        img.close()
        session["translated_images"][item.relative_name] = fallback_path
        session["pages"][idx]["status"] = "error"
        session["pages"][idx]["stage"] = "error"
        session["pages"][idx]["error"] = str(e)[:300]
        session["current_log"] = f"Page {idx + 1} : Erreur ({str(e)}), page originale conservée"
        gc.collect()
        return {"status": "error", "error": str(e)}


def _run_translation_worker(session_id: str, options: Dict[str, Any]):
    session = sessions.get(session_id)
    if not session:
        return

    session["status"] = "translating"
    session["cancelled"] = False

    provider = options.get("provider", "auto")
    api_key = options.get("api_key") or None
    base_url = options.get("base_url") or None
    model = options.get("model") or None
    src_lang = options.get("src_lang", "Japanese")
    tgt_lang = options.get("tgt_lang", "French")
    font_style = options.get("font_style", "bold")
    fixed_font_size = int(options.get("fixed_font_size", 0) or options.get("font_size", 0) or 0)
    text_color = options.get("text_color", "#000000")
    mask_style = options.get("mask_style") or options.get("bubble_shape") or "smart"
    max_pages = options.get("max_pages")

    session["last_render_options"] = {
        "font_style": font_style,
        "fixed_font_size": fixed_font_size,
        "text_color": text_color,
        "mask_style": mask_style,
    }

    client = CloudVisionClient(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        src_lang=src_lang,
        tgt_lang=tgt_lang,
    )

    image_items = session["image_items"]
    limit = int(max_pages) if (max_pages is not None and int(max_pages) > 0) else len(image_items)
    total = min(len(image_items), limit)

    # Inter-page context memory: sequential, ordered dialogue across pages
    context_history: List[Dict[str, str]] = []
    page_contexts: Dict[int, List[Dict[str, str]]] = {}
    page_events: Dict[int, threading.Event] = {i: threading.Event() for i in range(total)}
    context_lock = threading.Lock()
    last_model = "Cloud Vision"
    completed_count = 0

    # Multi-page parallel translation (concurrency = 2 or 3 workers)
    concurrency = min(3, max(1, total))
    concurrency = int(options.get("concurrency") or concurrency)

    session_dir = Path(session["session_dir"])
    pages_dir = session_dir / "pages"

    def _worker_task(page_idx: int):
        if session.get("cancelled"):
            return None

        # Incident recovery / Resumption check:
        # If page was already finished and translated image exists on disk, reuse it directly
        trans_file = pages_dir / f"page_{page_idx:03d}_trans.jpg"
        if session["pages"][page_idx].get("status") == "done" and trans_file.exists():
            item = session["image_items"][page_idx]
            session["translated_images"][item.relative_name] = trans_file
            with context_lock:
                page_contexts[page_idx] = [
                    {"original": b.get("original", ""), "translation": b.get("translation", "")}
                    for b in session["pages"][page_idx].get("blocks", [])
                    if b.get("original") or b.get("translation")
                ]
            page_events[page_idx].set()
            return page_idx, {
                "status": "done",
                "blocks_count": session["pages"][page_idx].get("blocks_count", 0),
                "blocks": session["pages"][page_idx].get("blocks", []),
                "model": "Resumed (cache disque)",
            }

        try:
            # Wait for preceding page context if page_idx > 0 to maintain natural narrative order
            if page_idx > 0 and not session.get("cancelled"):
                page_events[page_idx - 1].wait(timeout=5.0)

            with context_lock:
                ctx_ordered: List[Dict[str, str]] = []
                for i in range(page_idx):
                    if i in page_contexts:
                        ctx_ordered.extend(page_contexts[i])
                ctx_snapshot = list(ctx_ordered[-8:])

            res = _translate_single_page(
                session=session,
                idx=page_idx,
                client=client,
                tgt_lang=tgt_lang,
                font_style=font_style,
                fixed_font_size=fixed_font_size,
                text_color=text_color,
                mask_style=mask_style,
                context_history=ctx_snapshot,
                options=options,
            )

            with context_lock:
                page_contexts[page_idx] = [
                    {"original": b.get("original", ""), "translation": b.get("translation", "")}
                    for b in res.get("blocks", [])
                    if b.get("original") or b.get("translation")
                ]
                full_ordered: List[Dict[str, str]] = []
                for i in range(total):
                    if i in page_contexts:
                        full_ordered.extend(page_contexts[i])
                context_history[:] = full_ordered[-12:]

            return page_idx, res
        finally:
            page_events[page_idx].set()

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {executor.submit(_worker_task, p_idx): p_idx for p_idx in range(total)}
        for future in concurrent.futures.as_completed(futures):
            if session.get("cancelled"):
                session["status"] = "cancelled"
                session["current_log"] = "Traduction annulée."
                executor.shutdown(wait=False, cancel_futures=True)
                return

            try:
                result = future.result()
                if not result:
                    continue
                p_idx, res = result
                completed_count += 1
                session["progress_percent"] = round((completed_count / total) * 100) if total > 0 else 100

                if res.get("status") == "done":
                    last_model = res.get("model", "Cloud Vision")
                    last_blocks = res.get("blocks", [])

                    if last_blocks:
                        sample_b = last_blocks[0]
                        orig_snippet = sample_b.get("original", "")[:35]
                        trans_snippet = sample_b.get("translation", "")[:40]
                        session["last_bubble"] = {
                            "page": p_idx + 1,
                            "original": orig_snippet,
                            "translation": trans_snippet,
                            "model": last_model,
                        }
                        session["current_log"] = f"[{last_model}] Page {p_idx + 1}/{total} : « {orig_snippet} » -> « {trans_snippet} » ({completed_count}/{total} terminées)"
            except Exception as e:
                completed_count += 1
                session["progress_percent"] = round((completed_count / total) * 100) if total > 0 else 100

    session["status"] = "finished"
    session["progress_percent"] = 100
    n_err = sum(1 for p in session["pages"][:total] if p.get("status") == "error")
    session["errors_count"] = n_err
    session["current_log"] = (
        f"Traduction terminée via {last_model}." if n_err == 0
        else f"Traduction terminée : {n_err} page(s) en erreur sur {total}."
    )

    # Automatically save translated archive into permanent data/output/
    try:
        input_file = Path(session["input_file"])
        fmt = session["fmt"]
        safe_stem = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", input_file.stem)
        ext = ".cbz" if fmt in ("folder", "cbz") else input_file.suffix
        final_filename = f"{safe_stem}_fr_{session_id}{ext}"
        permanent_out_path = OUTPUT_DIR / final_filename
        ArchiveHandler.pack(
            fmt="cbz" if fmt == "folder" else fmt,
            input_path=input_file,
            output_path=permanent_out_path,
            items=session["items"],
            rendered_images=session["translated_images"],
        )
        session["permanent_file"] = str(permanent_out_path)
        session["permanent_filename"] = final_filename
    except Exception as exc:
        print("[Library] Erreur auto-archivage permanent:", exc)

    _record_session_history(session, model_name=last_model)


@app.post("/api/translate/start")
def start_translation(data: Dict[str, Any], background_tasks: BackgroundTasks):
    session_id = data.get("session_id")
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session introuvable")

    sessions[session_id]["cancelled"] = False
    background_tasks.add_task(_run_translation_worker, session_id, data)
    return {"status": "started", "session_id": session_id}


@app.post("/api/translate/cancel/{session_id}")
def cancel_translation(session_id: str):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session introuvable")
    session["cancelled"] = True
    session["status"] = "cancelled"
    session["current_log"] = "Annulation demandée par l'utilisateur..."
    return {"status": "cancelled", "session_id": session_id}


@app.post("/api/translate/page/{session_id}/{page_idx}")
def retranslate_single_page(session_id: str, page_idx: int, data: Optional[Dict[str, Any]] = None):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session introuvable")
    if page_idx < 0 or page_idx >= session["total_pages"]:
        raise HTTPException(status_code=400, detail="Index de page invalide")

    opts = data or {}
    provider = opts.get("provider", os.environ.get("DEFAULT_PROVIDER", "auto"))
    api_key = opts.get("api_key") or None
    base_url = opts.get("base_url") or None
    model = opts.get("model") or None
    src_lang = opts.get("src_lang", os.environ.get("SRC_LANG", "Japanese"))
    tgt_lang = opts.get("tgt_lang", os.environ.get("TGT_LANG", "French"))
    font_style = opts.get("font_style", os.environ.get("FONT_STYLE", "bold"))
    fixed_font_size = int(opts.get("fixed_font_size", os.environ.get("FIXED_FONT_SIZE", 0) or 0))
    text_color = opts.get("text_color", os.environ.get("TEXT_COLOR", "#000000"))
    mask_style = opts.get("mask_style") or opts.get("bubble_shape") or os.environ.get("MASK_STYLE", "smart")

    client = CloudVisionClient(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        src_lang=src_lang,
        tgt_lang=tgt_lang,
    )

    res = _translate_single_page(
        session=session,
        idx=page_idx,
        client=client,
        tgt_lang=tgt_lang,
        font_style=font_style,
        fixed_font_size=fixed_font_size,
        text_color=text_color,
        mask_style=mask_style,
        force_refresh=True,
        options=opts,
    )

    errors_count = sum(1 for p in session["pages"] if p.get("status") == "error")
    session["errors_count"] = errors_count
    if errors_count == 0:
        session["status"] = "finished"
        try:
            input_file = Path(session["input_file"])
            fmt = session["fmt"]
            safe_stem = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", input_file.stem)
            ext = ".cbz" if fmt in ("folder", "cbz") else input_file.suffix
            final_filename = f"{safe_stem}_fr_{session_id}{ext}"
            permanent_out_path = OUTPUT_DIR / final_filename
            ArchiveHandler.pack(
                fmt="cbz" if fmt == "folder" else fmt,
                input_path=input_file,
                output_path=permanent_out_path,
                items=session["items"],
                rendered_images=session["translated_images"],
            )
            session["permanent_file"] = str(permanent_out_path)
            session["permanent_filename"] = final_filename
        except Exception as exc:
            print("[Library] Erreur auto-archivage permanent lors du retranslate:", exc)

    return {"session_id": session_id, "page_idx": page_idx, **res}


@app.post("/api/rerender/{session_id}/{page_idx}")
def rerender_page_bubbles(session_id: str, page_idx: int, data: Dict[str, Any]):
    """
    Live Bubble Editor endpoint: regenerates the translated page image in < 50 ms
    from edited blocks (text or coordinates) without calling the Cloud Vision API.
    """
    t0 = time.perf_counter()
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session introuvable")
    if page_idx < 0 or page_idx >= session["total_pages"]:
        raise HTTPException(status_code=400, detail="Index de page invalide")

    raw_blocks = data.get("blocks")
    if not isinstance(raw_blocks, list):
        raise HTTPException(status_code=400, detail="Liste 'blocks' requise")

    last_opts = session.get("last_render_options", {})
    font_style = data.get("font_style", last_opts.get("font_style", "bold"))
    fixed_font_size = int(data.get("fixed_font_size", last_opts.get("fixed_font_size", 0)) or 0)
    text_color = data.get("text_color", last_opts.get("text_color", "#000000"))
    mask_style = data.get("mask_style") or data.get("bubble_shape") or last_opts.get("mask_style", "smart")

    norm_blocks: List[Dict[str, Any]] = []
    for b in raw_blocks:
        if not isinstance(b, dict):
            continue
        box = b.get("box")
        if box and len(box) == 4:
            x0, y0, x1, y1 = [float(v) for v in box]
        elif all(k in b for k in ("x", "y", "w", "h")):
            x0 = float(b["x"])
            y0 = float(b["y"])
            x1 = x0 + float(b["w"])
            y1 = y0 + float(b["h"])
        else:
            continue
        trans = str(b.get("fr") or b.get("translation") or b.get("text") or "").strip()
        orig = str(b.get("ja") or b.get("original") or "").strip()
        norm_blocks.append({
            "box": (x0, y0, x1, y1),
            "type": str(b.get("type") or "speech"),
            "original": orig,
            "translation": trans,
            "ja": orig,
            "fr": trans,
        })

    session_dir = Path(session["session_dir"])
    pages_dir = session_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    item = session["image_items"][page_idx]

    img = item.get_image()
    rendered = render_manga_page(
        img=img,
        blocks=norm_blocks,
        font_style=font_style,
        fixed_font_size=fixed_font_size,
        text_color=text_color,
        mask_style=mask_style,
    )
    trans_filename = f"page_{page_idx:03d}_trans.jpg"
    trans_path = pages_dir / trans_filename
    rendered.convert("RGB").save(trans_path, format="JPEG", quality=90)
    rendered.close()
    img.close()

    session["translated_images"][item.relative_name] = trans_path
    ser_blocks = _serialize_blocks(norm_blocks)
    session["pages"][page_idx]["status"] = "done"
    session["pages"][page_idx]["blocks_count"] = len(ser_blocks)
    session["pages"][page_idx]["blocks"] = ser_blocks
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    return {
        "status": "done",
        "session_id": session_id,
        "page_idx": page_idx,
        "blocks_count": len(ser_blocks),
        "blocks": ser_blocks,
        "elapsed_ms": elapsed_ms,
    }


@app.get("/api/status/{session_id}")
def get_session_status(session_id: str):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session introuvable")
    return {
        "status": session["status"],
        "current_page": session["current_page"],
        "total_pages": session["total_pages"],
        "progress_percent": session["progress_percent"],
        "current_log": session["current_log"],
        "last_bubble": session.get("last_bubble"),
        "errors_count": session.get("errors_count", 0),
        "pages": session["pages"],
    }


@app.get("/api/image/{session_id}/{version}/{page_idx}")
def get_page_image(session_id: str, version: str, page_idx: int):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session introuvable")

    pages_dir = Path(session["session_dir"]) / "pages"
    suffix = {"translated": "trans", "clean": "clean"}.get(version, "orig")
    img_file = pages_dir / f"page_{page_idx:03d}_{suffix}.jpg"

    if not img_file.exists():
        img_file = pages_dir / f"page_{page_idx:03d}_orig.jpg"

    if not img_file.exists():
        raise HTTPException(status_code=404, detail="Image non trouvée")

    return FileResponse(img_file, media_type="image/jpeg")


@app.get("/api/download/{session_id}")
def download_translated_manga(session_id: str):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session introuvable")

    perm_file = session.get("permanent_file")
    if perm_file and Path(perm_file).exists():
        perm_path = Path(perm_file)
        return FileResponse(perm_path, filename=perm_path.name, media_type="application/octet-stream")

    session_dir = Path(session["session_dir"])
    input_file = Path(session["input_file"])
    fmt = session["fmt"]

    if fmt == "folder":
        out_name = f"{input_file.name}_fr.cbz"
        out_path = session_dir / out_name
        ArchiveHandler.pack(
            fmt="cbz",
            input_path=input_file,
            output_path=out_path,
            items=session["items"],
            rendered_images=session["translated_images"],
        )
    else:
        out_name = f"{input_file.stem}_fr{input_file.suffix}"
        out_path = session_dir / out_name
        ArchiveHandler.pack(
            fmt=fmt,
            input_path=input_file,
            output_path=out_path,
            items=session["items"],
            rendered_images=session["translated_images"],
        )

    # Also preserve in permanent OUTPUT_DIR
    try:
        perm_dest = OUTPUT_DIR / f"{Path(out_name).stem}_{session_id}{Path(out_name).suffix}"
        if not perm_dest.exists():
            shutil.copy2(out_path, perm_dest)
    except Exception:
        pass

    return FileResponse(out_path, filename=out_name, media_type="application/octet-stream")


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except Exception:
                pass
    return total


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} o"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} Ko"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} Mo"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} Go"


@app.get("/api/system/storage")
def get_storage_stats():
    cache_sz = _dir_size(CACHE_DIR)
    sessions_sz = _dir_size(SESSIONS_DIR)
    output_sz = _dir_size(OUTPUT_DIR)
    history_count = 0
    history_file = BASE_DIR / "history" / "sessions.json"
    if history_file.exists():
        try:
            hdata = json.loads(history_file.read_text(encoding="utf-8"))
            history_count = len(hdata) if isinstance(hdata, list) else 0
        except Exception:
            pass
    total_sz = cache_sz + sessions_sz + output_sz
    storage_dir = os.environ.get("MTS_STORAGE_DIR", str(BASE_DIR / "data"))

    return {
        "status": "ok",
        "storage_dir": storage_dir,
        "sizes": {
            "cache_bytes": cache_sz,
            "cache_human": _format_size(cache_sz),
            "sessions_bytes": sessions_sz,
            "sessions_human": _format_size(sessions_sz),
            "output_bytes": output_sz,
            "output_human": _format_size(output_sz),
            "history_count": history_count,
            "total_bytes": total_sz,
            "total_human": _format_size(total_sz),
        },
    }


@app.post("/api/system/storage/purge")
def purge_storage(payload: Dict[str, Any]):
    target = payload.get("target", "all")
    keep_sid = payload.get("keep_session_id")
    freed_bytes = 0
    history_file = BASE_DIR / "history" / "sessions.json"

    # 1. Purge OCR cache
    if target in ("cache", "all"):
        if CACHE_DIR.exists():
            for f in CACHE_DIR.glob("*.json"):
                try:
                    freed_bytes += f.stat().st_size
                    f.unlink()
                except Exception:
                    pass

    # 2. Purge past sessions (keep active sessions)
    if target in ("sessions", "all"):
        if SESSIONS_DIR.exists():
            active_sids = set(sessions.keys())
            if keep_sid:
                active_sids.add(keep_sid)
            for s_folder in SESSIONS_DIR.iterdir():
                if s_folder.is_dir() and s_folder.name not in active_sids:
                    sz = _dir_size(s_folder)
                    try:
                        shutil.rmtree(s_folder)
                        freed_bytes += sz
                    except Exception:
                        pass

    # 3. Purge output translated files
    if target in ("output", "all"):
        if OUTPUT_DIR.exists():
            for f in OUTPUT_DIR.iterdir():
                if f.is_file():
                    try:
                        freed_bytes += f.stat().st_size
                        f.unlink()
                    except Exception:
                        pass

    # 4. Purge history
    if target in ("history", "all"):
        if history_file.exists():
            try:
                if keep_sid:
                    try:
                        hdata = json.loads(history_file.read_text(encoding="utf-8"))
                        kept = [entry for entry in hdata if entry.get("session_id") == keep_sid]
                        history_file.write_text(json.dumps(kept, indent=2, ensure_ascii=False), encoding="utf-8")
                    except Exception:
                        history_file.write_text("[]\n", encoding="utf-8")
                else:
                    history_file.write_text("[]\n", encoding="utf-8")
            except Exception:
                pass

    return {
        "status": "ok",
        "freed_bytes": freed_bytes,
        "freed_human": _format_size(freed_bytes),
        "target": target,
    }


@app.post("/api/system/storage/directory")
def update_storage_directory(payload: Dict[str, Any]):
    new_dir = str(payload.get("storage_dir", "")).strip()
    if not new_dir:
        raise HTTPException(status_code=400, detail="Chemin de répertoire invalide")
    target_path = Path(new_dir).expanduser().resolve()
    try:
        target_path.mkdir(parents=True, exist_ok=True)
        # Test write permission
        test_file = target_path / ".mts_write_test"
        test_file.write_text("test")
        test_file.unlink()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Impossible d'écrire dans ce dossier : {e}")

    save_env_key("MTS_STORAGE_DIR", str(target_path))
    return {
        "status": "ok",
        "storage_dir": str(target_path),
        "message": f"Dossier de stockage configuré avec succès : {target_path}",
    }
