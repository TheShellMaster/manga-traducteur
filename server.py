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
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
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

# Application constants
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = USER_DIR / "data"
SESSIONS_DIR = DATA_DIR / "sessions"
OUTPUT_DIR = DATA_DIR / "output"
CACHE_DIR = DATA_DIR / "cache"
HISTORY_FILE = USER_DIR / "history" / "sessions.json"
TEMPLATES_DIR = BASE_DIR / "web" / "templates"
STATIC_DIR = BASE_DIR / "web" / "static"
for _dir in (DATA_DIR, SESSIONS_DIR, OUTPUT_DIR, CACHE_DIR, HISTORY_FILE.parent):
    _dir.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Manga Translator Studio")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

sessions: Dict[str, Dict[str, Any]] = {}
_session_state_lock = threading.Lock()


def _record_session_history(session: Dict[str, Any], model_name: str):
    try:
        history = []
        if HISTORY_FILE.exists():
            history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
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


def _get_image_cache_key(img_bytes: bytes, tgt_lang: str, provider: str = "auto", model: str = "", src_lang: str = "Japanese") -> str:
    h = hashlib.sha256(img_bytes).hexdigest()
    scope = "_".join(value.lower().strip() for value in (provider, model, src_lang, tgt_lang))
    return f"{h}_{hashlib.sha256(scope.encode()).hexdigest()[:16]}"


def _load_cached_page_blocks(img_bytes: bytes, tgt_lang: str, provider: str = "auto", model: str = "", src_lang: str = "Japanese") -> Optional[Tuple[List[Dict[str, Any]], str]]:
    key = _get_image_cache_key(img_bytes, tgt_lang, provider, model, src_lang)
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


def _save_cached_page_blocks(img_bytes: bytes, tgt_lang: str, blocks: List[Dict[str, Any]], model_name: str, provider: str = "auto", model: str = "", src_lang: str = "Japanese"):
    try:
        key = _get_image_cache_key(img_bytes, tgt_lang, provider, model, src_lang)
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
                    "size_mb": size_mb,
                    "date": mtime_str,
                    "download_url": f"/api/library/download/{p.name}",
                })
    return {"library": items}


@app.get("/api/history")
def get_history():
    return get_translation_history()


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
    preset_url = PROVIDER_PRESETS.get(provider, {}).get("base_url")
    allowed_url = os.environ.get("CUSTOM_BASE_URL", "") if provider == "custom" else preset_url
    if provider == "ollama":
        allowed_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    if base_url and base_url.rstrip("/") != str(allowed_url or "").rstrip("/"):
        return {"ok": False, "error": "Adresse personnalisée non autorisée pour ce fournisseur."}
    if not base_url:
        base_url = allowed_url or ""
    if not api_key and provider != "custom":
        return {"ok": False, "error": "Clé API manquante."}
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if provider == "gemini":
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                resp = await client.post(url, headers={"x-goog-api-key": api_key}, json={"contents": [{"parts": [{"text": "Reply with: OK"}]}]})
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
        "custom_base_url": os.environ.get("CUSTOM_BASE_URL", "https://openrouter.ai/api/v1"),
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
            p: bool(os.environ.get("CUSTOM_API_KEY" if p == "custom" else f"{p.upper()}_API_KEY"))
            for p in ("gemini", "openrouter", "groq", "openai", "mistral", "nvidia", "custom")
        },
    }


_SETTING_KEYS = {
    "gemini_api_key", "openrouter_api_key", "groq_api_key", "openai_api_key",
    "mistral_api_key", "nvidia_api_key", "custom_api_key", "custom_base_url",
    "custom_model", "default_provider", "selected_model", "src_lang", "tgt_lang",
    "font_style", "fixed_font_size", "text_color", "mask_style",
}


