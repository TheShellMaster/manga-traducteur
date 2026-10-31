import base64
import io
import json
import os
import random
import re
import sys
import time
from typing import List, Dict, Any, Tuple, Optional
from PIL import Image

from app.config import (
    load_env,
    OPENROUTER_FREE_VISION_MODELS,
    NVIDIA_NIM_VISION_MODELS,
    GEMINI_FREE_VISION_MODELS,
    PROVIDER_PRESETS,
)


def build_system_prompt(
    src_lang: str = "Japanese",
    tgt_lang: str = "French",
    context_history: Optional[List[Dict[str, str]]] = None,
) -> str:
    ctx_block = ""
    if context_history:
        recent = context_history[-8:]
        ctx_block = (
            "\nPrevious pages context (keep character names, gender pronouns, and tu/vous register consistent):\n"
            + json.dumps(recent, ensure_ascii=False)
            + "\n"
        )
    return f"""You are an expert manga and comic translator.
Analyze this manga page image and detect every speech bubble, thought bubble, caption, narration box, and readable text block.
{ctx_block}
Return ONLY a valid JSON array, with no surrounding markdown or commentary:
[
  {{
    "x": 100,
    "y": 150,
    "w": 200,
    "h": 120,
    "type": "speech",
    "original": "<original {src_lang} text>",
    "translation": "<natural spoken {tgt_lang} translation>"
  }}
]

Rules:
1. Bounding box coordinates (x, y, w, h) are normalized integers from 0 to 1000:
   - x, y: top-left corner of the text block (0-1000)
   - w, h: width and height (x + w <= 1000, y + h <= 1000)
   - "type": one of "speech", "thought", "narration", "sfx"
2. Follow standard manga reading order: right-to-left, top-to-bottom.
3. Translate into natural, fluent, idiomatic spoken {tgt_lang} suitable for comic speech bubbles.
4. Ignore tiny watermarks, page numbers, credits, or scanlation logos.
5. Strictly output ONLY the JSON array."""


def encode_image_for_vision(img: Image.Image, max_side: int = 1600) -> Tuple[bytes, str]:
    """
    Resizes image keeping aspect ratio for Vision APIs.
    Adapts dynamically to standard manga scans, double-page spreads, and tall Webtoon/Manhwa strips.
    """
    img = img.convert("RGB")
    width, height = img.size
    long_side = max(width, height)
    short_side = max(1, min(width, height))
    aspect = long_side / float(short_side)

    if aspect > 2.4:
        # Webtoon / vertical strip: preserve horizontal legibility while capping extreme height
        scale = min(1.0, 1080.0 / short_side, 3200.0 / long_side)
    elif width > height * 1.15:
        # Double-page spread: allow higher horizontal resolution up to 2200px
        scale = min(1.0, float(max(max_side, 2200)) / long_side)
    else:
        scale = min(1.0, float(max_side) / long_side)

    if scale < 1.0:
        new_w = max(1, round(width * scale))
        new_h = max(1, round(height * scale))
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    raw_bytes = buf.getvalue()
    b64_str = base64.b64encode(raw_bytes).decode("utf-8")
    return raw_bytes, b64_str


def is_permanent_quota_error(exc: Exception) -> bool:
    """Detects permanent quota exhaustion (e.g. daily free limit exceeded) to immediately trigger provider failover."""
    err_str = str(exc).lower()
    return any(k in err_str for k in ("free-models-per-day", "insufficient_quota", "credit balance is too low", "billing"))


def is_transient_error(exc: Exception) -> bool:
    """Detects whether an API exception is transient (rate limit 429, 502/503/504 overload, timeouts)."""
    if is_permanent_quota_error(exc):
        return False
    err_str = str(exc).lower()
    transient_indicators = [
        "429", "rate limit", "too many requests", "resourceexhausted",
        "503", "502", "504", "service unavailable", "bad gateway", "gateway timeout",
        "overloaded", "server is busy", "timeout", "timed out",
        "connection reset", "connection refused", "remoteprotocolerror", "try again",
    ]
    return any(ind in err_str for ind in transient_indicators)


