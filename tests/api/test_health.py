from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_serves_html() -> None:
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Tempo" in response.text