@app.post("/api/settings")
async def save_settings(data: Dict[str, Any]):
    unknown = set(data) - _SETTING_KEYS
    if unknown:
        raise HTTPException(status_code=400, detail="Paramètre non autorisé.")
    for key, value in data.items():
        if value is None:
            continue
        value = str(value).strip()
        if len(value) > 4096 or "\n" in value or "\r" in value or "\x00" in value:
            raise HTTPException(status_code=400, detail="Valeur de paramètre invalide.")
        save_env_key(key.upper(), value)
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
            or (os.environ.get("OPENROUTER_API_KEY") if provider == "openrouter" else "")
            or ""
        )

    base_url = str(payload.get("base_url") or "").strip()
    preset_url = PROVIDER_PRESETS.get(provider, {}).get("base_url")
    allowed_url = os.environ.get("CUSTOM_BASE_URL", "") if provider == "custom" else preset_url
    if provider == "ollama":
        allowed_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    if base_url and base_url.rstrip("/") != str(allowed_url or "").rstrip("/"):
        return {"status": "error", "provider": provider, "models": [], "warning": "Adresse personnalisée non autorisée pour ce fournisseur."}
    if not base_url:
        base_url = allowed_url or ""

    models_list = []

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            if provider == "gemini":
                if not api_key:
                    # Provide official verified presets if no key yet
                    preset_models = PROVIDER_PRESETS.get("gemini", {}).get("models", [])
                    return {"status": "ok", "provider": provider, "models": preset_models}
                url = "https://generativelanguage.googleapis.com/v1beta/models"
                resp = await client.get(url, headers={"x-goog-api-key": api_key})
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
                        models_list.append({"id": mid, "label": f"{mid} (Groq LPU)", "is_free": False})
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
    image_items = [it for it in items if it.is_image]

    if not image_items:
        shutil.rmtree(session_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="Aucune image trouvée dans le fichier ou dossier fourni.")

    pages_info = []
    pages_dir = session_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    for idx, it in enumerate(image_items):
        img = it.get_image()
        orig_name = f"page_{idx:03d}_orig.jpg"
        w, h = img.width, img.height
        img.convert("RGB").save(pages_dir / orig_name, format="JPEG", quality=85)
        img.close()
        pages_info.append({
            "index": idx,
            "relative_name": it.relative_name,
            "status": "pending",
            "width": w,
            "height": h,
            "blocks_count": 0,
            "blocks": [],
        })
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

    session_id = str(uuid.uuid4())
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

    session_id = str(uuid.uuid4())
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
        cached = _load_cached_page_blocks(raw_img_bytes, tgt_lang, client.provider, client.model or "", client.src_lang)
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
            refine_translations_with_groq(
                blocks,
                target_lang=tgt_lang,
                context_history=context_history,
            )
            _save_cached_page_blocks(raw_img_bytes, tgt_lang, blocks, model_name, client.provider, client.model or "", client.src_lang)

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


def _translation_concurrency(options: Dict[str, Any], total: int) -> int:
    """Default to one page at a time; clamp explicit parallelism to safe bounds."""
    try:
        requested = int(options.get("concurrency") or 1)
    except (TypeError, ValueError):
        requested = 1
    return min(3, max(1, requested), max(1, total))


def _run_translation_worker(session_id: str, options: Dict[str, Any]):
    session = sessions.get(session_id)
    if not session:
        return

    if session.get("cancelled"):
        session["status"] = "cancelled"
        session["current_log"] = "Traduction annulée avant son démarrage."
        return
    session["status"] = "translating"

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

    # Inter-page context memory: last 8 translated lines across previous pages
    context_history: List[Dict[str, str]] = []
    last_model = "Cloud Vision"
    completed_count = 0

    # Multi-page translation with sequential execution as the safe default.
    # Keep provider requests page-scoped and sequential by default. Parallelism is
    # an explicit opt-in because many free tiers enforce strict per-minute quotas.
    concurrency = _translation_concurrency(options, total)

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
            return page_idx, {
                "status": "done",
                "blocks_count": session["pages"][page_idx].get("blocks_count", 0),
                "blocks": session["pages"][page_idx].get("blocks", []),
                "model": "Resumed (cache disque)",
            }

        ctx_snapshot = list(context_history[-8:])
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
        )
        return page_idx, res

    # Translate and commit pages in archive order. Eagerly submitting multiple
    # pages lets a worker read stale context before the prior page is committed,
    # even with max_workers=1. Serial dispatch keeps context and progress ordered.
    for p_idx in range(total):
        if session.get("cancelled"):
            session["status"] = "cancelled"
            session["current_log"] = "Traduction annulée."
            return
        try:
            result = _worker_task(p_idx)
            if not result:
                continue
            _, res = result
            completed_count += 1
            session["progress_percent"] = round((completed_count / total) * 100) if total > 0 else 100

            if res.get("status") == "done":
                last_model = res.get("model", "Cloud Vision")
                last_blocks = res.get("blocks", [])
                for b in last_blocks:
                    if b.get("original") or b.get("translation"):
                        context_history.append({
                            "original": b.get("original", ""),
                            "translation": b.get("translation", ""),
                        })
                if len(context_history) > 12:
                    context_history = context_history[-12:]

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
        except Exception:
            completed_count += 1
            session["progress_percent"] = round((completed_count / total) * 100) if total > 0 else 100

    session["status"] = "finished"
    session["progress_percent"] = 100
    failed_pages = [
        {"index": p.get("index", i), "relative_name": p.get("relative_name", ""), "error": p.get("error", "")}
        for i, p in enumerate(session["pages"][:total]) if p.get("status") == "error"
    ]
    n_err = len(failed_pages)
    session["errors_count"] = n_err
    session["failed_pages"] = failed_pages
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


def _run_translation_worker_safely(session_id: str, options: Dict[str, Any]):
    """Keep failed background runs observable without leaking provider exception details."""
    try:
        _run_translation_worker(session_id, options)
    except Exception:
        session = sessions.get(session_id)
        if session:
            session["status"] = "error"
            session["current_log"] = "La traduction a échoué avant son terme. Vérifiez les paramètres et les journaux locaux."


