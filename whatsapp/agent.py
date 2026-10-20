"""WhatsApp CS AI engine (separate from the Telegram AI engine).

Restricted tools only: read public data from the main DB and write only to the
WhatsApp DB. Security rules are hardcoded and cannot be disabled by an editable
prompt.
"""

import json
import logging

from ai.providers import build_chat_provider
from services.exceptions import ServiceError
from sqlalchemy.exc import SQLAlchemyError
from whatsapp.services import (
    ArrivalService,
    ContactService,
    MatchingService,
    PriceService,
    QuestionService,
    SettingsService,
)

logger = logging.getLogger(__name__)

NL = chr(10)

# Safe fallbacks for main-database read failures. Must never fabricate data,
# never escalate, and never write/delete anything on the main database.
DB_UNAVAILABLE_REPLY = "Maaf, data kendaraan atau riwayat servis belum dapat diperiksa saat ini. Silakan coba lagi nanti."
DB_UNAVAILABLE_TOOL = "GAGAL_MEMBACA_DATABASE: data tidak dapat dibaca saat ini (kesalahan sistem, bukan hasil pencarian kosong)."
SAVE_FAILED_REPLY = "Maaf, data Anda belum dapat disimpan saat ini. Silakan coba lagi nanti."
SAVE_FAILED_TOOL = "GAGAL_MENYIMPAN: data tidak dapat disimpan saat ini (kesalahan sistem)."
DEFAULT_SHOP_NAME = "Dava Radiator"


def _shop_name(settings) -> str:
    """Shop name for greetings/persona: dashboard name if set, else a safe default."""
    name = (getattr(settings, "nama_bengkel", None) or "").strip()
    return name or DEFAULT_SHOP_NAME


def _rollback_safe(session) -> None:
    """Roll back a session after a failed read. Cleanup only — never raises."""
    try:
        session.rollback()
    except Exception:  # noqa: BLE001 — cleanup must not mask the original failure
        pass


