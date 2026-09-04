import os
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///./test_dis360.db"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["ADMIN_PASSWORD"] = "test-admin-password"

from fastapi.testclient import TestClient
from app.main import app


def test_health_and_registration():
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["database"] == "ok"
        email = "student@example.com"
        response = client.post("/register", data={"email": email, "password": "reliable-password"}, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/dashboard"


def test_unauthorized_dashboard_redirects():
    with TestClient(app) as client:
        response = client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 303


def test_authenticated_csv_chart_and_websocket():
    with TestClient(app) as client:
        response = client.post(
            "/register",
            data={"email": "chart@example.com", "password": "reliable-password"},
            follow_redirects=False,
        )
        if response.status_code == 409:
            response = client.post(
                "/login",
                data={"email": "chart@example.com", "password": "reliable-password"},
                follow_redirects=False,
            )
        assert response.status_code == 303
        csv_path = Path("examples/sample_sales.csv")
        with csv_path.open("rb") as handle:
            result = client.post(
                "/analyze",
                data={"chart_type": "pie", "x_column": "region", "y_column": "revenue"},
                files={"data_file": (csv_path.name, handle, "text/csv")},
            )
        assert result.status_code == 200
        assert "6 строк" in result.text
        assert "Интерактивный график" in result.text
        assert "Как рассчитано" in result.text
        assert "\\u0441" not in result.text
        assert "\\u003c" not in result.text
        assert "бизнес-аналитик" in result.text
        with client.websocket_connect("/ws/status") as websocket:
            assert websocket.receive_json()["stage"] == "connected"
            websocket.send_text("test")
            assert websocket.receive_json()["stage"] == "ready"


def test_unicode_and_angle_brackets_are_readable():
    from app.services import normalize_text, pretty_json

    assert normalize_text(r"\u003cадрес\u003e") == "<адрес>"
    assert normalize_text("&lt;адрес&gt;") == "<адрес>"
    dumped = pretty_json({"answer": "<адрес> по <адрес>"})
    assert "<адрес>" in dumped
    assert r"\u003c" not in dumped
    assert r"\u0441" not in dumped

    with TestClient(app) as client:
        client.post("/register", data={"email": "unicode@example.com", "password": "reliable-password"}, follow_redirects=False)
        result = client.post(
            "/analyze",
            data={"chart_type": "bar"},
            files={"data_file": ("notes.csv", "city,note\nМосква,<адрес>\n".encode("utf-8"), "text/csv")},
        )
        assert result.status_code == 200
        assert r"\u003c" not in result.text
        assert "&lt;адрес&gt;" in result.text


def teardown_module():
    try:
        Path("test_dis360.db").unlink(missing_ok=True)
    except PermissionError:
        pass
