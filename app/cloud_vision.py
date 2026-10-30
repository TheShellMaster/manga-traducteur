import base64
import io
import json
import os
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
   - w, h: width and height of the text block (x + w <= 1000, y + h <= 1000)
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


def is_transient_error(exc: Exception) -> bool:
    """Detects whether an API exception is transient (rate limit 429, 503 overload, timeout)."""
    err_str = str(exc).lower()
    transient_indicators = [
        "429", "rate limit", "too many requests", "resourceexhausted", "quota",
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
    **kwargs,
):
    """Executes an API call with automatic exponential backoff on transient errors (429/503/timeouts)."""
    delay = initial_delay
    for attempt in range(1, max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            if attempt < max_retries and is_transient_error(exc):
                print(f"[CloudVision] Erreur temporaire détectée ({type(exc).__name__}: {str(exc)[:90]}). Nouvelle tentative {attempt + 1}/{max_retries} après {delay:.1f}s...")
                time.sleep(delay)
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

    data = None
    try:
        data = json.loads(raw)
    except Exception:
        start = raw.find("[")
        end = raw.rfind("]")
        if start != -1 and end > start:
            try:
                data = json.loads(raw[start:end + 1])
            except Exception:
                pass
        if data is None and start != -1:
            # Attempt to salvage truncated JSON array
            sub = raw[start:]
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
                w = float(item["w"])
                h = float(item["h"])
            except (TypeError, ValueError):
                continue
            if w <= 0 or h <= 0:
                continue
            # Auto-disambiguate if model returned (x2, y2) instead of (w, h) causing x + w > 1000
            if (x + w > 1000.0 and w > x and h > y) or (y + h > 1000.0 and h > y and w > x):
                x0, y0, x1, y1 = x, y, w, h
            else:
                x0, y0, x1, y1 = x, y, x + w, y + h
        # Case 3: array box / bbox / rect
        else:
            box = item.get("box") or item.get("bbox") or item.get("rect")
            if not box or len(box) != 4:
                continue
            try:
                x, y, w, h = [float(v) for v in box]
            except (TypeError, ValueError):
                continue
            if w <= 0 or h <= 0:
                continue
            if (x + w > 1000.0 and w > x and h > y) or (y + h > 1000.0 and h > y and w > x):
                x0, y0, x1, y1 = x, y, w, h
            else:
                x0, y0, x1, y1 = x, y, x + w, y + h

        x0 = max(0.0, min(1000.0, x0))
        y0 = max(0.0, min(1000.0, y0))
        x1 = max(0.0, min(1000.0, x1))
        y1 = max(0.0, min(1000.0, y1))

        if x1 - x0 < 6 or y1 - y0 < 6:
            continue
        if not orig and not trans:
            continue

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

        if not self.api_key:
            if self.provider not in ("auto", ""):
                self.api_key = os.environ.get(f"{self.provider.upper()}_API_KEY")
            else:
                self.api_key = (
                    os.environ.get("GEMINI_API_KEY")
                    or os.environ.get("OPENROUTER_API_KEY")
                    or os.environ.get("OLLAMA_API_KEY")
                    or os.environ.get("NVIDIA_API_KEY")
                )
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

        # 1. Explicit Custom / OpenAI compatible endpoint or specific providers (OpenAI, Groq, Mistral, Nvidia)
        if self.provider in ("custom", "openai", "groq", "mistral", "nvidia") or (self.base_url and self.api_key and self.model):
            preset = PROVIDER_PRESETS.get(self.provider, {})
            target_url = self.base_url or preset.get("base_url") or "https://openrouter.ai/api/v1"
            target_model = self.model or preset.get("default_model") or "gpt-4o-mini"
            blocks = self._call_openai_compatible(
                b64_str=b64_str,
                base_url=target_url,
                api_key=self.api_key or "",
                model_name=target_model,
                prompt=prompt,
            )
            return blocks, f"{self.provider}/{target_model}"

        # 2. Native Anthropic (if configured)
        if self.provider == "anthropic" or (self.provider == "auto" and os.environ.get("ANTHROPIC_API_KEY")):
            key = self.api_key if self.provider == "anthropic" else os.environ.get("ANTHROPIC_API_KEY")
            if key:
                model = self.model or "claude-3-opus-20240229"
                try:
                    blocks = self._call_anthropic(b64_str, key, model, prompt)
                    return blocks, f"anthropic/{model}"
                except Exception as e:
                    errors.append(f"Anthropic/{model}: {e}")
                    if self.provider == "anthropic":
                        raise

        # 3. Google Gemini provider
        if self.provider == "gemini" or (self.provider == "auto" and os.environ.get("GEMINI_API_KEY")):
            key = self.api_key if self.provider == "gemini" else os.environ.get("GEMINI_API_KEY")
            if key:
                model = self.model or GEMINI_FREE_VISION_MODELS[0]
                try:
                    blocks = self._call_gemini(raw_bytes, key, model, prompt)
                    return blocks, f"gemini/{model}"
                except Exception as e:
                    errors.append(f"Gemini/{model}: {e}")
                    if self.provider == "gemini":
                        raise

        # 4. OpenRouter provider
        or_key = (self.api_key if self.provider == "openrouter" else None) or os.environ.get("OPENROUTER_API_KEY")
        if or_key and self.provider in ("auto", "openrouter"):
            models_to_try = [self.model] if self.model else OPENROUTER_FREE_VISION_MODELS
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
                    if "free-models-per-day" in err_str:
                        break

        # 5. Fallback to NVIDIA NIM Vision if available
        nv_key = os.environ.get("NVIDIA_API_KEY")
        if nv_key:
            for m in NVIDIA_NIM_VISION_MODELS:
                try:
                    blocks = self._call_openai_compatible(
                        b64_str=b64_str,
                        base_url="https://integrate.api.nvidia.com/v1",
                        api_key=nv_key,
                        model_name=m,
                        prompt=prompt,
                    )
                    return blocks, f"nvidia-nim/{m}"
                except Exception as exc:
                    errors.append(f"NvidiaNIM/{m}: {str(exc)[:140]}")

        # 6. Fallback to Ollama Cloud if available (verified on https://ollama.com/v1/models)
        ollama_key = os.environ.get("OLLAMA_API_KEY")
        if ollama_key:
            for m in ("gemma4:31b", "nemotron-3-nano:30b"):
                try:
                    blocks = self._call_openai_compatible(
                        b64_str=b64_str,
                        base_url="https://ollama.com/v1",
                        api_key=ollama_key,
                        model_name=m,
                        prompt=prompt,
                    )
                    return blocks, f"ollama-cloud/{m}"
                except Exception as exc:
                    errors.append(f"OllamaCloud/{m}: {str(exc)[:140]}")

        raise RuntimeError("Échec Vision (" + " | ".join(errors) + ")")

    def _call_anthropic(self, b64_str: str, api_key: str, model_name: str, prompt: str) -> List[Dict[str, Any]]:
        """Calls Anthropic Claude vision API with exponential backoff on rate limits."""
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        def _do_call():
            response = client.messages.create(
                model=model_name,
                max_tokens=4000,
                temperature=0.2,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": b64_str,
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            )
            content = ""
            for block in response.content:
                if getattr(block, "text", None):
                    content += block.text
            return parse_and_validate_blocks(content)

        return execute_with_backoff(_do_call)

    def _call_gemini(self, image_bytes: bytes, api_key: str, model_name: str, prompt: str) -> List[Dict[str, Any]]:
        """Calls Gemini via google.generativeai or google.genai with exponential backoff."""
        def _do_call():
            try:
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                gmodel = genai.GenerativeModel(model_name)
                img_part = {"mime_type": "image/jpeg", "data": image_bytes}
                response = gmodel.generate_content([img_part, prompt])
                return parse_and_validate_blocks(response.text)
            except Exception:
                try:
                    from google import genai
                    from google.genai import types
                    client = genai.Client(api_key=api_key)
                    response = client.models.generate_content(
                        model=model_name,
                        contents=[types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"), prompt],
                    )
                    return parse_and_validate_blocks(response.text)
                except Exception as e:
                    raise RuntimeError(f"Gemini API error ({model_name}): {e}")

        return execute_with_backoff(_do_call)

    def _call_openai_compatible(
        self,
        b64_str: str,
        base_url: str,
        api_key: str,
        model_name: str,
        prompt: str,
    ) -> List[Dict[str, Any]]:
        """Calls any OpenAI-compatible Vision endpoint with exponential backoff."""
        from openai import OpenAI
        client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            default_headers={
                "User-Agent": "Mozilla/5.0",
                "HTTP-Referer": "https://github.com/manga-translator",
                "X-Title": "Manga Translator Web",
            },
            timeout=90,
            max_retries=0,
        )
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64_str}"},
                    },
                ],
            }
        ]

        def _do_call():
            resp = client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.2,
                max_tokens=4000,
            )
            content = resp.choices[0].message.content or ""
            return parse_and_validate_blocks(content)

        return execute_with_backoff(_do_call)
