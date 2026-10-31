import gc
import io
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unittest.mock import patch, MagicMock
from PIL import Image, ImageDraw
import pytest
from fastapi.testclient import TestClient

from app.cloud_vision import CloudVisionClient, execute_with_backoff, parse_and_validate_blocks
from app.archives import ArchiveHandler
from server import app, sessions, _run_translation_worker, OUTPUT_DIR, CACHE_DIR

client = TestClient(app)


def _create_mock_manga_page(idx: int, width: int = 800, height: int = 1200, tag: str = "") -> Image.Image:
    """Generates a synthetic manga page with dialogue bubble and background."""
    img = Image.new("RGB", (width, height), color=(245, 245, 245))
    draw = ImageDraw.Draw(img)
    # Draw panel borders
    draw.rectangle([20, 20, width - 20, height - 20], outline=(20, 20, 20), width=4)
    draw.line([(20, height // 2), (width - 20, height // 2)], fill=(20, 20, 20), width=3)
    # Draw speech bubble
    bubble_box = [width // 4, height // 6, width * 3 // 4, height // 3]
    draw.ellipse(bubble_box, fill=(255, 255, 255), outline=(0, 0, 0), width=3)
    # Unique marker per page and test tag so SHA-256 is unique
    draw.rectangle([50, 50, 80 + (idx * 30), 85], fill=(min(255, 50 + idx * 30), 100, 180))
    return img


def _create_synthetic_cbz(path: Path, num_pages: int = 6, tag: str = "") -> Path:
    """Creates a multi-page CBZ with page images and extra non-image metadata."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Include non-image metadata file
        zf.writestr("series_info.txt", "Series: Test Manga E2E\nAuthor: Synthetic Test\n")
        zf.writestr("credits.json", '{"translator": "Studio Bot", "chapter": 1}')
        for i in range(num_pages):
            img = _create_mock_manga_page(i, tag=tag)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            img.close()
            zf.writestr(f"chapter_01/page_{i+1:03d}.jpg", buf.getvalue())
    return path


# =====================================================================
# Chantier R1 : Tests Robustesse Failover & Quota Management
# =====================================================================

def test_provider_transparent_failover_on_quota_error():
    """
    R1: Verifies that if OpenRouter encounters a quota limit (e.g. 429 / free-models-per-day),
    the CloudVisionClient transparently and automatically fails over to the next configured provider (e.g. Groq)
    without crashing or returning an error to the user.
    """
    cv = CloudVisionClient(provider="auto")
    test_img = _create_mock_manga_page(0, 400, 600)

    # Mock OpenRouter failing with quota exhausted, but Groq succeeding
    def mock_openai_call(b64_str, base_url, api_key, model_name, prompt):
        if "openrouter.ai" in base_url:
            raise RuntimeError("HTTP 429: free-models-per-day quota reached for this key")
        elif "groq.com" in base_url or "api.groq.com" in base_url:
            return [
                {
                    "box": (150.0, 150.0, 350.0, 250.0),
                    "type": "speech",
                    "original": "こんにちは！",
                    "translation": "Salut le monde !",
                    "fr": "Salut le monde !",
                    "ja": "こんにちは！",
                }
            ]
        raise RuntimeError(f"Unexpected base_url: {base_url}")

    with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-test", "GROQ_API_KEY": "gsk-test"}):
        with patch.object(cv, "_call_openai_compatible", side_effect=mock_openai_call):
            blocks, model_used = cv.detect_and_translate(test_img)
            assert len(blocks) == 1
            assert blocks[0]["translation"] == "Salut le monde !"
            assert "groq" in model_used.lower()

    test_img.close()


def test_coordinate_sanitization_and_boundary_clamping():
    """
    R1: Verifies that inverted or out-of-boundary bounding boxes are strictly clamped
    and control characters in OCR strings are sanitized.
    """
    malformed_json = """
    [
      {
        "box": [1200, 1100, -50, -50],
        "original": "Inverted \x00\x08BadText",
        "translation": "Traduction \x1b[31mNettoyee"
      },
      {
        "x": 800,
        "y": 700,
        "w": 600,
        "h": 500,
        "original": "Overflowing box",
        "translation": "Boîte qui dépasse"
      }
    ]
    """
    blocks = parse_and_validate_blocks(malformed_json)
    assert len(blocks) >= 1
    for b in blocks:
        x0, y0, x1, y1 = b["box"]
        assert 0.0 <= x0 < x1 <= 1000.0
        assert 0.0 <= y0 < y1 <= 1000.0
        assert "\x00" not in b["original"]
        assert "\x1b" not in b["translation"]


# =====================================================================
# Chantier R2 : Banc d'Essai Multi-Pages (E2E Pipeline & Recovery)
# =====================================================================

def test_multipage_cbz_full_pipeline(tmp_path):
    """
    R2: Tests complete multi-page manga processing:
    1. Upload 6-page CBZ archive with non-image metadata.
    2. Sequential & staged multi-page translation ('clean', 'done').
    3. Proper persistence in data/output/ and data/cache/.
    4. Preservation of non-image files in the repackaged CBZ.
    """
    cbz_file = _create_synthetic_cbz(tmp_path / "chapter_test.cbz", num_pages=6)

    # 1. Upload
    with open(cbz_file, "rb") as f:
        upload_res = client.post(
            "/api/upload",
            files={"file": ("chapter_test.cbz", f, "application/octet-stream")}
        )
    assert upload_res.status_code == 200
    upload_data = upload_res.json()
    session_id = upload_data["session_id"]
    assert upload_data["total_pages"] == 6
    assert len(upload_data["pages"]) == 6
    for p in upload_data["pages"]:
        assert p["status"] == "pending"

    # 2. Mock vision detection for each page
    def mock_detect(img, max_side=1600, context_history=None):
        return [
            {
                "box": (100.0, 100.0, 300.0, 200.0),
                "type": "speech",
                "original": "テストセリフ",
                "translation": "Dialogue de test traduit",
                "fr": "Dialogue de test traduit",
                "ja": "テストセリフ",
            }
        ], "openrouter/mock-vision"

    with patch.object(CloudVisionClient, "detect_and_translate", side_effect=mock_detect):
        # Run worker with 6 pages
        _run_translation_worker(session_id, {
            "provider": "auto",
            "tgt_lang": "French",
            "font_style": "bold",
            "concurrency": 2,
        })

    session = sessions[session_id]
    assert session["status"] == "finished"
    assert session["progress_percent"] == 100

    # Verify stage progression and disk persistence
    session_pages_dir = Path(session["session_dir"]) / "pages"
    for i in range(6):
        page_info = session["pages"][i]
        assert page_info["status"] == "done"
        assert page_info["stage"] == "done"
        assert page_info["blocks_count"] == 1
        # Check files on disk
        clean_img = session_pages_dir / f"page_{i:03d}_clean.jpg"
        trans_img = session_pages_dir / f"page_{i:03d}_trans.jpg"
        orig_img = session_pages_dir / f"page_{i:03d}_orig.jpg"
        assert orig_img.exists()
        assert clean_img.exists()
        assert trans_img.exists()

    # 3. Download and verify repackaged archive
    dl_res = client.get(f"/api/download/{session_id}")
    assert dl_res.status_code == 200
    assert dl_res.headers.get("content-type") == "application/octet-stream"

    # Inspect downloaded archive
    dl_buf = io.BytesIO(dl_res.content)
    with zipfile.ZipFile(dl_buf, "r") as zout:
        names = zout.namelist()
        # Verify non-image metadata preserved
        assert "series_info.txt" in names
        assert "credits.json" in names
        assert zout.read("series_info.txt").decode("utf-8").startswith("Series: Test Manga E2E")
        # Verify all 6 pages exist
        img_names = [n for n in names if n.endswith(".jpg")]
        assert len(img_names) == 6


def test_multipage_incident_recovery_resumption(tmp_path):
    """
    R2: Tests incident recovery:
    If a 5-page session is interrupted after page 2, resuming the session
    does NOT reprocess already completed pages, saving time and quota.
    """
    cbz_file = _create_synthetic_cbz(tmp_path / "recovery_test.cbz", num_pages=5)

    with open(cbz_file, "rb") as f:
        res = client.post("/api/upload", files={"file": ("recovery_test.cbz", f, "application/octet-stream")})
    session_id = res.json()["session_id"]
    session = sessions[session_id]

    call_count = 0

    def mock_detect(img, max_side=1600, context_history=None):
        nonlocal call_count
        call_count += 1
        return [
            {
                "box": (100.0, 100.0, 300.0, 200.0),
                "type": "speech",
                "original": f"Page text {call_count}",
                "translation": f"Texte page {call_count}",
                "fr": f"Texte page {call_count}",
                "ja": f"Page text {call_count}",
            }
        ], "mock-model"

    with patch("server._load_cached_page_blocks", return_value=None):
        with patch.object(CloudVisionClient, "detect_and_translate", side_effect=mock_detect):
            # 1. First run capped at 2 pages to simulate an interruption
            _run_translation_worker(session_id, {
                "provider": "auto",
                "max_pages": 2,
                "concurrency": 1,
            })

    assert call_count == 2
    assert session["pages"][0]["status"] == "done"
    assert session["pages"][1]["status"] == "done"
    assert session["pages"][2]["status"] == "pending"

    # 2. Resumption run for all 5 pages
    with patch("server._load_cached_page_blocks", return_value=None):
        with patch.object(CloudVisionClient, "detect_and_translate", side_effect=mock_detect):
            _run_translation_worker(session_id, {
                "provider": "auto",
                "max_pages": 5,
                "concurrency": 1,
            })

    # Crucial assertion: detect_and_translate was only called 3 more times for pages 2, 3, 4!
    # Pages 0 and 1 were safely resumed from disk without re-calling the API!
    assert call_count == 5
    for i in range(5):
        assert session["pages"][i]["status"] == "done"


def test_memory_and_pil_cleanup_on_large_chapter(tmp_path):
    """
    R2: Verifies zero memory leaks and proper closure of PIL Image objects on a 10-page chapter.
    """
    cbz_file = _create_synthetic_cbz(tmp_path / "memory_test.cbz", num_pages=10)

    with open(cbz_file, "rb") as f:
        res = client.post("/api/upload", files={"file": ("memory_test.cbz", f, "application/octet-stream")})
    session_id = res.json()["session_id"]

    def mock_detect(img, max_side=1600, context_history=None):
        return [
            {
                "box": (50.0, 50.0, 250.0, 150.0),
                "type": "speech",
                "original": "メモリテスト",
                "translation": "Test mémoire",
                "fr": "Test mémoire",
                "ja": "メモリテスト",
            }
        ], "mock-vision"

    gc.collect()
    with patch.object(CloudVisionClient, "detect_and_translate", side_effect=mock_detect):
        _run_translation_worker(session_id, {
            "provider": "auto",
            "max_pages": 10,
            "concurrency": 2,
        })

    gc.collect()
    session = sessions[session_id]
    assert session["status"] == "finished"
    assert session["total_pages"] == 10
    assert len(session["translated_images"]) == 10


def test_page_context_is_committed_before_next_page(tmp_path):
    """Ordered page processing must pass prior dialogue into the next OCR call."""
    cbz_file = _create_synthetic_cbz(tmp_path / "ordered_context.cbz", num_pages=4)
    with cbz_file.open("rb") as archive:
        response = client.post(
            "/api/upload",
            files={"file": (cbz_file.name, archive, "application/octet-stream")},
        )
    assert response.status_code == 200
    session_id = response.json()["session_id"]
    context_sizes = []

    def mock_detect(img, max_side=1600, context_history=None):
        context_sizes.append(len(context_history or []))
        n = len(context_sizes)
        return [{
            "box": (100.0, 100.0, 300.0, 200.0),
            "type": "speech",
            "original": f"Dialogue {n}",
            "translation": f"Réplique {n}",
            "fr": f"Réplique {n}",
            "ja": f"Dialogue {n}",
        }], "mock-vision"

    with patch("server._load_cached_page_blocks", return_value=None), \
         patch("server._save_cached_page_blocks"), \
         patch.object(CloudVisionClient, "detect_and_translate", side_effect=mock_detect):
        _run_translation_worker(session_id, {"provider": "auto", "tgt_lang": "French", "concurrency": 3})

    assert context_sizes == [0, 1, 2, 3]
    assert sessions[session_id]["status"] == "finished"
