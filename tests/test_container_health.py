from fastapi.testclient import TestClient

from server import app


def test_root_endpoint_used_by_container_healthcheck():
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