def execute_with_backoff(
    func,
    *args,
    max_retries: int = 3,
    initial_delay: float = 2.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    **kwargs,
):
    """Executes an API call with automatic exponential backoff and jitter on transient errors (429/503/timeouts)."""
    delay = initial_delay
    for attempt in range(1, max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            if attempt < max_retries and is_transient_error(exc):
                jitter_mult = random.uniform(0.75, 1.25) if jitter else 1.0
                actual_delay = delay * jitter_mult
                print(f"[CloudVision] Erreur temporaire détectée ({type(exc).__name__}: {str(exc)[:90]}). Nouvelle tentative {attempt + 1}/{max_retries} après {actual_delay:.2f}s...")
                time.sleep(actual_delay)
                delay *= backoff_factor
            else:
                raise


def parse_and_validate_blocks(raw_text: str) -> List[Dict[str, Any]]:
    """
    Extracts JSON blocks from model response and validates/disambiguates normalized coordinates.
    Supports:
    - {"x": x, "y": y, "w": w, "h": h}
    - {"xmin": x0, "ymin": y0, "xmax": x1, "ymax": y1}
    - {"box": [x, y, w, h]}
    Auto-corrects when a model outputs [xmin, ymin, xmax, ymax] inside x,y,w,h (where x + w > 1000).
    """
    raw = (raw_text or "").strip()
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if m:
        raw = m.group(1).strip()

    # Pre-clean raw string to remove invalid unescaped control characters before parsing JSON
    cleaned_raw = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw)

    data = None
    try:
        data = json.loads(cleaned_raw)
    except Exception:
        start = cleaned_raw.find("[")
        end = cleaned_raw.rfind("]")
        if start != -1 and end > start:
            try:
                data = json.loads(cleaned_raw[start:end + 1])
            except Exception:
                pass
        if data is None and start != -1:
            # Attempt to salvage truncated JSON array
            sub = cleaned_raw[start:]
            last_brace = sub.rfind("}")
            if last_brace != -1:
                try:
                    data = json.loads(sub[:last_brace + 1] + "]")
                except Exception:
                    pass

    if data is None:
        raise ValueError(f"Réponse LLM non-JSON : {raw[:200]}")

    if isinstance(data, dict):
        for key in ("blocks", "text_blocks", "items", "data", "results"):
            if key in data and isinstance(data[key], list):
                data = data[key]
                break

    if not isinstance(data, list):
        raise ValueError("Format attendu : liste JSON")

    valid_blocks: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue

        orig = str(item.get("original") or item.get("ja") or item.get("text") or "").strip()
        trans = str(item.get("translation") or item.get("fr") or item.get("french") or "").strip()
        btype = str(item.get("type") or "speech").strip().lower()

        x0 = y0 = x1 = y1 = None

        # Case 1: explicit xmin, ymin, xmax, ymax (or x1, y1, x2, y2)
        if all(k in item for k in ("xmin", "ymin", "xmax", "ymax")):
            try:
                x0 = float(item["xmin"])
                y0 = float(item["ymin"])
                x1 = float(item["xmax"])
                y1 = float(item["ymax"])
            except (TypeError, ValueError):
                continue
        elif all(k in item for k in ("x1", "y1", "x2", "y2")):
            try:
                x0 = float(item["x1"])
                y0 = float(item["y1"])
                x1 = float(item["x2"])
                y1 = float(item["y2"])
            except (TypeError, ValueError):
                continue
        # Case 2: explicit x, y, w, h keys
        elif all(k in item for k in ("x", "y", "w", "h")):
            try:
                x = float(item["x"])
                y = float(item["y"])
        trans = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", trans).strip()

        valid_blocks.append({
            "box": (x0, y0, x1, y1),
            "type": btype,
            "original": orig,
            "translation": trans,
            "fr": trans,
            "ja": orig,
        })

    return valid_blocks


