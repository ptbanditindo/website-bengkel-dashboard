"""Regression tests: WhatsApp CS new-customer registration flow (WA-CS-REGISTRATION-FLOW-FIX-01)."""

import asyncio

from whatsapp.agent import WhatsAppAgent, build_system_prompt, run_restricted_tool
from whatsapp.services import ContactService, QuestionService, SettingsService


def test_context_includes_recent_conversation(wa_session, session):
    c = ContactService(wa_session).get_or_create("0812-1")
    ContactService(wa_session).record_message(c.id, "customer", "Mau tanya, bisa service kaki kaki mobil?", "gw-1")
    ContactService(wa_session).record_message(c.id, "ai", "Bisa, apa keluhan dan data kendaraannya?", "gw-2")
    ContactService(wa_session).record_message(c.id, "customer", "Keletek kletek, Fortuner 2016 plat B 2940 HDJ", "gw-3")
    wa_session.commit()

    ctx = WhatsAppAgent()._context(c, session, wa_session=wa_session)

    assert "Mau tanya, bisa service kaki kaki mobil?" in ctx
    assert "Keletek kletek" in ctx
    assert "B 2940 HDJ" in ctx
    assert "Fortuner" in ctx
    assert "Riwayat percakapan terakhir" in ctx


def test_registration_flow_saves_memory_no_escalation(wa_session, session):
    c = ContactService(wa_session).get_or_create("0812-1")
    ContactService(wa_session).record_message(c.id, "customer", "Keletek kletek, untuk Fortuner tahun 2016 plat B 2940 HDJ.", "gw-1")
    ContactService(wa_session).record_message(c.id, "ai", "Boleh info nama pemilik dan detail bunyi?", "gw-2")
    wa_session.commit()

    class P:
        configured = True

        def __init__(self):
            self.n = 0

        async def chat(self, messages, tools=None):
            self.n += 1
            if self.n == 1:
                return {
                    "content": None,
                    "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "save_memory", "arguments": '{"nama": "Putra", "issue_summary": "bunyi kletek-kletek di depan, muncul saat belok"}'}}],
                }
            return {"content": "Baik Kak Putra, sudah saya catat.", "tool_calls": []}

    agent = WhatsAppAgent()
    agent._provider = P()
    reply = asyncio.run(agent.reply("0812-1", "Putra, muncul di depan, saat belok.", wa_session, session))

    assert reply == "Baik Kak Putra, sudah saya catat."
    assert "Maaf, saya belum bisa menjawab" not in reply
    c2 = ContactService(wa_session).get_or_create("0812-1")
    assert c2.nama == "Putra"


def test_prompt_says_registration_not_escalation(wa_session):
    prompt = build_system_prompt(SettingsService(wa_session).get())
    assert "Melengkapi data pendaftaran atau keluhan BUKAN alasan untuk eskalasi" in prompt
    assert "save_memory" in prompt


def test_save_memory_persists_vehicle_and_name(wa_session, session):
    c = ContactService(wa_session).get_or_create("0812-1")
    wa_session.commit()
    run_restricted_tool(
        "save_memory",
        {"nama": "Putra", "plat": "B 2940 HDJ", "jenis_mobil": "Fortuner", "tahun_mobil": 2016, "issue_summary": "bunyi kletek-kletek"},
        c, wa_session, session,
    )
    c2 = ContactService(wa_session).get(c.id)
    assert c2.nama == "Putra"
    assert c2.plat == "B 2940 HDJ"
    assert c2.jenis_mobil == "Fortuner"
    assert c2.tahun_mobil == 2016
    assert "kletek" in c2.issue_summary


def test_saved_vehicle_info_present_in_next_context(wa_session, session):
    c = ContactService(wa_session).get_or_create("0812-1")
    wa_session.commit()
    run_restricted_tool(
        "save_memory",
        {"plat": "B 2940 HDJ", "jenis_mobil": "Fortuner", "tahun_mobil": 2016, "issue_summary": "bunyi kletek-kletek"},
        c, wa_session, session,
    )
    c2 = ContactService(wa_session).get(c.id)
    ctx = WhatsAppAgent()._context(c2, session, wa_session=wa_session)
    assert "B 2940 HDJ" in ctx
    assert "Fortuner" in ctx
    assert "2016" in ctx
    assert "kletek" in ctx


def test_escalation_still_works_for_unanswerable(wa_session, session):
    c = ContactService(wa_session).get_or_create("0812-1")
    wa_session.commit()
    out = run_restricted_tool("escalate_to_owner", {"alasan": "harga part tidak tersedia"}, c, wa_session, session)
    assert out == "Pertanyaan diteruskan ke owner."
    assert QuestionService(wa_session).list()


def test_context_without_wa_session_backward_compatible(wa_session, session):
    c = ContactService(wa_session).get_or_create("0812-1")
    ContactService(wa_session).update_memory(c.id, nama="Putra", plat="B 2940 HDJ")
    wa_session.commit()
    ctx = WhatsAppAgent()._context(c, session)
    assert "Putra" in ctx
    assert "B 2940 HDJ" in ctx
    assert "Riwayat percakapan terakhir" not in ctx
