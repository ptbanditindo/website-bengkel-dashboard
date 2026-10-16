"""Tests for integration settings endpoints (secrets never leak; mocked providers)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import api.app as api_app
from config import settings as settings_store
from whatsapp.models import WhatsAppBase

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
def env(engine, monkeypatch, tmp_path):
    from database.session import get_db as real_get_db
    from whatsapp.db import get_whatsapp_db as real_wa_get_db

    monkeypatch.setattr(settings_store, "SETTINGS_PATH", tmp_path / "integration_settings.json")
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
    yield TestClient(api_app.app)
    api_app.app.dependency_overrides.pop(real_get_db, None)
    api_app.app.dependency_overrides.pop(real_wa_get_db, None)
    wa_eng.dispose()


def test_auth_required(env):
    assert env.get("/api/integrations/status").status_code == 401


def test_status_masks_secrets(env):
    settings_store.set("deepseek_api_key", "sk-abcdef1234567890")
    r = env.get("/api/integrations/status", headers=AUTH)
    body = r.json()
    assert "sk-abcdef1234567890" not in r.text
    assert body["providers"]["deepseek"]["masked"] != "sk-abcdef1234567890"


def test_empty_value_does_not_save(env):
    with pytest.raises(ValueError):
        settings_store.set("gemini_api_key", "")
    assert settings_store.get("gemini_api_key") is None


def test_telegram_save_invalid_does_not_replace(env, monkeypatch):
    settings_store.set("telegram_bot_token", "OLD")
    monkeypatch.setattr("api.integration_routes.testing_mod.test_telegram_token", lambda t: {"valid": False, "error": "bad"})
    r = env.post("/api/integrations/telegram/save", json={"token": "NEW"}, headers=AUTH)
    assert r.status_code == 400
    assert settings_store.get("telegram_bot_token") == "OLD"


def test_telegram_test_valid_mock(env, monkeypatch):
    monkeypatch.setattr("api.integration_routes.testing_mod.test_telegram_token", lambda t: {"valid": True, "username": "mybot"})
    r = env.post("/api/integrations/telegram/test", json={"token": "x"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["valid"] is True


def test_ai_test_mock(env, monkeypatch):
    monkeypatch.setattr("api.integration_routes.testing_mod.test_deepseek_key", lambda k: {"valid": True})
    monkeypatch.setattr("api.integration_routes.testing_mod.test_gemini_key", lambda k: {"valid": False, "error": "x"})
    assert env.post("/api/integrations/deepseek/test", json={"value": "k"}, headers=AUTH).json()["valid"] is True
    assert env.post("/api/integrations/gemini/test", json={"value": "k"}, headers=AUTH).json()["valid"] is False


def test_gateway_status_honest_unavailable(env, monkeypatch):
    import whatsapp.baileys_client as bc
    monkeypatch.setattr(bc, "status", lambda: {"status": "bridge_unavailable", "error": "conn"})
    r = env.get("/api/integrations/whatsapp/status", headers=AUTH)
    assert r.json()["status"] == "bridge_unavailable"


def test_qr_and_pairing_proxy_gateway(env, monkeypatch):
    import whatsapp.baileys_client as bc
    monkeypatch.setattr(bc, "start_qr", lambda: {"status": "connecting"})
    monkeypatch.setattr(bc, "request_pairing", lambda p: {"status": "awaiting_pairing", "pairingCode": "1234-5678"})
    assert env.post("/api/integrations/whatsapp/qr/start", headers=AUTH).json()["status"] == "connecting"
    r = env.post("/api/integrations/whatsapp/pairing/request", json={"phone": "62812"}, headers=AUTH)
    assert r.json()["pairingCode"] == "1234-5678"


def test_inbound_dedup_and_reply(env, monkeypatch):
    # fake agent reply
    class FakeAgent:
        async def reply(self, wa_number, text, wdb, main):
            return "balasan demo"
    import api.integration_routes as ir
    monkeypatch.setattr(ir, "WhatsAppAgent", lambda: FakeAgent())
    import whatsapp.baileys_client as bc
    monkeypatch.setattr(bc, "status", lambda: {"status": "disconnected"})
    payload = {"from": "0812-1", "message_id": "gw-1", "text": "halo"}
    hdr = {"Authorization": "Bearer " + settings_store.get_internal_token()}
    r1 = env.post("/api/integrations/whatsapp/inbound", json=payload, headers=hdr)
    r2 = env.post("/api/integrations/whatsapp/inbound", json=payload, headers=hdr)
    assert r1.json()["processed"] is True
    assert r2.json()["duplicate"] is True


def test_conversation_isolation_via_services(wa_session):
    # covered by test_whatsapp_core; sanity re-check via service layer (isolated DB)
    from whatsapp.services import ContactService
    s = wa_session
    a = ContactService(s).get_or_create("0812-1")
    b = ContactService(s).get_or_create("0812-2")
    ContactService(s).update_memory(a.id, nama="A")
    ContactService(s).update_memory(b.id, nama="B")
    s.commit()
    assert ContactService(s).get_or_create("0812-1").nama == "A"
    assert ContactService(s).get_or_create("0812-2").nama == "B"
