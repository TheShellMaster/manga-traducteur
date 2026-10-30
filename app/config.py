import json
import os
import re
from pathlib import Path

import sys

APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
# Writable user folder: project folder in dev, ~/MangaTranslatorStudio once installed (frozen build)
if os.environ.get("MTS_HOME"):
    USER_DIR = Path(os.environ["MTS_HOME"]).expanduser()
elif getattr(sys, "frozen", False):
    USER_DIR = Path.home() / "MangaTranslatorStudio"
else:
    USER_DIR = ROOT_DIR
USER_DIR.mkdir(parents=True, exist_ok=True)
ENV_PATH = USER_DIR / ".env"
BUNDLED_FONTS_DIR = APP_DIR / "fonts"
HOME_ENV_PATH = Path.home() / ".env"
OPENCODE_AUTH_PATH = Path.home() / ".local" / "share" / "opencode" / "auth.json"
FONT_PATH = str(APP_DIR / "fonts" / "DejaVuSans-Bold.ttf")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def _load_env_file(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:]
        key, val = line.split("=", 1)
        clean_val = val.strip().strip('"').strip("'")
        if clean_val:
            os.environ.setdefault(key.strip(), clean_val)


def load_env():
    """Load variables from workspace .env and user global configs without overwriting."""
    _load_env_file(ENV_PATH)
    _load_env_file(HOME_ENV_PATH)
    if OPENCODE_AUTH_PATH.exists():
        try:
            auth_data = json.loads(OPENCODE_AUTH_PATH.read_text(encoding="utf-8"))
            nv_key = auth_data.get("nvidia", {}).get("key", "")
            if nv_key:
                os.environ.setdefault("NVIDIA_API_KEY", nv_key)
        except Exception:
            pass


def save_env_key(key: str, value: str):
    """Save or update an API key in the workspace .env file."""
    lines = []
    found = False
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{key}=") or line.strip().startswith(f"export {key}="):
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value


# Universal Provider Catalog & Verified Vision Models (Zero Invented Names)
PROVIDER_PRESETS = {
    "gemini": {
        "name": "Google Gemini (Recommandé - 1500 req/j gratuites)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "models": [
            {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash (Ultra-rapide, Quota gratuit)"},
            {"id": "gemini-2.5-flash-lite", "label": "Gemini 2.5 Flash Lite (Économique)"},
            {"id": "gemini-1.5-flash", "label": "Gemini 1.5 Flash (Stable)"},
            {"id": "gemini-2.5-pro", "label": "Gemini 2.5 Pro (Haute précision visuelle)"},
        ],
        "default_model": "gemini-2.5-flash",
    },
    "openrouter": {
        "name": "OpenRouter (Agrégateur Multi-Fournisseurs)",
        "base_url": "https://openrouter.ai/api/v1",
        "models": [
            {"id": "nvidia/nemotron-3.5-super-vl:free", "label": "Nvidia Nemotron 3.5 Super VL (Gratuit)"},
            {"id": "meta-llama/llama-3.2-11b-vision-instruct", "label": "Llama 3.2 11B Vision Instruct"},
            {"id": "qwen/qwen-2.5-vl-72b-instruct", "label": "Qwen 2.5 VL 72B (Excellente détection manga)"},
            {"id": "openai/gpt-4o", "label": "OpenAI GPT-4o Vision"},
            {"id": "anthropic/claude-3.5-sonnet", "label": "Anthropic Claude 3.5 Sonnet"},
        ],
        "default_model": "nvidia/nemotron-3.5-super-vl:free",
    },
    "openai": {
        "name": "OpenAI Direct (Officiel)",
        "base_url": "https://api.openai.com/v1",
        "models": [
            {"id": "gpt-4o", "label": "GPT-4o (Vision multimodal haute résolution)"},
            {"id": "gpt-4o-mini", "label": "GPT-4o Mini (Rapide et économique)"},
        ],
        "default_model": "gpt-4o-mini",
    },
    "groq": {
        "name": "Groq Cloud (Inférence Ultra-Rapide)",
        "base_url": "https://api.groq.com/openai/v1",
        "models": [
            {"id": "llama-3.2-11b-vision-preview", "label": "Llama 3.2 11B Vision (Groq LPU)"},
            {"id": "llama-3.2-90b-vision-preview", "label": "Llama 3.2 90B Vision (Groq LPU)"},
        ],
        "default_model": "llama-3.2-11b-vision-preview",
    },
    "mistral": {
        "name": "Mistral AI (Modèles Pixtral)",
        "base_url": "https://api.mistral.ai/v1",
        "models": [
            {"id": "pixtral-12b-2409", "label": "Pixtral 12B Vision"},
            {"id": "pixtral-large-latest", "label": "Pixtral Large Vision"},
        ],
        "default_model": "pixtral-12b-2409",
    },
    "nvidia": {
        "name": "NVIDIA NIM (Inférence Vision)",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "models": [
            {"id": "meta/llama-3.2-11b-vision-instruct", "label": "Llama 3.2 11B Vision (NVIDIA NIM)"},
            {"id": "meta/llama-3.2-90b-vision-instruct", "label": "Llama 3.2 90B Vision (NVIDIA NIM)"},
            {"id": "nvidia/nemotron-3.5-super-vl-120b-a12b", "label": "Nemotron 3.5 Super VL 120B"},
        ],
        "default_model": "meta/llama-3.2-11b-vision-instruct",
    },
    "custom": {
        "name": "Endpoint Personnalisé (Compatible OpenAI / Local Ollama / vLLM)",
        "base_url": "http://localhost:11434/v1",
        "models": [],
        "default_model": "llama3.2-vision",
    },
}

OPENROUTER_FREE_VISION_MODELS = [
    "nvidia/nemotron-3.5-super-vl:free",
    "meta-llama/llama-3.2-11b-vision-instruct",
]

NVIDIA_NIM_VISION_MODELS = [
    "meta/llama-3.2-11b-vision-instruct",
    "meta/llama-3.2-90b-vision-instruct",
    "nvidia/nemotron-3.5-super-vl-120b-a12b",
]

GEMINI_FREE_VISION_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-1.5-flash",
]

GROQ_DEFAULT_MODEL = "qwen/qwen3.8-27b"
