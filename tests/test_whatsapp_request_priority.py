"""Regression tests: WhatsApp CS request priority & save safety (WA-PRIORITY)."""

import asyncio

from sqlalchemy.exc import OperationalError

from whatsapp.agent import (
    DEFAULT_SHOP_NAME,
    SAVE_FAILED_REPLY,
    SAVE_FAILED_TOOL,
    WA_SECURITY_RULES,
    WhatsAppAgent,
    build_system_prompt,
    run_restricted_tool,
)
from whatsapp.models import WaMessage
from whatsapp.services import (
    ArrivalService,
    ContactService,
    QuestionService,
    SettingsService,
)


def _raise_db(*args, **kwargs):
    raise OperationalError("INSERT", None, None)


class _ScriptProvider:
    configured = True

    def __init__(self, responses):
        self._responses = list(responses)
        self._i = 0

    async def chat(self, messages, tools=None):
        response = self._responses[self._i]
        self._i += 1
        return response


def _agent(script):
    agent = WhatsAppAgent()
    agent._provider = _ScriptProvider(script)
    return agent


def _tool_call(name, arguments):
    return {"id": "t1", "type": "function", "function": {"name": name, "arguments": arguments}}


# 1. Old radiator history must not be auto-merged into a new oil-change request.
def test_prompt_prioritizes_latest_request(wa_session):
    prompt = build_system_prompt(SettingsService(wa_session).get())
    assert "PRIORITAS" in prompt
    assert "RIWAYAT" in prompt
    assert "SEKALI" in prompt
    assert "Uppertank" in prompt and "Tutup Radiator" in prompt
    assert "escalate_to_owner" in prompt
    assert WA_SECURITY_RULES.strip() in prompt


def test_context_labels_issue_as_history(wa_session, session):
    c = ContactService(wa_session).get_or_create("0812-1")
    ContactService(wa_session).update_memory(c.id, issue_summary="servis radiator + uppertank")
    wa_session.commit()
    ctx = WhatsAppAgent()._context(c, session)
    assert "Riwayat kebutuhan sebelumnya" in ctx
    assert "servis radiator + uppertank" in ctx
    assert "Keluhan:" not in ctx


# 2 & 3. Latest message is the focus; old issue is labelled as history.
def test_reply_passes_latest_message_with_history_label(wa_session, session):
    c = ContactService(wa_session).get_or_create("0812-1")
    ContactService(wa_session).update_memory(c.id, issue_summary="servis radiator + uppertank")
    wa_session.commit()
    captured = {}

    class Capture:
        configured = True

        async def chat(self, messages, tools=None):
            captured["messages"] = messages
            return {"content": "Baik, ganti oli.", "tool_calls": []}

    agent = WhatsAppAgent()
    agent._provider = Capture()
    reply = asyncio.run(agent.reply("0812-1", "Apakah bisa ganti oli?", wa_session, session))
    assert reply == "Baik, ganti oli."
    user_msg = captured["messages"][-1]["content"]
    assert "PESAN PELANGGAN" in user_msg
    assert "Apakah bisa ganti oli?" in user_msg
    assert "Riwayat kebutuhan sebelumnya" in user_msg
    assert "servis radiator" in user_msg


# 4. Customer rejects old work -> only oil change is stored.
def test_flow_reject_old_work_stores_oil_only(wa_session, session):
    ContactService(wa_session).get_or_create("0812-1")
    wa_session.commit()
    agent = _agent([
        {"content": None, "tool_calls": [_tool_call("save_arrival_plan", '{"rencana_hari": "hari ini", "catatan": "ganti oli saja"}')]},
        {"content": "Baik, fokus ganti oli saja.", "tool_calls": []},
    ])
    reply = asyncio.run(agent.reply("0812-1", "ganti oli saja", wa_session, session))
    plans = ArrivalService(wa_session).list()
    assert reply == "Baik, fokus ganti oli saja."
    assert len(plans) == 1
    assert plans[0].catatan == "ganti oli saja"
    assert "radiator" not in plans[0].catatan.lower()


# 5. Customer approves both -> combined selected work.
def test_flow_approve_both_merges_work(wa_session, session):
    ContactService(wa_session).get_or_create("0812-1")
    wa_session.commit()
    agent = _agent([
        {"content": None, "tool_calls": [_tool_call("save_arrival_plan", '{"rencana_hari": "hari ini", "catatan": "ganti oli + servis radiator"}')]},
        {"content": "Baik, keduanya digabungkan.", "tool_calls": []},
    ])
    reply = asyncio.run(agent.reply("0812-1", "setuju keduanya", wa_session, session))
    plans = ArrivalService(wa_session).list()
    assert reply == "Baik, keduanya digabungkan."
    assert plans[0].catatan == "ganti oli + servis radiator"


# 6. No plan is created until the customer actually decides.
def test_no_plan_until_customer_decides(wa_session, session):
    ContactService(wa_session).get_or_create("0812-1")
    wa_session.commit()
    agent = _agent([{"content": "Apakah servis radiator ikut dikerjakan?", "tool_calls": []}])
    asyncio.run(agent.reply("0812-1", "ganti oli", wa_session, session))
    assert ArrivalService(wa_session).list() == []


