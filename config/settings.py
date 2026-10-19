"""Secure server-side store for integration credentials and AI provider config.

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

SECRET_KEYS = ("telegram_bot_token", "deepseek_api_key", "openrouter_api_key")
CONFIG_KEYS = ("ai_provider", "openrouter_chat_model", "openrouter_vision_model")

_ENV_MAP = {
    "telegram_bot_token": "TELEGRAM_TOKEN",
    "deepseek_api_key": "DEEPSEEK_API_KEY",
    "openrouter_api_key": "OPENROUTER_API_KEY",
    "ai_provider": "AI_PROVIDER",
    "openrouter_chat_model": "OPENROUTER_CHAT_MODEL",
    "openrouter_vision_model": "OPENROUTER_VISION_MODEL",
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


def set_config(key: str, value: str) -> None:
    """Persist a non-secret AI config value (empty string removes the key)."""
    if key not in CONFIG_KEYS:
        raise ValueError("kunci konfigurasi tidak dikenal")
    value = (value or "").strip()
    with _lock:
        data = _load()
        if value:
            data[key] = value
        else:
            data.pop(key, None)
        _save(data)


def get_config(key: str) -> str:
    if key not in CONFIG_KEYS:
        raise ValueError("kunci konfigurasi tidak dikenal")
    with _lock:
        return (_load().get(key) or "")


def delete_config(key: str) -> None:
    if key not in CONFIG_KEYS:
        raise ValueError("kunci konfigurasi tidak dikenal")
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


def config_status(key: str) -> dict:
    stored = get_config(key)
    env_key = _ENV_MAP[key]
    active = os.getenv(env_key) or ""
    return {
        "stored": stored,
        "active": active,
        "needs_restart": bool(stored) and stored != active,
    }


def status() -> dict:
    return {
        "telegram": provider_status("telegram_bot_token"),
        "deepseek": provider_status("deepseek_api_key"),
        "openrouter": provider_status("openrouter_api_key"),
        "ai_provider": config_status("ai_provider"),
        "openrouter_chat_model": config_status("openrouter_chat_model"),
        "openrouter_vision_model": config_status("openrouter_vision_model"),
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
