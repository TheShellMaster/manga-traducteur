import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional, Callable, Dict
from PIL import Image

from app.config import load_env
from app.archives import ArchiveHandler, ArchiveItem
from app.cloud_vision import CloudVisionClient
from app.groq_refine import refine_translations_with_groq
from app.typesetter import render_manga_page


def run_translation_pipeline(
    input_path: str | Path,
    output_path: Optional[str | Path] = None,
    provider: str = "auto",
    max_side: int = 1600,
    target_lang: str = "French",
    use_refiner: Optional[bool] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Path:
    """End-to-end translation pipeline for manga archives, folders, and images.

    use_refiner: optional stylistic second pass. If None, reads REFINER_ENABLED
    from .env (disabled by default). A single translation model is enough for
    most users; the refiner only polishes phrasing when explicitly enabled.
    """
    load_env()
    src = Path(input_path).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"Fichier ou dossier source introuvable : {src}")

    # Refiner is OPT-IN: one good translation pass is the default.
    if use_refiner is None:
        use_refiner = os.environ.get("REFINER_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")

    # Determine default output path if not specified
    if output_path is None:
        if src.is_dir():
            dst = src.with_name(f"{src.name}_fr")
        else:
            dst = src.with_name(f"{src.stem}_fr{src.suffix}")
    else:
        dst = Path(output_path).expanduser().resolve()

    work_dir = Path(tempfile.mkdtemp(prefix="manga_trans_"))
    try:
        # 1. Extract archive / scan folder
        fmt, items = ArchiveHandler.extract(src, work_dir)
        image_items = [item for item in items if item.is_image]
        total_images = len(image_items)

        if total_images == 0:
            raise ValueError(f"Aucune image trouvée dans {src}")

        # 2. Initialize Cloud Vision Client
        client = CloudVisionClient(preferred_provider=provider)
        rendered_images: Dict[str, Image.Image] = {}

        for idx, item in enumerate(image_items, start=1):
            if progress_callback:
                progress_callback(idx, total_images, f"Traduction de {item.relative_name}...")

            img = item.get_image()
            try:
                # Detection + Translation via Cloud API
                blocks, model_used = client.detect_and_translate(img, max_side=max_side)
                # OPTIONAL stylistic refinement (only if user enabled it)
                if use_refiner:
                    refine_translations_with_groq(blocks, target_lang=target_lang)
                # Render translated text onto image
                rendered = render_manga_page(img, blocks)
                rendered_images[item.relative_name] = rendered
                info = f"{item.relative_name}: {len(blocks)} bulles traduites via {model_used}"
            except Exception as e:
                # If a page fails, keep the original image to avoid blocking the whole chapter
                rendered_images[item.relative_name] = img
                info = f"! {item.relative_name}: échec ({e}), page originale conservée"

            if progress_callback:
                progress_callback(idx, total_images, info)

        # 3. Pack items back into the exact original format
        if progress_callback:
            progress_callback(total_images, total_images, f"Création de la sortie : {dst.name}...")

        final_path = ArchiveHandler.pack(
            fmt=fmt,
            input_path=src,
            output_path=dst,
            items=items,
            rendered_images=rendered_images,
        )

        return final_path

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
