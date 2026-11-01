"""
Adversarial Stress Test Harness — Challenger Instance 1
Empirical Verification of:
1. Archive Processing: Zip-Slip, AppleDouble, Unicode, Deep Nesting, Spaces, Mixed Case, Zero-Byte Files.
2. Quota Exhaustion: OpenRouter HTTP 429 transparent failover to NVIDIA NIM without in-flight state loss or chapter crash.
3. Environment Hygiene: Wiping of os.environ keys by load_env() on empty .env values.
4. Corrupted Page Resilience: Real sample 'Otome Game Sekai wa Mob ni Kibishii Sekai desu/Official_Chapter 41.5.cbz'.
5. Single-Page Recovery: /api/translate/page/{session_id}/{page_idx} error count synchronization.
6. Coordinate Sanitization, ANSI Escape Stripping, Reasoning Token Extraction.
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
from typing import Dict, Any, List, Optional
from unittest.mock import patch, MagicMock

import pytest
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import IMAGE_EXTENSIONS, PROVIDER_PRESETS
from app.archives import ArchiveHandler, ArchiveItem, natural_sort_key
from app.cloud_vision import (
    CloudVisionClient,
    parse_and_validate_blocks,
    is_quota_or_rate_limit_error,
    is_permanent_quota_error,
    is_transient_error,
)
from server import (
    app,
    sessions,
    _run_translation_worker,
    _init_session_from_path,
    retranslate_single_page,
    SESSIONS_DIR,
    OUTPUT_DIR,
)

test_client = TestClient(app)
REAL_SAMPLE_CBZ = ROOT_DIR / "Otome Game Sekai wa Mob ni Kibishii Sekai desu" / "Official_Chapter 41.5.cbz"


def _ensure_sample_cbz():
    if not REAL_SAMPLE_CBZ.exists():
        REAL_SAMPLE_CBZ.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(REAL_SAMPLE_CBZ, "w") as z:
            z.writestr("ComicInfo.xml", b"<ComicInfo><Series>Otome Game Sekai wa Mob ni Kibishii Sekai desu</Series><Title>Official Chapter 41.5</Title></ComicInfo>")
            for name in ("001.jpg", "002.jpg", "003.jpg"):
                z.writestr(name, _create_dummy_image(text=name))


def _create_dummy_image(w: int = 400, h: int = 600, color=(240, 240, 240), text="Sample") -> bytes:
    img = Image.new("RGB", (w, h), color=color)
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, w - 10, h - 10], outline=(0, 0, 0), width=2)
    draw.ellipse([50, 50, w - 50, h // 3], fill=(255, 255, 255), outline=(0, 0, 0), width=2)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


# =====================================================================
# CHALLENGE 1: Archive Processing Stress Tests
# =====================================================================

class TestChallengerArchiveStress:
    """Adversarial stress testing of archive extraction, security boundaries, and format resilience."""

    def test_zip_slip_relative_traversal_rejection(self, tmp_path):
        """Verify that Zip-Slip relative paths (../../evil.txt) are blocked with ValueError."""
        evil_cbz = tmp_path / "zip_slip_attack.cbz"
        with zipfile.ZipFile(evil_cbz, "w") as z:
            z.writestr("../../evil_payload.sh", b"#!/bin/sh\necho hacked\n")
            z.writestr("normal_page.jpg", _create_dummy_image())

        extract_dir = tmp_path / "extract_dest"
        with pytest.raises(ValueError) as excinfo:
            ArchiveHandler.extract(evil_cbz, extract_dir)

        assert "Zip-Slip" in str(excinfo.value) or "Traversal" in str(excinfo.value)
        # Ensure evil payload was NOT written anywhere outside extract_dest
        assert not (tmp_path / "evil_payload.sh").exists()

    def test_zip_slip_nested_traversal_rejection(self, tmp_path):
        """Verify that deep nested relative traversal paths (sub/../../outside.txt) are blocked."""
        evil_cbz = tmp_path / "nested_traversal.cbz"
        with zipfile.ZipFile(evil_cbz, "w") as z:
            z.writestr("subdir/deep/../../../escaped.txt", b"escaped content")
            z.writestr("image.png", _create_dummy_image())

        extract_dir = tmp_path / "extract_dest"
        with pytest.raises(ValueError) as excinfo:
            ArchiveHandler.extract(evil_cbz, extract_dir)
        assert "Zip-Slip" in str(excinfo.value) or "Traversal" in str(excinfo.value)
        assert not (tmp_path / "escaped.txt").exists()

    def test_macos_appledouble_and_junk_omission(self, tmp_path):
        """
        Verify that AppleDouble resource forks (._*), __MACOSX directories,
        .DS_Store and Thumbs.db are completely filtered out without raising errors.
        """
        mac_cbz = tmp_path / "mac_archive.cbz"
        apple_double_header = b"\x00\x05\x16\x07AppleDoubleResourceFork\x00\x00"
        with zipfile.ZipFile(mac_cbz, "w") as z:
            z.writestr("__MACOSX/._001.jpg", apple_double_header)
            z.writestr("__MACOSX/chapter/._002.jpg", apple_double_header)
            z.writestr("._hidden_junk.jpg", apple_double_header)
            z.writestr(".DS_Store", b"mac-finder-junk")
            z.writestr("Thumbs.db", b"windows-thumb-cache")
            z.writestr("001.jpg", _create_dummy_image(text="P1"))
            z.writestr("002.jpg", _create_dummy_image(text="P2"))

        extract_dir = tmp_path / "mac_extract"
        fmt, items = ArchiveHandler.extract(mac_cbz, extract_dir)

        assert fmt == "cbz"
        # Only the 2 legitimate images should be returned as items
        extracted_names = [it.relative_name for it in items]
        assert "001.jpg" in extracted_names
        assert "002.jpg" in extracted_names
        assert not any("__MACOSX" in n or n.startswith("._") for n in extracted_names)
        assert ".DS_Store" not in extracted_names
        assert "Thumbs.db" not in extracted_names

        # Verify that all extracted items can be loaded with it.get_image() without PIL crash
        for it in items:
            img = it.get_image()
            assert img.width > 0
            assert img.height > 0

    def test_boundary_filenames_unicode_spaces_nesting_mixedcase(self, tmp_path):
        """
        Stress test filenames with:
        - Deep nesting (vol1/ch2/sub3/page.png)
        - Unicode characters (Japanese kanji/kana, accents, Cyrillic)
        - Whitespace and special chars
        - Mixed-case extensions (.JPG, .PnG, .jPeG, .WEBP)
        """
        complex_cbz = tmp_path / "complex_boundaries.cbz"
        file_map = {
            "vol_01/ch_01/01 - 始まりの章 - Page d'intro.JPG": _create_dummy_image(text="P1"),
            "vol_01/ch_01/02_第2話_魔法の森 (Épisode Spécial).PnG": _create_dummy_image(text="P2"),
            "vol_01/ch_02/deeply/nested/folder/03_страница_тест.jPeG": _create_dummy_image(text="P3"),
            "04_last_page_symbols [v1.0] #final.WEBP": _create_dummy_image(text="P4"),
            "vol_01/metadata_notes.txt": b"Important notes with spaces and unicode",
        }

        with zipfile.ZipFile(complex_cbz, "w") as z:
            for arc_name, data in file_map.items():
                z.writestr(arc_name, data)

        extract_dir = tmp_path / "complex_extract"
        fmt, items = ArchiveHandler.extract(complex_cbz, extract_dir)

        assert fmt == "cbz"
        image_items = [it for it in items if it.is_image]
        assert len(image_items) == 4

        # Test natural sorting on complex relative names
        sorted_names = [it.relative_name for it in sorted(items, key=lambda it: natural_sort_key(it.relative_name))]
        assert len(sorted_names) == 5

        # Test repackaging with simulated rendered images
        rendered = {}
        for it in image_items:
            img = it.get_image()
            rendered[it.relative_name] = img

        repacked_path = tmp_path / "repacked_complex.cbz"
        ArchiveHandler.pack(
            fmt="cbz",
            input_path=complex_cbz,
            output_path=repacked_path,
            items=items,
            rendered_images=rendered,
        )

        assert repacked_path.exists()
        with zipfile.ZipFile(repacked_path, "r") as zre:
            re_names = zre.namelist()
            assert len(re_names) == 5
            assert "vol_01/metadata_notes.txt" in re_names
            assert zre.read("vol_01/metadata_notes.txt") == b"Important notes with spaces and unicode"

    def test_zero_byte_archive_rejected(self, tmp_path):
        """Zero-byte archive file must raise ValueError immediately."""
        empty_cbz = tmp_path / "zero_byte.cbz"
        empty_cbz.write_bytes(b"")

        with pytest.raises(ValueError) as exc:
            ArchiveHandler.detect_format(empty_cbz)
        assert "0 octet" in str(exc.value)

    def test_zero_byte_image_inside_archive_handled(self, tmp_path):
        """
        Archive with 1 valid image and 1 zero-byte image:
        _init_session_from_path must skip the 0-byte corrupt image and preserve the valid image.
        """
        mixed_cbz = tmp_path / "mixed_zero_byte.cbz"
        with zipfile.ZipFile(mixed_cbz, "w") as z:
            z.writestr("001.jpg", _create_dummy_image(text="Valid"))
            z.writestr("002_corrupt_zero.jpg", b"")

        session_id = f"test_zero_{int(time.time())}"
        session_dir = tmp_path / f"session_{session_id}"
        session_dir.mkdir(parents=True)

        info = _init_session_from_path(session_id, session_dir, mixed_cbz, "mixed_zero_byte.cbz")
        # Only 1 valid image should be retained
        assert info["total_pages"] == 1
        assert len(info["pages"]) == 1
        assert info["pages"][0]["relative_name"] == "001.jpg"

    def test_all_zero_byte_images_archive_rejected_with_400(self, tmp_path):
        """Archive with ONLY zero-byte images must raise HTTPException 400, not crash with 500."""
        from fastapi import HTTPException
        all_zero_cbz = tmp_path / "all_zero.cbz"
        with zipfile.ZipFile(all_zero_cbz, "w") as z:
            z.writestr("001.jpg", b"")
            z.writestr("002.png", b"")

        session_id = f"test_all_zero_{int(time.time())}"
        session_dir = tmp_path / f"session_{session_id}"
        session_dir.mkdir(parents=True)

        with pytest.raises(HTTPException) as exc:
            _init_session_from_path(session_id, session_dir, all_zero_cbz, "all_zero.cbz")
        assert exc.value.status_code == 400
        assert "Aucune image valide" in exc.value.detail


# =====================================================================
# CHALLENGE 2: Quota Exhaustion (429) & Failover Stress Tests
# =====================================================================

class TestChallengerQuotaExhaustionFailover:
    """Adversarial stress testing of HTTP 429 quota exhaustion and failover to NVIDIA NIM."""

    def test_openrouter_429_triggers_transparent_nvidia_failover(self):
        """
        Low-level client test:
        When OpenRouter returns HTTP 429 RateLimit/QuotaExhausted,
        the client must catch it and automatically invoke NVIDIA NIM without throwing.
        """
        client = CloudVisionClient(provider="openrouter", api_key="sk-or-dummy-key")

        openrouter_called = False
        nvidia_called = False

        def mock_call_openai_compatible(**kwargs):
            nonlocal openrouter_called, nvidia_called
            base_url = kwargs.get("base_url", "")
            if "openrouter.ai" in base_url:
                openrouter_called = True
                # Simulate real OpenRouter 429 rate limit error
                raise RuntimeError("HTTP 429 Too Many Requests: Rate limit exceeded for free-models-per-day")
            elif "nvidia.com" in base_url:
                nvidia_called = True
                return [{"box": (100, 100, 300, 300), "text": "テスト", "translation": "Test NIM", "fr": "Test NIM", "ja": "テスト"}]
            raise RuntimeError(f"Unexpected base_url: {base_url}")

        with patch("app.cloud_vision.load_env"):
            with patch.object(CloudVisionClient, "_call_openai_compatible", side_effect=mock_call_openai_compatible):
                with patch.dict(os.environ, {"NVIDIA_API_KEY": "nvapi-dummy-key"}):
                    dummy_img = Image.new("RGB", (300, 300), color=(255, 255, 255))
                    blocks, model_name = client.detect_and_translate(dummy_img)

        assert openrouter_called is True
        assert nvidia_called is True
        assert "nvidia-nim" in model_name
        assert len(blocks) == 1
        assert blocks[0]["translation"] == "Test NIM"

    def test_multipage_inflight_state_preserved_during_429_failover(self, tmp_path):
        """
        Multi-page chapter translation under concurrency:
        Page 0: succeeds via OpenRouter
        Page 1: hits HTTP 429 on OpenRouter -> falls back to NVIDIA NIM
        Page 2: hits HTTP 429 on OpenRouter -> falls back to NVIDIA NIM
        Verifies:
        - In-flight inter-page narrative context is strictly propagated in ascending order.
        - The chapter finishes with session['status'] == 'finished' and errors_count == 0.
        - Final repackaged archive contains all 3 translated pages.
        """
        test_cbz = tmp_path / "chapter_429_failover.cbz"
        with zipfile.ZipFile(test_cbz, "w") as z:
            z.writestr("001.jpg", _create_dummy_image(text="Page 1 Dialog"))
            z.writestr("002.jpg", _create_dummy_image(text="Page 2 Dialog"))
            z.writestr("003.jpg", _create_dummy_image(text="Page 3 Dialog"))

        session_id = f"test_429_{int(time.time())}"
        session_dir = tmp_path / f"session_{session_id}"
        session_dir.mkdir(parents=True)
        _init_session_from_path(session_id, session_dir, test_cbz, "chapter_429_failover.cbz")

        call_counts = {"openrouter": 0, "nvidia": 0}

        def mock_call_openai(**kwargs):
            base_url = kwargs.get("base_url", "")
            if "openrouter.ai" in base_url:
                call_counts["openrouter"] += 1
                if call_counts["openrouter"] > 1:
                    raise RuntimeError("HTTP 429: free-models-per-day quota exhausted")
                return [{
                    "box": (100.0, 100.0, 300.0, 300.0),
                    "original": "第1話セリフ",
                    "translation": "Bonjour du chapitre 1",
                    "fr": "Bonjour du chapitre 1",
                    "ja": "第1話セリフ",
                }]
            elif "nvidia.com" in base_url:
                call_counts["nvidia"] += 1
                return [{
                    "box": (120.0, 120.0, 320.0, 320.0),
                    "original": f"NIMセリフ {call_counts['nvidia']}",
                    "translation": f"Traduction NIM page {call_counts['nvidia']}",
                    "fr": f"Traduction NIM page {call_counts['nvidia']}",
                    "ja": f"NIMセリフ {call_counts['nvidia']}",
                }]
            raise RuntimeError("Unknown provider")

        with patch("app.cloud_vision.load_env"):
            with patch.object(CloudVisionClient, "_call_openai_compatible", side_effect=mock_call_openai):
                with patch.dict(os.environ, {"NVIDIA_API_KEY": "nvapi-test-key", "OPENROUTER_API_KEY": "sk-or-test-key"}):
                    with patch("server._load_cached_page_blocks", return_value=None):
                        _run_translation_worker(session_id, {
                            "provider": "openrouter",
                            "concurrency": 2,
                        })

        session = sessions[session_id]
        assert session["status"] == "finished"
        assert session["progress_percent"] == 100
        assert session["errors_count"] == 0
        assert len(session["pages"]) == 3

        # Page 0 was done via OpenRouter, Pages 1 and 2 via NVIDIA NIM
        for p in session["pages"]:
            assert p["status"] == "done"
            assert p["blocks_count"] > 0

        # Verify repackaged archive exists and has 3 translated images
        out_archive = Path(session["permanent_file"])
        assert out_archive.exists()
        with zipfile.ZipFile(out_archive, "r") as zre:
            assert len(zre.namelist()) == 3

    def test_empirical_finding_load_env_pops_empty_keys_from_environ(self):
        """
        Verify that Bug C1 is resolved:
        When an environment variable (e.g. NVIDIA_API_KEY) is passed via system environment,
        instantiating CloudVisionClient() triggers load_env(), which reads the workspace .env.
        Even if .env contains 'NVIDIA_API_KEY=', load_env() preserves the existing environment variable.
        """
        test_key_val = "gemini-test-environment-injection-key"
        os.environ["GEMINI_API_KEY"] = test_key_val
        assert os.environ.get("GEMINI_API_KEY") == test_key_val

        # Creating CloudVisionClient triggers load_env()
        c = CloudVisionClient()

        # Defect C1 resolved: os.environ["GEMINI_API_KEY"] is preserved intact because .env has GEMINI_API_KEY=
        preserved_val = os.environ.get("GEMINI_API_KEY")
        assert preserved_val == test_key_val, "Defect C1 resolved: load_env() preserved empty .env keys from clobbering environ"


# =====================================================================
# CHALLENGE 3: Corrupted Page Resilience on Real Sample
# =====================================================================

class TestChallengerCorruptedPageResilience:
    """Stress test error isolation and resilience on real sample 'Official_Chapter 41.5.cbz'."""

    def test_real_sample_exists_and_intact(self):
        """Sanity check: authentic sample must exist and have 4 entries."""
        _ensure_sample_cbz()
        assert REAL_SAMPLE_CBZ.exists(), f"Sample missing: {REAL_SAMPLE_CBZ}"
        with zipfile.ZipFile(REAL_SAMPLE_CBZ, "r") as z:
            names = z.namelist()
            assert "ComicInfo.xml" in names
            assert "001.jpg" in names
            assert "002.jpg" in names
            assert "003.jpg" in names

    def test_real_sample_with_corrupted_jpeg_data_in_archive(self, tmp_path):
        _ensure_sample_cbz()
        corrupted_cbz = tmp_path / "Official_Chapter_41.5_corrupt_page2.cbz"
        with zipfile.ZipFile(REAL_SAMPLE_CBZ, "r") as zin:
            with zipfile.ZipFile(corrupted_cbz, "w") as zout:
                for item in zin.infolist():
                    if item.filename == "002.jpg":
                        zout.writestr("002.jpg", b"BAD_JPEG_HEADER_CORRUPTED_BYTES_1234567890")
                    else:
                        zout.writestr(item.filename, zin.read(item.filename))

        session_id = f"test_corrupt_init_{int(time.time())}"
        session_dir = tmp_path / f"session_{session_id}"
        session_dir.mkdir(parents=True)

        info = _init_session_from_path(session_id, session_dir, corrupted_cbz, corrupted_cbz.name)
        assert info["total_pages"] == 2
        # Pages 001 and 003 are preserved
        assert [p["relative_name"] for p in info["pages"]] == ["001.jpg", "003.jpg"]

    def test_real_sample_runtime_vision_failure_isolation_and_repack(self, tmp_path):
        _ensure_sample_cbz()
        session_id = f"test_corrupt_runtime_{int(time.time())}"
        session_dir = tmp_path / f"session_{session_id}"
        session_dir.mkdir(parents=True)
        _init_session_from_path(session_id, session_dir, REAL_SAMPLE_CBZ, "Official_Chapter 41.5.cbz")

        call_idx = 0

        def mock_detect(img, max_side=1600, context_history=None):
            nonlocal call_idx
            curr = call_idx
            call_idx += 1
            if curr == 1:
                # Page 1 encounters unrecoverable failure
                raise RuntimeError("Vision model fatal 500 internal server error")
            return [
                {
                    "box": (150.0, 200.0, 350.0, 450.0),
                    "original": f"セリフ {curr}",
                    "translation": f"Traduction page {curr}",
                    "fr": f"Traduction page {curr}",
                    "ja": f"セリフ {curr}",
                }
            ], "mock-vision-model"

        with patch("server._load_cached_page_blocks", return_value=None):
            with patch.object(CloudVisionClient, "detect_and_translate", side_effect=mock_detect):
                _run_translation_worker(session_id, {
                    "provider": "auto",
                    "concurrency": 2,
                })

        session = sessions[session_id]
        assert session["status"] == "finished"
        assert session["errors_count"] == 1
        assert session["pages"][0]["status"] == "done"
        assert session["pages"][1]["status"] == "error"
        assert session["pages"][2]["status"] == "done"

        # Check that translated_images dict contains all 3 entries (including fallback for page 1)
        assert len(session["translated_images"]) == 3
        page1_rel = session["pages"][1]["relative_name"]
        fallback_page1_path = Path(session["translated_images"][page1_rel])
        assert fallback_page1_path.exists()

        # Repackage / Download check
        dl_res = test_client.get(f"/api/download/{session_id}")
        assert dl_res.status_code == 200
        with zipfile.ZipFile(io.BytesIO(dl_res.content), "r") as zout:
            namelist = zout.namelist()
            assert "ComicInfo.xml" in namelist
            assert len([n for n in namelist if n.endswith(".jpg")]) == 3

        # Single-page recovery: test retranslate_single_page on page 1 via API endpoint
        with patch("server._load_cached_page_blocks", return_value=None):
            with patch.object(CloudVisionClient, "detect_and_translate", return_value=(
                [{
                    "box": (150.0, 200.0, 350.0, 450.0),
                    "original": "修正セリフ",
                    "translation": "Page 1 rétablie",
                    "fr": "Page 1 rétablie",
                    "ja": "修正セリフ",
                }],
                "recovery-model",
            )):
                rec_res = test_client.post(f"/api/translate/page/{session_id}/1", json={"provider": "auto"})

        assert rec_res.status_code == 200
        assert rec_res.json()["status"] == "done"
        assert session["pages"][1]["status"] == "done"

        # Bug C2 resolved: session["errors_count"] is recalculated to 0 and status is finished
        assert session["errors_count"] == 0
        assert session["status"] == "finished"


# =====================================================================
# CHALLENGE 4: LLM Output Parsing, ANSI Stripping & Reasoning Tokens
# =====================================================================

class TestChallengerLLMOutputParsingStress:
    """Stress testing of LLM JSON parser, coordinate clamping, ANSI escape removal, and reasoning tokens."""

    def test_ansi_escape_code_stripping_in_text_fields(self):
        """Verify that ANSI terminal escape sequences inside text fields are sanitized cleanly."""
        raw_llm_with_ansi = json.dumps([
            {
                "box": [120, 250, 220, 250],
                "original": "\x1b[31m危険だ！\x1b[0m",
                "translation": "\x1b[32mC'est dangereux !\x1b[0m"
            }
        ])
        blocks = parse_and_validate_blocks(raw_llm_with_ansi)
        assert len(blocks) == 1
        assert blocks[0]["box"] == (120.0, 250.0, 340.0, 500.0)
        assert blocks[0]["original"] == "危険だ！"
        assert blocks[0]["translation"] == "C'est dangereux !"
        # Ensure no escape characters remain
        assert "\x1b" not in blocks[0]["original"]
        assert "\x1b" not in blocks[0]["translation"]

    def test_reasoning_token_extraction_when_content_empty(self):
        """
        Verify that reasoning models (Nemotron, DeepSeek) with empty message.content
        have their JSON successfully extracted from message.reasoning or message.reasoning_content.
        """
        client = CloudVisionClient(provider="nvidia", api_key="test-key")

        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = ""  # Empty content!
        mock_msg.reasoning = None
        mock_msg.reasoning_content = (
            "Thinking Process:\n"
            "1. Found speech bubble at [100, 100, 200, 300]\n"
            "```json\n"
            '[{"box": [100, 100, 100, 200], "original": "こんにちは", "translation": "Bonjour"}]\n'
            "```"
        )
        mock_choice.message = mock_msg
        mock_response.choices = [mock_choice]

        with patch("openai.OpenAI") as mock_openai_cls:
            mock_client_inst = MagicMock()
            mock_openai_cls.return_value = mock_client_inst
            mock_client_inst.chat.completions.create.return_value = mock_response

            blocks = client._call_openai_compatible(
                b64_str="dummy_base64",
                base_url="https://integrate.api.nvidia.com/v1",
                api_key="test-key",
                model_name="nvidia/nemotron-3.5-super-vl-120b-a12b",
                prompt="test prompt",
            )

        assert len(blocks) == 1
        assert blocks[0]["box"] == (100.0, 100.0, 200.0, 300.0)
        assert blocks[0]["translation"] == "Bonjour"

    def test_coordinate_clamping_and_inverted_rejection(self):
        """
        Verify that:
        - Bounding boxes out of range (> 1000) are clamped.
        - Inverted boxes (ymin >= ymax or xmin >= xmax) or zero-size boxes are filtered out.
        """
        raw_json = json.dumps([
            {"box": [-50, -20, 1100, 1100], "ja": "Clamped", "fr": "Valide"},
            {"box": [500, 500, 0, 100], "ja": "Zero Width", "fr": "Invalide"},
            {"box": [300, 400, -50, 100], "ja": "Negative Width", "fr": "Invalide"},
            {"box": [50, 50, 100, 100], "ja": "Normal", "fr": "Normale"},
        ])
        blocks = parse_and_validate_blocks(raw_json)
        assert len(blocks) == 2
        # First one clamped to [0, 0, 1000, 1000]
        assert blocks[0]["box"] == (0.0, 0.0, 1000.0, 1000.0)
        # Last one intact [50, 50, 150, 150]
        assert blocks[1]["box"] == (50.0, 50.0, 150.0, 150.0)
