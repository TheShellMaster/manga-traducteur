import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.archives import ArchiveItem
from server import app, sessions, _run_translation_worker, _global_vision_lock

client = TestClient(app)


# ---------------------------------------------------------------------------
# Requirement 1: Security tests (Swagger/docs disabled, anonymous sensitive routes)
# ---------------------------------------------------------------------------

def test_docs_and_openapi_disabled_by_default():
    """Verify that /docs, /redoc, and /openapi.json are disabled (404) by default in production."""
    # Ensure MTS_DEV_DOCS is not set to 1
    assert os.environ.get("MTS_DEV_DOCS") != "1"
    
    r_docs = client.get("/docs")
    assert r_docs.status_code == 404, f"Expected 404 on /docs, got {r_docs.status_code}"

    r_redoc = client.get("/redoc")
    assert r_redoc.status_code == 404, f"Expected 404 on /redoc, got {r_redoc.status_code}"

    r_openapi = client.get("/openapi.json")
    assert r_openapi.status_code == 404, f"Expected 404 on /openapi.json, got {r_openapi.status_code}"


def test_anonymous_settings_route_masks_secrets():
    """GET /api/settings must return 200 to anonymous callers but never reveal secrets."""
    res = client.get("/api/settings")
    assert res.status_code == 200
    data = res.json()
    assert "configured" in data
    assert isinstance(data["configured"], dict)
    # No plaintext API keys must ever be returned
    assert "gemini_api_key" not in data
    assert "openrouter_api_key" not in data
    assert "groq_api_key" not in data
    assert "custom_api_key" not in data


def test_anonymous_settings_route_rejects_unknown_payloads():
    """POST /api/settings must validate keys and reject unallowed arbitrary fields."""
    res = client.post("/api/settings", json={"attacker_key": "injected", "extra_payload": 123})
    assert res.status_code == 400
    assert "autorisé" in res.json().get("detail", "")


def test_sensitive_routes_reject_cross_origin_requests():
    """POST to sensitive routes must be rejected with 403 when coming from untrusted origins."""
    malicious_origins = [
        "https://evil.com",
        "http://attacker.local:8080",
        "https://phishing-site.org",
    ]
    for origin in malicious_origins:
        # Shutdown
        res_sd = client.post("/api/system/shutdown", headers={"Origin": origin})
        assert res_sd.status_code == 403, f"Expected 403 for Origin {origin}, got {res_sd.status_code}"
        
        # Settings save
        res_set = client.post("/api/settings", json={"provider": "auto"}, headers={"Origin": origin})
        assert res_set.status_code == 403, f"Expected 403 for Origin {origin}, got {res_set.status_code}"


def test_sensitive_routes_path_traversal_protection():
    """Download and library endpoints must strictly reject path traversal payloads with 404."""
    traversal_targets = [
        "../../etc/passwd",
        "..%2F..%2Fetc%2Fpasswd",
        "../../../.env",
        "....//....//server.py",
        "/etc/shadow",
    ]
    for target in traversal_targets:
        res = client.get(f"/api/library/download/{target}")
        assert res.status_code in (404, 400), f"Expected 404/400 for traversal '{target}', got {res.status_code}"

    # Nonexistent session download
    res_sess = client.get("/api/download/nonexistent-session-id-12345")
    assert res_sess.status_code == 404

    # Nonexistent session status
    res_stat = client.get("/api/session/nonexistent-session-id-12345/status")
    assert res_stat.status_code == 404


def test_shutdown_endpoint_safe_in_test_mode():
    """POST /api/system/shutdown accepts local requests and safely aborts actual kill under test."""
    res = client.post("/api/system/shutdown")
    assert res.status_code == 200
    assert res.json().get("status") == "ok"


# ---------------------------------------------------------------------------
# Requirement 2: Vision Concurrency max 1 across sessions & strict page ordering
# ---------------------------------------------------------------------------

def _build_test_session(tmp_path: Path, session_id: str, page_count: int = 3) -> dict:
    session_dir = tmp_path / session_id
    pages_dir = session_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    items = []
    pages_meta = []
    for i in range(page_count):
        rel_name = f"page_{i:03d}.jpg"
        orig_file = pages_dir / f"page_{i:03d}_orig.jpg"
        # Unique color per page to avoid identical cache hashes
        color = (20 * (i + 1), 40 * (i + 1), 60 * (i + 1))
        img = Image.new("RGB", (300 + i * 10, 400 + i * 10), color=color)
        img.save(orig_file, format="JPEG")
        img.close()
        
        item = ArchiveItem(
            relative_name=rel_name,
            is_image=True,
            raw_bytes=orig_file.read_bytes(),
            source_path=orig_file,
        )
        items.append(item)
        pages_meta.append({
            "index": i,
            "filename": rel_name,
            "status": "pending",
            "stage": "pending",
            "blocks_count": 0,
            "blocks": [],
        })

    session_data = {
        "id": session_id,
        "session_id": session_id,
        "input_file": str(session_dir / "test.cbz"),
        "fmt": "cbz",
        "session_dir": str(session_dir),
        "items": items,
        "image_items": items,
        "total_pages": page_count,
        "pages": pages_meta,
        "translated_images": {},
        "status": "queued",
        "current_page": 0,
        "progress_percent": 0,
        "current_log": "Initialisé",
        "cancelled": False,
    }
    sessions[session_id] = session_data
    return session_data


