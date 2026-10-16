"""WhatsApp CS AI engine (separate from the Telegram AI engine).

Restricted tools only: read public data from the main DB and write only to the
WhatsApp DB. Security rules are hardcoded and cannot be disabled by an editable
prompt.
"""

import json
import logging

from ai.providers import DeepSeekProvider
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

WA_SECURITY_RULES = """ATURAN KEAMANAN (wajib, tidak bisa dinonaktifkan):
- Kamu adalah customer service bengkel via WhatsApp.
- Hanya gunakan tool yang disediakan. JANGAN mengarang harga, stok, jam operasional, riwayat servis, atau status kendaraan.
- JANGAN mengungkap jumlah stok, harga modal/beli, keuntungan/margin, laporan keuangan, atau data pelanggan lain.
- Estimasi harga selalu perkiraan dan bukan harga final; arahkan pelanggan datang untuk pemeriksaan.
- Rencana kedatangan hanyalah rencana, bukan bukti pelanggan benar-benar datang.
- Jika tidak tahu, data tidak tersedia, konflik, atau pelanggan minta manusia, gunakan tool eskalasi ke owner.
- Jangan mengaku bisa mengubah data servis, stok, atau transaksi.
"""


def build_system_prompt(settings) -> str:
    lines = [
        "Kamu adalah CS bengkel: " + (settings.nama_bengkel or "AI Bengkel") + ".",
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
    _schema("save_arrival_plan", "Catat rencana kedatangan pelanggan.", {
        "rencana_hari": _str_prop("hari ini / besok / tanggal (opsional)"),
        "tanggal": _str_prop("YYYY-MM-DD (opsional)"),
        "waktu_perkiraan": _str_prop("Jam perkiraan (opsional)"),
        "catatan": _str_prop("Catatan (opsional)"),
    }, []),
    _schema("escalate_to_owner", "Teruskan pertanyaan ke owner karena AI tidak bisa menjawab.", {"alasan": _str_prop("Alasan eskalasi")}, ["alasan"]),
]


def run_restricted_tool(name, args, contact, wa_session, main_session) -> str:
    if name == "lookup_customer":
        matches = MatchingService(main_session).match_by_wa_number(contact.wa_number)
        if not matches:
            return "Belum ada kendaraan terdaftar untuk nomor ini."
        return NL.join([
            "Kendaraan id=%s, plat=%s, nama=%s, jenis=%s, tahun=%s" % (v.id, v.nopol, v.nama_client or "-", v.jenis_mobil or "-", v.tahun_mobil or "-")
            for v in matches
        ])
    if name == "get_service_history":
        try:
            history = MatchingService(main_session).service_history(int(args.get("vehicle_id")), contact.wa_number)
        except Exception as e:
            return "Tidak dapat membaca riwayat: " + str(e)
        if not history:
            return "Belum ada riwayat servis."
        return NL.join([
            "- %s: pekerjaan=%s; part=%s; catatan=%s" % (h["waktu"], ", ".join(h["pekerjaan"]) or "-", ", ".join(h["part"]) or "-", h["catatan"] or "-")
            for h in history
        ])
    if name == "check_stock":
        return PriceService(main_session).check_stock(str(args.get("nama_part", "")))
    if name == "get_part_price":
        price = PriceService(main_session).part_price(str(args.get("nama_part", "")))
        return ("Harga jual part sekitar Rp%s (perkiraan, bisa berubah)." % ("{0:,.0f}".format(price).replace(",", "."))) if price is not None else "Harga part tidak diketahui."
    if name == "get_jasa_price":
        price = PriceService(main_session).jasa_price(str(args.get("nama_jasa", "")))
        return ("Harga jasa sekitar Rp%s (perkiraan, bisa berubah)." % ("{0:,.0f}".format(price).replace(",", "."))) if price is not None else "Harga jasa tidak diketahui."
    if name == "save_memory":
        fields = {k: v for k, v in args.items() if v is not None and k in ("nama", "plat", "jenis_mobil", "tahun_mobil", "issue_summary")}
        ContactService(wa_session).update_memory(contact.id, **fields)
        wa_session.commit()
        return "Memori tersimpan."
    if name == "save_arrival_plan":
        ArrivalService(wa_session).create_plan(
            contact.id,
            rencana_hari=args.get("rencana_hari"),
            tanggal=args.get("tanggal"),
            waktu_perkiraan=args.get("waktu_perkiraan"),
            catatan=args.get("catatan"),
        )
        return "Rencana kedatangan tersimpan."
    if name == "escalate_to_owner":
        QuestionService(wa_session).create(contact.id, contact.wa_number, contact.context_summary or "", alasan=args.get("alasan"))
        return "Pertanyaan diteruskan ke owner."
    return "Tool tidak dikenal."


class WhatsAppAgent:
    def __init__(self):
        self._provider = DeepSeekProvider()

    async def reply(self, wa_number, text, wa_session, main_session) -> str:
        contact = ContactService(wa_session).get_or_create(wa_number)
        ContactService(wa_session).update_memory(contact.id, context_summary=(text[:400]))
        wa_session.commit()
        settings = SettingsService(wa_session).get()
        system = build_system_prompt(settings)
        context = self._context(contact, main_session)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "KONTEKS KONTAK:" + NL + context + NL + NL + "PESAN PELANGGAN:" + NL + text},
        ]
        if not self._provider.configured:
            return self._escalate(contact, wa_session, "AI tidak dikonfigurasi.")
        for _ in range(4):
            try:
                resp = await self._provider.chat(messages, tools=TOOL_SCHEMAS)
            except Exception as e:
                logger.error("WhatsApp agent error: %s", e)
                return self._escalate(contact, wa_session, "AI gagal menjawab.")
            tool_calls = resp.get("tool_calls") or []
            content = resp.get("content") or ""
            if not tool_calls:
                return content
            messages.append({"role": "assistant", "content": content or None, "tool_calls": tool_calls})
            for tc in tool_calls:
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = run_restricted_tool(tc["function"]["name"], args, contact, wa_session, main_session)
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
        return self._escalate(contact, wa_session, "AI tidak dapat menyelesaikan permintaan.")

    def _context(self, contact, main_session) -> str:
        matches = MatchingService(main_session).match_by_wa_number(contact.wa_number)
        lines = [
            "Nomor WhatsApp: " + contact.wa_number,
            "Nama: " + (contact.nama or "belum diketahui"),
            "Plat: " + (contact.plat or "belum diketahui"),
            "Jenis: " + (contact.jenis_mobil or "belum diketahui"),
            "Tahun: " + (str(contact.tahun_mobil) if contact.tahun_mobil else "belum diketahui"),
            "Keluhan: " + (contact.issue_summary or "belum ada"),
            "Kendaraan terdaftar: " + (str([MatchingService.public_vehicle(v) for v in matches]) if matches else "belum ada"),
        ]
        return NL.join(lines)

    def _escalate(self, contact, wa_session, alasan) -> str:
        QuestionService(wa_session).create(contact.id, contact.wa_number, contact.context_summary or "", alasan=alasan)
        return "Maaf, saya belum bisa menjawab pertanyaan ini. Pertanyaan Anda akan diteruskan ke pemilik bengkel."
