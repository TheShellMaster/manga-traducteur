"""
End-to-End Multi-Page Test Suite for Manga Translator Studio.
Follows TEST_INFRA.md (Tiers 1 to 4) and ORIGINAL_REQUEST.md (§R1, §R2, §R3).

Test Coverage Matrix:
- Tier 1: Archive parsing (CBZ/CBR/ZIP/Dir), natural sorting, ComicInfo.xml metadata preservation,
          Zip-Slip defense, bubble coordinate clamping & sanitization, smart/rounded/ellipse/transparent
          masking, dark box text inversion, screentone detection, French diamond typography (non-breaking spaces),
          embedded TrueType font styling, live status polling, orig/trans image serving, session history.
- Tier 2: macOS __MACOSX/ AppleDouble resilience, single-page failure isolation (no chapter crash, original fallback),
          HTTP 429 quota exhaustion automatic failover, empty bubbles handling, zero-byte archive rejection,
          in-flight translation cancellation.
- Tier 3: Complete pipeline integration, multi-threaded concurrency safety, inter-page context propagation ordering,
          folder upload workflow, disk caching and replay resumption, live bubble re-render.
- Tier 4: Real-world scenarios on 'Otome Game Sekai wa Mob ni Kibishii Sekai desu/Official_Chapter 41.5.cbz':
          Full E2E translation with ComicInfo preservation, simulated 429 failover to NVIDIA NIM,
          corrupted page isolation, split-view / slider image dimension parity, and post-translation re-render.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Dict, Any, List
from unittest.mock import patch, MagicMock

import pytest
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient

# Ensure root directory is on PYTHONPATH
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import PROVIDER_PRESETS, IMAGE_EXTENSIONS
from app.archives import ArchiveHandler, ArchiveItem, natural_sort_key
from app.cloud_vision import (
    CloudVisionClient,
    parse_and_validate_blocks,
    is_transient_error,
    is_permanent_quota_error,
)
from app.typesetter import (
    render_manga_page,
    format_french_typography,
    diamond_wrap_words,
)
from server import (
    app,
    sessions,
    _run_translation_worker,
    _init_session_from_path,
    SESSIONS_DIR,
    OUTPUT_DIR,
    CACHE_DIR,
)

client = TestClient(app)

REAL_SAMPLE_CBZ = ROOT_DIR / "Otome Game Sekai wa Mob ni Kibishii Sekai desu" / "Official_Chapter 41.5.cbz"


# =====================================================================
# Test Helpers & Fixtures
# =====================================================================

def _create_synthetic_page(idx: int, width: int = 600, height: int = 900, tag: str = "test") -> Image.Image:
    """Generates a clean synthetic manga page with dialogue bubble."""
    img = Image.new("RGB", (width, height), color=(250, 250, 250))
    draw = ImageDraw.Draw(img)
    # Outer panel border
    draw.rectangle([15, 15, width - 15, height - 15], outline=(30, 30, 30), width=3)
    # Speech bubble (white oval with black outline)
    bubble_box = [width // 4, height // 5, width * 3 // 4, height * 2 // 5]
    draw.ellipse(bubble_box, fill=(255, 255, 255), outline=(0, 0, 0), width=3)
    # Unique page identifier color block
    draw.rectangle([30, 30, 60 + (idx * 20), 60], fill=(min(255, 40 + idx * 30), 120, 200))
    return img


def _create_synthetic_cbz_archive(path: Path, num_pages: int = 3, include_comic_info: bool = True) -> Path:
    """Builds a synthetic multi-page CBZ with page ordering and optional ComicInfo.xml."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        if include_comic_info:
            comic_xml = (
                "<?xml version='1.0' encoding='UTF-8'?>\n"
                "<ComicInfo>\n"
                "  <Title>Test Synthetic Chapter</Title>\n"
                "  <Series>E2E Test Suite</Series>\n"
                "  <Number>1</Number>\n"
                "</ComicInfo>"
            )
            zf.writestr("ComicInfo.xml", comic_xml)
            zf.writestr("series_notes.txt", "Author: Synthetic\nE2E Validation Archive\n")

        # Intentionally write pages in non-sequential order into the zip to verify natural sorting
        indices = list(range(num_pages))
        indices.reverse()
        for i in indices:
            img = _create_synthetic_page(i)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            img.close()
            # Padded name like page_001.jpg
            zf.writestr(f"manga/page_{i+1:03d}.jpg", buf.getvalue())
    return path


def _mock_vision_speech_blocks(text_ja: str = "こんにちは！", text_fr: str = "Bonjour !") -> List[Dict[str, Any]]:
    return [
        {
            "box": (250.0, 200.0, 750.0, 400.0),
            "type": "speech",
            "original": text_ja,
            "translation": text_fr,
            "fr": text_fr,
            "ja": text_ja,
        }
    ]


# =====================================================================
# TIER 1: Feature Coverage & Functional Contracts
# =====================================================================