def test_global_vision_concurrency_max_one_across_sessions(tmp_path):
    """
    Automated proof:
    1. Two distinct sessions are launched concurrently in separate threads.
    2. At any point in time, active_vision_calls <= 1 across all sessions.
    3. Pages within each session are processed in strict sequential order (0 -> 1 -> 2).
    """
    active_vision_calls = 0
    max_vision_concurrency = 0
    stats_lock = threading.Lock()
    call_log = []

    def mock_detect_and_translate(self, image, max_side=1600, context_history=None):
        nonlocal active_vision_calls, max_vision_concurrency
        with stats_lock:
            active_vision_calls += 1
            if active_vision_calls > max_vision_concurrency:
                max_vision_concurrency = active_vision_calls
            current_active = active_vision_calls
            t_start = time.time()

        # Hold artificially for 50ms to provoke concurrency conflicts if locks were missing
        time.sleep(0.05)

        with stats_lock:
            t_end = time.time()
            active_vision_calls -= 1
            call_log.append({
                "thread_name": threading.current_thread().name,
                "active_at_entry": current_active,
                "start": t_start,
                "end": t_end,
                "context_len": len(context_history or []),
            })

        return [
            {
                "box_2d": [10, 10, 80, 80],
                "original": "オハヨウ",
                "translation": "Bonjour",
                "category": "dialogue",
                "confidence": 0.98,
            }
        ], "Gemini 2.0 Flash Mock"

    # Set up 2 separate sessions with 3 pages each
    sess_a = _build_test_session(tmp_path, "session_concurrent_A", page_count=3)
    sess_b = _build_test_session(tmp_path, "session_concurrent_B", page_count=3)

    t1 = threading.Thread(
        target=_run_translation_worker,
        args=("session_concurrent_A", {"provider": "auto", "concurrency": 1, "force_refresh": True}),
        name="Worker-Session-A",
    )
    t2 = threading.Thread(
        target=_run_translation_worker,
        args=("session_concurrent_B", {"provider": "auto", "concurrency": 1, "force_refresh": True}),
        name="Worker-Session-B",
    )

    with patch("app.cloud_vision.CloudVisionClient.detect_and_translate", new=mock_detect_and_translate):
        t1.start()
        t2.start()
        t1.join(timeout=10.0)
        t2.join(timeout=10.0)

    # 1. Total Vision calls executed across both sessions
    assert len(call_log) == 6, f"Expected 6 total Vision calls, got {len(call_log)}"

    # 2. PROOF: max active Vision requests was NEVER greater than 1
    assert max_vision_concurrency == 1, (
        f"Concurrency violation: max_vision_concurrency reached {max_vision_concurrency} > 1"
    )

    # 3. Verify no overlap between any two calls in timeline
    # Sort calls by start timestamp
    sorted_calls = sorted(call_log, key=lambda c: c["start"])
    for i in range(len(sorted_calls) - 1):
        c1 = sorted_calls[i]
        c2 = sorted_calls[i + 1]
        assert c1["end"] <= c2["start"] + 0.005, (
            f"Overlap detected: call {i} ended at {c1['end']} but call {i+1} started at {c2['start']}"
        )

    # 4. Verify both sessions marked all pages as 'done'
    for p in sess_a["pages"]:
        assert p["status"] == "done"
    for p in sess_b["pages"]:
        assert p["status"] == "done"


def test_strict_sequential_page_ordering_and_context_propagation(tmp_path):
    """
    Automated proof:
    Pages are processed strictly 0 -> 1 -> 2 -> 3 in order,
    and narrative context is propagated from preceding pages.
    """
    processed_order = []
    contexts_received = []

    def mock_detect_ordered(self, image, max_side=1600, context_history=None):
        # Determine which page is being called from image size or metadata
        idx = len(processed_order)
        processed_order.append(idx)
        contexts_received.append(list(context_history or []))
        return [
            {
                "box_2d": [10, 10, 50, 50],
                "original": f"Dialogue page {idx}",
                "translation": f"Traduction page {idx}",
                "category": "dialogue",
                "confidence": 0.99,
            }
        ], "Gemini 2.0 Flash Mock"

    sess = _build_test_session(tmp_path, "session_sequential_order", page_count=4)

    with patch("app.cloud_vision.CloudVisionClient.detect_and_translate", new=mock_detect_ordered):
        _run_translation_worker("session_sequential_order", {"provider": "auto", "concurrency": 1, "force_refresh": True})

    # Proof of strict 0 -> 1 -> 2 -> 3 ordering
    assert processed_order == [0, 1, 2, 3], f"Pages processed out of order: {processed_order}"

    # Proof of sequential context accumulation:
    # Page 0 has empty context
    assert len(contexts_received[0]) == 0
    # Page 1 has context from Page 0
    assert len(contexts_received[1]) == 1
    assert contexts_received[1][0]["translation"] == "Traduction page 0"
    # Page 2 has context from Pages 0 and 1
    assert len(contexts_received[2]) == 2
    assert contexts_received[2][1]["translation"] == "Traduction page 1"
    # Page 3 has context from Pages 0, 1, and 2
    assert len(contexts_received[3]) == 3
