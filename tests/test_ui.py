"""Targeted tests for the local browser UI (H8F).

Only verifies serving of the public shell and assets; data endpoints remain
covered by the existing H8B–H8E tests.
"""

from fastapi.testclient import TestClient

import api.app as api_app


def _client(monkeypatch):
    monkeypatch.setattr(api_app, "init_db", lambda: None)
    return TestClient(api_app.app)


def test_ui_page_served_publicly(monkeypatch):
    client = _client(monkeypatch)
    r = client.get("/ui")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "AI Bengkel" in r.text
    assert 'id="login-view"' in r.text  # login shell, no data


def test_static_assets_served(monkeypatch):
    client = _client(monkeypatch)
    assert client.get("/static/styles.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_ui_shell_contains_no_private_data(monkeypatch):
    # The public shell must not leak any vehicle/backup data.
    client = _client(monkeypatch)
    html = client.get("/ui").text
    assert "nopol" not in html
    assert "vehicle_count" not in html


def test_ui_uses_real_service_record_endpoint(monkeypatch):
    # The service-detail view must hit the real API (no dummy data).
    client = _client(monkeypatch)
    js = client.get("/static/app.js").text
    assert "/api/service-records/" in js
    assert "renderServiceDetail" in js
    assert "jobsTable" in js


def test_data_endpoints_still_require_auth(monkeypatch):
    monkeypatch.setattr(api_app, "init_db", lambda: None)
    monkeypatch.setenv("UI_ACCESS_TOKEN", "test-token")
    client = TestClient(api_app.app)
    assert client.get("/api/dashboard").status_code == 401
    assert client.get("/api/vehicles").status_code == 401
    assert client.post("/api/admin/backup").status_code == 401
    assert client.post("/api/admin/restore", content=b"x").status_code == 401
