"""H5 limited live test — 1 skenario laporan (maks 3 request, tanpa retry).

Memverifikasi model memilih tool laporan yang tepat dan jawabannya cocok dengan
fixture database sementara. TIDAK menyentuh data/workshop.db. Tanpa rahasia.
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

import database.models  # noqa: E402,F401
from ai.context import ConversationHistory  # noqa: E402
from ai.orchestrator import AIOrchestrator  # noqa: E402
from ai.providers import DeepSeekProvider  # noqa: E402
from ai.tools import PendingStore  # noqa: E402
from database.base import Base  # noqa: E402
from services.service_record_service import ServiceRecordService  # noqa: E402
from services.vehicle_service import VehicleService  # noqa: E402

MAX_REQUESTS = 3


class BudgetExceeded(Exception):
    pass


class RecordingProvider:
    def __init__(self, provider):
        self._p = provider
        self.count = 0
        self.tool_calls_seen = []

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
        resp = await self._p.chat(messages, tools=tools)
        for tc in resp.get("tool_calls") or []:
            self.tool_calls_seen.append(
                {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]}
            )
        return resp


def make_db():
    d = tempfile.mkdtemp(prefix="h5live_")
    eng = create_engine(f"sqlite:///{os.path.join(d, 't.db')}", future=True)

    @event.listens_for(eng, "connect")
    def _fk(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(eng)
    return eng, d


async def main():
    report = {
        "scenario": "report_tool_selection",
        "request_count": 0,
        "model": None,
        "tool_calls_seen": [],
        "reply": None,
        "fixture": None,
        "errors": [],
    }
    provider = RecordingProvider(DeepSeekProvider())
    if not provider.configured:
        report["errors"].append("DEEPSEEK_API_KEY kosong — live test dihentikan")
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return

    report["model"] = provider.model
    engine, db_dir = make_db()
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    # Seed fixture with known values.
    s = factory()
    vs = VehicleService(s)
    srs = ServiceRecordService(s)
    v1 = vs.create_vehicle(nama_client="Budi", nopol="B1111AAA", jenis_mobil="Avanza", tahun_mobil=2021)
    v2 = vs.create_vehicle(nama_client="Dhani", nopol="B2222BBB", jenis_mobil="Xenia", tahun_mobil=2022)
    srs.add_service_record(v1.id, jobs=[{"deskripsi": "Ganti oli", "jumlah": 1, "harga": 50000}])
    srs.add_service_record(v1.id, jobs=[{"deskripsi": "Ganti radiator"}], total_servis="600rb")
    srs.add_service_record(v2.id, jobs=[{"deskripsi": "Ganti oli", "jumlah": 1, "harga": 50000}])
    s.close()

    report["fixture"] = {"vehicles": 2, "service_records": 3, "total_servis": "700000.00"}

    orchestrator = AIOrchestrator(provider, PendingStore())
    history = ConversationHistory()
    q = "Berapa jumlah kendaraan dan jumlah riwayat servis yang tercatat di database ini?"
    s2 = factory()
    try:
        result = await orchestrator.handle_message(q, s2, history, user_id=222)
        report["reply"] = result.reply
    except BudgetExceeded:
        report["errors"].append("melebihi batas 3 request")
    s2.close()

    report["tool_calls_seen"] = provider.tool_calls_seen
    report["request_count"] = provider.count
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))

    engine.dispose()
    shutil.rmtree(db_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
