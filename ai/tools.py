"""Business tool definitions and dispatch for the AI assistant.

Tools map onto the service layer (Tahap B). Read tools execute immediately;
mutation tools produce a ``PendingConfirmation`` that the bot turns into a user
confirmation before anything is written.
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Optional

from database.models import normalize_plate
from services.catalog import apply_auto_split, catalog_price_warnings
from services.exceptions import ConflictError, NotFoundError, ValidationError
from services.reporting import ReportingService
from services.service_record_service import ServiceRecordService
from services.vehicle_service import VehicleService

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "Kamu adalah asisten pencatatan arsip servis untuk bengkel mobil (dipakai pemilik bengkel, internal).\n"
    "Bantu pemilik mencatat kendaraan, pelanggan, pekerjaan servis, suku cadang, harga, dan garansi.\n"
    "Ini BUKAN sistem booking/pendaftaran pelanggan: setiap permintaan servis adalah pekerjaan servis aktual.\n"
    "Aturan:\n"
    "- Gunakan bahasa Indonesia yang ramah; pahami bahasa sehari-hari dan singkatan (mis. '600rb', 'Rp600.000', '1,5 juta').\n"
    "- Gunakan tool untuk membaca dan mengubah data. Jangan membuat data, menghitung total, atau menjalankan SQL sendiri.\n"
    "- Untuk mencatat servis, GUNAKAN tool `record_service_visit`. Tool ini otomatis mendaftarkan kendaraan bila plat belum ada, lalu mencatat riwayat servisnya sekaligus.\n"
    "- Jangan memanggil `create_vehicle` lalu `add_service_record` terpisah untuk satu servis; cukup `record_service_visit`.\n"
    "- Ekstrak dari pesan: nama client, plat, nomor WA, jenis mobil, tahun, alamat, tanggal servis, pekerjaan, part, harga, total, dan garansi.\n"
    "- Untuk nominal uang, tuliskan persis seperti yang disebut pengguna (mis. '600rb', 'Rp600.000', '1,5 juta'); aplikasi yang menormalisasi. Jangan mengubah makna nominal.\n"
    "- Jika pengguna hanya memberi 'total semua X', isi field `total` saja; JANGAN memecahnya menjadi biaya jasa atau harga part.\n"
    "- Jangan menebak makna nominal (total vs biaya jasa vs harga part). Jika tidak jelas, tanyakan.\n"
    "- Jangan mengarang data yang tidak disebutkan (nomor WA, tahun, harga, tanggal garansi, nama client).\n"
    "- Nama client, nomor WA, jenis, tahun, dan alamat BERSIFAT OPSIONAL dan bisa menyusul. Jika pemilik sedang sibuk, fokus catat plat + pekerjaan servis dulu; tanyakan data pelanggan hanya jika pemilik ingin melengkapi.\n"
    "- Jangan menebak/mengisi harga dari katalog sendiri; aplikasi akan membandingkan harga yang dimasukkan dengan katalog Harga Jasa/Stok dan memperingatkan pemilik bila berbeda.\n"
    "- Jika informasi wajib belum ada (hanya plat) atau data ambigu, ajukan pertanyaan klarifikasi.\n"
    "- Satu nomor polisi = satu kendaraan. Jika sudah terdaftar, gunakan arsip yang ada; jangan duplikat.\n"
    "- Perhitungan uang dilakukan oleh aplikasi (tool), bukan olehmu.\n"
    "\n"
    "FORMAT JAWABAN (wajib, agar mudah dibaca pemilik di Telegram):\n"
    "- Tulis teks polos. JANGAN pakai tabel Markdown (garis |), JANGAN pakai **bold**, *italic*, atau `backtick`.\n"
    "- Gunakan baris pendek dengan emoji dan indentasi dua spasi untuk rincian; pisahkan bagian dengan satu baris kosong.\n"
    "- Tulis uang dengan format Rp150.000 (titik ribuan, tanpa desimal bila bulat).\n"
    "- Jawab singkat dan jelas; jangan ulangi kalimat yang sama."
)


@dataclass
class ReadResult:
    """A completed read-tool result fed back to the model."""

    data: str


@dataclass
class PendingConfirmation:
    """A mutation that must be confirmed by the user before execution."""

    tool_name: str
    arguments: dict
    summary: str


@dataclass
class PendingAction:
    """A stored pending mutation (one or more steps) with a one-time token.

    Bound to a specific user and expires after a short TTL. ``steps`` is a list
    of ``{"tool": name, "arguments": {...}}`` executed in order on confirmation.
    """

    token: str
    user_id: int
    steps: list
    summary: str
    created_at: float


class PendingStore:
    """In-memory store of pending actions, keyed by a one-time token.

    Tokens are bound to a user and expire after ``ttl_seconds`` (default 30 min).
    """

    def __init__(self, ttl_seconds: int = 1800):
        self._items: dict[str, PendingAction] = {}
        self._ttl = ttl_seconds

    def add(self, user_id: int, steps: list, summary: str) -> PendingAction:
        token = uuid.uuid4().hex
        action = PendingAction(
            token=token,
            user_id=user_id,
            steps=steps,
            summary=summary,
            created_at=time.time(),
        )
        self._items[token] = action
        return action

    def get(self, token: str, user_id: int) -> Optional[PendingAction]:
        action = self._items.get(token)
        if action is None or action.user_id != user_id:
            return None
        if time.time() - action.created_at > self._ttl:
            self._items.pop(token, None)
            return None
        return action

    def pop(self, token: str, user_id: int) -> Optional[PendingAction]:
        action = self.get(token, user_id)
        if action is None:
            return None
        del self._items[token]
        return action


@dataclass
class PhotoDraft:
    """A photo-extraction draft awaiting a plate number, bound to one user."""

    user_id: int
    data: dict
    created_at: float


class PhotoDraftStore:
    """In-memory photo drafts keyed by user (one active draft per user).

    Bound to a user and expires after ``ttl_seconds`` (default 30 min); popped
    once, so it cannot be continued by another user or processed repeatedly.
    """

    def __init__(self, ttl_seconds: int = 1800):
        self._drafts: dict[int, PhotoDraft] = {}
        self._ttl = ttl_seconds

    def add(self, user_id: int, data: dict) -> PhotoDraft:
        draft = PhotoDraft(user_id=user_id, data=data, created_at=time.time())
        self._drafts[user_id] = draft
        return draft

    def pop(self, user_id: int) -> Optional[PhotoDraft]:
        draft = self._drafts.get(user_id)
        if draft is None:
            return None
        if time.time() - draft.created_at > self._ttl:
            del self._drafts[user_id]
            return None
        del self._drafts[user_id]
        return draft

    def clear(self, user_id: int) -> None:
        self._drafts.pop(user_id, None)


def _schema(name: str, description: str, properties: dict, required: list) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


def _str_prop(description: str) -> dict:
    return {"type": "string", "description": description}


def _int_prop(description: str) -> dict:
    return {"type": "integer", "description": description}


# Names of tools that mutate data (require confirmation).
MUTATION_TOOLS = {
    "create_vehicle",
    "update_vehicle",
    "add_service_record",
    "record_service_visit",
    "update_warranty",
    "confirm_warranty_claim",
}


TOOL_SCHEMAS = [
    _schema(
        "search_vehicle_by_plate",
        "Cari satu kendaraan berdasarkan nomor polisi (huruf besar, spasi diabaikan).",
        {"nopol": _str_prop("Nomor polisi kendaraan")},
        ["nopol"],
    ),
    _schema(
        "search_vehicles",
        "Cari kendaraan/pelanggan berdasarkan nama client, plat, jenis mobil, dan/atau tahun.",
        {
            "query": _str_prop("Nama client, plat, atau jenis mobil (sebagian)"),
            "jenis_mobil": _str_prop("Jenis mobil untuk disaring (opsional)"),
            "tahun_mobil": _int_prop("Tahun mobil untuk disaring (opsional)"),
        },
        ["query"],
    ),
    _schema(
        "create_vehicle",
        "Daftarkan kendaraan baru (butuh konfirmasi pengguna).",
        {
            "nama_client": _str_prop("Nama client (opsional)"),
            "nopol": _str_prop("Nomor polisi"),
            "nomor_wa": _str_prop("Nomor WhatsApp (opsional)"),
            "jenis_mobil": _str_prop("Jenis mobil (opsional)"),
            "tahun_mobil": _int_prop("Tahun mobil (opsional)"),
            "alamat_client": _str_prop("Alamat client (opsional)"),
        },
        ["nopol"],
    ),
    _schema(
        "update_vehicle",
        "Perbarui field kendaraan yang diizinkan (butuh konfirmasi).",
        {
            "nopol": _str_prop("Nomor polisi kendaraan yang akan diperbarui"),
            "nama_client": _str_prop("Nama client baru (opsional)"),
            "nomor_wa": _str_prop("Nomor WhatsApp baru (opsional)"),
            "jenis_mobil": _str_prop("Jenis mobil baru (opsional)"),
            "tahun_mobil": _int_prop("Tahun mobil baru (opsional)"),
            "alamat_client": _str_prop("Alamat client baru (opsional)"),
        },
        ["nopol"],
    ),
    _schema(
        "add_service_record",
        "Tambahkan riwayat servis baru (butuh konfirmasi).",
        {
            "nopol": _str_prop("Nomor polisi kendaraan"),
            "jobs": {
                "type": "array",
                "description": "Daftar pekerjaan/jasa",
                "items": {
                    "type": "object",
                    "properties": {
                        "deskripsi": _str_prop("Nama pekerjaan"),
                        "jumlah": _int_prop("Jumlah (default 1)"),
                        "harga": _str_prop("Harga satuan (opsional)"),
                    },
                },
            },
            "parts": {
                "type": "array",
                "description": "Daftar part yang diganti",
                "items": {
                    "type": "object",
                    "properties": {
                        "nama_part": _str_prop("Nama part"),
                        "jumlah": _int_prop("Jumlah (default 1)"),
                        "harga_satuan": _str_prop("Harga satuan (opsional)"),
                    },
                },
            },
            "garansi_sampai": _str_prop("Tanggal akhir garansi YYYY-MM-DD (opsional)"),
            "catatan": _str_prop("Catatan tambahan (opsional)"),
            "total": _str_prop("Total biaya servis keseluruhan (jika pengguna hanya memberi total tanpa rincian jasa/part)"),
        },
        ["nopol"],
    ),
    _schema(
        "record_service_visit",
        "Catat satu kunjungan servis. Jika plat belum terdaftar, kendaraan dibuat sekaligus dengan riwayat servisnya dalam satu langkah (butuh konfirmasi). Gunakan tool ini untuk semua pencatatan servis.",
        {
            "nopol": _str_prop("Nomor polisi kendaraan (wajib)"),
            "nama_client": _str_prop("Nama client (opsional)"),
            "nomor_wa": _str_prop("Nomor WhatsApp (opsional)"),
            "jenis_mobil": _str_prop("Jenis mobil (opsional)"),
            "tahun_mobil": _int_prop("Tahun mobil (opsional)"),
            "alamat_client": _str_prop("Alamat client (opsional)"),
            "waktu_service": _str_prop("Tanggal servis YYYY-MM-DD (opsional)"),
            "jobs": {
                "type": "array",
                "description": "Daftar pekerjaan/jasa",
                "items": {
                    "type": "object",
                    "properties": {
                        "deskripsi": _str_prop("Nama pekerjaan"),
                        "jumlah": _int_prop("Jumlah (default 1)"),
                        "harga": _str_prop("Harga satuan (opsional)"),
                    },
                },
            },
            "parts": {
                "type": "array",
                "description": "Daftar part yang diganti",
                "items": {
                    "type": "object",
                    "properties": {
                        "nama_part": _str_prop("Nama part"),
                        "jumlah": _int_prop("Jumlah (default 1)"),
                        "harga_satuan": _str_prop("Harga satuan (opsional)"),
                    },
                },
            },
            "garansi_sampai": _str_prop("Tanggal akhir garansi YYYY-MM-DD (opsional)"),
            "catatan": _str_prop("Catatan tambahan (opsional)"),
            "total": _str_prop("Total biaya servis keseluruhan (jika pengguna hanya memberi total tanpa rincian jasa/part)"),
        },
        ["nopol"],
    ),
    _schema(
        "list_service_history",
        "Lihat seluruh riwayat servis sebuah kendaraan berdasarkan plat.",
        {"nopol": _str_prop("Nomor polisi kendaraan")},
        ["nopol"],
    ),
    _schema(
        "get_warranty_info",
        "Lihat informasi garansi (tanggal & status klaim) semua servis kendaraan.",
        {"nopol": _str_prop("Nomor polisi kendaraan")},
        ["nopol"],
    ),
    _schema(
        "update_warranty",
        "Perbarui tanggal akhir garansi sebuah riwayat servis (butuh konfirmasi).",
        {
            "record_id": _int_prop("ID riwayat servis"),
            "garansi_sampai": _str_prop("Tanggal akhir garansi YYYY-MM-DD"),
        },
        ["record_id", "garansi_sampai"],
    ),
    _schema(
        "confirm_warranty_claim",
        "Tandai garansi sebuah servis sebagai 'Sudah claim' (butuh konfirmasi).",
        {"record_id": _int_prop("ID riwayat servis")},
        ["record_id"],
    ),
    _schema(
        "get_service_detail",
        "Lihat detail satu riwayat servis beserta perhitungan total.",
        {"record_id": _int_prop("ID riwayat servis")},
        ["record_id"],
    ),
    _schema(
        "search_service_records_by_job",
        "Cari riwayat servis berdasarkan nama pekerjaan/jasa yang pernah dilakukan.",
        {"query": _str_prop("Nama pekerjaan (sebagian)")},
        ["query"],
    ),
    _schema(
        "count_vehicles",
        "Hitung jumlah kendaraan unik dalam arsip.",
        {},
        [],
    ),
    _schema(
        "count_service_records",
        "Hitung jumlah riwayat servis yang tercatat.",
        {},
        [],
    ),
    _schema(
        "report_service_totals",
        "Rekap jumlah servis dan total nilai servis (opsional dalam rentang tanggal).",
        {
            "start_date": _str_prop("Tanggal awal YYYY-MM-DD (opsional)"),
            "end_date": _str_prop("Tanggal akhir (eksklusif) YYYY-MM-DD (opsional)"),
        },
        [],
    ),
    _schema(
        "report_period_summary",
        "Rekap jumlah servis dan total nilai per bulan (opsional untuk satu tahun).",
        {"year": _int_prop("Tahun (opsional)")},
        [],
    ),
    _schema(
        "report_top_jobs",
        "Pekerjaan servis yang paling sering dilakukan.",
        {"limit": _int_prop("Jumlah baris teratas (default 5)")},
        [],
    ),
    _schema(
        "report_vehicles_under_warranty",
        "Kendaraan yang masih dalam masa garansi (garansi belum lewat).",
        {},
        [],
    ),
    _schema(
        "report_part_usage",
        "Ringkasan penggunaan suku cadang dan jumlahnya.",
        {},
        [],
    ),
    _schema(
        "report_activity_summary",
        "Ringkasan aktivitas: jumlah kendaraan, servis, pekerjaan, part, dan total nilai servis.",
        {},
        [],
    ),
]


# ---------------------------------------------------------------------------
# Plain-text formatting for tool results (fed back to the model)
# ---------------------------------------------------------------------------
def _fmt_vehicle(v) -> str:
    lines = [f"ID kendaraan: {v.id}", f"Plat: {v.nopol}", f"Nama: {v.nama_client}"]
    if v.jenis_mobil:
        lines.append(f"Jenis: {v.jenis_mobil}")
    if v.tahun_mobil:
        lines.append(f"Tahun: {v.tahun_mobil}")
    if v.nomor_wa:
        lines.append(f"WA: {v.nomor_wa}")
    if v.alamat_client:
        lines.append(f"Alamat: {v.alamat_client}")
    return "\n".join(lines)


def _fmt_record(r) -> str:
    lines = [f"Servis ID {r.id} — {r.waktu_service.strftime('%d/%m/%Y')}"]
    if r.jobs:
        lines.append("Pekerjaan:")
        for j in r.jobs:
            harga = j.harga if j.harga is not None else "belum diketahui"
            lines.append(f"  - {j.deskripsi} x{j.jumlah} @ {harga}")
    if r.parts:
        lines.append("Part:")
        for p in r.parts:
            harga = p.harga_satuan if p.harga_satuan is not None else "belum diketahui"
            lines.append(f"  - {p.nama_part} x{p.jumlah} @ {harga}")
    lines.append(f"Biaya jasa: {r.biaya_jasa if r.biaya_jasa is not None else 'belum diketahui'}")
    lines.append(f"Total part: {r.total_part if r.total_part is not None else 'belum diketahui'}")
    lines.append(f"Total servis: {r.total_servis if r.total_servis is not None else 'belum diketahui'}")
    lines.append(f"Garansi s/d: {r.garansi_sampai if r.garansi_sampai else 'belum diketahui'}")
    lines.append(f"Status klaim: {r.status_klaim}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Read handlers (execute immediately)
# ---------------------------------------------------------------------------
def _search_vehicle_by_plate(args, session) -> ReadResult:
    vehicle = VehicleService(session).find_vehicle_by_plate(args.get("nopol", ""))
    if vehicle is None:
        return ReadResult(f"Kendaraan dengan plat {normalize_plate(args.get('nopol', ''))} tidak ditemukan.")
    return ReadResult(_fmt_vehicle(vehicle))


def _search_vehicles(args, session) -> ReadResult:
    results = VehicleService(session).search_vehicles_filtered(
        args.get("query", ""), args.get("jenis_mobil"), args.get("tahun_mobil")
    )
    if not results:
        return ReadResult("Tidak ada kendaraan yang cocok.")
    return ReadResult("\n\n".join(_fmt_vehicle(v) for v in results))


def _list_service_history(args, session) -> ReadResult:
    vehicle = VehicleService(session).find_vehicle_by_plate(args.get("nopol", ""))
    if vehicle is None:
        return ReadResult(f"Kendaraan dengan plat {normalize_plate(args.get('nopol', ''))} tidak ditemukan.")
    records = ServiceRecordService(session).list_service_records(vehicle.id)
    if not records:
        return ReadResult("Belum ada riwayat servis.")
    return ReadResult("\n\n".join(_fmt_record(r) for r in records))


def _get_warranty_info(args, session) -> ReadResult:
    # Records already include warranty fields, so reuse the history result.
    return _list_service_history(args, session)


def _get_service_detail(args, session) -> ReadResult:
    try:
        record = ServiceRecordService(session).get_service_record(int(args.get("record_id")))
    except NotFoundError as e:
        return ReadResult(str(e))
    return ReadResult(_fmt_record(record))


def _fmt_money(value) -> str:
    if value is None:
        return "belum diketahui"
    return f"Rp{value:,.0f}".replace(",", ".")


def _parse_optional_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise ValidationError(f"Format tanggal tidak valid: {value}. Gunakan YYYY-MM-DD.")


def _search_service_records_by_job(args, session) -> ReadResult:
    query = (args.get("query") or "").strip()
    if not query:
        return ReadResult("Nama pekerjaan tidak boleh kosong.")
    records = ReportingService(session).search_records_by_job(query)
    if not records:
        return ReadResult(f"Tidak ada riwayat servis dengan pekerjaan '{query}'.")
    return ReadResult("\n\n".join(_fmt_record(r) for r in records))


def _count_vehicles(args, session) -> ReadResult:
    return ReadResult(f"Jumlah kendaraan unik: {ReportingService(session).count_vehicles()}")


def _count_service_records(args, session) -> ReadResult:
    return ReadResult(f"Jumlah riwayat servis: {ReportingService(session).count_service_records()}")


def _report_service_totals(args, session) -> ReadResult:
    start = _parse_optional_date(args.get("start_date"))
    end = _parse_optional_date(args.get("end_date"))
    data = ReportingService(session).service_totals(start, end)
    lines = [
        f"Rekap servis (rentang {start or '-'} s/d {end or '-'}):",
        f"- Jumlah servis: {data['jumlah_servis']}",
        f"- Total nilai servis: {_fmt_money(data['total_servis'])}",
    ]
    if data["total_servis"] is None and data["jumlah_servis"]:
        lines.append("- Catatan: sebagian servis belum memiliki total, jadi total tidak dijumlahkan.")
    return ReadResult("\n".join(lines))


def _report_period_summary(args, session) -> ReadResult:
    year = args.get("year")
    rows = ReportingService(session).period_summary(year)
    if not rows:
        return ReadResult("Belum ada data servis untuk periode tersebut.")
    lines = ["Rekap servis per bulan:"]
    for row in rows:
        lines.append(f"- {row['periode']}: {row['jumlah_servis']} servis, total {_fmt_money(row['total_servis'])}")
    return ReadResult("\n".join(lines))


def _report_top_jobs(args, session) -> ReadResult:
    limit = int(args.get("limit") or 5)
    rows = ReportingService(session).top_jobs(limit)
    if not rows:
        return ReadResult("Belum ada pekerjaan yang tercatat.")
    lines = ["Pekerjaan paling sering:"]
    for row in rows:
        lines.append(f"- {row['deskripsi']}: {row['jumlah']}x")
    return ReadResult("\n".join(lines))


def _report_vehicles_under_warranty(args, session) -> ReadResult:
    rows = ReportingService(session).vehicles_under_warranty()
    if not rows:
        return ReadResult("Tidak ada kendaraan dalam masa garansi.")
    lines = ["Kendaraan dalam masa garansi:"]
    for v in rows:
        lines.append(f"- {v['nopol']} ({v['nama_client']}) garansi s/d {v['garansi_sampai']} — {v['status_klaim']}")
    return ReadResult("\n".join(lines))


def _report_part_usage(args, session) -> ReadResult:
    rows = ReportingService(session).part_usage()
    if not rows:
        return ReadResult("Belum ada penggunaan part yang tercatat.")
    lines = ["Penggunaan part:"]
    for row in rows:
        lines.append(f"- {row['nama_part']}: {row['jumlah']} unit ({row['jumlah_servis']} baris)")
    return ReadResult("\n".join(lines))


def _report_activity_summary(args, session) -> ReadResult:
    data = ReportingService(session).activity_summary()
    lines = [
        "Ringkasan aktivitas bengkel:",
        f"- Kendaraan: {data['jumlah_kendaraan']}",
        f"- Servis: {data['jumlah_servis']}",
        f"- Pekerjaan tercatat: {data['jumlah_pekerjaan']}",
        f"- Part tercatat: {data['jumlah_part']}",
        f"- Total nilai servis: {_fmt_money(data['total_servis'])}",
    ]
    return ReadResult("\n".join(lines))


# ---------------------------------------------------------------------------
# Mutation plan handlers (validate + summarize; do NOT execute)
# ---------------------------------------------------------------------------
def _plan_create_vehicle(args, session) -> PendingConfirmation:
    nopol = normalize_plate(str(args.get("nopol", "")))
    if not nopol:
        raise ValidationError("Nomor polisi wajib diisi.")
    if VehicleService(session).find_vehicle_by_plate(nopol) is not None:
        raise ConflictError(f"Kendaraan dengan plat {nopol} sudah terdaftar.")
    normalized = dict(args)
    normalized["nopol"] = nopol
    lines = [
        "Daftar kendaraan baru:",
        f"• Nama client: {args.get('nama_client', '-')}",
        f"• Plat: {nopol}",
        f"• Nomor WA: {args.get('nomor_wa') or '-'}",
        f"• Jenis mobil: {args.get('jenis_mobil') or '-'}",
        f"• Tahun: {args.get('tahun_mobil') or '-'}",
        f"• Alamat: {args.get('alamat_client') or '-'}",
    ]
    return PendingConfirmation("create_vehicle", normalized, "\n".join(lines))


def _plan_update_vehicle(args, session) -> PendingConfirmation:
    vehicle = VehicleService(session).find_vehicle_by_plate(args.get("nopol", ""))
    if vehicle is None:
        raise NotFoundError(f"Kendaraan dengan plat {normalize_plate(args.get('nopol', ''))} tidak ditemukan.")
    changes = {k: v for k, v in args.items() if k != "nopol" and v is not None}
    if not changes:
        raise ValidationError("Tidak ada field yang akan diperbarui.")
    normalized = {"vehicle_id": vehicle.id, **changes}
    lines = [f"Perbarui kendaraan {vehicle.nopol}:"]
    for k, v in changes.items():
        lines.append(f"• {k}: {v}")
    return PendingConfirmation("update_vehicle", normalized, "\n".join(lines))


def _plan_add_service_record(args, session) -> PendingConfirmation:
    nopol = normalize_plate(str(args.get("nopol", "")))
    if not nopol:
        raise ValidationError("Nomor polisi wajib diisi.")
    vehicle = VehicleService(session).find_vehicle_by_plate(nopol)
    # Defer plate->vehicle resolution to execution so a combined
    # create_vehicle + add_service_record works in one confirmation.
    normalized = {
        "nopol": nopol,
        "jobs": args.get("jobs") or [],
        "parts": args.get("parts") or [],
        "garansi_sampai": args.get("garansi_sampai"),
        "catatan": args.get("catatan"),
        "total": args.get("total"),
    }
    split_notes, normalized["jobs"], normalized["parts"] = apply_auto_split(
        session, normalized["jobs"], normalized["parts"]
    )
    lines = [f"Tambah servis untuk {nopol}:"]
    for j in normalized["jobs"]:
        lines.append(f"• Pekerjaan: {j.get('deskripsi')} x{j.get('jumlah', 1)} @ {j.get('harga', '-')}")
    for p in normalized["parts"]:
        lines.append(f"• Part: {p.get('nama_part')} x{p.get('jumlah', 1)} @ {p.get('harga_satuan', '-')}")
    if args.get("total") is not None:
        lines.append(f"• Total servis: {args.get('total')} (rincian jasa/part belum dipisah)")
    lines.append(f"• Garansi s/d: {args.get('garansi_sampai') or '-'}")
    if vehicle is None:
        lines.append("• Catatan: kendaraan akan didaftarkan terlebih dahulu")
    for note in split_notes:
        lines.append(note)
    for warning in catalog_price_warnings(session, normalized["jobs"], normalized["parts"]):
        lines.append(warning)
    return PendingConfirmation("add_service_record", normalized, "\n".join(lines))


def _plan_record_service_visit(args, session) -> PendingConfirmation:
    nopol = normalize_plate(str(args.get("nopol", "")))
    if not nopol:
        raise ValidationError("Nomor polisi wajib diisi.")
    vehicle = VehicleService(session).find_vehicle_by_plate(nopol)

    normalized = {
        "nopol": nopol,
        "nama_client": args.get("nama_client"),
        "nomor_wa": args.get("nomor_wa"),
        "jenis_mobil": args.get("jenis_mobil"),
        "tahun_mobil": args.get("tahun_mobil"),
        "alamat_client": args.get("alamat_client"),
        "waktu_service": args.get("waktu_service"),
        "jobs": args.get("jobs") or [],
        "parts": args.get("parts") or [],
        "garansi_sampai": args.get("garansi_sampai"),
        "catatan": args.get("catatan"),
        "total": args.get("total"),
    }
    split_notes, normalized["jobs"], normalized["parts"] = apply_auto_split(
        session, normalized["jobs"], normalized["parts"]
    )
    status = "sudah terdaftar" if vehicle is not None else "baru"
    lines = [f"Catat servis untuk {nopol} (kendaraan {status}):"]
    if vehicle is None:
        lines.append(f"• Nama client: {args.get('nama_client') or '-'}")
        lines.append(f"• Jenis mobil: {args.get('jenis_mobil') or '-'}")
        lines.append(f"• Tahun: {args.get('tahun_mobil') or '-'}")
    for j in normalized["jobs"]:
        lines.append(f"• Pekerjaan: {j.get('deskripsi')} x{j.get('jumlah', 1)} @ {j.get('harga', '-')}")
    for p in normalized["parts"]:
        lines.append(f"• Part: {p.get('nama_part')} x{p.get('jumlah', 1)} @ {p.get('harga_satuan', '-')}")
    if args.get("total") is not None:
        lines.append(f"• Total servis: {args.get('total')} (rincian jasa/part belum dipisah)")
    if args.get("garansi_sampai"):
        lines.append(f"• Garansi s/d: {args.get('garansi_sampai')}")
    for note in split_notes:
        lines.append(note)
    for warning in catalog_price_warnings(session, normalized["jobs"], normalized["parts"]):
        lines.append(warning)
    return PendingConfirmation("record_service_visit", normalized, "\n".join(lines))


def _plan_update_warranty(args, session) -> PendingConfirmation:
    record_id = int(args.get("record_id"))
    record = ServiceRecordService(session).get_service_record(record_id)
    lines = [
        f"Perbarui garansi servis ID {record_id} ({record.waktu_service.strftime('%d/%m/%Y')}):",
        f"• Garansi s/d: {args.get('garansi_sampai')}",
    ]
    return PendingConfirmation(
        "update_warranty",
        {"record_id": record_id, "garansi_sampai": args.get("garansi_sampai")},
        "\n".join(lines),
    )


def _plan_confirm_warranty_claim(args, session) -> PendingConfirmation:
    record_id = int(args.get("record_id"))
    record = ServiceRecordService(session).get_service_record(record_id)
    lines = [
        f"Klaim garansi servis ID {record_id} ({record.waktu_service.strftime('%d/%m/%Y')}):",
        f"• Status saat ini: {record.status_klaim}",
    ]
    return PendingConfirmation("confirm_warranty_claim", {"record_id": record_id}, "\n".join(lines))


# ---------------------------------------------------------------------------
# Executors (run only after user confirmation)
# ---------------------------------------------------------------------------
def _exec_create_vehicle(args, session) -> str:
    vehicle = VehicleService(session).create_vehicle(
        nama_client=args.get("nama_client"),
        nopol=args.get("nopol"),
        nomor_wa=args.get("nomor_wa"),
        jenis_mobil=args.get("jenis_mobil"),
        tahun_mobil=args.get("tahun_mobil"),
        alamat_client=args.get("alamat_client"),
        commit=False,
    )
    return f"Kendaraan {vehicle.nopol} ({vehicle.nama_client}) berhasil didaftarkan."


def _exec_update_vehicle(args, session) -> str:
    changes = {k: v for k, v in args.items() if k != "vehicle_id"}
    vehicle = VehicleService(session).update_vehicle(args.get("vehicle_id"), commit=False, **changes)
    return f"Kendaraan {vehicle.nopol} berhasil diperbarui."


def _exec_add_service_record(args, session) -> str:
    vehicle_id = args.get("vehicle_id")
    if vehicle_id is None:
        nopol = normalize_plate(str(args.get("nopol", "")))
        vehicle = VehicleService(session).find_vehicle_by_plate(nopol)
        if vehicle is None:
            raise NotFoundError(f"Kendaraan dengan plat {nopol} belum terdaftar.")
        vehicle_id = vehicle.id
    record = ServiceRecordService(session).add_service_record(
        vehicle_id,
        jobs=args.get("jobs"),
        parts=args.get("parts"),
        garansi_sampai=args.get("garansi_sampai"),
        catatan=args.get("catatan"),
        total_servis=args.get("total"),
        commit=False,
    )
    return _fmt_record(record)


def _exec_record_service_visit(args, session) -> str:
    record = ServiceRecordService(session).record_service_visit(
        nopol=args.get("nopol"),
        nama_client=args.get("nama_client"),
        nomor_wa=args.get("nomor_wa"),
        jenis_mobil=args.get("jenis_mobil"),
        tahun_mobil=args.get("tahun_mobil"),
        alamat_client=args.get("alamat_client"),
        jobs=args.get("jobs"),
        parts=args.get("parts"),
        waktu_service=args.get("waktu_service"),
        garansi_sampai=args.get("garansi_sampai"),
        catatan=args.get("catatan"),
        total_servis=args.get("total"),
        commit=False,
    )
    return _fmt_record(record)


def _exec_update_warranty(args, session) -> str:
    record = ServiceRecordService(session).update_warranty(
        int(args.get("record_id")), args.get("garansi_sampai"), commit=False
    )
    return f"Garansi servis ID {record.id} diperbarui s/d {record.garansi_sampai}."


def _exec_confirm_warranty_claim(args, session) -> str:
    record = ServiceRecordService(session).mark_claim(int(args.get("record_id")), commit=False)
    return f"Status klaim servis ID {record.id} menjadi {record.status_klaim}."


# ---------------------------------------------------------------------------
# Registry and dispatch
# ---------------------------------------------------------------------------
_PLAN_HANDLERS = {
    "search_vehicle_by_plate": _search_vehicle_by_plate,
    "search_vehicles": _search_vehicles,
    "search_service_records_by_job": _search_service_records_by_job,
    "create_vehicle": _plan_create_vehicle,
    "update_vehicle": _plan_update_vehicle,
    "add_service_record": _plan_add_service_record,
    "record_service_visit": _plan_record_service_visit,
    "list_service_history": _list_service_history,
    "get_warranty_info": _get_warranty_info,
    "update_warranty": _plan_update_warranty,
    "confirm_warranty_claim": _plan_confirm_warranty_claim,
    "get_service_detail": _get_service_detail,
    "count_vehicles": _count_vehicles,
    "count_service_records": _count_service_records,
    "report_service_totals": _report_service_totals,
    "report_period_summary": _report_period_summary,
    "report_top_jobs": _report_top_jobs,
    "report_vehicles_under_warranty": _report_vehicles_under_warranty,
    "report_part_usage": _report_part_usage,
    "report_activity_summary": _report_activity_summary,
}

_EXECUTORS = {
    "create_vehicle": _exec_create_vehicle,
    "update_vehicle": _exec_update_vehicle,
    "add_service_record": _exec_add_service_record,
    "record_service_visit": _exec_record_service_visit,
    "update_warranty": _exec_update_warranty,
    "confirm_warranty_claim": _exec_confirm_warranty_claim,
}


def plan_tool(name: str, arguments: dict, session):
    """Plan a tool call. Returns ReadResult or PendingConfirmation."""
    handler = _PLAN_HANDLERS.get(name)
    if handler is None:
        raise ValidationError(f"Tool tidak dikenal: {name}")
    return handler(arguments, session)


def execute_mutation(name: str, arguments: dict, session) -> str:
    """Execute a confirmed mutation via the service layer."""
    executor = _EXECUTORS.get(name)
    if executor is None:
        raise ValidationError(f"Tool mutasi tidak dikenal: {name}")
    return executor(arguments, session)




