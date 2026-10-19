"""Tests for WhatsApp CS API endpoints (auth + core flows, isolated DBs)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import api.app as api_app
from whatsapp.models import WhatsAppBase
from whatsapp.services import CandidateService, ContactService

TOKEN = "test-ui-token"
AUTH = {"Authorization": "Bearer " + TOKEN}


def _wa_engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(eng, "connect")
    def _fk(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    WhatsAppBase.metadata.create_all(eng)
    return eng


@pytest.fixture()
def wa_env(engine, monkeypatch):
    from database.session import get_db as real_get_db
    from whatsapp.db import get_whatsapp_db as real_wa_get_db

    main_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    wa_eng = _wa_engine()
    wa_factory = sessionmaker(bind=wa_eng, autoflush=False, expire_on_commit=False)

    def _get_db():
        db = main_factory()
        try:
            yield db
        finally:
            db.close()

    def _wa_get_db():
        db = wa_factory()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(api_app, "init_db", lambda: None)
    monkeypatch.setattr(api_app, "init_whatsapp_db", lambda: None)
    monkeypatch.setenv("UI_ACCESS_TOKEN", TOKEN)
    api_app.app.dependency_overrides[real_get_db] = _get_db
    api_app.app.dependency_overrides[real_wa_get_db] = _wa_get_db
    yield TestClient(api_app.app), wa_factory
    api_app.app.dependency_overrides.pop(real_get_db, None)
    api_app.app.dependency_overrides.pop(real_wa_get_db, None)
    wa_eng.dispose()


def test_auth_required(wa_env):
    client, _ = wa_env
    assert client.get("/api/wa/contacts").status_code == 401


def test_settings_get_and_update(wa_env):
    client, _ = wa_env
    r = client.get("/api/wa/settings", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["default_delay_seconds"] == 60
    r2 = client.put("/api/wa/settings", json={"nama_bengkel": "Bengkel Baru", "default_delay_seconds": 90}, headers=AUTH)
    assert r2.status_code == 200
    assert r2.json()["nama_bengkel"] == "Bengkel Baru"
    assert r2.json()["default_delay_seconds"] == 90


def test_gateway_status_honest(wa_env, monkeypatch):
    import whatsapp.baileys_client as bc
    client, _ = wa_env
    monkeypatch.setattr(bc, "status", lambda: {"status": "disconnected", "provider": "baileys", "authedNumber": "", "error": ""})
    r = client.get("/api/wa/gateway/status", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["connected"] is False


def test_gateway_status_connected(wa_env, monkeypatch):
    import whatsapp.baileys_client as bc
    client, _ = wa_env
    monkeypatch.setattr(bc, "status", lambda: {"status": "connected", "provider": "baileys", "authedNumber": "62812", "error": ""})
    r = client.get("/api/wa/gateway/status", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["connected"] is True


def test_contacts_empty(wa_env):
    client, _ = wa_env
    assert client.get("/api/wa/contacts", headers=AUTH).json() == []


def test_candidate_approve_via_api(wa_env):
    client, wa_factory = wa_env
    s = wa_factory()
    contact = ContactService(s).get_or_create("0812-1")
    cand = CandidateService(s, None).create(contact.id, nopol="B1234ABC", nama="Budi")
    s.commit()
    s.close()
    r = client.post("/api/wa/candidates/" + str(cand.id) + "/approve", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["status"] == "DISETUJUI"
    assert r.json()["linked_vehicle_id"] is not None


def test_owner_reply_sets_takeover_and_answers_question(wa_env):
    from whatsapp.services import QuestionService
    client, wa_factory = wa_env
    s = wa_factory()
    contact = ContactService(s).get_or_create("0812-9")
    QuestionService(s).create(contact.id, contact.wa_number, "pertanyaan AI", alasan="AI gagal")
    s.commit()
    s.close()
    r = client.post("/api/wa/contacts/" + str(contact.id) + "/reply", json={"text": "jawaban owner"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["owner_takeover"] is True
    s2 = wa_factory()
    assert ContactService(s2).is_taken_over(contact.id) is True
    qs = [q for q in QuestionService(s2).list() if q.contact_id == contact.id]
    assert len(qs) == 1
    assert qs[0].status == "DIJAWAB"
    assert qs[0].jawaban_owner == "jawaban owner"
    s2.close()
