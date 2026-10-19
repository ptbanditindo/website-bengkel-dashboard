"""Deterministic verification of the report tool layer (H5 Part B).

Tests the tool REGISTRATION and the plan_tool/orchestrator dispatch path — not
just ReportingService directly. No API calls.
"""

from datetime import datetime

import bot.ai.tools as tools
from bot.ai.tools import TOOL_SCHEMAS, PendingConfirmation, ReadResult, plan_tool

REPORT_TOOLS = [
    "count_vehicles",
    "count_service_records",
    "report_service_totals",
    "report_period_summary",
    "report_top_jobs",
    "report_vehicles_under_warranty",
    "report_part_usage",
    "report_activity_summary",
    "search_service_records_by_job",
]


def _seed(vehicle_service, service_record_service):
    v1 = vehicle_service.create_vehicle(
        nama_client="Budi", nopol="B1111AAA", jenis_mobil="Avanza", tahun_mobil=2021
    )
    v2 = vehicle_service.create_vehicle(
        nama_client="Dhani", nopol="B2222BBB", jenis_mobil="Xenia", tahun_mobil=2022
    )
    service_record_service.add_service_record(
        v1.id, waktu_service=datetime(2026, 1, 5),
        jobs=[{"deskripsi": "Ganti oli", "jumlah": 1, "harga": 50000}],
    )
    service_record_service.add_service_record(
        v1.id, waktu_service=datetime(2026, 2, 10),
        jobs=[{"deskripsi": "Ganti radiator"}], total_servis="600rb",
    )
    service_record_service.add_service_record(
        v2.id, waktu_service=datetime(2026, 3, 1),
        jobs=[{"deskripsi": "Ganti oli", "jumlah": 1, "harga": 50000}],
    )
    return v1, v2


def test_every_schema_has_plan_handler():
    names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    missing = names - set(tools._PLAN_HANDLERS)
    assert not missing, f"schema tanpa handler: {missing}"


def test_every_mutation_has_executor():
    missing = set(tools.MUTATION_TOOLS) - set(tools._EXECUTORS)
    assert not missing, f"mutasi tanpa executor: {missing}"


def test_report_tools_are_read_only():
    assert set(REPORT_TOOLS) & set(tools.MUTATION_TOOLS) == set()
    assert set(REPORT_TOOLS) & set(tools._EXECUTORS) == set()


def test_report_tools_return_read_result(vehicle_service, service_record_service, session):
    _seed(vehicle_service, service_record_service)
    for name in REPORT_TOOLS:
        args = {"query": "oli"} if name == "search_service_records_by_job" else {}
        result = plan_tool(name, args, session)
        assert isinstance(result, ReadResult), f"{name} harus ReadResult"
        assert not isinstance(result, PendingConfirmation), f"{name} tidak boleh butuh konfirmasi"


def test_count_tools_match_fixture(vehicle_service, service_record_service, session):
    _seed(vehicle_service, service_record_service)
    assert "2" in plan_tool("count_vehicles", {}, session).data
    assert "3" in plan_tool("count_service_records", {}, session).data


def test_report_service_totals_matches_fixture(vehicle_service, service_record_service, session):
    _seed(vehicle_service, service_record_service)
    data = plan_tool("report_service_totals", {}, session).data
    assert "Jumlah servis: 3" in data
    # 50000 + 600000 + 50000 = 700000
    assert "Rp700.000" in data


def test_report_top_jobs_matches_fixture(vehicle_service, service_record_service, session):
    _seed(vehicle_service, service_record_service)
    data = plan_tool("report_top_jobs", {}, session).data
    assert "Ganti oli: 2x" in data
    assert "Ganti radiator: 1x" in data


def test_report_activity_summary_matches_fixture(vehicle_service, service_record_service, session):
    _seed(vehicle_service, service_record_service)
    data = plan_tool("report_activity_summary", {}, session).data
    assert "Kendaraan: 2" in data
    assert "Servis: 3" in data
    assert "Pekerjaan tercatat: 3" in data
    assert "Total nilai servis: Rp700.000" in data


def test_search_service_records_by_job_via_plan_tool(vehicle_service, service_record_service, session):
    _seed(vehicle_service, service_record_service)
    data = plan_tool("search_service_records_by_job", {"query": "oli"}, session).data
    assert data.count("Ganti oli") == 2
    data = plan_tool("search_service_records_by_job", {"query": "radiator"}, session).data
    assert "Ganti radiator" in data


def test_search_vehicles_filtered_by_type_and_year(vehicle_service, service_record_service, session):
    _seed(vehicle_service, service_record_service)
    by_type = plan_tool("search_vehicles", {"query": "", "jenis_mobil": "Avanza"}, session).data
    assert "B1111AAA" in by_type
    assert "B2222BBB" not in by_type
    by_year = plan_tool("search_vehicles", {"query": "", "tahun_mobil": 2022}, session).data
    assert "B2222BBB" in by_year
    assert "B1111AAA" not in by_year


def test_report_tools_empty_database(session):
    assert "0" in plan_tool("count_vehicles", {}, session).data
    assert "0" in plan_tool("count_service_records", {}, session).data
    assert "Belum ada pekerjaan yang tercatat." in plan_tool("report_top_jobs", {}, session).data
    assert "Belum ada penggunaan part yang tercatat." in plan_tool("report_part_usage", {}, session).data
    assert "Tidak ada kendaraan dalam masa garansi." in plan_tool(
        "report_vehicles_under_warranty", {}, session
    ).data
    assert "Belum ada data servis" in plan_tool("report_period_summary", {}, session).data
    assert "Jumlah servis: 0" in plan_tool("report_service_totals", {}, session).data
    summary = plan_tool("report_activity_summary", {}, session).data
    assert "Kendaraan: 0" in summary
    assert "Servis: 0" in summary
