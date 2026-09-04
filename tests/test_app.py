import os
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///./test_dis360.db"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["ADMIN_PASSWORD"] = "test-admin-password"

Path("test_dis360.db").unlink(missing_ok=True)

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


def test_chat_file_context_stub_chart_and_export():
    with TestClient(app) as client:
        response = client.post("/register", data={"email": "chat@example.com", "password": "reliable-password"}, follow_redirects=False)
        assert response.status_code == 303
        created = client.post("/chat/new", follow_redirects=False)
        assert created.status_code == 303
        chat_url = created.headers["location"]
        csv_path = Path("examples/sample_sales.csv")
        with csv_path.open("rb") as handle:
            uploaded = client.post(f"{chat_url}/upload", files={"data_file": (csv_path.name, handle, "text/csv")}, follow_redirects=False)
        assert uploaded.status_code == 303
        answer = client.post(f"{chat_url}/message", data={"question": "Кратко проанализируй файл"}, follow_redirects=True)
        assert answer.status_code == 200
        assert "Демо-режим" in answer.text
        assert "6 строк" in answer.text
        chart = client.post(f"{chat_url}/chart", data={"chart_type": "pie", "x_column": "region", "y_column": "revenue"}, follow_redirects=True)
        assert chart.status_code == 200
        assert "График pie" in chart.text
        report = client.post(f"{chat_url}/export", follow_redirects=True)
        assert report.status_code == 200
        assert "Отчёт Markdown" in report.text


def teardown_module():
    try:
        Path("test_dis360.db").unlink(missing_ok=True)
    except PermissionError:
        pass
