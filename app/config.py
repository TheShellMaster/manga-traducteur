import json
import os
import re
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT_DIR / ".env"
HOME_ENV_PATH = Path.home() / ".env"
OPENCODE_AUTH_PATH = Path.home() / ".local" / "share" / "opencode" / "auth.json"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
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


# Free Vision models on OpenRouter discovered via /api/v1/models (input_modalities includes "image")
OPENROUTER_FREE_VISION_MODELS = [
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3.5-super-vl:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "dots-studio/dots-3-note-preview:free",
]

# Free Vision models on Ollama Cloud discovered via https://ollama.com/v1/models & validated (HTTP 200)
OLLAMA_CLOUD_VISION_MODELS = [
    "gemma4:31b",
]

# Vision models on NVIDIA NIM discovered via https://integrate.api.nvidia.com/v1/models & validated (HTTP 200)
NVIDIA_NIM_VISION_MODELS = [
    "meta/llama-3.2-90b-vision-instruct",
    "meta/llama-3.2-11b-vision-instruct",
    "nvidia/nemotron-3.5-super-vl-120b-a12b",
]

# Free Vision models on Google Gemini (via Google AI Studio)
GEMINI_FREE_VISION_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-1.5-flash",
]

# Groq text refinement model discovered via https://api.groq.com/openai/v1/models & validated (HTTP 200)
GROQ_DEFAULT_MODEL = "qwen/qwen3.8-27b"