# 7. Confirmation is asked only once -> enforced via prompt rules.
def test_prompt_asks_confirmation_once(wa_session):
    prompt = build_system_prompt(SettingsService(wa_session).get())
    assert "Jangan ulangi konfirmasi" in prompt
    assert "jangan ulangi jika pelanggan sudah menjawab" in prompt


# 8. History preserved, not treated as approval.
def test_history_preserved_not_approval(wa_session):
    c = ContactService(wa_session).get_or_create("0812-1")
    ContactService(wa_session).record_message(c.id, "customer", "servis radiator", "gw-1")
    ContactService(wa_session).record_message(c.id, "customer", "ganti oli", "gw-2")
    wa_session.commit()
    assert len(wa_session.query(WaMessage).all()) == 2
    assert ArrivalService(wa_session).list() == []


# 9. Save must never claim success when the commit fails.
def test_run_tool_save_plan_failure_sentinel(wa_session, session, monkeypatch):
    c = ContactService(wa_session).get_or_create("0812-1")
    wa_session.commit()
    monkeypatch.setattr(ArrivalService, "create_plan", _raise_db)
    out = run_restricted_tool("save_arrival_plan", {"catatan": "ganti oli saja"}, c, wa_session, session)
    assert out == SAVE_FAILED_TOOL


def test_run_tool_save_memory_failure_sentinel(wa_session, session, monkeypatch):
    c = ContactService(wa_session).get_or_create("0812-1")
    wa_session.commit()
    monkeypatch.setattr(ContactService, "update_memory", _raise_db)
    out = run_restricted_tool("save_memory", {"nama": "Budi"}, c, wa_session, session)
    assert out == SAVE_FAILED_TOOL


def test_reply_save_failure_returns_safe_reply(wa_session, session, monkeypatch):
    ContactService(wa_session).get_or_create("0812-1")
    wa_session.commit()
    monkeypatch.setattr(ArrivalService, "create_plan", _raise_db)
    agent = _agent([
        {"content": None, "tool_calls": [_tool_call("save_arrival_plan", '{"catatan": "ganti oli saja"}')]},
        {"content": "harus tidak tercapai", "tool_calls": []},
    ])
    reply = asyncio.run(agent.reply("0812-1", "ganti oli saja", wa_session, session))
    assert reply == SAVE_FAILED_REPLY
    assert ArrivalService(wa_session).list() == []


def test_escalate_save_failure_returns_safe_reply(wa_session, monkeypatch):
    c = ContactService(wa_session).get_or_create("0812-1")
    wa_session.commit()
    monkeypatch.setattr(QuestionService, "create", _raise_db)
    reply = WhatsAppAgent()._escalate(c, wa_session, "x")
    assert reply == SAVE_FAILED_REPLY


# Greeting uses dashboard name, with "Dava Radiator" fallback.
def test_greeting_uses_dashboard_name(wa_session, session):
    s = SettingsService(wa_session).get()
    s.nama_bengkel = "Bengkel Jaya"
    wa_session.commit()
    reply = asyncio.run(WhatsAppAgent().reply("0812-1", "halo", wa_session, session))
    assert "Bengkel Jaya" in reply
    assert "ada yang bisa kami bantu" in reply


def test_greeting_fallback_name(wa_session, session):
    s = SettingsService(wa_session).get()
    s.nama_bengkel = None
    wa_session.commit()
    reply = asyncio.run(WhatsAppAgent().reply("0812-1", "halo", wa_session, session))
    assert DEFAULT_SHOP_NAME in reply


# 10. Context isolation, message dedup, and 5s reply delay still hold.
def test_context_isolation_between_numbers(wa_session, session):
    c1 = ContactService(wa_session).get_or_create("0812-1")
    c2 = ContactService(wa_session).get_or_create("0812-2")
    ContactService(wa_session).update_memory(c1.id, nama="A", issue_summary="servis radiator")
    ContactService(wa_session).update_memory(c2.id, nama="B", issue_summary="ganti oli")
    wa_session.commit()
    ctx1 = WhatsAppAgent()._context(c1, session)
    ctx2 = WhatsAppAgent()._context(c2, session)
    assert "628121" in ctx1 and "628122" not in ctx1
    assert "628122" in ctx2 and "628121" not in ctx2


def test_message_dedup_by_gateway_id(wa_session):
    c = ContactService(wa_session).get_or_create("0812-1")
    created1, m1 = ContactService(wa_session).record_message(c.id, "customer", "halo", "gw-1")
    created2, m2 = ContactService(wa_session).record_message(c.id, "customer", "halo", "gw-1")
    wa_session.commit()
    assert created1 is True and created2 is False
    assert m1.id == m2.id


def test_reply_delay_is_5_seconds():
    from api.whatsapp_routes import WA_REPLY_DELAY_SECONDS, _reply_delay
    assert WA_REPLY_DELAY_SECONDS == 5
    assert _reply_delay() == 5