@app.post("/api/translate/start")
def start_translation(data: Dict[str, Any], background_tasks: BackgroundTasks):
    session_id = data.get("session_id")
    if not session_id:
        raise HTTPException(status_code=404, detail="Session introuvable")

    requested_concurrency = data.get("concurrency", 1)
    if isinstance(requested_concurrency, bool):
        raise HTTPException(status_code=400, detail="La concurrence doit être un entier de 1 à 3.")
    try:
        requested_concurrency = int(requested_concurrency)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="La concurrence doit être un entier de 1 à 3.")
    if requested_concurrency < 1 or requested_concurrency > 3:
        raise HTTPException(status_code=400, detail="La concurrence doit être un entier de 1 à 3.")

    # Reserve the session before queuing work so duplicate HTTP requests cannot
    # start two workers against the same page files and provider quota.
    with _session_state_lock:
        session = sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session introuvable")
        if session.get("status") in ("queued", "translating"):
            raise HTTPException(status_code=409, detail="Traduction déjà en cours.")
        session["status"] = "queued"
        session["cancelled"] = False

    options = {k: v for k, v in data.items() if k != "session_id"}
    background_tasks.add_task(_run_translation_worker_safely, session_id, options)
    return {"status": "started", "session_id": session_id}


@app.post("/api/translate/cancel/{session_id}")
def cancel_translation(session_id: str):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session introuvable")
    session["cancelled"] = True
    return {"status": "cancelled", "session_id": session_id}


@app.post("/api/translate/page/{session_id}/{page_idx}")
def retranslate_single_page(session_id: str, page_idx: int, data: Optional[Dict[str, Any]] = None):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session introuvable")
    if page_idx < 0 or page_idx >= session["total_pages"]:
        raise HTTPException(status_code=404, detail="Page introuvable")
    opts = data or {}
    provider = opts.get("provider", "auto")
    api_key = opts.get("api_key") or None
    base_url = opts.get("base_url") or None
    model = opts.get("model") or None
    tgt_lang = opts.get("tgt_lang", "French")
    render_opts = session.get("last_render_options", {})
    client = CloudVisionClient(provider=provider, api_key=api_key, base_url=base_url, model=model, src_lang=opts.get("src_lang", "Japanese"), tgt_lang=tgt_lang)
    res = _translate_single_page(session, page_idx, client, tgt_lang, render_opts.get("font_style", "bold"), render_opts.get("fixed_font_size", 0), render_opts.get("text_color", "#000000"), render_opts.get("mask_style", "smart"))
    return {"session_id": session_id, "page_idx": page_idx, **res}


@app.post("/api/rerender/{session_id}/{page_idx}")
def rerender_page_bubbles(session_id: str, page_idx: int, data: Dict[str, Any]):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session introuvable")
    if page_idx < 0 or page_idx >= session["total_pages"]:
        raise HTTPException(status_code=404, detail="Page introuvable")
    page = session["pages"][page_idx]
    if page.get("status") != "done":
        raise HTTPException(status_code=400, detail="Page non traduite")
    blocks = []
    for block in data.get("blocks", []):
        box = block.get("box", (0, 0, 100, 100))
        blocks.append({
            "box": tuple(float(v) for v in box),
            "type": str(block.get("type") or "speech"),
            "original": str(block.get("original") or block.get("ja") or ""),
            "translation": str(block.get("fr") or block.get("translation") or ""),
            "ja": str(block.get("ja") or block.get("original") or ""),
            "fr": str(block.get("fr") or block.get("translation") or ""),
        })
    img = session["image_items"][page_idx].get_image()
    opts = session.get("last_render_options", {})
    rendered = render_manga_page(img, blocks, **opts)
    pages_dir = Path(session["session_dir"]) / "pages"
    out = pages_dir / f"page_{page_idx:03d}_trans.jpg"
    rendered.convert("RGB").save(out, format="JPEG", quality=90)
    rendered.close()
    img.close()
    session["pages"][page_idx]["blocks"] = _serialize_blocks(blocks)
    session["pages"][page_idx]["blocks_count"] = len(blocks)
    return {"status": "ok", "page_idx": page_idx}


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
        "failed_pages": session.get("failed_pages", []),
        "pages": session["pages"],
    }


@app.get("/api/image/{session_id}/{version}/{page_idx}")
def get_page_image(session_id: str, version: str, page_idx: int):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session introuvable")
    pages_dir = Path(session["session_dir"]) / "pages"
    suffix = {"translated": "trans", "clean": "clean"}.get(version, "orig")
    image_path = pages_dir / f"page_{page_idx:03d}_{suffix}.jpg"
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image introuvable")
    return FileResponse(image_path)


@app.get("/api/download/{session_id}")
def download_translated_manga(session_id: str):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session introuvable")
    if session.get("status") != "finished":
        raise HTTPException(status_code=400, detail="Traduction non terminée")
    out_path = session.get("permanent_file")
    if not out_path or not Path(out_path).exists():
        raise HTTPException(status_code=404, detail="Archive introuvable")
    return FileResponse(out_path, filename=session.get("permanent_filename", Path(out_path).name), media_type="application/octet-stream")


@app.get("/api/library/download/{filename}")
def download_library_file(filename: str):
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide")
    path = OUTPUT_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@app.get("/api/pipeline")
def pipeline_status():
    return {"status": "ok"}
