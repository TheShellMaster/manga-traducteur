from fastapi import BackgroundTasks
from fastapi.testclient import TestClient

from server import app, sessions, start_translation

client = TestClient(app)


class TaskCollector(BackgroundTasks):
    def __init__(self):
        super().__init__()
        self.tasks = []

    def add_task(self, func, *args, **kwargs):
        self.tasks.append((func, args, kwargs))


def _session(status="pending"):
    return {
        "status": status,
        "cancelled": False,
        "current_log": "",
    }


def test_translation_start_reserves_session_and_prevents_duplicate(monkeypatch):
    session_id = "test-sequence-reservation"
    sessions[session_id] = _session()
    tasks = TaskCollector()
    try:
        result = start_translation({"session_id": session_id}, tasks)
        assert result["status"] == "started"
        assert sessions[session_id]["status"] == "queued"
        assert tasks.tasks[0][0].__name__ == "_run_translation_worker_safely"
        assert tasks.tasks[0][1][1]["concurrency"] == 1

        response = client.post("/api/translate/start", json={"session_id": session_id})
        assert response.status_code == 409
        assert len(tasks.tasks) == 1
    finally:
        sessions.pop(session_id, None)


def test_translation_start_rejects_invalid_concurrency():
    session_id = "test-sequence-invalid-concurrency"
    sessions[session_id] = _session()
    try:
        response = client.post(
            "/api/translate/start",
            json={"session_id": session_id, "concurrency": 4},
        )
        assert response.status_code == 400
        assert sessions[session_id]["status"] == "pending"
    finally:
        sessions.pop(session_id, None)


def test_translation_start_rejects_missing_session():
    response = client.post("/api/translate/start", json={"session_id": "not-a-session"})
    assert response.status_code == 404
