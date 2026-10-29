import json
import os
import re
from typing import List, Dict, Any, Optional
from openai import OpenAI

from app.config import GROQ_DEFAULT_MODEL


def refine_translations_with_groq(
    blocks: List[Dict[str, Any]],
    groq_api_key: Optional[str] = None,
    target_lang: str = "French",
    context_history: Optional[List[Dict[str, str]]] = None,
) -> None:
    """Uses Groq's fast free API to polish and harmonize all manga speech bubble translations."""
    key = groq_api_key or os.environ.get("GROQ_API_KEY")
    if not key or not blocks:
        return

    # Send ALL bubbles on the page that have source text or draft translation
    target_indices = [
        i for i, b in enumerate(blocks)
        if (b.get("ja") or b.get("original") or b.get("fr") or b.get("translation"))
    ]
    if not target_indices:
        return

    client = OpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=key,
        timeout=30,
        max_retries=1,
    )
    model = os.environ.get("GROQ_MODEL") or GROQ_DEFAULT_MODEL
    payload_items = [
        {
            "ja": str(blocks[i].get("ja") or blocks[i].get("original") or ""),
            "draft_fr": str(blocks[i].get("fr") or blocks[i].get("translation") or ""),
        }
        for i in target_indices
    ]

    ctx_section = ""
    if context_history:
        recent = context_history[-8:]
        ctx_section = (
            "Previous page context (keep character names, gender, and tu/vous register consistent):\n"
            + json.dumps(recent, ensure_ascii=False)
            + "\n\n"
        )

    prompt = (
        f"You are a professional manga scanlation editor and translator into {target_lang}.\n"
        "Polish and harmonize each manga speech bubble below into natural, punchy, idiomatic spoken "
        f"{target_lang} suitable for manga speech bubbles.\n"
        "Rules:\n"
        "- Improve awkward literal phrasing from 'draft_fr' while staying faithful to 'ja'.\n"
        "- Keep lines concise so they fit neatly inside comic bubbles.\n"
        "- Maintain consistent character voice, pronouns, and register across the page.\n"
        "- Return ONLY a valid JSON array of strings in the exact same order as the input array.\n"
        "- No markdown formatting, no explanations.\n\n"
        + ctx_section
        + "Input bubbles:\n"
        + json.dumps(payload_items, ensure_ascii=False)
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=2000,
        )
        content = resp.choices[0].message.content or ""
        # Strip reasoning <think>...</think> blocks if present
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        # Clean markdown code blocks if any
        m = re.search(r"```(?:json)?\s*(.*?)```", content, re.DOTALL)
        if m:
            content = m.group(1).strip()
        try:
            parsed = json.loads(content)
        except Exception:
            start = content.find("[")
            end = content.rfind("]")
            if start != -1 and end > start:
                parsed = json.loads(content[start:end + 1])
            else:
                return
        if isinstance(parsed, list) and len(parsed) == len(target_indices):
            for idx, trans in zip(target_indices, parsed):
                if isinstance(trans, str) and trans.strip():
                    cleaned = trans.strip()
                    blocks[idx]["fr"] = cleaned
                    blocks[idx]["translation"] = cleaned
    except Exception:
        # Groq refinement is an optional enhancement; never crash the pipeline if it fails
        pass
