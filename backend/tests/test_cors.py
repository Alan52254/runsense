from fastapi.testclient import TestClient

from app.main import app


def test_default_vite_origins_accept_localhost_and_loopback() -> None:
    client = TestClient(app)

    for origin in ("http://localhost:5173", "http://127.0.0.1:5174"):
        response = client.options(
            "/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
