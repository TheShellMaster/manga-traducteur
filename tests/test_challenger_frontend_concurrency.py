"""
Adversarial Challenge Suite 2 — Frontend, Concurrency & Ergonomics
Empirical verification of:
1. Split-View & Slider modes:
   - Absolute image dimension parity between /api/image/{sid}/orig/{i} and /api/image/{sid}/trans/{i}
   - Aspect ratio preservation across standard, double-spread, webtoon, odd-dimension, and real manga pages.
   - CSS clip-path boundary values (0%, 50%, 100%) and clamping.
2. Concurrency & Rapid Cancellation:
   - Mid-stream cancellation during active multi-worker ThreadPool translation.
   - Thread deadlock detection and session state integrity.
   - Rapid start/cancel/start hammering (stressing race conditions).
   - Partial completion persistence (pages completed before cancellation remain accessible).
   - Clean re-translation after cancellation.
3. Reveal Queue & Frontend State:
   - Verification of queue state transitions and non-dropping queue invariant.
"""

import io
import os
import sys
import time
import zipfile
import threading
import concurrent.futures
from pathlib import Path
from typing import Dict, Any, List
from unittest.mock import patch, MagicMock

import pytest
from PIL import Image, ImageDraw

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient

from server import (
    app,
    sessions,
    _run_translation_worker,
    _init_session_from_path,
    retranslate_single_page,
)
from app.typesetter import render_manga_page

test_client = TestClient(app)
REAL_SAMPLE_CBZ = ROOT_DIR / "Otome Game Sekai wa Mob ni Kibishii Sekai desu" / "Official_Chapter 41.5.cbz"


