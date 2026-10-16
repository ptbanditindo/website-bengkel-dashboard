"""Security tests for the API foundation (H8B): authentication + docs policy."""

import pytest
from fastapi.testclient import TestClient

import api.app as api_app

VALID_TOKEN = "test-ui-token-123"
AUTH = {"Authorization": f"Bearer {VALID_TOKEN}"}


@pytest.fixture()
def secure_client(monkeypatch):
    monkeypatch.setattr(api_app, "init_db", lambda: None)
    monkeypatch.setenv("UI_ACCESS_TOKEN", VALID_TOKEN)
    return TestClient(api_app.app)


def test_protected_rejects_missing_token(secure_client):
    assert secure_client.get("/").status_code == 401


def test_protected_rejects_wrong_token(secure_client):
    r = secure_client.get("/", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_protected_accepts_valid_token(secure_client):
    r = secure_client.get("/", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["name"] == "AI Bengkel API"


def test_protected_fails_closed_when_unconfigured(monkeypatch):
    monkeypatch.setattr(api_app, "init_db", lambda: None)
    monkeypatch.delenv("UI_ACCESS_TOKEN", raising=False)
    client = TestClient(api_app.app)
    assert client.get("/", headers=AUTH).status_code == 503  # fail closed


def test_health_public_minimal(secure_client):
    r = secure_client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}  # minimal, no secrets


def test_error_does_not_leak_token(secure_client):
    r = secure_client.get("/", headers={"Authorization": "Bearer secret-leak"})
    assert r.status_code == 401
    assert "secret-leak" not in r.text
    assert "Bearer" not in r.json().get("detail", "")


def test_docs_disabled(secure_client):
    assert secure_client.get("/docs").status_code == 404
    assert secure_client.get("/redoc").status_code == 404
    assert secure_client.get("/openapi.json").status_code == 404
