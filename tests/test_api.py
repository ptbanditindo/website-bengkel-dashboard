"""Tests for the localhost API foundation."""

import pytest
from fastapi.testclient import TestClient

import api.app as api_app


@pytest.fixture()
def client(monkeypatch):
    # Avoid touching the real database during startup lifespan.
    monkeypatch.setattr(api_app, "init_db", lambda: None)
    return TestClient(api_app.app)


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_requires_auth(client):
    # Root is protected; without a configured token it must fail closed (503).
    response = client.get("/")
    assert response.status_code == 503
