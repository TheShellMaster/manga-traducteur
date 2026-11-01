"""Détection heuristique de bulles manga avec OCR facultatif.

Ce module ne remplace pas un modèle spécialisé : il fournit des régions
candidates à partir des contours OpenCV lorsqu'il est installé. En son
absence, il retourne une région pleine page (fallback explicite), jamais
une liste de bulles inventées.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

logger = logging.getLogger(__name__)
Box = Tuple[int, int, int, int]


def _regions(image: Image.Image) -> List[Box]:
    """Détecte des contours candidats, ou utilise la page entière en fallback."""
    width, height = image.size
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        gray = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
        # Les contours fermés à fort contraste sont des candidats, pas une
        # classification fiable de bulle. Filtrer les régions minuscules.
        threshold = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 31, 7,
        )
        contours, _ = cv2.findContours(
            threshold, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        boxes: List[Box] = []
        min_area = max(400, int(width * height * 0.001))
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w * h >= min_area and w >= 24 and h >= 16:
                boxes.append((x, y, x + w, y + h))
        # Une détection excessive de grandes régions nuit à l'OCR; conserver
        # les candidats triés de haut en bas et gauche à droite.
        if boxes:
            boxes.sort(key=lambda b: (b[1], b[0]))
            return boxes[:100]
    except ImportError:
        logger.info("OpenCV/numpy absent : repli OCR sur la page entière")
    except Exception:
        logger.exception("Échec de la détection par contours; repli pleine page")
    return [(0, 0, width, height)] if width and height else []


def detect_bubbles(image: Image.Image, *, ocr: bool = True) -> List[Dict[str, Any]]:
    """Retourne des régions candidate et le texte reconnu si Tesseract est disponible.

    Chaque élément contient ``box`` (gauche, haut, droite, bas) et ``text``.
    L'absence de moteur OCR ne fait pas échouer le traitement: le texte vaut
    une chaîne vide et l'appelant peut transmettre le crop à un LLM vision.
    """
    if not isinstance(image, Image.Image):
        raise TypeError("image doit être une instance PIL.Image.Image")
    results: List[Dict[str, Any]] = []
    for box in _regions(image):
        text = ""
        if ocr:
            try:
                import pytesseract  # type: ignore
                text = pytesseract.image_to_string(image.crop(box)).strip()
            except ImportError:
                logger.info("pytesseract absent : texte vide, le crop reste disponible")
            except Exception:
                logger.exception("Échec OCR pour la région %s", box)
        results.append({"box": box, "text": text})
    return results
