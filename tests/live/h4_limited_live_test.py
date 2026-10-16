"""H4 limited live test — maksimal 3 request DeepSeek API, tanpa retry.

Memverifikasi integrasi model dengan implementasi H3:
  1. Pemetaan instruksi -> tool `record_service_visit` (lewat orchestrator nyata).
  2. Konfirmasi atomik (deterministik, 0 request).
  3. Pemilihan tool laporan (1 request).

Memakai database SQLite sementara yang terisolasi; TIDAK menyentuh data/workshop.db.
Tidak mencetak API key/token. Semua argumen adalah data fiktif.
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import database.models  # noqa: E402,F401  (register models)
from ai.context import ConversationHistory  # noqa: E402
from ai.orchestrator import AIOrchestrator  # noqa: E402
from ai.providers import DeepSeekProvider  # noqa: E402
from ai.tools import SYSTEM_PROMPT, TOOL_SCHEMAS, PendingStore, plan_tool  # noqa: E402
from database.base import Base  # noqa: E402
from database.models import ServiceRecord, Vehicle  # noqa: E402

MAX_REQUESTS = 3


class BudgetExceeded(Exception):
    pass


class CappedProvider:
    """Wraps the real provider and enforces the 3-request hard cap."""

    def __init__(self, provider):
        self._p = provider
        self.count = 0

    @property
    def configured(self):
        return self._p.configured

    @property
    def model(self):
        return self._p.model

    async def chat(self, messages, tools=None):
        if self.count >= MAX_REQUESTS:
            raise BudgetExceeded()
        self.count += 1
        return await self._p.chat(messages, tools=tools)


def make_db():
    d = tempfile.mkdtemp(prefix="h4live_")
    eng = create_engine(f"sqlite:///{os.path.join(d, 't.db')}", future=True)

    @event.listens_for(eng, "connect")
    def _fk(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(eng)
    return eng, d


def _vehicle_dict(v):
    return {
        "nopol": v.nopol,
        "nama_client": v.nama_client,
        "jenis_mobil": v.jenis_mobil,
        "tahun_mobil": v.tahun_mobil,
        "nomor_wa": v.nomor_wa,
        "alamat_client": v.alamat_client,
    }


def _record_dict(r):
    return {
        "id": r.id,
        "total_servis": str(r.total_servis),
        "biaya_jasa": str(r.biaya_jasa),
        "total_part": str(r.total_part),
        "jobs": [j.deskripsi for j in r.jobs],
        "parts": [p.nama_part for p in r.parts],
    }


async def main():
    report = {"requests": [], "request_count": 0, "model": None, "errors": []}

    provider = CappedProvider(DeepSeekProvider())
    if not provider.configured:
        report["errors"].append("DEEPSEEK_API_KEY kosong — live test dihentikan")
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return

    report["model"] = provider.model
    engine, db_dir = make_db()
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    orchestrator = AIOrchestrator(provider, PendingStore())
    history = ConversationHistory()

    # ---- Request 1: pemetaan instruksi -> record_service_visit ----
    msg = (
        "Catat servis hari ini, Avanza 2021 ganti radiator, total semua 600rb. "
        "Plat B 3413 FED, nama Budi, WA 081234567890, alamat Bandung."
    )
    req1 = {"id": 1, "scenario": "record_service_visit_mapping", "pending": False}
    token = None
    s = factory()
    before = (s.query(Vehicle).count(), s.query(ServiceRecord).count())
    try:
        result = await orchestrator.handle_message(msg, s, history, user_id=111)
        req1["reply"] = result.reply
        if result.pending_action is not None:
            req1["pending"] = True
            req1["steps"] = result.pending_action.steps
            req1["summary"] = result.pending_action.summary
            token = result.pending_action.token
        after_plan = (s.query(Vehicle).count(), s.query(ServiceRecord).count())
        req1["no_premature_mutation"] = before == after_plan
    except BudgetExceeded:
        req1["error"] = "melebihi batas 3 request (model melakukan tool call ekstra)"
        report["errors"].append("Request 1 melebihi batas 3 request")
    s.close()
    report["requests"].append(req1)

    # ---- Request 2: konfirmasi & konsistensi (0 request API) ----
    req2 = {"id": 2, "scenario": "confirmation_and_consistency", "executed": False}
    if token is not None:
        s2 = factory()
        try:
            req2["result_text"] = orchestrator.execute_pending(token, s2, user_id=111)
            req2["executed"] = True
        except Exception as e:  # noqa: BLE001
            req2["error"] = str(e)
        s2.close()

        s3 = factory()
        veh = s3.query(Vehicle).all()
        recs = s3.query(ServiceRecord).all()
        req2["db_after"] = {
            "vehicle_count": len(veh),
            "record_count": len(recs),
            "vehicles": [_vehicle_dict(v) for v in veh],
            "service_records": [_record_dict(r) for r in recs],
        }
        s3.close()
    report["requests"].append(req2)

    # ---- Request 3: pemilihan tool laporan (1 request API) ----
    req3 = {"id": 3, "scenario": "report_tool_selection", "tool_calls": None, "tool_results": None}
    if provider.count < MAX_REQUESTS:
        q = "Berapa jumlah kendaraan, jumlah riwayat servis, dan total nilai servis yang tercatat di database ini?"
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": q}]
        try:
            resp = await provider.chat(messages, tools=TOOL_SCHEMAS)
            req3["content"] = resp.get("content")
            tool_calls = []
            tool_results = []
            s4 = factory()
            for tc in resp.get("tool_calls") or []:
                name = tc["function"]["name"]
                args = tc["function"]["arguments"]
                tool_calls.append({"name": name, "arguments": args})
                try:
                    outcome = plan_tool(name, json.loads(args or "{}"), s4)
                    tool_results.append(getattr(outcome, "data", str(outcome)))
                except Exception as e:  # noqa: BLE001
                    tool_results.append(f"Error: {e}")
            s4.close()
            req3["tool_calls"] = tool_calls
            req3["tool_results"] = tool_results
        except BudgetExceeded:
            req3["note"] = "budget habis"
    else:
        req3["note"] = "budget habis (request 1 sudah pakai 3)"
    report["requests"].append(req3)

    report["request_count"] = provider.count
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))

    engine.dispose()
    shutil.rmtree(db_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())

