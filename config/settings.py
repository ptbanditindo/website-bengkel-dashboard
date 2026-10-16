"""Secure server-side store for integration credentials.

Secrets are persisted to data/integration_settings.json (private, never served
as static). Endpoints return masked presence status only, never the full value.
The runtime still reads .env; stored values are the owner-managed config that
may require a restart to take effect (reported via needs_restart).
"""

import json
import os
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = PROJECT_ROOT / "data" / "integration_settings.json"

_lock = threading.Lock()

SECRET_KEYS = ("telegram_bot_token", "deepseek_api_key", "gemini_api_key")

_ENV_MAP = {
    "telegram_bot_token": "TELEGRAM_TOKEN",
    "deepseek_api_key": "DEEPSEEK_API_KEY",
    "gemini_api_key": "GEMINI_API_KEY",
}


def _load() -> dict:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, SETTINGS_PATH)


def get_all() -> dict:
    with _lock:
        return {k: v for k, v in _load().items() if k in SECRET_KEYS and v}


def get(key: str):
    return get_all().get(key)


def set(key: str, value: str) -> None:
    if key not in SECRET_KEYS:
        raise ValueError("kunci tidak dikenal")
    value = (value or "").strip()
    if not value:
        raise ValueError("nilai tidak boleh kosong")
    with _lock:
        data = _load()
        data[key] = value
        _save(data)


def delete(key: str) -> None:
    if key not in SECRET_KEYS:
        raise ValueError("kunci tidak dikenal")
    with _lock:
        data = _load()
        data.pop(key, None)
        _save(data)


def mask(value) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return value[:4] + "••••" + value[-4:]


def provider_status(key: str) -> dict:
    stored = get(key)
    env_key = _ENV_MAP[key]
    active = os.getenv(env_key) or ""
    return {
        "stored": bool(stored),
        "active": bool(active),
        "masked": mask(stored),
        "needs_restart": bool(stored) and stored != active,
    }


def status() -> dict:
    return {
        "telegram": provider_status("telegram_bot_token"),
        "deepseek": provider_status("deepseek_api_key"),
        "gemini": provider_status("gemini_api_key"),
    }


def get_internal_token() -> str:
    """Return (and lazily generate) the internal gateway auth token."""
    import secrets
    with _lock:
        data = _load()
        token = data.get("whatsapp_internal_token")
        if not token:
            token = secrets.token_hex(32)
            data["whatsapp_internal_token"] = token
            _save(data)
        return token
