"""Tests for WA price-fetch rules: service + related part before estimating total."""

import asyncio

import whatsapp.agent as agent_mod
from services.harga_jasa_service import HargaJasaService
from services.stock_service import StockService
from whatsapp.agent import WhatsAppAgent, build_system_prompt, run_restricted_tool
from whatsapp.services import ContactService, SettingsService


def _seed(session):
    StockService(session).create_item(nama="Oli Mesin", kode="OLI", harga_modal=55000, harga_jual=80000, jumlah=60)
    StockService(session).create_item(nama="Tutup Radiator", kode="RD", harga_modal=50000, harga_jual=90000, jumlah=54)
    HargaJasaService(session).create_item(nama="Ganti Oli Mesin", keuntungan=150000)
    HargaJasaService(session).create_item(nama="Servis Radiator", keuntungan=150000)


def test_prompt_instructs_service_and_part_price(wa_session):
    prompt = build_system_prompt(SettingsService(wa_session).get())
    assert "get_part_price" in prompt
    assert 'get_part_price("oli mesin")' in prompt
    assert "check_stock" in prompt
    assert "satuan" in prompt and "total" in prompt


def test_prompt_does_not_hardcode_fixture_prices(wa_session):
    prompt = build_system_prompt(SettingsService(wa_session).get())
    for forbidden in ("150000", "150.000", "80000", "80.000", "230000", "230.000"):
        assert forbidden not in prompt, forbidden


def test_prompt_distinguishes_satuan_from_total_and_capacity(wa_session):
    prompt = build_system_prompt(SettingsService(wa_session).get())
    assert "kapasitas" in prompt
    assert "Jangan mengasumsikan" in prompt


def test_prompt_does_not_force_package_for_jasa_only(wa_session):
    prompt = build_system_prompt(SettingsService(wa_session).get())
    assert "lazim membutuhkan part" in prompt


def test_prompt_old_request_not_in_estimate(wa_session):
    prompt = build_system_prompt(SettingsService(wa_session).get())
    assert "permintaan lama yang belum disetujui tidak boleh ikut diestimasi" in prompt


def test_prompt_uppertank_rule_preserved(wa_session):
    prompt = build_system_prompt(SettingsService(wa_session).get())
    assert "Uppertank" in prompt and "Tutup Radiator" in prompt


def test_fixture_prices_via_tools(session, wa_session):
    _seed(session)
    contact = ContactService(wa_session).get_or_create("0812-1")
    jasa = run_restricted_tool("get_jasa_price", {"nama_jasa": "ganti oli"}, contact, wa_session, session)
    part = run_restricted_tool("get_part_price", {"nama_part": "oli mesin"}, contact, wa_session, session)
    assert "150.000" in jasa
    assert "80.000" in part


def test_part_price_unknown_is_stated_not_fabricated(session, wa_session):
    contact = ContactService(wa_session).get_or_create("0812-1")
    out = run_restricted_tool("get_part_price", {"nama_part": "oli mesin"}, contact, wa_session, session)
    assert "tidak diketahui" in out


def test_flow_ganti_oli_calls_both_tools(wa_session, session, monkeypatch):
    _seed(session)
    ContactService(wa_session).get_or_create("0812-1")
    wa_session.commit()
    calls = []
    orig = agent_mod.run_restricted_tool

    def wrapped(name, args, contact, wa_session_, main_session_):
        calls.append((name, args))
        return orig(name, args, contact, wa_session_, main_session_)

    monkeypatch.setattr(agent_mod, "run_restricted_tool", wrapped)

    class P:
        configured = True

        def __init__(self):
            self.n = 0

        async def chat(self, messages, tools=None):
            self.n += 1
            if self.n == 1:
                return {
                    "content": None,
                    "tool_calls": [
                        {"id": "t1", "type": "function", "function": {"name": "get_jasa_price", "arguments": '{"nama_jasa": "ganti oli"}'}},
                        {"id": "t2", "type": "function", "function": {"name": "get_part_price", "arguments": '{"nama_part": "oli mesin"}'}},
                    ],
                }
            return {"content": "Estimasi total sekitar Rp230.000.", "tool_calls": []}

    agent = WhatsAppAgent()
    agent._provider = P()
    reply = asyncio.run(agent.reply("0812-1", "Apakah bisa ganti oli?", wa_session, session))

    assert reply == "Estimasi total sekitar Rp230.000."
    assert ("get_jasa_price", {"nama_jasa": "ganti oli"}) in calls
    assert ("get_part_price", {"nama_part": "oli mesin"}) in calls


def test_usage_metadata_not_leaked_to_model(wa_session, session):
    ContactService(wa_session).get_or_create("0812-1")
    wa_session.commit()
    captured = []

    class P:
        configured = True

        def __init__(self):
            self.n = 0

        async def chat(self, messages, tools=None):
            captured.append(messages)
            self.n += 1
            if self.n == 1:
                return {
                    "content": None,
                    "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "lookup_customer", "arguments": "{}"}}],
                    "usage": {"provider": "deepseek", "model": "m", "total_tokens": 99},
                }
            return {"content": "oke", "tool_calls": [], "usage": {"provider": "deepseek", "model": "m", "total_tokens": 5}}

    agent = WhatsAppAgent()
    agent._provider = P()
    reply = asyncio.run(agent.reply("0812-1", "cek kendaraan saya", wa_session, session))

    assert reply == "oke"
    for messages in captured:
        for m in messages:
            assert "usage" not in m
