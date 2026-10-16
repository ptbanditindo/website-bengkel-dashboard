"""Live integration test runner: 50 owner-assistant scenarios against real DeepSeek.

Run: python tests/live/owner_assistant_50_scenarios.py

Uses an ISOLATED temporary SQLite DB (never touches data/workshop.db) and the
real application code (provider, orchestrator, tool calling, service layer).
Prints/writes only sanitized output — never secrets.

Note: file intentionally NOT named test_*.py so pytest does not collect it.
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy.orm import sessionmaker

from ai.context import ConversationHistory
from ai.orchestrator import AIOrchestrator
from ai.providers import DeepSeekProvider
from ai.tools import TOOL_SCHEMAS
from database.models import ServiceRecord, Vehicle
from database.session import _build_engine, _ensure_sqlite_directory, run_migrations
from services.service_record_service import ServiceRecordService
from services.vehicle_service import VehicleService


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------
class LiveClient:
    """Wraps orchestrator + provider, tracking requests, tool calls, transcript."""

    def __init__(self, provider, session, user_id=1):
        self.orchestrator = AIOrchestrator(provider)
        self.session = session
        self.user_id = user_id
        self.history = ConversationHistory()
        self.api_requests = 0
        self.tool_calls_log = []
        self.transcript = []
        self._orig_chat = provider.chat
        provider.chat = self._counting_chat

    async def _counting_chat(self, messages, tools=None):
        self.api_requests += 1
        resp = await self._orig_chat(messages, tools=tools)
        for tc in resp.get("tool_calls") or []:
            self.tool_calls_log.append(
                {"name": tc["function"]["name"], "args": tc["function"]["arguments"]}
            )
        return resp

    async def send(self, text):
        result = await self.orchestrator.handle_message(
            text, self.session, self.history, user_id=self.user_id
        )
        self.transcript.append(
            {"user": text, "reply": result.reply[:400], "pending": result.pending_action is not None}
        )
        return result

    async def confirm(self, result):
        if result.pending_action is None:
            return "no pending action"
        text = await self.orchestrator.execute_pending(
            result.pending_action.token, self.session, user_id=self.user_id
        )
        self.transcript.append({"confirm": True, "reply": text[:400]})
        return text


def fresh_db():
    """Create an isolated temp SQLite DB with schema; returns (session, cleanup)."""
    tmpdir = tempfile.mkdtemp(prefix="bengkel_h2_")
    db_url = f"sqlite:///{(Path(tmpdir) / 'test.db').as_posix()}"
    _ensure_sqlite_directory(db_url)
    run_migrations(db_url)
    engine = _build_engine(db_url)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()

    def cleanup():
        session.close()
        engine.dispose()
        shutil.rmtree(tmpdir, ignore_errors=True)

    return session, cleanup


def db_counts(session):
    return {
        "vehicles": session.query(Vehicle).count(),
        "services": session.query(ServiceRecord).count(),
    }


def mask(value):
    return "SET" if value else "EMPTY"


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
async def smoke_test():
    provider = DeepSeekProvider()
    out = {"deepseek_configured": provider.configured, "model": provider.model}
    if not provider.configured:
        out["status"] = "SKIPPED"
        return out

    t0 = time.time()
    try:
        r = await provider.chat([{"role": "user", "content": "Jawab satu kata: halo"}])
        out["text_ok"] = bool(r["content"])
        out["text_time"] = round(time.time() - t0, 2)
    except Exception as e:
        out["text_ok"] = False
        out["text_error"] = f"{type(e).__name__}: {str(e)[:150]}"

    t0 = time.time()
    try:
        r = await provider.chat(
            [{"role": "user", "content": "Cari kendaraan plat B 1234 XYZ"}], tools=TOOL_SCHEMAS
        )
        out["toolcall_count"] = len(r["tool_calls"])
        out["toolcall_names"] = [tc["function"]["name"] for tc in r["tool_calls"]]
        out["toolcall_time"] = round(time.time() - t0, 2)
    except Exception as e:
        out["toolcall_count"] = 0
        out["toolcall_error"] = f"{type(e).__name__}: {str(e)[:150]}"

    return out


# ---------------------------------------------------------------------------
# Scenario registry
# ---------------------------------------------------------------------------
SCENARIOS = []


def register(sid, name, group, stype):
    def deco(fn):
        SCENARIOS.append({"id": sid, "name": name, "group": group, "type": stype, "fn": fn})
        return fn
    return deco


def seed_vehicle(session, **kw):
    defaults = dict(nama_client="Budi", nopol="B1234XYZ", jenis_mobil="Avanza", tahun_mobil=2021)
    defaults.update(kw)
    return VehicleService(session).create_vehicle(**defaults)


async def flow(client, messages, auto_confirm=True):
    last = None
    for m in messages:
        last = await client.send(m)
        if last.pending_action is not None and auto_confirm:
            await client.confirm(last)
    return last


def v(session, nopol="B1234XYZ"):
    return session.query(Vehicle).filter_by(nopol=nopol).all()


def s(session, vehicle_id):
    return session.query(ServiceRecord).filter_by(vehicle_id=vehicle_id).all()


# ===========================================================================
# Group A — data entry (H001–H010)
# ===========================================================================
@register("H001", "Daftar kendaraan lengkap", "A", "LIVE API")
async def h001(client, session):
    await flow(client, ["Daftarkan mobil Budi plat B 1234 XYZ, Avanza 2021, WA 081234567890, alamat Jakarta"])
    veh = v(session)
    ok = len(veh) == 1 and veh[0].nama_client == "Budi" and veh[0].jenis_mobil == "Avanza" and veh[0].tahun_mobil == 2021
    return {"status": "PASS" if ok else "FAIL", "evidence": f"vehicles={len(veh)} nama={veh[0].nama_client if veh else None}"}


@register("H002", "Kendaraan info tidak lengkap (klarifikasi)", "A", "LIVE API")
async def h002(client, session):
    r = await client.send("Daftarkan mobil plat B 1234 XYZ")
    asked = r.pending_action is None and any(k in r.reply.lower() for k in ["nama", "siapa", "client"])
    await flow(client, ["Nama pelanggannya Budi"], auto_confirm=True)
    veh = v(session)
    ok = len(veh) == 1 and veh[0].nama_client == "Budi"
    return {"status": "PASS" if (ok and asked) else "FAIL", "evidence": f"asked={asked} vehicles={len(veh)}"}


@register("H003", "Servis total saja (tanpa mengarang rincian)", "A", "LIVE API")
async def h003(client, session):
    seed_vehicle(session)
    await flow(client, ["Catat servis mobil B 1234 XYZ, ganti radiator total 600000"])
    veh = v(session)
    recs = s(session, veh[0].id) if veh else []
    ok = len(recs) == 1 and recs[0].total_servis == Decimal("600000.00") and recs[0].biaya_jasa is None and recs[0].total_part is None
    return {"status": "PASS" if ok else "FAIL", "evidence": f"services={len(recs)} total={recs[0].total_servis if recs else None}"}


@register("H004", "Servis beberapa part + harga", "A", "LIVE API")
async def h004(client, session):
    seed_vehicle(session)
    await flow(client, ["Catat servis mobil B 1234 XYZ: ganti radiator, part radiator 850000, air radiator 2 buah @50000"])
    veh = v(session)
    recs = s(session, veh[0].id) if veh else []
    parts = recs[0].parts if recs else []
    ok = len(recs) == 1 and len(parts) == 2 and recs[0].total_part == Decimal("950000.00")
    return {"status": "PASS" if ok else "FAIL", "evidence": f"parts={[(p.nama_part, str(p.harga_satuan)) for p in parts]}"}


@register("H005", "Jasa dan part terpisah", "A", "LIVE API")
async def h005(client, session):
    seed_vehicle(session)
    await flow(client, ["Servis B 1234 XYZ: jasa pasang radiator 150000, part radiator 850000"])
    veh = v(session)
    recs = s(session, veh[0].id) if veh else []
    ok = len(recs) == 1 and recs[0].biaya_jasa == Decimal("150000.00") and recs[0].total_part == Decimal("850000.00")
    return {"status": "PASS" if ok else "FAIL", "evidence": f"jasa={recs[0].biaya_jasa if recs else None} part={recs[0].total_part if recs else None}"}


@register("H006", "Servis untuk kendaraan terdaftar (tanpa duplikat)", "A", "LIVE API")
async def h006(client, session):
    seed_vehicle(session)
    await flow(client, ["Servis mobil B 1234 XYZ, ganti oli 50000"])
    veh = v(session)
    recs = s(session, veh[0].id)
    ok = len(veh) == 1 and len(recs) == 1
    return {"status": "PASS" if ok else "FAIL", "evidence": f"vehicles={len(veh)} services={len(recs)}"}


@register("H007", "Beberapa pekerjaan satu kunjungan", "A", "LIVE API")
async def h007(client, session):
    seed_vehicle(session)
    await flow(client, ["Servis B 1234 XYZ: ganti oli dan pasang radiator, total 200000"])
    veh = v(session)
    recs = s(session, veh[0].id) if veh else []
    jobs = recs[0].jobs if recs else []
    ok = len(recs) == 1 and len(jobs) >= 2
    return {"status": "PASS" if ok else "FAIL", "evidence": f"jobs={[j.deskripsi for j in jobs]}"}


@register("H008", "Tanggal servis eksplisit", "A", "LIVE API")
async def h008(client, session):
    seed_vehicle(session)
    await flow(client, ["Servis B 1234 XYZ tanggal 2026-10-01, ganti oli 50000"])
    veh = v(session)
    recs = s(session, veh[0].id) if veh else []
    ok = len(recs) == 1 and recs[0].waktu_service.date() == date(2026, 10, 1)
    return {"status": "PASS" if ok else "FAIL", "evidence": f"date={recs[0].waktu_service if recs else None}"}


@register("H009", "Garansi tersedia (tidak dikarang)", "A", "LIVE API")
async def h009(client, session):
    seed_vehicle(session)
    await flow(client, ["Servis B 1234 XYZ, ganti radiator, garansi sampai 2027-01-14"])
    veh = v(session)
    recs = s(session, veh[0].id) if veh else []
    ok = len(recs) == 1 and recs[0].garansi_sampai == date(2027, 1, 14)
    return {"status": "PASS" if ok else "FAIL", "evidence": f"garansi={recs[0].garansi_sampai if recs else None}"}


@register("H010", "Daftar kendaraan + servis (gabungan)", "A", "LIVE API")
async def h010(client, session):
    await flow(client, ["Daftarkan mobil Budi plat B 1234 XYZ, Avanza 2021, dan catat servis ganti radiator total 600000"])
    veh = v(session)
    recs = s(session, veh[0].id) if veh else []
    ok = len(veh) == 1 and len(recs) == 1
    return {"status": "PASS" if ok else "FAIL", "evidence": f"vehicles={len(veh)} services={len(recs)}"}


# ===========================================================================
# Group B — banyak data berturut-turut (H011–H018)
# ===========================================================================
@register("H011", "Daftar 3 kendaraan dalam satu sesi", "B", "LIVE API")
async def h011(client, session):
    await flow(client, [
        "Daftarkan Budi plat B 1234 XYZ Avanza 2021",
        "Daftarkan Andi plat B 5678 ABC Innova 2020",
        "Daftarkan Siti plat D 1111 AA Avanza 2022",
    ])
    total = session.query(Vehicle).count()
    return {"status": "PASS" if total == 3 else "FAIL", "evidence": f"vehicles={total}"}


@register("H012", "Servis kendaraan 1 lalu kendaraan 2 (tidak campur)", "B", "LIVE API")
async def h012(client, session):
    seed_vehicle(session, nama_client="Budi", nopol="B1234XYZ")
    seed_vehicle(session, nama_client="Andi", nopol="B5678ABC")
    await flow(client, ["Servis B 1234 XYZ ganti oli 50000", "Servis B 5678 ABC ganti aki 800000"])
    v1 = v(session, "B1234XYZ")
    v2 = v(session, "B5678ABC")
    ok = len(s(session, v1[0].id)) == 1 and len(s(session, v2[0].id)) == 1
    return {"status": "PASS" if ok else "FAIL", "evidence": f"s1={len(s(session, v1[0].id))} s2={len(s(session, v2[0].id))}"}


@register("H013", "Info pelanggan dulu, lalu plat di pesan berikut", "B", "LIVE API")
async def h013(client, session):
    await client.send("Pelanggan baru namanya Budi, WA 081234567890")
    await flow(client, ["Plat B 1234 XYZ, Avanza 2021"], auto_confirm=True)
    veh = v(session)
    ok = len(veh) == 1 and veh[0].nama_client == "Budi"
    return {"status": "PASS" if ok else "FAIL", "evidence": f"vehicles={len(veh)} nama={veh[0].nama_client if veh else None}"}


@register("H014", "Part ditambahkan bertahap", "B", "LIVE API")
async def h014(client, session):
    seed_vehicle(session)
    await client.send("Servis B 1234 XYZ ganti radiator")
    await flow(client, ["Part radiator 850000, tambah air radiator 2 buah @50000"], auto_confirm=True)
    veh = v(session)
    recs = s(session, veh[0].id) if veh else []
    parts = recs[-1].parts if recs else []
    ok = len(recs) >= 1 and any(p.nama_part == "Radiator" for p in parts)
    return {"status": "PASS" if ok else "FAIL", "evidence": f"services={len(recs)} parts={[(p.nama_part, str(p.harga_satuan)) for p in parts]}"}


@register("H015", "Koreksi harga sebelum konfirmasi", "B", "LIVE API")
async def h015(client, session):
    seed_vehicle(session)
    await client.send("Servis B 1234 XYZ ganti radiator 600000")
    last = await client.send("harganya jadi 550000")
    if last.pending_action is not None:
        await client.confirm(last)
    veh = v(session)
    recs = s(session, veh[0].id) if veh else []
    total = recs[-1].total_servis if recs else None
    ok = len(recs) >= 1 and total == Decimal("550000.00")
    return {"status": "PASS" if ok else "FAIL", "evidence": f"total={total}"}


@register("H016", "Lengkapi setelah klarifikasi (lanjut operasi sama)", "B", "LIVE API")
async def h016(client, session):
    await client.send("Catat servis mobil")
    await flow(client, ["B 1234 XYZ, Budi, ganti oli 50000"], auto_confirm=True)
    veh = v(session)
    recs = s(session, veh[0].id) if veh else []
    ok = len(veh) == 1 and len(recs) == 1
    return {"status": "PASS" if ok else "FAIL", "evidence": f"vehicles={len(veh)} services={len(recs)}"}


@register("H017", "Dua servis untuk kendaraan sama (record terpisah)", "B", "LIVE API")
async def h017(client, session):
    seed_vehicle(session)
    await flow(client, ["Servis B 1234 XYZ ganti oli 50000", "Servis B 1234 XYZ ganti radiator 600000"])
    veh = v(session)
    recs = s(session, veh[0].id)
    return {"status": "PASS" if len(recs) == 2 else "FAIL", "evidence": f"services={len(recs)}"}


@register("H018", "Beberapa instruksi dalam satu percakapan", "B", "LIVE API")
async def h018(client, session):
    await flow(client, ["Daftarkan Andi plat B 5678 ABC Innova 2020, dan daftarkan Siti plat D 1111 AA Avanza 2022"])
    total = session.query(Vehicle).count()
    return {"status": "PASS" if total == 2 else "FAIL", "evidence": f"vehicles={total}"}


# ===========================================================================
# Group C — query data tersimpan (H019–H028)
# ===========================================================================
@register("H019", "Cari kendaraan berdasarkan plat", "C", "LIVE API")
async def h019(client, session):
    seed_vehicle(session)
    r = await client.send("Cari kendaraan B 1234 XYZ")
    ok = "budi" in r.reply.lower() and "b1234xyz" in r.reply.lower()
    return {"status": "PASS" if ok else "FAIL", "evidence": r.reply[:200]}


@register("H020", "Cari kendaraan berdasarkan nama pelanggan", "C", "LIVE API")
async def h020(client, session):
    seed_vehicle(session)
    r = await client.send("Cari kendaraan milik Budi")
    ok = "b1234xyz" in r.reply.lower()
    return {"status": "PASS" if ok else "FAIL", "evidence": r.reply[:200]}


@register("H021", "Semua kendaraan satu pelanggan", "C", "LIVE API")
async def h021(client, session):
    seed_vehicle(session, nama_client="Budi", nopol="B1234XYZ")
    seed_vehicle(session, nama_client="Budi", nopol="B5678ABC")
    r = await client.send("Budi punya kendaraan apa saja?")
    ok = "b1234xyz" in r.reply.lower() and "b5678abc" in r.reply.lower()
    return {"status": "PASS" if ok else "FAIL", "evidence": r.reply[:200]}


@register("H022", "Riwayat servis kendaraan", "C", "LIVE API")
async def h022(client, session):
    veh = seed_vehicle(session)
    ServiceRecordService(session).add_service_record(veh.id, jobs=[{"deskripsi": "ganti oli", "jumlah": 1, "harga": 50000}])
    r = await client.send("Riwayat servis B 1234 XYZ")
    ok = "ganti oli" in r.reply.lower()
    return {"status": "PASS" if ok else "FAIL", "evidence": r.reply[:200]}


@register("H023", "Servis terbaru", "C", "LIVE API")
async def h023(client, session):
    veh = seed_vehicle(session)
    ServiceRecordService(session).add_service_record(veh.id, jobs=[{"deskripsi": "ganti oli", "jumlah": 1, "harga": 50000}])
    ServiceRecordService(session).add_service_record(veh.id, jobs=[{"deskripsi": "ganti radiator", "jumlah": 1, "harga": 600000}])
    r = await client.send("Servis terakhir B 1234 XYZ apa?")
    ok = "radiator" in r.reply.lower()
    return {"status": "PASS" if ok else "FAIL", "evidence": r.reply[:200]}


@register("H024", "Cari by jenis + tahun", "C", "LIVE API")
async def h024(client, session):
    seed_vehicle(session, jenis_mobil="Avanza", tahun_mobil=2021)
    r = await client.send("Cari kendaraan Avanza tahun 2021")
    ok = "b1234xyz" in r.reply.lower()
    return {"status": "PASS" if ok else "FAIL", "evidence": r.reply[:200]}


@register("H025", "Cari servis by pekerjaan", "C", "LIVE API")
async def h025(client, session):
    veh = seed_vehicle(session)
    ServiceRecordService(session).add_service_record(veh.id, jobs=[{"deskripsi": "ganti radiator", "jumlah": 1, "harga": 600000}])
    r = await client.send("Servis ganti radiator ada di kendaraan mana?")
    ok = "b1234xyz" in r.reply.lower()
    return {"status": "PASS" if ok else "FAIL", "evidence": r.reply[:200]}


@register("H026", "Part + harga pernah dipasang", "C", "LIVE API")
async def h026(client, session):
    veh = seed_vehicle(session)
    ServiceRecordService(session).add_service_record(veh.id, parts=[{"nama_part": "Radiator", "jumlah": 1, "harga_satuan": 850000}])
    r = await client.send("Part apa yang pernah dipasang di B 1234 XYZ beserta harganya?")
    ok = "radiator" in r.reply.lower()
    return {"status": "PASS" if ok else "FAIL", "evidence": r.reply[:200]}


@register("H027", "Status garansi", "C", "LIVE API")
async def h027(client, session):
    veh = seed_vehicle(session)
    ServiceRecordService(session).add_service_record(veh.id, garansi_sampai=date(2027, 1, 14), jobs=[{"deskripsi": "ganti radiator", "jumlah": 1, "harga": 600000}])
    r = await client.send("Garansi B 1234 XYZ sampai kapan?")
    ok = "2027" in r.reply or "14/01/2027" in r.reply
    return {"status": "PASS" if ok else "FAIL", "evidence": r.reply[:200]}


@register("H028", "Data tidak ditemukan (tidak mengarang)", "C", "LIVE API")
async def h028(client, session):
    r = await client.send("Cari kendaraan plat ZZ 9999 ZZ")
    ok = ("tidak ditemukan" in r.reply.lower()) or ("tidak ada" in r.reply.lower())
    return {"status": "PASS" if ok else "FAIL", "evidence": r.reply[:200]}


# ===========================================================================
# Group D — laporan & analisis operasional (H029–H035) [deterministik + AI]
# ===========================================================================
def _count_vehicles(session):
    return session.query(Vehicle).count()


def _sum_totals(session):
    return sum((r.total_servis or Decimal("0") for r in session.query(ServiceRecord).all()), Decimal("0"))


@register("H029", "Hitung jumlah kendaraan unik", "D", "deterministic + LIVE")
async def h029(client, session):
    seed_vehicle(session, nama_client="Budi", nopol="B1234XYZ")
    seed_vehicle(session, nama_client="Andi", nopol="B5678ABC")
    seed_vehicle(session, nama_client="Siti", nopol="D1111AA")
    expected = _count_vehicles(session)
    r = await client.send("Berapa jumlah kendaraan yang terdaftar?")
    ok = str(expected) in r.reply
    return {"status": "PASS" if ok else "FAIL", "evidence": f"expected={expected} | {r.reply[:200]}"}


@register("H030", "Hitung servis dalam rentang tanggal", "D", "deterministic + LIVE")
async def h030(client, session):
    veh = seed_vehicle(session)
    ServiceRecordService(session).add_service_record(veh.id, waktu_service=datetime(2026, 10, 1), jobs=[{"deskripsi": "ganti oli", "jumlah": 1, "harga": 50000}])
    ServiceRecordService(session).add_service_record(veh.id, waktu_service=datetime(2026, 10, 5), jobs=[{"deskripsi": "ganti radiator", "jumlah": 1, "harga": 600000}])
    expected = session.query(ServiceRecord).filter(ServiceRecord.waktu_service >= datetime(2026, 10, 1), ServiceRecord.waktu_service <= datetime(2026, 10, 31)).count()
    r = await client.send("Berapa jumlah servis selama Oktober 2026?")
    ok = str(expected) in r.reply
    return {"status": "PASS" if ok else "FAIL", "evidence": f"expected={expected} | {r.reply[:200]}"}


@register("H031", "Total nilai servis", "D", "deterministic + LIVE")
async def h031(client, session):
    veh = seed_vehicle(session)
    ServiceRecordService(session).add_service_record(veh.id, jobs=[{"deskripsi": "ganti oli", "jumlah": 1, "harga": 50000}])
    ServiceRecordService(session).add_service_record(veh.id, jobs=[{"deskripsi": "ganti radiator", "jumlah": 1, "harga": 600000}])
    expected = _sum_totals(session)
    r = await client.send("Berapa total nilai servis yang tercatat?")
    ok = "650000" in r.reply or "650.000" in r.reply
    return {"status": "PASS" if ok else "FAIL", "evidence": f"expected={expected} | {r.reply[:200]}"}


@register("H032", "Pelanggan paling sering servis", "D", "deterministic + LIVE")
async def h032(client, session):
    v1 = seed_vehicle(session, nama_client="Budi", nopol="B1234XYZ")
    v2 = seed_vehicle(session, nama_client="Andi", nopol="B5678ABC")
    ServiceRecordService(session).add_service_record(v1.id, jobs=[{"deskripsi": "a", "jumlah": 1, "harga": 10000}])
    ServiceRecordService(session).add_service_record(v1.id, jobs=[{"deskripsi": "b", "jumlah": 1, "harga": 10000}])
    ServiceRecordService(session).add_service_record(v2.id, jobs=[{"deskripsi": "c", "jumlah": 1, "harga": 10000}])
    r = await client.send("Pelanggan mana yang paling sering servis?")
    ok = "budi" in r.reply.lower()
    return {"status": "PASS" if ok else "FAIL", "evidence": r.reply[:200]}


@register("H033", "Pekerjaan paling sering", "D", "deterministic + LIVE")
async def h033(client, session):
    veh = seed_vehicle(session)
    ServiceRecordService(session).add_service_record(veh.id, jobs=[{"deskripsi": "ganti oli", "jumlah": 1, "harga": 50000}])
    ServiceRecordService(session).add_service_record(veh.id, jobs=[{"deskripsi": "ganti oli", "jumlah": 1, "harga": 50000}])
    ServiceRecordService(session).add_service_record(veh.id, jobs=[{"deskripsi": "ganti radiator", "jumlah": 1, "harga": 600000}])
    r = await client.send("Pekerjaan servis apa yang paling sering dilakukan?")
    ok = "ganti oli" in r.reply.lower()
    return {"status": "PASS" if ok else "FAIL", "evidence": r.reply[:200]}


@register("H034", "Kendaraan masih dalam garansi", "D", "deterministic + LIVE")
async def h034(client, session):
    veh = seed_vehicle(session)
    ServiceRecordService(session).add_service_record(veh.id, garansi_sampai=date(2027, 1, 14), jobs=[{"deskripsi": "ganti radiator", "jumlah": 1, "harga": 600000}])
    r = await client.send("Kendaraan mana yang masih dalam masa garansi?")
    ok = "b1234xyz" in r.reply.lower()
    return {"status": "PASS" if ok else "FAIL", "evidence": r.reply[:200]}


@register("H035", "Ringkasan kegiatan servis", "D", "deterministic + LIVE")
async def h035(client, session):
    veh = seed_vehicle(session)
    ServiceRecordService(session).add_service_record(veh.id, jobs=[{"deskripsi": "ganti oli", "jumlah": 1, "harga": 50000}])
    ServiceRecordService(session).add_service_record(veh.id, total_servis="600000")
    r = await client.send("Ringkas kegiatan servis bengkel")
    ok = ("2" in r.reply) or ("dua" in r.reply.lower())
    return {"status": "PASS" if ok else "FAIL", "evidence": r.reply[:200]}


# ===========================================================================
# Group E — koreksi, konfirmasi, pembatalan (H036–H042)
# ===========================================================================
@register("H036", "Batal formulir registrasi (tidak jadi)", "E", "deterministic")
async def h036(client, session):
    from bot.handlers import CANCEL_REGEX
    ok = CANCEL_REGEX.match("tidak jadi") is not None
    return {"status": "PASS" if ok else "FAIL", "evidence": "CANCEL_REGEX menangkap 'tidak jadi' (alur penuh via unit test)"}


@register("H037", "Tolak konfirmasi (tanpa mutasi)", "E", "LIVE API")
async def h037(client, session):
    seed_vehicle(session)
    last = await client.send("Servis B 1234 XYZ ganti oli 50000")
    veh = v(session)
    recs = s(session, veh[0].id)
    ok = last.pending_action is not None and len(recs) == 0
    return {"status": "PASS" if ok else "FAIL", "evidence": f"pending={last.pending_action is not None} services={len(recs)}"}


@register("H038", "Setujui konfirmasi (mutasi dijalankan)", "E", "LIVE API")
async def h038(client, session):
    seed_vehicle(session)
    last = await client.send("Servis B 1234 XYZ ganti oli 50000")
    if last.pending_action is not None:
        await client.confirm(last)
    veh = v(session)
    recs = s(session, veh[0].id)
    ok = len(recs) == 1
    return {"status": "PASS" if ok else "FAIL", "evidence": f"services={len(recs)}"}


@register("H039", "Koreksi sebelum konfirmasi (nilai terbaru)", "E", "LIVE API")
async def h039(client, session):
    seed_vehicle(session)
    await client.send("Servis B 1234 XYZ ganti radiator 600000")
    last = await client.send("ubah totalnya jadi 550000")
    if last.pending_action is not None:
        await client.confirm(last)
    veh = v(session)
    recs = s(session, veh[0].id) if veh else []
    total = recs[-1].total_servis if recs else None
    ok = len(recs) >= 1 and total == Decimal("550000.00")
    return {"status": "PASS" if ok else "FAIL", "evidence": f"total={total}"}


@register("H040", "Koreksi data tersimpan (update)", "E", "LIVE API")
async def h040(client, session):
    seed_vehicle(session)
    await flow(client, ["Ubah nama pelanggan B 1234 XYZ jadi Budi Santoso"], auto_confirm=True)
    veh = v(session)
    ok = len(veh) == 1 and veh[0].nama_client == "Budi Santoso"
    return {"status": "PASS" if ok else "FAIL", "evidence": f"nama={veh[0].nama_client if veh else None}"}


@register("H041", "Batal setelah sebagian info (pending dibersihkan)", "E", "LIVE API")
async def h041(client, session):
    last = await client.send("Daftarkan mobil Budi plat B 1234 XYZ Avanza 2021")
    if last.pending_action is not None:
        client.orchestrator.pending_store.pop(last.pending_action.token, client.user_id)
    veh = v(session)
    return {"status": "PASS" if len(veh) == 0 else "FAIL", "evidence": f"vehicles={len(veh)}"}


@register("H042", "Hapus kendaraan ber-riwayat (ditolak service)", "E", "deterministic")
async def h042(client, session):
    from services.exceptions import ConflictError
    veh = seed_vehicle(session)
    ServiceRecordService(session).add_service_record(veh.id, jobs=[{"deskripsi": "ganti oli", "jumlah": 1, "harga": 50000}])
    rejected = False
    try:
        VehicleService(session).delete_vehicle(veh.id)
    except ConflictError:
        rejected = True
    ok = rejected and session.query(Vehicle).count() == 1
    return {"status": "PASS" if ok else "FAIL", "evidence": f"rejected={rejected} vehicles={session.query(Vehicle).count()}"}


# ===========================================================================
# Group F — konteks, akurasi, error handling (H043–H050)
# ===========================================================================
@register("H043", "Tanya 'tadi saya masukkan apa?'", "F", "LIVE API")
async def h043(client, session):
    await flow(client, ["Daftarkan Budi plat B 1234 XYZ Avanza 2021"], auto_confirm=True)
    r = await client.send("Tadi saya memasukkan data apa saja?")
    ok = "budi" in r.reply.lower() or "b1234xyz" in r.reply.lower()
    return {"status": "PASS" if ok else "FAIL", "evidence": r.reply[:200]}


@register("H044", "Pindah topik lalu kembali (tidak campur)", "F", "LIVE API")
async def h044(client, session):
    seed_vehicle(session)
    await client.send("Servis B 1234 XYZ ganti oli 50000")
    await client.send("Cari kendaraan milik Budi")
    await flow(client, ["Lanjut catat servis ganti oli 50000"], auto_confirm=True)
    veh = v(session)
    recs = s(session, veh[0].id)
    return {"status": "PASS" if len(recs) >= 1 else "FAIL", "evidence": f"services={len(recs)}"}


@register("H045", "Dua kendaraan disebut (minta klarifikasi)", "F", "LIVE API")
async def h045(client, session):
    seed_vehicle(session, nama_client="Budi", nopol="B1234XYZ")
    seed_vehicle(session, nama_client="Andi", nopol="B5678ABC")
    r = await client.send("Catat servis untuk mobil Budi dan Andi ganti oli")
    clarified = r.pending_action is None and any(k in r.reply.lower() for k in ["mana", "yang", "plat", "pilih"])
    return {"status": "PASS" if clarified else "FAIL", "evidence": r.reply[:200]}


@register("H046", "Info bertentangan (minta klarifikasi)", "F", "LIVE API")
async def h046(client, session):
    seed_vehicle(session)
    r = await client.send("Servis B 1234 XYZ ganti radiator total 600000 atau 700000?")
    return {"status": "PASS" if r.pending_action is None else "FAIL", "evidence": r.reply[:200]}


@register("H047", "Hitung angka tak bisa ditentukan (jelaskan data hilang)", "F", "LIVE API")
async def h047(client, session):
    veh = seed_vehicle(session)
    ServiceRecordService(session).add_service_record(veh.id, jobs=[{"deskripsi": "ganti oli", "jumlah": 1}])
    r = await client.send("Berapa total biaya servis B 1234 XYZ?")
    ok = ("belum" in r.reply.lower()) or ("tidak diketahui" in r.reply.lower())
    return {"status": "PASS" if ok else "FAIL", "evidence": r.reply[:200]}


@register("H048", "Error provider (kontrol, bukan live)", "F", "deterministic")
async def h048(client, session):
    from ai.errors import AIProviderError
    from ai.orchestrator import AIOrchestrator

    class Failing:
        async def chat(self, messages, tools=None):
            raise AIProviderError("simulasi timeout")

    orch = AIOrchestrator(Failing())
    r = await orch.handle_message("halo", session, ConversationHistory(), user_id=1)
    return {"status": "PASS" if "❌" in r.reply else "FAIL", "evidence": r.reply[:150]}


@register("H049", "Pesan sama berulang (tanpa duplikasi liar)", "F", "LIVE API")
async def h049(client, session):
    seed_vehicle(session)
    await flow(client, ["Servis B 1234 XYZ ganti oli 50000", "Servis B 1234 XYZ ganti oli 50000"])
    veh = v(session)
    recs = s(session, veh[0].id)
    return {"status": "PASS" if len(recs) <= 2 else "FAIL", "evidence": f"services={len(recs)}"}


@register("H050", "Isolasi pending action antar sesi", "F", "deterministic")
async def h050(client, session):
    from ai.tools import PendingStore
    store = PendingStore()
    a = store.add(1, [{"tool": "create_vehicle", "arguments": {"nopol": "B1234XYZ"}}], "summary A")
    ok = store.get(a.token, 2) is None and store.get(a.token, 1) is not None
    return {"status": "PASS" if ok else "FAIL", "evidence": "user 2 tidak dapat mengakses pending user 1"}


# ---------------------------------------------------------------------------
# Main runner + report generation
# ---------------------------------------------------------------------------
# Representative 20-scenario subset (reduced from 50 per request).
SELECTED = [
    "H001", "H003", "H006", "H010", "H011", "H017",
    "H019", "H022", "H027", "H028", "H029", "H031",
    "H037", "H038", "H042", "H043", "H045", "H046", "H048", "H050",
]


async def run_all(provider):
    results = []
    for sc in SCENARIOS:
        if sc["id"] not in SELECTED:
            continue
        session, cleanup = fresh_db()
        client = LiveClient(provider, session)
        res = {"id": sc["id"], "name": sc["name"], "group": sc["group"], "type": sc["type"], "status": "SKIPPED"}
        try:
            out = await sc["fn"](client, session)
            res.update(out)
        except Exception as e:
            res["status"] = "FAIL"
            res["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        finally:
            res["api_requests"] = client.api_requests
            res["tool_calls"] = client.tool_calls_log
            res["transcript"] = client.transcript
            cleanup()
        results.append(res)
        print(f"{res['id']} {res['status']:7s} {res['name'][:55]}")
    return results


def summary_counts(results):
    c = {"PASS": 0, "FAIL": 0, "SKIPPED": 0}
    for r in results:
        c[r["status"]] = c.get(r["status"], 0) + 1
    return c


def write_reports(smoke, results, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "stage_h2_50_owner_assistant_tests.json", "w", encoding="utf-8") as f:
        json.dump(
            {"smoke": smoke, "results": results, "summary": summary_counts(results)},
            f, ensure_ascii=False, indent=2,
        )

    lines = [
        "# Laporan Live Test 50 Skenario — AI Asisten Pemilik Bengkel",
        "",
        f"- Provider: DeepSeek `{smoke.get('model', '?')}` (config: {mask(os.getenv('DEEPSEEK_API_KEY', ''))})",
        f"- Gemini: {mask(os.getenv('GEMINI_API_KEY', ''))} (SKIPPED jika EMPTY)",
        f"- Smoke: text_ok={smoke.get('text_ok')} toolcall={smoke.get('toolcall_count')} names={smoke.get('toolcall_names')}",
        "",
        "## Ringkasan",
        "",
    ]
    c = summary_counts(results)
    lines.append(f"- PASS: {c['PASS']} | FAIL: {c['FAIL']} | SKIPPED: {c['SKIPPED']}")
    lines.append(f"- Total API request: {sum(r.get('api_requests', 0) for r in results)}")
    lines.append("")
    lines.append("## Hasil per skenario")
    lines.append("")
    lines.append("| ID | Kel | Status | Nama | Bukti |")
    lines.append("|----|-----|--------|------|-------|")
    for r in results:
        ev = (r.get("evidence") or r.get("error") or "")[:70].replace("|", "/")
        lines.append(f"| {r['id']} | {r['group']} | {r['status']} | {r['name']} | {ev} |")
    lines.append("")
    lines.append("## Transcript & tool call (tersanitasi)")
    lines.append("")
    for r in results:
        lines.append(f"### {r['id']} — {r['name']} ({r['status']})")
        lines.append(f"Type: {r['type']} | API requests: {r.get('api_requests', 0)}")
        if r.get("tool_calls"):
            lines.append("Tool calls:")
            for tc in r["tool_calls"]:
                lines.append(f"- `{tc['name']}` args={tc['args'][:120]}")
        if r.get("transcript"):
            lines.append("Transcript:")
            for t in r["transcript"]:
                lines.append(f"- user: {t['user'][:120]}")
                lines.append(f"  reply: {t['reply'][:200]}")
        lines.append("")
    (out_dir / "stage_h2_50_owner_assistant_tests.md").write_text("\n".join(lines), encoding="utf-8")


async def main():
    provider = DeepSeekProvider()
    out_dir = Path(__file__).resolve().parent.parent.parent / "reports"
    print("=== SMOKE ===")
    smoke = await smoke_test()
    print(json.dumps(smoke, ensure_ascii=False, default=str))

    if not provider.configured:
        print("DeepSeek not configured — aborting LIVE scenarios")
        results = [{"id": sc["id"], "name": sc["name"], "group": sc["group"], "type": sc["type"], "status": "SKIPPED"} for sc in SCENARIOS if sc["id"] in SELECTED]
        write_reports(smoke, results, out_dir)
        return

    print(f"\n=== RUN {len(SELECTED)} SCENARIOS (dari 50) ===")
    results = await run_all(provider)
    write_reports(smoke, results, out_dir)
    print("\nReports written to reports/")


if __name__ == "__main__":
    asyncio.run(main())