WA_SECURITY_RULES = """ATURAN KEAMANAN (wajib, tidak bisa dinonaktifkan):
- Kamu adalah customer service bengkel via WhatsApp.
- PRIORITAS: permintaan TERBARU (pesan pelanggan saat ini) selalu diproses lebih dulu dan menjadi fokus utama jawaban. Jangan membawa kebutuhan lama ke perhitungan permintaan baru.
- issue_summary pada konteks hanyalah RIWAYAT kebutuhan lama, BUKAN pekerjaan yang disetujui untuk kunjungan saat ini.
- Selesaikan permintaan terbaru sampai tuntas (rincian harga, total hanya dari komponen yang valid, tanya info kendaraan yang masih kurang). Setelah itu, BOLEH konfirmasi kebutuhan lama SEKALI dengan pertanyaan yang jelas. Jangan ulangi konfirmasi pada tiap balasan, jangan ulangi jika pelanggan sudah menjawab, dan jangan anggap pelanggan sudah menyetujui pekerjaan lama.
- Hanya gunakan tool yang disediakan. JANGAN mengarang harga, stok, jam operasional, riwayat servis, atau status kendaraan.
- Saat pelanggan bertanya harga jasa/part, WAJIB panggil tool get_jasa_price / get_part_price dan jawab pakai angka dari tool.
- Jika pekerjaan yang ditanyakan lazim membutuhkan part/bahan (mis. ganti oli), periksa harga JASA dan harga PART/bahan terkait sebelum memberi estimasi total. Untuk ganti oli mesin, panggil get_jasa_price untuk jasa ganti oli dan get_part_price("oli mesin").
- Cek stok lewat check_stock jika pelanggan menanyakan ketersediaan atau jika jawaban membutuhkan info stok.
- Jangan mengarang harga, stok, kuantitas, atau biaya tambahan. Ambil semua angka dari tool.
- Jika harga jasa atau part tidak tersedia, nyatakan komponen mana yang belum diketahui. Jangan menyajikan total pasti seolah-olah lengkap.
- Bedakan harga satuan dari total (total = satuan x jumlah yang diperlukan). Jangan mengasumsikan kapasitas/volume oli atau jumlah part jika belum dikonfirmasi pelanggan.
- Untuk beberapa pekerjaan, jumlahkan hanya komponen yang relevan dengan pekerjaan yang disetujui pelanggan; permintaan lama yang belum disetujui tidak boleh ikut diestimasi.
- JAWAB hanya berdasarkan hasil tool (data stok/harga asli). JANGAN mengarang padanan/alias barang. "Uppertank" BUKAN sinonim "Tutup Radiator", perlakukan sebagai part yang berbeda.
- Jika nama part tidak ditemukan di stok (tool bilang tidak terdaftar/tidak diketahui), jelaskan bahwa data part tersebut belum tersedia lalu arahkan ke owner via tool escalate_to_owner. JANGAN menebak atau memilih barang lain sebagai padanan.
- Jika pertanyaan harga ambigu/terlalu umum (mis. "service radiator"), tetap panggil tool lalu tampilkan daftar pilihan yang cocok beserta harganya; jangan langsung eskalasi.
- Jika pertanyaan berisi beberapa hal dan sebagian tidak ada di data, JAWAB dulu bagian yang bisa dijawab (mis. harga jasa), lalu jelaskan item yang tidak tersedia dan minta info tambahan. JANGAN eskalasi seluruh pertanyaan hanya karena satu item tidak ditemukan.
- JANGAN mengungkap jumlah stok, harga modal/beli, keuntungan/margin, laporan keuangan, atau data pelanggan lain.
- Estimasi harga selalu perkiraan dan bukan harga final; arahkan pelanggan datang untuk pemeriksaan.
- Rencana kedatangan hanyalah rencana, bukan bukti pelanggan benar-benar datang.
- Saat pelanggan memutuskan pekerjaan untuk kunjungan ini (mis. "ganti oli saja" atau "ganti oli + servis radiator"), simpan keputusan itu melalui tool save_arrival_plan pada kolom catatan, dan anggap tersimpan hanya jika tool mengonfirmasi berhasil.
- Gunakan tool escalate_to_owner HANYA jika: pelanggan eksplisit minta bicara manusia, ATAU tidak ada satu pun bagian pertanyaan yang bisa dijawab dari tool, ATAU identitas/harga part tidak terverifikasi.
- Jika pelanggan tampak frustasi atau gagal identifikasi (nama/plat tidak cocok berulang kali), tawarkan/gunakan tool escalate_to_owner.
- Jangan mengaku bisa mengubah data servis, stok, atau transaksi.
"""


def build_system_prompt(settings) -> str:
    lines = [
        "Kamu adalah CS bengkel: " + _shop_name(settings) + ".",
        "Alamat: " + (settings.alamat or "belum diatur") + ".",
        "Jam operasional: " + (settings.jam_operasional or "belum diatur") + ".",
        "Lokasi: " + (settings.maps_link or "belum diatur") + ".",
        "",
    ]
    if settings.agent_prompt:
        lines.append("Instruksi tambahan pemilik:")
        lines.append(settings.agent_prompt)
        lines.append("")
    lines.append(WA_SECURITY_RULES)
    return NL.join(lines)