class CloudVisionClient:
    """Universal Cloud Vision Client supporting Gemini, OpenRouter, Ollama Cloud, NVIDIA NIM, Anthropic, and custom endpoints."""

    def __init__(
        self,
        provider: str = "auto",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        src_lang: str = "Japanese",
        tgt_lang: str = "French",
    ):
        load_env()
        self.provider = (provider or "auto").lower()
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.src_lang = src_lang
        self.tgt_lang = tgt_lang

        if not self.api_key and self.provider not in ("auto", ""):
            env_key_name = "CUSTOM_API_KEY" if self.provider == "custom" else f"{self.provider.upper()}_API_KEY"
            self.api_key = os.environ.get(env_key_name)
        self.provider_key = self.api_key
        if self.provider == "auto" and not self.api_key:
            self.api_key = None
        if self.provider == "custom":
            self.base_url = self.base_url or os.environ.get("CUSTOM_BASE_URL")
            self.model = self.model or os.environ.get("CUSTOM_MODEL")

    def detect_and_translate(
        self,
        img: Image.Image,
        max_side: int = 1600,
        context_history: Optional[List[Dict[str, str]]] = None,
    ) -> Tuple[List[Dict[str, Any]], str]:
        """Performs vision translation via configured or auto provider with automatic fallback."""
        raw_bytes, b64_str = encode_image_for_vision(img, max_side=max_side)
        prompt = build_system_prompt(self.src_lang, self.tgt_lang, context_history=context_history)
        errors: List[str] = []

        # 1. Explicit Custom / Specific provider requested by user (Groq, OpenRouter, NVIDIA, Custom, OpenAI, Mistral)
        if self.provider in ("custom", "openai", "groq", "mistral", "nvidia") or (self.base_url and self.api_key and self.model):
            preset = PROVIDER_PRESETS.get(self.provider, {})
            target_url = self.base_url or preset.get("base_url") or "https://openrouter.ai/api/v1"
            target_model = self.model or preset.get("default_model") or "gpt-4o-mini"
            try:
                blocks = self._call_openai_compatible(
                    b64_str=b64_str,
                    base_url=target_url,
                    api_key=self.api_key or "",
                    model_name=target_model,
                    prompt=prompt,
                )
                return blocks, f"{self.provider}/{target_model}"
            except Exception as e:
                errors.append(f"{self.provider}/{target_model}: {str(e)[:140]}")
                print(f"[CloudVision] Échec sur {self.provider}/{target_model} ({e}). Basculement automatique vers les fournisseurs de secours configurés dans .env...")

        # 2. OpenRouter provider (Models: Nemotron 3.5, Qwen 2.5 VL 72B, Llama 3.2 11B)
        or_key = os.environ.get("OPENROUTER_API_KEY") or (self.provider_key if self.provider == "openrouter" else None)
        if or_key and self.provider != "openrouter":
            models_to_try = [self.model] if (self.model and "openrouter" in self.provider) else [
                "nvidia/nemotron-3.5-super-vl:free",
                "qwen/qwen-2.5-vl-72b-instruct",
                "meta-llama/llama-3.2-11b-vision-instruct",
            ]
            for m in models_to_try:
                try:
                    blocks = self._call_openai_compatible(
                        b64_str=b64_str,
                        base_url="https://openrouter.ai/api/v1",
                        api_key=or_key,
                        model_name=m,
                        prompt=prompt,
                    )
                    return blocks, f"openrouter/{m}"
                except Exception as exc:
                    err_str = str(exc)
                    errors.append(f"OpenRouter/{m}: {err_str[:140]}")
                    if is_permanent_quota_error(exc) or "free-models-per-day" in err_str:
                        print(f"[CloudVision] Quota OpenRouter atteint pour {m}. Basculement immédiat vers le fournisseur suivant...")
                        break

        # 3. Groq Cloud Vision provider (LPU Ultra-rapide)
        groq_key = os.environ.get("GROQ_API_KEY") or (self.provider_key if self.provider == "groq" else None)
        if groq_key and self.provider not in ("groq",):
            for m in ("qwen/qwen3.8-27b",):
                try:
                    blocks