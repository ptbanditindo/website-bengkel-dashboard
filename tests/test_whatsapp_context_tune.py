"""Regression tests: conversation-context tuning (WA-CS-REGISTRATION-CONTEXT-TUNE-01)."""

import asyncio

from whatsapp.agent import WhatsAppAgent
from whatsapp.services import ContactService


def test_recent_messages_filters_by_contact(wa_session):
    c1 = ContactService(wa_session).get_or_create("0812-1")
    c2 = ContactService(wa_session).get_or_create("0812-2")
    ContactService(wa_session).record_message(c1.id, "customer", "pesan kontak 1", "gw-1")
    ContactService(wa_session).record_message(c2.id, "customer", "pesan kontak 2", "gw-2")
    wa_session.commit()

    msgs = ContactService(wa_session).recent_messages(c1.id)

    assert len(msgs) == 1
    assert msgs[0].body == "pesan kontak 1"
    assert all(m.contact_id == c1.id for m in msgs)


def test_recent_messages_chronological_order(wa_session):
    c = ContactService(wa_session).get_or_create("0812-1")
    ContactService(wa_session).record_message(c.id, "customer", "pertama", "gw-1")
    ContactService(wa_session).record_message(c.id, "customer", "kedua", "gw-2")
    ContactService(wa_session).record_message(c.id, "customer", "ketiga", "gw-3")
    wa_session.commit()

    msgs = ContactService(wa_session).recent_messages(c.id)

    assert [m.body for m in msgs] == ["pertama", "kedua", "ketiga"]


def test_recent_messages_limit_12(wa_session):
    c = ContactService(wa_session).get_or_create("0812-1")
    for i in range(15):
        ContactService(wa_session).record_message(c.id, "customer", "msg-%02d" % i, "gw-%d" % i)
    wa_session.commit()

    msgs = ContactService(wa_session).recent_messages(c.id)

    assert len(msgs) == 12
    assert msgs[0].body == "msg-03"
    assert msgs[-1].body == "msg-14"


def test_history_truncates_to_300_chars(wa_session, session):
    c = ContactService(wa_session).get_or_create("0812-1")
    long = "x" * 350
    ContactService(wa_session).record_message(c.id, "customer", long, "gw-1")
    wa_session.commit()

    ctx = WhatsAppAgent()._context(c, session, wa_session=wa_session)

    assert "x" * 300 in ctx
    assert "x" * 301 not in ctx


def test_current_message_not_duplicated_in_history(wa_session, session):
    c = ContactService(wa_session).get_or_create("0812-1")
    ContactService(wa_session).record_message(c.id, "customer", "Keluhan lama", "gw-1")
    ContactService(wa_session).record_message(c.id, "ai", "Baik, apa lanjutannya?", "gw-2")
    ContactService(wa_session).record_message(c.id, "customer", "Pesan sekarang", "gw-3")
    wa_session.commit()

    captured = {}

    class P:
        configured = True

        async def chat(self, messages, tools=None):
            captured["messages"] = messages
            return {"content": "oke", "tool_calls": []}

    agent = WhatsAppAgent()
    agent._provider = P()
    asyncio.run(agent.reply("0812-1", "Pesan sekarang", wa_session, session))

    user_content = captured["messages"][1]["content"]
    assert user_content.count("Pesan sekarang") == 1
    assert "Keluhan lama" in user_content
    assert "Baik, apa lanjutannya?" in user_content


def test_identical_text_messages_not_all_removed(wa_session, session):
    c = ContactService(wa_session).get_or_create("0812-1")
    ContactService(wa_session).record_message(c.id, "customer", "sama", "gw-1")
    ContactService(wa_session).record_message(c.id, "customer", "sama", "gw-2")
    wa_session.commit()

    ctx = WhatsAppAgent()._context(c, session, wa_session=wa_session, text="sama")

    assert ctx.count("sama") == 1


def test_context_without_wa_session_backward_compatible(wa_session, session):
    c = ContactService(wa_session).get_or_create("0812-1")
    ContactService(wa_session).update_memory(c.id, nama="Putra", plat="B 2940 HDJ")
    wa_session.commit()

    ctx = WhatsAppAgent()._context(c, session)

    assert "Putra" in ctx
    assert "B 2940 HDJ" in ctx
    assert "Riwayat percakapan terakhir" not in ctx