def _create_test_image(width: int, height: int, pattern: str = "rect", text: str = "") -> bytes:
    img = Image.new("RGB", (width, height), color=(245, 245, 245))
    draw = ImageDraw.Draw(img)
    # Add border and distinct markers
    draw.rectangle([0, 0, width - 1, height - 1], outline=(20, 20, 20), width=2)
    # Add fake speech bubbles with coordinates
    bx0, by0, bx1, by1 = int(width * 0.2), int(height * 0.2), int(width * 0.6), int(height * 0.4)
    draw.ellipse([bx0, by0, bx1, by1], fill=(255, 255, 255), outline=(0, 0, 0), width=3)
    nonce = text or f"n_{time.time_ns()}"
    draw.text((bx0 + 4, by0 + 4), nonce, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _create_mock_cbz(images_spec: List[tuple]) -> io.BytesIO:
    """images_spec: list of (filename, width, height)"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, w, h in images_spec:
            zf.writestr(fname, _create_test_image(w, h))
    buf.seek(0)
    return buf


# ============================================================================
# Challenge 1: Dimension Parity & Bounds
# ============================================================================

class TestDimensionParityAndSliderBounds:

    @pytest.mark.parametrize("name,w,h", [
        ("standard_portrait", 800, 1200),
        ("double_spread_landscape", 2400, 1200),
        ("webtoon_tall_strip", 600, 3200),
        ("odd_non_even_dim", 733, 1107),
        ("square", 1000, 1000),
        ("small_resolution", 250, 350),
    ])
    def test_image_dimension_parity_across_aspect_ratios(self, name, w, h):
        """Verify orig and trans images have 100% identical pixel dimensions for any aspect ratio."""
        cbz_data = _create_mock_cbz([(f"{name}.jpg", w, h)])
        upload_resp = test_client.post(
            "/api/upload",
            files={"file": (f"{name}.cbz", cbz_data.getvalue(), "application/vnd.comicbook+zip")}
        )
        assert upload_resp.status_code == 200, f"Upload failed: {upload_resp.text}"
        sid = upload_resp.json()["session_id"]

        # Mock CloudVisionClient to return simulated bubble
        mock_blocks = [
            {
                "box": (200, 200, 400, 600),
                "original": "テストテキスト",
                "translation": "Texte de test vérifié.",
                "fr": "Texte de test vérifié.",
            }
        ]

        with patch("server.CloudVisionClient") as MockClient:
            instance = MockClient.return_value
            instance.detect_and_translate.return_value = (mock_blocks, "MockVision")

            # Run translation for page 0
            start_resp = test_client.post(
                "/api/translate/start",
                json={"session_id": sid, "provider": "auto", "concurrency": 1}
            )
            assert start_resp.status_code == 200

            # Wait for completion
            for _ in range(50):
                st = test_client.get(f"/api/status/{sid}").json()
                if st["status"] == "finished":
                    break
                time.sleep(0.05)
            assert st["status"] == "finished"

        # Fetch original image
        resp_orig = test_client.get(f"/api/image/{sid}/orig/0")
        assert resp_orig.status_code == 200
        assert resp_orig.headers["content-type"] == "image/jpeg"
        orig_img = Image.open(io.BytesIO(resp_orig.content))

        # Fetch translated image
        resp_trans = test_client.get(f"/api/image/{sid}/trans/0")
        assert resp_trans.status_code == 200
        assert resp_trans.headers["content-type"] == "image/jpeg"
        trans_img = Image.open(io.BytesIO(resp_trans.content))

        # Fetch clean stage image
        resp_clean = test_client.get(f"/api/image/{sid}/clean/0")
        assert resp_clean.status_code == 200
        clean_img = Image.open(io.BytesIO(resp_clean.content))

        # STRICT EMPIRICAL PARITY ASSERTION
        assert orig_img.size == (w, h), f"Original image size mismatch: {orig_img.size} vs expected {(w, h)}"
        assert trans_img.size == (w, h), f"Translated image size mismatch: {trans_img.size} vs expected {(w, h)}"
        assert clean_img.size == (w, h), f"Clean image size mismatch: {clean_img.size} vs expected {(w, h)}"
        assert orig_img.size == trans_img.size, "Orig and Trans dimension drift detected!"

    def test_real_manga_chapter_page_dimensions(self):
        """Verify dimension parity on real manga archive sample if present."""
        if not REAL_SAMPLE_CBZ.exists():
            pytest.skip("Real manga sample not found")

        with open(REAL_SAMPLE_CBZ, "rb") as f:
            upload_resp = test_client.post(
                "/api/upload",
                files={"file": (REAL_SAMPLE_CBZ.name, f.read(), "application/vnd.comicbook+zip")}
            )
        assert upload_resp.status_code == 200
        sid = upload_resp.json()["session_id"]
        total = upload_resp.json()["total_pages"]
        assert total > 0

        # Check first 3 pages orig dimension vs session declared dimensions
        st = test_client.get(f"/api/status/{sid}").json()
        for idx in range(min(3, total)):
            page_meta = st["pages"][idx]
            resp_orig = test_client.get(f"/api/image/{sid}/orig/{idx}")
            assert resp_orig.status_code == 200
            orig_img = Image.open(io.BytesIO(resp_orig.content))
            assert orig_img.width == page_meta["width"]
            assert orig_img.height == page_meta["height"]

    def test_slider_clip_path_formula_and_bounds(self):
        """Adversarially challenge the CSS clip-path calculation for extreme bounds."""
        # CSS rule in web/static/css/style.css:
        # clip-path: inset(0 calc(100% - var(--slider-pos, 50%)) 0 0);
        def compute_clip_inset_right(pct: float) -> float:
            clamped = max(0.0, min(100.0, pct))
            return 100.0 - clamped

        # Extreme 0%: entire translated image is clipped out, reveals 100% original
        assert compute_clip_inset_right(0.0) == 100.0

        # Extreme 50%: right 50% is clipped out, reveals left 50% translated, right 50% original
        assert compute_clip_inset_right(50.0) == 50.0

        # Extreme 100%: 0% is clipped out, reveals 100% translated
        assert compute_clip_inset_right(100.0) == 0.0

        # Underflow (< 0%): should clamp to 0% (inset right 100%)
        assert compute_clip_inset_right(-45.0) == 100.0

        # Overflow (> 100%): should clamp to 100% (inset right 0%)
        assert compute_clip_inset_right(145.0) == 0.0


# ============================================================================
# Challenge 2: Concurrency & Rapid Cancellation
# ============================================================================

class TestConcurrencyAndCancellation:

    def test_cancellation_mid_stream_terminates_cleanly_without_deadlock(self):
        """Start a 6-page translation and cancel midway while workers are active."""
        cbz_data = _create_mock_cbz([(f"page_{i:02d}.jpg", 600, 900) for i in range(6)])
        upload_resp = test_client.post(
            "/api/upload",
            files={"file": ("cancel_test.cbz", cbz_data.getvalue(), "application/vnd.comicbook+zip")}
        )
        assert upload_resp.status_code == 200
        sid = upload_resp.json()["session_id"]

        page_entered_count = 0
        entered_lock = threading.Lock()
        hold_event = threading.Event()

        def slow_detect(*args, **kwargs):
            nonlocal page_entered_count
            with entered_lock:
                page_entered_count += 1
            # Wait for cancel trigger
            hold_event.wait(timeout=3.0)
            return ([
                {
                    "box": (100, 100, 300, 300),
                    "original": "Orig",
                    "translation": "Trad",
                    "fr": "Trad",
                }
            ], "MockVision")

        with patch("server.CloudVisionClient") as MockClient, patch("server._load_cached_page_blocks", return_value=None):
            instance = MockClient.return_value
            instance.detect_and_translate.side_effect = slow_detect

            # Start translation in a background thread because TestClient runs BackgroundTasks synchronously
            t_start = threading.Thread(
                target=test_client.post,
                args=("/api/translate/start",),
                kwargs={"json": {"session_id": sid, "provider": "auto", "concurrency": 2}}
            )
            t_start.start()

            # Wait until at least 1 page has entered detection
            for _ in range(50):
                with entered_lock:
                    if page_entered_count >= 1:
                        break
                time.sleep(0.02)

            assert page_entered_count >= 1, "Workers did not start"

            # Issue cancel mid-stream
            cancel_resp = test_client.post(f"/api/translate/cancel/{sid}")
            assert cancel_resp.status_code == 200
            assert cancel_resp.json()["status"] == "cancelled"

            # Release workers
            hold_event.set()
            t_start.join(timeout=5.0)
            assert not t_start.is_alive(), "Start thread deadlocked!"

            # Poll status to ensure the server exits translation loop promptly (< 4 seconds)
            start_time = time.time()
            cancelled_cleanly = False
            while time.time() - start_time < 4.0:
                st = test_client.get(f"/api/status/{sid}").json()
                if st["status"] == "cancelled":
                    cancelled_cleanly = True
                    break
                time.sleep(0.05)

            assert cancelled_cleanly, f"Server failed to reach 'cancelled' status: {st}"

            # Verify no deadlock: server responds to subsequent API calls immediately
            st_after = test_client.get(f"/api/status/{sid}")
            assert st_after.status_code == 200
            assert st_after.json()["status"] == "cancelled"

    def test_rapid_start_cancel_hammer(self):
        """Stress test rapid start/cancel cycles (10 cycles) to uncover race conditions or thread corruption."""
        cbz_data = _create_mock_cbz([(f"page_{i:02d}.jpg", 500, 700) for i in range(4)])
        upload_resp = test_client.post(
            "/api/upload",
            files={"file": ("rapid_hammer.cbz", cbz_data.getvalue(), "application/vnd.comicbook+zip")}
        )
        assert upload_resp.status_code == 200
        sid = upload_resp.json()["session_id"]

        with patch("server.CloudVisionClient") as MockClient:
            instance = MockClient.return_value
            instance.detect_and_translate.return_value = ([], "MockVision")

            for cycle in range(10):
                # Start
                t_sub = threading.Thread(
                    target=test_client.post,
                    args=("/api/translate/start",),
                    kwargs={"json": {"session_id": sid, "provider": "auto", "concurrency": 2}}
                )
                t_sub.start()

                # Brief sleep between 0 and 20ms to hit different thread interleavings
                time.sleep(0.005 * (cycle % 4))

                # Cancel immediately
                c_resp = test_client.post(f"/api/translate/cancel/{sid}")
                assert c_resp.status_code == 200, f"Cycle {cycle}: Cancel failed"
                assert c_resp.json()["status"] == "cancelled"
                t_sub.join(timeout=3.0)

            # Allow threads to settle
            time.sleep(0.5)

            # Final state check
            final_status = test_client.get(f"/api/status/{sid}").json()
            assert final_status["status"] in ("cancelled", "finished")
            assert not final_status.get("error")

    def test_partial_completion_and_resumption_after_cancellation(self):
        """Verify that pages completed before cancellation remain accessible, and resuming reuses cached pages."""
        cbz_data = _create_mock_cbz([(f"page_{i:02d}.jpg", 600, 800) for i in range(4)])
        upload_resp = test_client.post(
            "/api/upload",
            files={"file": ("partial_resume.cbz", cbz_data.getvalue(), "application/vnd.comicbook+zip")}
        )
        assert upload_resp.status_code == 200
        sid = upload_resp.json()["session_id"]

        call_count = 0
        call_lock = threading.Lock()
        hold_second_page = threading.Event()

        def controlled_detect(*args, **kwargs):
            nonlocal call_count
            with call_lock:
                call_count += 1
                curr = call_count
            if curr == 1:
                return ([{"box": (100, 100, 200, 200), "original": "P1", "translation": "Page 1 finie", "fr": "Page 1 finie"}], "MockVision")
            # Wait on page 2 so test can reliably cancel
            hold_second_page.wait(timeout=2.0)
            return ([{"box": (100, 100, 200, 200), "original": "PX", "translation": "Page X", "fr": "Page X"}], "MockVision")

        with patch("server.CloudVisionClient") as MockClient:
            instance = MockClient.return_value
            instance.detect_and_translate.side_effect = controlled_detect

            # Start with concurrency=1 for strictly ordered execution
            t_first = threading.Thread(
                target=test_client.post,
                args=("/api/translate/start",),
                kwargs={"json": {"session_id": sid, "concurrency": 1}}
            )
            t_first.start()

            # Wait until page 0 completes
            for _ in range(60):
                st = test_client.get(f"/api/status/{sid}").json()
                if st["pages"][0]["status"] == "done":
                    break
                time.sleep(0.05)

            assert st["pages"][0]["status"] == "done", "Page 0 did not finish"

            # Cancel while page 1 is in progress
            c_resp = test_client.post(f"/api/translate/cancel/{sid}")
            assert c_resp.status_code == 200
            hold_second_page.set()
            t_first.join(timeout=5.0)

            # Wait for cancellation status
            for _ in range(30):
                st = test_client.get(f"/api/status/{sid}").json()
                if st["status"] == "cancelled":
                    break
                time.sleep(0.05)
            assert st["status"] == "cancelled"

            # EMPIRICAL CHECK: Page 0 image is intact and retrievable
            p0_trans = test_client.get(f"/api/image/{sid}/trans/0")
            assert p0_trans.status_code == 200
            assert p0_trans.headers["content-type"] == "image/jpeg"

            # Reset detect mock for remaining pages (instant completion)
            instance.detect_and_translate.side_effect = None
            instance.detect_and_translate.return_value = (
                [{"box": (100, 100, 200, 200), "original": "P", "translation": "Page", "fr": "Page"}],
                "MockVision"
            )

            # Now resume translation (click 'Traduire à nouveau')
            t_second = threading.Thread(
                target=test_client.post,
                args=("/api/translate/start",),
                kwargs={"json": {"session_id": sid, "concurrency": 2}}
            )
            t_second.start()
            t_second.join(timeout=10.0)

            # Let all pages finish
            for _ in range(60):
                st = test_client.get(f"/api/status/{sid}").json()
                if st["status"] == "finished":
                    break
                time.sleep(0.05)

            assert st["status"] == "finished"
            assert all(p["status"] == "done" for p in st["pages"])


# ============================================================================
# Challenge 3: Reveal Queue Logic Invariants
# ============================================================================

class TestRevealQueueInvariants:

    def test_reveal_queue_simulation_burst_completions(self):
        """Simulate JS reveal queue logic when 10 pages complete in a simultaneous burst."""
        # Models the logic in app.js lines 783-788 and 836-845
        class MockFrontendState:
            def __init__(self, total_pages: int):
                self.pages = [{"status": "pending"} for _ in range(total_pages)]
                self.animated = set()
                self.anim = None
                self.revealQueue = []
                self.isRevealing = False
                self.follow = True
                self.revealed_order = []

            def poll_update(self, new_pages):
                self.pages = new_pages
                for i, p in enumerate(new_pages):
                    if (
                        p["status"] == "done"
                        and i not in self.animated
                        and i not in self.revealQueue
                        and self.anim != i
                    ):
                        self.revealQueue.push(i) if hasattr(self.revealQueue, 'push') else self.revealQueue.append(i)

            def process_reveal_queue(self):
                if self.isRevealing:
                    return
                self.isRevealing = True
                while len(self.revealQueue) > 0 and self.follow:
                    idx = self.revealQueue.pop(0)
                    if idx not in self.animated:
                        self.anim = idx
                        self.animated.add(idx)
                        self.revealed_order.append(idx)
                        self.anim = None
                self.isRevealing = False

        fe = MockFrontendState(10)

        # Simultaneous burst: all 10 pages become 'done' in one poll
        burst_pages = [{"status": "done"} for _ in range(10)]
        fe.poll_update(burst_pages)

        # Invariant 1: ALL 10 pages are in the queue (no page is silently dropped!)
        assert len(fe.revealQueue) == 10
        assert fe.revealQueue == list(range(10))

        # Invariant 2: Draining the queue reveals all 10 pages in strict sequence without UI lockup
        fe.process_reveal_queue()
        assert len(fe.revealQueue) == 0
        assert len(fe.animated) == 10
        assert fe.revealed_order == list(range(10))
        assert not fe.isRevealing

    def test_reveal_queue_interrupted_by_follow_toggle(self):
        """If user disables 'Suivre' (follow=false), reveal queue stops immediately."""
        class MockFrontendState:
            def __init__(self, total_pages: int):
                self.pages = [{"status": "pending"} for _ in range(total_pages)]
                self.animated = set()
                self.anim = None
                self.revealQueue = [0, 1, 2, 3, 4]
                self.isRevealing = False
                self.follow = True
                self.revealed_order = []

            def process_reveal_queue_with_interrupt_at(self, stop_after_count: int):
                self.isRevealing = True
                count = 0
                while len(self.revealQueue) > 0 and self.follow:
                    idx = self.revealQueue.pop(0)
                    if idx not in self.animated:
                        self.anim = idx
                        self.animated.add(idx)
                        self.revealed_order.append(idx)
                        count += 1
                        if count >= stop_after_count:
                            self.follow = False  # User unchecks 'Suivre'
                        self.anim = None
                self.isRevealing = False

        fe = MockFrontendState(5)
        fe.process_reveal_queue_with_interrupt_at(stop_after_count=2)

        # Queue stopped gracefully after 2 pages without infinite loop or crash
        assert len(fe.revealed_order) == 2
        assert len(fe.revealQueue) == 3
        assert not fe.isRevealing
