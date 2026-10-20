"""AI Bengkel - Kontrol Layanan (Python version of run_all.bat).

Usage:
    python run_all.py                         # menu interaktif
    python run_all.py start|restart|stop|status|dashboard
"""
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOGS = ROOT / "logs"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

SERVICES = [
    {
        "key": "api",
        "label": "API + Dashboard",
        "url": "http://127.0.0.1:8000/ui",
        "cmd": [sys.executable, "run_api.py"],
        "out": LOGS / "api.log",
        "err": LOGS / "api.err.log",
        "pidfile": LOGS / "api.pid",
    },
    {
        "key": "telegram",
        "label": "Bot Telegram",
        "cmd": [sys.executable, "main.py"],
        "out": LOGS / "telegram.log",
        "err": LOGS / "telegram.err.log",
        "pidfile": LOGS / "telegram.pid",
    },
    {
        "key": "whatsapp",
        "label": "Gateway WhatsApp (Baileys)",
        "cmd": ["node", "gateway/whatsapp_bridge.js"],
        "out": LOGS / "whatsapp.log",
        "err": LOGS / "whatsapp.err.log",
        "pidfile": LOGS / "whatsapp.pid",
    },
]


def _is_running(pid):
    if not pid:
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        return str(pid) in out
    except Exception:
        return False


def check_prereqs():
    errors = []
    if not (ROOT / ".env").exists():
        errors.append("File .env tidak ditemukan. Salin .env.example menjadi .env.")
    if shutil.which("node") is None:
        errors.append("Node.js tidak ditemukan di PATH.")
    return errors


def stop_all():
    for svc in SERVICES:
        pidfile = svc["pidfile"]
        pid = None
        if pidfile.exists():
            try:
                pid = int(pidfile.read_text().strip())
            except Exception:
                pid = None
        if pid:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True, timeout=15,
            )
        if pidfile.exists():
            try:
                pidfile.unlink()
            except OSError:
                pass


def start_all():
    LOGS.mkdir(exist_ok=True)
    stop_all()
    time.sleep(1)
    for svc in SERVICES:
        out_f = open(svc["out"], "w", encoding="utf-8")
        err_f = open(svc["err"], "w", encoding="utf-8")
        p = subprocess.Popen(
            svc["cmd"], cwd=ROOT, stdout=out_f, stderr=err_f,
            creationflags=CREATE_NO_WINDOW,
        )
        out_f.close()
        err_f.close()
        svc["pidfile"].write_text(str(p.pid))
        print("  [started] %s (PID %d)" % (svc["label"], p.pid))


def status():
    for svc in SERVICES:
        pid = None
        if svc["pidfile"].exists():
            try:
                pid = int(svc["pidfile"].read_text().strip())
            except Exception:
                pid = None
        running = _is_running(pid)
        print("  %-10s: %s%s" % (
            svc["key"],
            "RUNNING" if running else "STOPPED",
            " (PID %d)" % pid if pid else "",
        ))


def open_dashboard():
    webbrowser.open("http://127.0.0.1:8000/ui")
    print("Dashboard dibuka di browser: http://127.0.0.1:8000/ui")


def menu():
    while True:
        print("=" * 50)
        print("  AI Bengkel - Kontrol Layanan")
        print("=" * 50)
        print("  1. Start semua layanan")
        print("  2. Restart semua layanan")
        print("  3. Stop semua layanan")
        print("  4. Buka Dashboard (browser)")
        print("  5. Cek status layanan")
        print("  6. Keluar")
        print("=" * 50)
        choice = input("Pilih nomor (1-6): ").strip()
        if choice in ("1", "2"):
            errors = check_prereqs()
            if errors:
                for e in errors:
                    print("[ERROR] " + e)
                continue
            print("Menjalankan layanan di latar belakang...")
            start_all()
            print("Selesai. Log tersimpan di folder logs.")
        elif choice == "3":
            stop_all()
            print("Semua layanan dihentikan.")
        elif choice == "4":
            open_dashboard()
        elif choice == "5":
            status()
        elif choice == "6":
            sys.exit(0)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd in ("start", "restart"):
            errors = check_prereqs()
            if errors:
                for e in errors:
                    print("[ERROR] " + e)
                sys.exit(1)
            start_all()
        elif cmd == "stop":
            stop_all()
            print("Semua layanan dihentikan.")
        elif cmd == "status":
            status()
        elif cmd == "dashboard":
            open_dashboard()
        else:
            print("Gunakan: python run_all.py [start|restart|stop|status|dashboard]")
    else:
        menu()
