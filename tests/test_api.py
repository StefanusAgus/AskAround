from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_does_not_require_google_credentials() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_exposes_all_three_google_places_operations() -> None:
    paths = app.openapi()["paths"]

    assert "/places/search" in paths
    assert "/places/nearby" in paths
    assert "/places/{place_id}" in paths