def _schema(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


def _str_prop(desc):
    return {"type": "string", "description": desc}


def _int_prop(desc):
    return {"type": "integer", "description": desc}


TOOL_SCHEMAS = [
    _schema("lookup_customer", "Cocokkan nomor WhatsApp dengan kendaraan terdaftar milik pelanggan.", {}, []),
    _schema("lookup_by_plate", "Identifikasi pelanggan lewat plat + nama (keduanya wajib cocok).", {
        "nopol": _str_prop("Plat nomor kendaraan"),
        "nama": _str_prop("Nama pemilik yang diketik pelanggan"),
    }, ["nopol", "nama"]),
    _schema("get_service_history", "Riwayat servis kendaraan milik pelanggan (tanpa data keuangan).", {"vehicle_id": _int_prop("ID kendaraan")}, ["vehicle_id"]),
    _schema("check_stock", "Cek apakah suatu part tersedia (tanpa jumlah stok).", {"nama_part": _str_prop("Nama part")}, ["nama_part"]),
    _schema("get_part_price", "Harga jual suatu part.", {"nama_part": _str_prop("Nama part")}, ["nama_part"]),
    _schema("get_jasa_price", "Harga jasa servis.", {"nama_jasa": _str_prop("Nama jasa")}, ["nama_jasa"]),
    _schema("save_memory", "Simpan/perbarui memori pelanggan (nama, plat, jenis, tahun, keluhan).", {
        "nama": _str_prop("Nama (opsional)"),
        "plat": _str_prop("Plat nomor (opsional)"),
        "jenis_mobil": _str_prop("Jenis mobil (opsional)"),
        "tahun_mobil": _int_prop("Tahun mobil (opsional)"),
        "issue_summary": _str_prop("Keluhan/kebutuhan (opsional)"),
    }, []),
    _schema("save_arrival_plan", "Catat rencana kedatangan pelanggan beserta pekerjaan yang dipilih untuk kunjungan ini.", {
        "rencana_hari": _str_prop("hari ini / besok / tanggal (opsional)"),
        "tanggal": _str_prop("YYYY-MM-DD (opsional)"),
        "waktu_perkiraan": _str_prop("Jam perkiraan (opsional)"),
        "catatan": _str_prop("Pekerjaan yang dipilih untuk kunjungan ini (mis. 'ganti oli saja' / 'ganti oli + servis radiator')"),
    }, []),
    _schema("escalate_to_owner", "Teruskan pertanyaan ke owner karena AI tidak bisa menjawab.", {"alasan": _str_prop("Alasan eskalasi")}, ["alasan"]),
]


def run_restricted_tool(name, args, contact, wa_session, main_session) -> str:
    if name == "lookup_customer":
        try:
            matches = MatchingService(main_session).match_by_wa_number(contact.wa_number)
            if not matches and contact.linked_vehicle_id:
                v = MatchingService(main_session).get_vehicle(contact.linked_vehicle_id)
                if v is not None:
                    matches = [v]
        except SQLAlchemyError as e:
            _rollback_safe(main_session)
            logger.error("[debug-deepseek] db_unavailable tool=lookup_customer error=%s", e)
            return DB_UNAVAILABLE_TOOL
        if not matches:
            return "Belum ada kendaraan terdaftar untuk nomor ini."
        return NL.join([
            "Kendaraan id=%s, plat=%s, nama=%s, jenis=%s, tahun=%s" % (v.id, v.nopol, v.nama_client or "-", v.jenis_mobil or "-", v.tahun_mobil or "-")
            for v in matches
        ])
    if name == "lookup_by_plate":
        try:
            vehicle = MatchingService(main_session).match_by_plate(str(args.get("nopol", "")))
        except SQLAlchemyError as e:
            _rollback_safe(main_session)
            logger.error("[debug-deepseek] db_unavailable tool=lookup_by_plate error=%s", e)
            return DB_UNAVAILABLE_TOOL
        if vehicle is None:
            return "Plat tidak ditemukan di database."
        if not MatchingService._names_match(str(args.get("nama", "")), vehicle.nama_client or ""):
            return "Nama tidak cocok dengan plat tersebut."
        ContactService(wa_session).update_memory(
            contact.id,
            linked_vehicle_id=vehicle.id,
            linked_vehicle_nopol=vehicle.nopol,
            nama=vehicle.nama_client,
            plat=vehicle.nopol,
            jenis_mobil=vehicle.jenis_mobil,
            tahun_mobil=vehicle.tahun_mobil,
        )
        wa_session.commit()
        return "Kendaraan terverifikasi: plat=%s, nama=%s, jenis=%s, tahun=%s (id=%s)" % (
            vehicle.nopol, vehicle.nama_client or "-", vehicle.jenis_mobil or "-", vehicle.tahun_mobil or "-", vehicle.id,
        )
    if name == "get_service_history":
        vehicle_id = args.get("vehicle_id")
        try:
            vehicle_id = int(vehicle_id)
        except (TypeError, ValueError):
            return "ID kendaraan tidak valid."
        try:
            authorized = (contact.linked_vehicle_id == vehicle_id)
            history = MatchingService(main_session).service_history(vehicle_id, contact.wa_number, authorized=authorized)
        except SQLAlchemyError as e:
            _rollback_safe(main_session)
            logger.error("[debug-deepseek] db_unavailable tool=get_service_history error=%s", e)
            return DB_UNAVAILABLE_TOOL
        except ServiceError as e:
            return str(e)
        if not history:
            return "Belum ada riwayat servis."
        return NL.join([
            "- %s: pekerjaan=%s; part=%s; catatan=%s; garansi_sampai=%s; status_klaim=%s" % (
                h["waktu"],
                ", ".join(h["pekerjaan"]) or "-",
                ", ".join(h["part"]) or "-",
                h["catatan"] or "-",
                h.get("garansi_sampai") or "tidak ada",
                h.get("status_klaim") or "-",
            )
            for h in history
        ])
    if name == "check_stock":
        try:
            return PriceService(main_session).check_stock(str(args.get("nama_part", "")))
        except SQLAlchemyError as e:
            _rollback_safe(main_session)
            logger.error("[debug-deepseek] db_unavailable tool=check_stock error=%s", e)
            return DB_UNAVAILABLE_TOOL
    if name == "get_part_price":
        try:
            price = PriceService(main_session).part_price(str(args.get("nama_part", "")))
        except SQLAlchemyError as e:
            _rollback_safe(main_session)
            logger.error("[debug-deepseek] db_unavailable tool=get_part_price error=%s", e)
            return DB_UNAVAILABLE_TOOL
        if isinstance(price, str):
            return price
        return ("Harga jual part sekitar Rp%s (perkiraan, bisa berubah)." % ("{0:,.0f}".format(price).replace(",", "."))) if price is not None else "Harga part tidak diketahui."
    if name == "get_jasa_price":
        try:
            price = PriceService(main_session).jasa_price(str(args.get("nama_jasa", "")))
        except SQLAlchemyError as e:
            _rollback_safe(main_session)
            logger.error("[debug-deepseek] db_unavailable tool=get_jasa_price error=%s", e)
            return DB_UNAVAILABLE_TOOL
        if isinstance(price, str):
            return price
        return ("Harga jasa sekitar Rp%s (perkiraan, bisa berubah)." % ("{0:,.0f}".format(price).replace(",", "."))) if price is not None else "Harga jasa tidak diketahui."
    if name == "save_memory":
        fields = {k: v for k, v in args.items() if v is not None and k in ("nama", "plat", "jenis_mobil", "tahun_mobil", "issue_summary")}
        try:
            ContactService(wa_session).update_memory(contact.id, **fields)
            wa_session.commit()
        except SQLAlchemyError as e:
            _rollback_safe(wa_session)
            logger.error("[debug-deepseek] save_failed tool=save_memory error=%s", e)
            return SAVE_FAILED_TOOL
        return "Memori tersimpan."
    if name == "save_arrival_plan":
        try:
            ArrivalService(wa_session).create_plan(
                contact.id,
                rencana_hari=args.get("rencana_hari"),
                tanggal=args.get("tanggal"),
                waktu_perkiraan=args.get("waktu_perkiraan"),
                catatan=args.get("catatan"),
            )
        except SQLAlchemyError as e:
            _rollback_safe(wa_session)
            logger.error("[debug-deepseek] save_failed tool=save_arrival_plan error=%s", e)
            return SAVE_FAILED_TOOL
        return "Rencana kedatangan tersimpan."
    if name == "escalate_to_owner":
        try:
            QuestionService(wa_session).create(contact.id, contact.wa_number, contact.context_summary or "", alasan=args.get("alasan"))
        except SQLAlchemyError as e:
            _rollback_safe(wa_session)
            logger.error("[debug-deepseek] save_failed tool=escalate_to_owner error=%s", e)
            return SAVE_FAILED_TOOL
        return "Pertanyaan diteruskan ke owner."
    return "Tool tidak dikenal."


class WhatsAppAgent:
    def __init__(self):
        self._provider = build_chat_provider()

    async def reply(self, wa_number, text, wa_session, main_session) -> str:
        settings = SettingsService(wa_session).get()
        if text.strip().lower() in {"halo", "hai", "hi", "pagi", "siang", "sore", "malam"}:
            logger.info("[debug-deepseek] greeting_fast_path text_length=%d", len(text))
            return "Halo saya dengan " + _shop_name(settings) + ", ada yang bisa kami bantu?"
        contact = ContactService(wa_session).get_or_create(wa_number)
        ContactService(wa_session).update_memory(contact.id, context_summary=(text[:400]))
        wa_session.commit()
        system = build_system_prompt(settings)
        try:
            context = self._context(contact, main_session)
        except SQLAlchemyError as e:
            _rollback_safe(main_session)
            logger.error("[debug-deepseek] db_unavailable stage=context error=%s", e)
            return DB_UNAVAILABLE_REPLY
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "KONTEKS KONTAK:" + NL + context + NL + NL + "PESAN PELANGGAN:" + NL + text},
        ]
        if not self._provider.configured:
            logger.error("[debug-deepseek] skipped configured=false")
            return self._escalate(contact, wa_session, "AI tidak dikonfigurasi.")
        logger.info("[debug-deepseek] agent_start contact=%s text_length=%d", wa_number, len(text))
        for iteration in range(3):
            try:
                resp = await self._provider.chat(messages, tools=TOOL_SCHEMAS)
            except Exception as e:
                logger.error("[debug-deepseek] agent_error iteration=%d type=%s", iteration + 1, type(e).__name__)
                logger.error("WhatsApp agent error: %s", e)
                return self._escalate(contact, wa_session, "AI gagal menjawab.")
            tool_calls = resp.get("tool_calls") or []
            content = resp.get("content") or ""
            logger.info("[debug-deepseek] agent_result iteration=%d content_length=%d tool_calls=%d", iteration + 1, len(content), len(tool_calls))
            if not tool_calls:
                logger.info("[debug-deepseek] agent_complete reply_length=%d", len(content))
                return content
            messages.append({"role": "assistant", "content": content or None, "tool_calls": tool_calls})
            for tc in tool_calls:
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = run_restricted_tool(tc["function"]["name"], args, contact, wa_session, main_session)
                if result == DB_UNAVAILABLE_TOOL:
                    _rollback_safe(main_session)
                    return DB_UNAVAILABLE_REPLY
                if result == SAVE_FAILED_TOOL:
                    _rollback_safe(wa_session)
                    return SAVE_FAILED_REPLY
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
                if tc["function"]["name"] == "escalate_to_owner":
                    return "Maaf, saya belum bisa menjawab pertanyaan ini. Pertanyaan Anda akan diteruskan ke pemilik bengkel."
        return self._escalate(contact, wa_session, "AI tidak dapat menyelesaikan permintaan.")

    def _context(self, contact, main_session) -> str:
        matches = MatchingService(main_session).match_by_wa_number(contact.wa_number)
        if not matches and contact.linked_vehicle_id:
            v = MatchingService(main_session).get_vehicle(contact.linked_vehicle_id)
            if v is not None:
                matches = [v]
        lines = [
            "Nomor WhatsApp: " + contact.wa_number,
            "Nama: " + (contact.nama or "belum diketahui"),
            "Plat: " + (contact.plat or "belum diketahui"),
            "Jenis: " + (contact.jenis_mobil or "belum diketahui"),
            "Tahun: " + (str(contact.tahun_mobil) if contact.tahun_mobil else "belum diketahui"),
            "Riwayat kebutuhan sebelumnya (belum tentu dikerjakan sekarang): " + (contact.issue_summary or "belum ada"),
            "Kendaraan terdaftar: " + (str([MatchingService.public_vehicle(v) for v in matches]) if matches else "belum ada"),
        ]
        return NL.join(lines)

    def _escalate(self, contact, wa_session, alasan) -> str:
        try:
            QuestionService(wa_session).create(contact.id, contact.wa_number, contact.context_summary or "", alasan=alasan)
        except SQLAlchemyError as e:
            _rollback_safe(wa_session)
            logger.error("[debug-deepseek] escalate_save_failed error=%s", e)
            return SAVE_FAILED_REPLY
        return "Maaf, saya belum bisa menjawab pertanyaan ini. Pertanyaan Anda akan diteruskan ke pemilik bengkel."
