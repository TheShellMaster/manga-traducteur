import os

from fastapi.testclient import TestClient

from server import app, _translation_concurrency

client = TestClient(app)


def test_settings_never_returns_saved_secrets(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "do-not-return-this")
    response = client.get("/api/settings")
    assert response.status_code == 200
    body = response.json()
    assert "gemini_api_key" not in body
    assert "custom_api_key" not in body
    assert body["configured"]["gemini"] is True


def test_settings_rejects_unknown_fields():
    response = client.post(
        "/api/settings",
        json={"unexpected": "value"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 400


def test_csrf_rejects_missing_origin():
    response = client.post("/api/settings", json={"key": "val"})
    assert response.status_code == 403


def test_csrf_rejects_null_origin():
    response = client.post(
        "/api/settings",
        json={"key": "val"},
        headers={"Origin": "null"},
    )
    assert response.status_code == 403


def test_cross_origin_post_is_rejected():
    response = client.post("/api/system/shutdown", headers={"Origin": "https://attacker.example"})
    assert response.status_code == 403


def test_concurrency_hard_capped_to_one():
    for req in [0, 1, 2, 3, 99]:
        assert _translation_concurrency({"concurrency": req}, 100) == 1
    assert _translation_concurrency({}, 50) == 1