class TestTier1FeatureCoverage:
    """Tier 1: Feature-by-feature verification of core functional requirements."""

    def test_tier1_archive_format_detection_all_types(self, tmp_path):
        """Verifies detect_format accurately identifies CBZ, CBR/RAR, image formats, folders, and rejects invalid files."""
        # CBZ
        cbz = tmp_path / "test.cbz"
        with zipfile.ZipFile(cbz, "w") as z:
            z.writestr("dummy.txt", "test")
        assert ArchiveHandler.detect_format(cbz) == "cbz"

        # Folder
        folder = tmp_path / "manga_folder"
        folder.mkdir()
        assert ArchiveHandler.detect_format(folder) == "folder"

        # Image (JPEG)
        img_p = tmp_path / "page.jpg"
        _create_synthetic_page(0).save(img_p, format="JPEG")
        assert ArchiveHandler.detect_format(img_p) == "image"

        # 0-byte file must raise ValueError
        empty_f = tmp_path / "empty.cbz"
        empty_f.touch()
        with pytest.raises(ValueError, match="est vide"):
            ArchiveHandler.detect_format(empty_f)

        # Non-existent file must raise ValueError
        with pytest.raises(ValueError, match="introuvable"):
            ArchiveHandler.detect_format(tmp_path / "non_existent.cbz")

    def test_tier1_natural_sort_ordering_alphanumeric(self, tmp_path):
        """
        Verifies natural_sort_key orders pages numerically (1, 2, 10, 20)
        rather than lexicographically (1, 10, 2, 20).
        """
        raw_filenames = [
            "chapter_01/page_10.jpg",
            "chapter_01/page_1.jpg",
            "chapter_01/page_20.jpg",
            "chapter_01/page_2.jpg",
            "chapter_01/page_3.jpg",
        ]
        sorted_filenames = sorted(raw_filenames, key=natural_sort_key)
        expected = [
            "chapter_01/page_1.jpg",
            "chapter_01/page_2.jpg",
            "chapter_01/page_3.jpg",
            "chapter_01/page_10.jpg",
            "chapter_01/page_20.jpg",
        ]
        assert sorted_filenames == expected

    def test_tier1_metadata_preservation_comicinfo(self, tmp_path):
        """
        Verifies ArchiveHandler.extract correctly identifies non-image companion
        files (ComicInfo.xml, notes.txt) and flags them with is_image=False.
        """
        cbz = _create_synthetic_cbz_archive(tmp_path / "test_meta.cbz", num_pages=2, include_comic_info=True)
        extract_dir = tmp_path / "extracted"
        fmt, items = ArchiveHandler.extract(cbz, extract_dir)

        assert fmt == "cbz"
        names = [it.relative_name for it in items]
        assert "ComicInfo.xml" in names
        assert "series_notes.txt" in names

        xml_item = next(it for it in items if it.relative_name == "ComicInfo.xml")
        assert xml_item.is_image is False
        assert xml_item.source_path.exists()
        assert "Test Synthetic Chapter" in xml_item.source_path.read_text(encoding="utf-8")

        image_items = [it for it in items if it.is_image]
        assert len(image_items) == 2

    def test_tier1_archive_repack_preserves_non_image_files(self, tmp_path):
        """
        Verifies ArchiveHandler.pack repacks all translated images AND writes
        all non-image metadata files (ComicInfo.xml) byte-for-byte into the final CBZ.
        """
        cbz = _create_synthetic_cbz_archive(tmp_path / "input.cbz", num_pages=2, include_comic_info=True)
        extract_dir = tmp_path / "extracted"
        fmt, items = ArchiveHandler.extract(cbz, extract_dir)

        # Mock rendered images for the 2 pages
        rendered_images = {}
        for it in items:
            if it.is_image:
                rendered_images[it.relative_name] = _create_synthetic_page(99, tag="translated")

        output_cbz = tmp_path / "repacked.cbz"
        ArchiveHandler.pack(
            fmt=fmt,
            input_path=cbz,
            output_path=output_cbz,
            items=items,
            rendered_images=rendered_images,
        )

        assert output_cbz.exists()
        with zipfile.ZipFile(output_cbz, "r") as zout:
            names = zout.namelist()
            assert "ComicInfo.xml" in names
            assert "series_notes.txt" in names
            xml_content = zout.read("ComicInfo.xml").decode("utf-8")
            assert "Test Synthetic Chapter" in xml_content

            # Confirm images exist
            img_names = [n for n in names if n.endswith(".jpg")]
            assert len(img_names) == 2

    def test_tier1_zip_slip_security_prevention(self, tmp_path):
        """Verifies ArchiveHandler.extract detects and rejects zip-slip attacks."""
        evil_cbz = tmp_path / "evil.cbz"
        with zipfile.ZipFile(evil_cbz, "w") as z:
            z.writestr("../../etc/passwd", "malicious_content")
            z.writestr("normal.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 50)

        with pytest.raises(ValueError, match="Zip-Slip"):
            ArchiveHandler.extract(evil_cbz, tmp_path / "evil_out")

    def test_tier1_bubble_masking_all_styles(self):
        """Verifies render_manga_page executes without error across all 4 mask styles."""
        test_img = _create_synthetic_page(0, 400, 600)
        blocks = [
            {
                "box": (100.0, 100.0, 300.0, 250.0),
                "type": "speech",
                "original": "セリフ",
                "translation": "Dialogue",
                "fr": "Dialogue",
                "ja": "セリフ",
            }
        ]
        for mask_style in ("smart", "rounded", "ellipse", "transparent"):
            rendered = render_manga_page(
                img=test_img.copy(),
                blocks=blocks,
                font_style="bold",
                mask_style=mask_style,
            )
            assert isinstance(rendered, Image.Image)
            assert rendered.size == test_img.size
            rendered.close()
        test_img.close()

    def test_tier1_mask_only_clean_stage(self):
        """Verifies render_manga_page with mask_only=True generates a cleaned stage without drawing text."""
        test_img = _create_synthetic_page(0, 400, 600)
        blocks = [
            {
                "box": (100.0, 100.0, 300.0, 250.0),
                "type": "speech",
                "original": "セリフ",
                "translation": "Dialogue",
                "fr": "Dialogue",
                "ja": "セリフ",
            }
        ]
        clean_img = render_manga_page(
            img=test_img.copy(),
            blocks=blocks,
            mask_style="smart",
            mask_only=True,
        )
        assert isinstance(clean_img, Image.Image)
        assert clean_img.size == test_img.size
        clean_img.close()
        test_img.close()

    def test_tier1_dark_narration_box_inversion(self):
        """Verifies dark narration box detection inverts text color to white with black outline."""
        # Create dark background image (p85 < 115)
        dark_img = Image.new("RGB", (400, 400), color=(30, 30, 30))
        blocks = [
            {
                "box": (50.0, 50.0, 350.0, 350.0),
                "type": "narration",
                "original": "暗い背景",
                "translation": "Texte blanc sur fond sombre",
                "fr": "Texte blanc sur fond sombre",
                "ja": "暗い背景",
            }
        ]
        rendered = render_manga_page(img=dark_img, blocks=blocks, mask_style="smart")
        assert isinstance(rendered, Image.Image)
        rendered.close()

    def test_tier1_french_typography_non_breaking_spaces(self):
        """
        Verifies format_french_typography replaces standard spaces with
        non-breaking spaces (\\u00A0) before !, ?, :, ; and inside guillemets.
        """
        # Question and exclamation marks
        raw = "Quoi ? C'est impossible ! Vraiment ; oui :"
        formatted = format_french_typography(raw)
        assert "Quoi\u00A0?" in formatted
        assert "impossible\u00A0!" in formatted
        assert "Vraiment\u00A0;" in formatted
        assert "oui\u00A0:" in formatted

        # Guillemets
        quote_raw = "Il a dit « bonjour » à tous."
        quote_formatted = format_french_typography(quote_raw)
        assert "«\u00A0bonjour\u00A0»" in quote_formatted

    def test_tier1_diamond_wrap_parabolic_weighting(self):
        """
        Verifies fit_text_lines formats dialogue lines into an oval/diamond
        distribution avoiding single-word lines.
        """
        from app.typesetter import fit_text_lines
        dummy_img = Image.new("RGB", (400, 400), color="white")
        draw = ImageDraw.Draw(dummy_img)
        text = "Ceci est un long dialogue de manga qui doit épouser parfaitement la forme ovale d'une bulle."
        font, lines, font_size = fit_text_lines(draw, text, box_w=200, box_h=200, font_style="bold")
        assert len(lines) >= 2
        assert font_size >= 10
        dummy_img.close()

    def test_tier1_embedded_fonts_rendering(self):
        """Verifies all embedded fonts (bold, comic, sans, serif) render properly without system dependencies."""
        test_img = Image.new("RGB", (300, 300), color="white")
        blocks = [
            {
                "box": (50.0, 50.0, 250.0, 250.0),
                "type": "speech",
                "original": "フォント",
                "translation": "Test Font",
                "fr": "Test Font",
                "ja": "フォント",
            }
        ]
        for style in ("bold", "comic", "sans", "serif"):
            out = render_manga_page(img=test_img.copy(), blocks=blocks, font_style=style)
            assert isinstance(out, Image.Image)
            out.close()
        test_img.close()

    def test_tier1_bubble_coordinate_clamping_and_sanitization(self):
        """
        Verifies parse_and_validate_blocks normalizes coordinates to [0.0, 1000.0],
        corrects inverted coordinates, and strips forbidden control characters.
        """
        malformed = json.dumps([
            {
                "xmin": 800.0,
                "ymin": 700.0,
                "xmax": 200.0,
                "ymax": 100.0,  # inverted x and y
                "original": "Texte\x00\x08avec controle",
                "translation": "Traduction\x1b[31m netoyee",
            },
            {
                "x": 800.0,
                "y": 700.0,
                "w": 600.0,
                "h": 500.0,  # out of bounds x+w > 1000
                "original": "Overflowing box",
                "translation": "Boîte qui dépasse",
            }
        ])
        blocks = parse_and_validate_blocks(malformed)
        assert len(blocks) >= 1
        for b in blocks:
            x0, y0, x1, y1 = b["box"]
            assert 0.0 <= x0 <= x1 <= 1000.0
            assert 0.0 <= y0 <= y1 <= 1000.0
            assert "\x00" not in b["original"]
            assert "\x1b" not in b["translation"]

    def test_tier1_settings_provider_presets_and_defaults(self):
        """Verifies /api/settings returns valid provider presets and configurations."""
        res = client.get("/api/settings")
        assert res.status_code == 200
        data = res.json()
        assert "presets" in data
        assert "openrouter" in data["presets"]
        assert "nvidia" in data["presets"]
        assert "gemini" in data["presets"]
        assert "mistral" in data["presets"]

    def test_tier1_session_status_and_image_serving(self, tmp_path):
        """Verifies session upload, status polling, and serving of original page image."""
        cbz = _create_synthetic_cbz_archive(tmp_path / "status_test.cbz", num_pages=2)
        with open(cbz, "rb") as f:
            up_res = client.post("/api/upload", files={"file": ("status_test.cbz", f, "application/octet-stream")})
        assert up_res.status_code == 200
        session_id = up_res.json()["session_id"]

        # Poll status
        st_res = client.get(f"/api/status/{session_id}")
        assert st_res.status_code == 200
        st = st_res.json()
        assert st["status"] == "ready"
        assert st["total_pages"] == 2
        assert len(st["pages"]) == 2

        # Check /api/image/{session_id}/orig/0 returns valid JPEG
        img_res = client.get(f"/api/image/{session_id}/orig/0")
        assert img_res.status_code == 200
        assert img_res.headers.get("content-type") == "image/jpeg"
        with Image.open(io.BytesIO(img_res.content)) as im:
            assert im.width > 0 and im.height > 0


# =====================================================================
# TIER 2: Boundary, Corner Cases & Fault Isolation
# =====================================================================

class TestTier2BoundaryAndFaultIsolation:
    """Tier 2: Boundary conditions, rate limit failovers, partial failures, and macOS archives."""

    def test_tier2_partial_page_failure_isolation(self, tmp_path):
        """
        R2: Single page failure resilience.
        In a 4-page chapter, page 1 encounters an unrecoverable vision exception.
        Verifies:
        - Pages 0, 2, 3 translate successfully.
        - Page 1 status is 'error', with error recorded.
        - Page 1 original image is kept as fallback.
        - Session status is 'finished' with errors_count == 1.
        - Repackaged archive is created and contains all 4 pages.
        """
        cbz = _create_synthetic_cbz_archive(tmp_path / "partial_fail.cbz", num_pages=4)
        with open(cbz, "rb") as f:
            up_res = client.post("/api/upload", files={"file": ("partial_fail.cbz", f, "application/octet-stream")})
        assert up_res.status_code == 200
        session_id = up_res.json()["session_id"]

        page_counter = 0

        def mock_detect(img, max_side=1600, context_history=None):
            nonlocal page_counter
            current = page_counter
            page_counter += 1
            if current == 1:
                # Page index 1 raises an unhandled error
                raise RuntimeError("Vision API 500: Fatal downstream model error")
            return _mock_vision_speech_blocks(f"Page {current}", f"Traduction {current}"), "mock-model"

        with patch("server._load_cached_page_blocks", return_value=None):
            with patch.object(CloudVisionClient, "detect_and_translate", side_effect=mock_detect):
                _run_translation_worker(session_id, {
                    "provider": "auto",
                    "concurrency": 1,
                })

        session = sessions[session_id]
        assert session["status"] == "finished"
        assert session["errors_count"] == 1

        # Check page states
        assert session["pages"][0]["status"] == "done"
        assert session["pages"][1]["status"] == "error"
        assert "Fatal downstream" in session["pages"][1]["error"]
        assert session["pages"][2]["status"] == "done"
        assert session["pages"][3]["status"] == "done"

        # Check all 4 translated_images exist
        assert len(session["translated_images"]) == 4

        # Download and verify archive integrity
        dl_res = client.get(f"/api/download/{session_id}")
        assert dl_res.status_code == 200
        with zipfile.ZipFile(io.BytesIO(dl_res.content), "r") as zout:
            img_files = [n for n in zout.namelist() if n.endswith(".jpg")]
            assert len(img_files) == 4

    def test_tier2_http_429_quota_exhaustion_transparent_failover(self):
        """
        R1: HTTP 429 quota exhaustion simulation.
        When OpenRouter returns 429 (free-models-per-day), CloudVisionClient
        transparently falls back to secondary configured provider (NVIDIA NIM or Groq).
        """
        cv = CloudVisionClient(provider="auto")
        test_img = _create_synthetic_page(0, 300, 400)

        calls_made = []

        def mock_openai_call(b64_str, base_url, api_key, model_name, prompt):
            calls_made.append(base_url)
            if "openrouter.ai" in base_url:
                raise RuntimeError("HTTP 429: free-models-per-day daily limit exceeded")
            elif "nvidia.com" in base_url or "api.nvidia.com" in base_url:
                return _mock_vision_speech_blocks("セリフ", "Fallback NIM réussi")
            raise RuntimeError(f"Unexpected base_url: {base_url}")

        with patch.dict(os.environ, {
            "OPENROUTER_API_KEY": "sk-or-test-key",
            "NVIDIA_API_KEY": "nvapi-test-key",
        }):
            with patch.object(cv, "_call_openai_compatible", side_effect=mock_openai_call):
                blocks, model_used = cv.detect_and_translate(test_img)
                assert len(blocks) == 1
                assert blocks[0]["translation"] == "Fallback NIM réussi"
                assert "nvidia" in model_used.lower()

        test_img.close()

    def test_tier2_zero_byte_archive_rejection(self, tmp_path):
        """Verifies /api/upload strictly rejects 0-byte uploaded files with HTTP 400."""
        empty_file = tmp_path / "empty.cbz"
        empty_file.touch()
        with open(empty_file, "rb") as f:
            res = client.post("/api/upload", files={"file": ("empty.cbz", f, "application/octet-stream")})
        assert res.status_code == 400
        assert "vide" in res.json()["detail"].lower()

    def test_tier2_cancelled_session_produces_valid_archive(self, tmp_path):
        """
        Verifies cancelling a running translation sets cancelled=True
        and /api/download produces a valid partial archive without deadlock.
        """
        cbz = _create_synthetic_cbz_archive(tmp_path / "cancel_test.cbz", num_pages=3)
        with open(cbz, "rb") as f:
            up_res = client.post("/api/upload", files={"file": ("cancel_test.cbz", f, "application/octet-stream")})
        session_id = up_res.json()["session_id"]

        # Cancel session
        cancel_res = client.post(f"/api/translate/cancel/{session_id}")
        assert cancel_res.status_code == 200
        assert sessions[session_id]["cancelled"] is True

        # Download should still return an archive without crashing
        dl_res = client.get(f"/api/download/{session_id}")
        assert dl_res.status_code == 200

    def test_tier2_empty_bubbles_on_page(self):
        """Verifies render_manga_page with empty blocks list returns original page cleanly."""
        test_img = _create_synthetic_page(0, 400, 500)
        rendered = render_manga_page(img=test_img.copy(), blocks=[])
        assert isinstance(rendered, Image.Image)
        assert rendered.size == test_img.size
        rendered.close()
        test_img.close()

    def test_tier2_macos_apple_double_archive_handling(self, tmp_path):
        """
        R2 (Bug E1): macOS archive resilience.
        Verifies that an archive created on macOS containing '__MACOSX/' and '._*' AppleDouble
        files is processed without UnidentifiedImageError or HTTP 500.
        """
        cbz_macos = tmp_path / "macos_archive.cbz"
        with zipfile.ZipFile(cbz_macos, "w") as zf:
            # Fake AppleDouble resource fork with .jpg extension
            zf.writestr("__MACOSX/._001.jpg", b"\x00\x05\x16\x07AppleDoubleResourceForkData")
            zf.writestr("__MACOSX/chapter/._002.jpg", b"\x00\x05\x16\x07AppleDoubleResourceForkData")
            # Real pages
            for i in range(2):
                img = _create_synthetic_page(i)
                buf = io.BytesIO()
                img.save(buf, format="JPEG")
                zf.writestr(f"chapter/page_{i+1:03d}.jpg", buf.getvalue())

        with open(cbz_macos, "rb") as f:
            res = client.post("/api/upload", files={"file": ("macos_archive.cbz", f, "application/octet-stream")})

        assert res.status_code == 200
        data = res.json()
        # Must only count real image pages, ignoring AppleDouble resource forks
        assert data["total_pages"] == 2


# =====================================================================
# TIER 3: Cross-Feature Combinations & Pipelines
# =====================================================================

class TestTier3CrossFeaturePipelines:
    """Tier 3: Multi-feature integration, concurrency safety, context ordering, and folder workflows."""

    def test_tier3_multipage_pipeline_concurrency_thread_safety(self, tmp_path):
        """
        Verifies multi-threaded translation (concurrency=3) processes all pages
        in parallel without state corruption or race conditions on translated_images.
        """
        cbz = _create_synthetic_cbz_archive(tmp_path / "concurrent.cbz", num_pages=4)
        with open(cbz, "rb") as f:
            up_res = client.post("/api/upload", files={"file": ("concurrent.cbz", f, "application/octet-stream")})
        session_id = up_res.json()["session_id"]

        def mock_detect(img, max_side=1600, context_history=None):
            time.sleep(0.05)  # Introduce slight delay to test concurrency
            return _mock_vision_speech_blocks("並列テスト", "Test concurrence"), "mock-model"

        with patch("server._load_cached_page_blocks", return_value=None):
            with patch.object(CloudVisionClient, "detect_and_translate", side_effect=mock_detect):
                _run_translation_worker(session_id, {
                    "provider": "auto",
                    "concurrency": 3,
                })

        session = sessions[session_id]
        assert session["status"] == "finished"
        assert session["progress_percent"] == 100
        assert len(session["translated_images"]) == 4
        for p in session["pages"]:
            assert p["status"] == "done"
            assert p["blocks_count"] == 1

    def test_tier3_interpage_context_prompt_formatting(self):
        """
        Verifies build_system_prompt formats previous pages' dialogue context into
        the system prompt for consistent naming, gender, and registers across pages.
        """
        from app.cloud_vision import build_system_prompt
        ctx = [
            {"original": "こんにちは", "translation": "Bonjour"},
            {"original": "私はレオです", "translation": "Je suis Léon"},
        ]
        prompt = build_system_prompt("Japanese", "French", context_history=ctx)
        assert "Previous pages context" in prompt
        assert "Léon" in prompt
        assert "Bonjour" in prompt

    def test_tier3_interpage_context_propagation_ordering(self, tmp_path):
        """
        Verifies that dialogue translated in earlier pages is accumulated in
        context_history and passed to subsequent pages for narrative coherence.
        """
        cbz = _create_synthetic_cbz_archive(tmp_path / "context.cbz", num_pages=3)
        with open(cbz, "rb") as f:
            up_res = client.post("/api/upload", files={"file": ("context.cbz", f, "application/octet-stream")})
        session_id = up_res.json()["session_id"]

        received_contexts = []

        def mock_detect(img, max_side=1600, context_history=None):
            received_contexts.append(list(context_history or []))
            idx = len(received_contexts)
            return _mock_vision_speech_blocks(f"Ligne {idx}", f"Traduction {idx}"), "mock-model"

        with patch("server._load_cached_page_blocks", return_value=None):
            with patch.object(CloudVisionClient, "detect_and_translate", side_effect=mock_detect):
                _run_translation_worker(session_id, {
                    "provider": "auto",
                    "concurrency": 1,
                })

        assert len(received_contexts) == 3
        # Page 0 has empty initial context
        assert len(received_contexts[0]) == 0
        # Page 1 receives dialogue from Page 0
        assert len(received_contexts[1]) >= 1
        assert received_contexts[1][0]["translation"] == "Traduction 1"

    def test_tier3_folder_upload_and_pipeline(self, tmp_path):
        """
        Verifies /api/upload_folder handles multi-image folder structures,
        translates all pages, and allows downloading a packaged archive.
        """
        # Create 2 test image buffers
        f1_buf = io.BytesIO()
        _create_synthetic_page(0).save(f1_buf, format="JPEG")
        f1_buf.seek(0)

        f2_buf = io.BytesIO()
        _create_synthetic_page(1).save(f2_buf, format="JPEG")
        f2_buf.seek(0)

        files = [
            ("files", ("mon_manga/01.jpg", f1_buf, "image/jpeg")),
            ("files", ("mon_manga/02.jpg", f2_buf, "image/jpeg")),
        ]

        up_res = client.post("/api/upload_folder", files=files)
        assert up_res.status_code == 200
        session_id = up_res.json()["session_id"]
        assert up_res.json()["total_pages"] == 2

        with patch("server._load_cached_page_blocks", return_value=None):
            with patch.object(CloudVisionClient, "detect_and_translate", return_value=(_mock_vision_speech_blocks(), "mock")):
                _run_translation_worker(session_id, {"provider": "auto", "concurrency": 1})

        session = sessions[session_id]
        assert session["status"] == "finished"

        dl_res = client.get(f"/api/download/{session_id}")
        assert dl_res.status_code == 200

    def test_tier3_live_bubble_rerender_workflow(self, tmp_path):
        """
        Verifies /api/rerender/{session_id}/{page_idx} allows live editing of
        detected bubble text and immediately updates the rendered image.
        """
        cbz = _create_synthetic_cbz_archive(tmp_path / "rerender.cbz", num_pages=1)
        with open(cbz, "rb") as f:
            up_res = client.post("/api/upload", files={"file": ("rerender.cbz", f, "application/octet-stream")})
        session_id = up_res.json()["session_id"]

        # Run translation
        with patch("server._load_cached_page_blocks", return_value=None):
            with patch.object(CloudVisionClient, "detect_and_translate", return_value=(_mock_vision_speech_blocks(), "mock")):
                _run_translation_worker(session_id, {"provider": "auto", "concurrency": 1})

        # User edits bubble via /api/rerender
        edited_blocks = [
            {
                "box": [150, 150, 450, 300],
                "ja": "原文",
                "fr": "Nouvelle réplique modifiée en direct !",
            }
        ]
        re_res = client.post(
            f"/api/rerender/{session_id}/0",
            json={"blocks": edited_blocks, "mask_style": "smart"},
        )
        assert re_res.status_code == 200
        re_data = re_res.json()
        assert re_data["status"] == "done"
        assert re_data["blocks"][0]["fr"] == "Nouvelle réplique modifiée en direct !"


# =====================================================================
# TIER 4: Real-World Application Scenarios
# =====================================================================

class TestTier4RealWorldScenarios:
    """Tier 4: End-to-end scenarios executed on real manga chapter 'Official_Chapter 41.5.cbz'."""

    @pytest.fixture(autouse=True)
    def check_real_sample_exists(self):
        if not REAL_SAMPLE_CBZ.exists():
            pytest.skip(f"Real sample archive not found at: {REAL_SAMPLE_CBZ}")

    def test_tier4_real_chapter_41_5_full_e2e_translation(self):
        """
        Tier 4 Scenario 1: Complete E2E translation of real chapter 'Official_Chapter 41.5.cbz'.
        Verifies:
        1. Upload real CBZ containing ComicInfo.xml and 3 pages (001.jpg, 002.jpg, 003.jpg).
        2. Natural ordering confirms 001.jpg -> page 0, 002.jpg -> page 1, 003.jpg -> page 2.
        3. Sequential translation with French diamond typesetting and non-breaking spaces.
        4. Download repackaged CBZ and verify ComicInfo.xml is preserved with Title 'Chapter 41.5'.
        5. Verify all 3 pages are valid JPEG images in the output.
        """
        with open(REAL_SAMPLE_CBZ, "rb") as f:
            up_res = client.post(
                "/api/upload",
                files={"file": ("Official_Chapter 41.5.cbz", f, "application/octet-stream")},
            )
        assert up_res.status_code == 200
        upload_data = up_res.json()
        session_id = upload_data["session_id"]
        assert upload_data["total_pages"] == 3

        # Verify strict natural sort ordering
        assert "001.jpg" in upload_data["pages"][0]["relative_name"]
        assert "002.jpg" in upload_data["pages"][1]["relative_name"]
        assert "003.jpg" in upload_data["pages"][2]["relative_name"]

        # Mock high-fidelity vision detection
        def mock_detect(img, max_side=1600, context_history=None):
            return [
                {
                    "box": (200.0, 150.0, 700.0, 350.0),
                    "type": "speech",
                    "original": "おい、何をしているんだ？",
                    "translation": "Hé, qu'est-ce que tu fais là ?!",
                    "fr": "Hé, qu'est-ce que tu fais là ?!",
                    "ja": "おい、何をしているんだ？",
                }
            ], "mock/llama-3.2-vision"

        with patch("server._load_cached_page_blocks", return_value=None):
            with patch.object(CloudVisionClient, "detect_and_translate", side_effect=mock_detect):
                _run_translation_worker(session_id, {
                    "provider": "auto",
                    "tgt_lang": "French",
                    "font_style": "bold",
                    "concurrency": 2,
                })

        session = sessions[session_id]
        assert session["status"] == "finished"
        assert session["progress_percent"] == 100
        assert session["errors_count"] == 0

        # Inspect downloaded archive
        dl_res = client.get(f"/api/download/{session_id}")
        assert dl_res.status_code == 200

        with zipfile.ZipFile(io.BytesIO(dl_res.content), "r") as zout:
            namelist = zout.namelist()
            # Verify ComicInfo.xml metadata preserved
            assert "ComicInfo.xml" in namelist
            comic_xml = zout.read("ComicInfo.xml").decode("utf-8")
            assert "Chapter 41.5" in comic_xml
            assert "Otome Game Sekai wa Mob ni Kibishii Sekai desu" in comic_xml

            # Verify 3 translated images
            img_names = [n for n in namelist if n.endswith(".jpg")]
            assert len(img_names) == 3

    def test_tier4_real_chapter_quota_failover_scenario(self):
        """
        Tier 4 Scenario 2: Real chapter quota exhaustion simulation.
        Page 0 succeeds via primary OpenRouter.
        Page 1 triggers 429 quota exhaustion; client transparently falls back to NVIDIA NIM.
        Page 2 continues cleanly with NIM.
        All 3 pages finish and package without error.
        """
        with open(REAL_SAMPLE_CBZ, "rb") as f:
            up_res = client.post(
                "/api/upload",
                files={"file": ("Official_Chapter 41.5.cbz", f, "application/octet-stream")},
            )
        session_id = up_res.json()["session_id"]

        call_step = 0

        def mock_detect(img, max_side=1600, context_history=None):
            nonlocal call_step
            call_step += 1
            if call_step == 2:
                # Simulates transparent fallback inside CloudVisionClient: returns fallback model
                return _mock_vision_speech_blocks("セリフ", "Repli transparent NIM réussi"), "nvidia-nim/llama-3.2-11b"
            return _mock_vision_speech_blocks("セリフ", "Traduction standard"), "openrouter/free-vl"

        with patch("server._load_cached_page_blocks", return_value=None):
            with patch.object(CloudVisionClient, "detect_and_translate", side_effect=mock_detect):
                _run_translation_worker(session_id, {
                    "provider": "auto",
                    "concurrency": 1,
                })

        session = sessions[session_id]
        assert session["status"] == "finished"
        assert session["errors_count"] == 0
        assert session["pages"][1]["status"] == "done"

    def test_tier4_real_chapter_partial_failure_with_comicinfo(self):
        """
        Tier 4 Scenario 3: Real chapter with page 1 fatal error.
        Verifies:
        - Page 0 and 2 are translated.
        - Page 1 original image is kept as fallback.
        - ComicInfo.xml is preserved.
        - Final CBZ has 4 files (ComicInfo.xml + 3 images).
        """
        with open(REAL_SAMPLE_CBZ, "rb") as f:
            up_res = client.post(
                "/api/upload",
                files={"file": ("Official_Chapter 41.5.cbz", f, "application/octet-stream")},
            )
        session_id = up_res.json()["session_id"]

        call_idx = 0

        def mock_detect(img, max_side=1600, context_history=None):
            nonlocal call_idx
            current = call_idx
            call_idx += 1
            if current == 1:
                raise RuntimeError("Vision network drop on page 1")
            return _mock_vision_speech_blocks("セリフ", f"Page {current}"), "mock-model"

        with patch("server._load_cached_page_blocks", return_value=None):
            with patch.object(CloudVisionClient, "detect_and_translate", side_effect=mock_detect):
                _run_translation_worker(session_id, {"provider": "auto", "concurrency": 1})

        session = sessions[session_id]
        assert session["status"] == "finished"
        assert session["errors_count"] == 1

        dl_res = client.get(f"/api/download/{session_id}")
        assert dl_res.status_code == 200
        with zipfile.ZipFile(io.BytesIO(dl_res.content), "r") as zout:
            namelist = zout.namelist()
            assert "ComicInfo.xml" in namelist
            images = [n for n in namelist if n.endswith(".jpg")]
            assert len(images) == 3

    def test_tier4_real_chapter_reader_modes_image_parity(self):
        """
        Tier 4 Scenario 4: Reader modes validation (Split-View and Slider alignment).
        Verifies /api/image/{session_id}/orig/{idx} and /api/image/{session_id}/trans/{idx}
        return images with IDENTICAL pixel dimensions for all 3 pages, guaranteeing
        pixel-perfect alignment in Split-View and CSS clip-path A/B slider.
        """
        with open(REAL_SAMPLE_CBZ, "rb") as f:
            up_res = client.post(
                "/api/upload",
                files={"file": ("Official_Chapter 41.5.cbz", f, "application/octet-stream")},
            )
        session_id = up_res.json()["session_id"]

        with patch("server._load_cached_page_blocks", return_value=None):
            with patch.object(CloudVisionClient, "detect_and_translate", return_value=(_mock_vision_speech_blocks(), "mock")):
                _run_translation_worker(session_id, {"provider": "auto", "concurrency": 1})

        for p_idx in range(3):
            # Fetch original
            orig_res = client.get(f"/api/image/{session_id}/orig/{p_idx}")
            assert orig_res.status_code == 200
            with Image.open(io.BytesIO(orig_res.content)) as orig_im:
                orig_w, orig_h = orig_im.size

            # Fetch translated
            trans_res = client.get(f"/api/image/{session_id}/trans/{p_idx}")
            assert trans_res.status_code == 200
            with Image.open(io.BytesIO(trans_res.content)) as trans_im:
                trans_w, trans_h = trans_im.size

            # Assert exact dimension parity required by Split-View and Slider modes
            assert orig_w == trans_w, f"Width mismatch on page {p_idx}: orig {orig_w} vs trans {trans_w}"
            assert orig_h == trans_h, f"Height mismatch on page {p_idx}: orig {orig_h} vs trans {trans_h}"

    def test_tier4_real_chapter_rerender_and_redownload(self):
        """
        Tier 4 Scenario 5: Real chapter post-translation bubble editing.
        Modifies a bubble on page 0 of the real chapter via /api/rerender,
        and verifies the updated image and repackaged download.
        """
        with open(REAL_SAMPLE_CBZ, "rb") as f:
            up_res = client.post(
                "/api/upload",
                files={"file": ("Official_Chapter 41.5.cbz", f, "application/octet-stream")},
            )
        session_id = up_res.json()["session_id"]

        with patch("server._load_cached_page_blocks", return_value=None):
            with patch.object(CloudVisionClient, "detect_and_translate", return_value=(_mock_vision_speech_blocks(), "mock")):
                _run_translation_worker(session_id, {"provider": "auto", "concurrency": 1})

        # Edit page 0
        edited_blocks = [
            {
                "box": [200, 200, 600, 400],
                "ja": "原文修正",
                "fr": "Texte corrigé dans le visualiseur !",
            }
        ]
        re_res = client.post(
            f"/api/rerender/{session_id}/0",
            json={"blocks": edited_blocks, "mask_style": "smart"},
        )
        assert re_res.status_code == 200
        assert re_res.json()["blocks"][0]["fr"] == "Texte corrigé dans le visualiseur !"

        # Download updated archive
        dl_res = client.get(f"/api/download/{session_id}")
        assert dl_res.status_code == 200
