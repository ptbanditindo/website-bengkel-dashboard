"""Backend connection tests for Telegram / DeepSeek / OpenRouter (real calls).

Automated tests must monkeypatch these functions; they never run against real
accounts or production keys.
"""

import asyncio
import json
import os
import urllib.request


def test_telegram_token(token: str) -> dict:
    token = (token or "").strip()
    if not token:
        return {"valid": False, "error": "Token kosong."}
    url = "https://api.telegram.org/bot" + token + "/getMe"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"valid": False, "error": str(e)}
    if data.get("ok"):
        r = data.get("result") or {}
        return {"valid": True, "username": r.get("username"), "name": r.get("first_name")}
    return {"valid": False, "error": data.get("description", "Token tidak valid.")}


def test_deepseek_key(key: str) -> dict:
    key = (key or "").strip()
    if not key:
        return {"valid": False, "error": "API key kosong."}
    try:
        from ai.providers import DeepSeekProvider
        provider = DeepSeekProvider(api_key=key)
        asyncio.run(provider.chat([{"role": "user", "content": "ping"}]))
        return {"valid": True}
    except Exception as e:
        return {"valid": False, "error": str(e)}


def test_openrouter_key(key: str) -> dict:
    key = (key or "").strip()
    if not key:
        return {"valid": False, "error": "API key kosong."}
    model = (os.getenv("OPENROUTER_CHAT_MODEL") or "").strip()
    if not model:
        return {"valid": False, "error": "OPENROUTER_CHAT_MODEL belum disetel."}
    try:
        from ai.providers import OpenRouterProvider
        provider = OpenRouterProvider(api_key=key, model=model)
        asyncio.run(provider.chat([{"role": "user", "content": "ping"}]))
        return {"valid": True}
    except Exception as e:
        return {"valid": False, "error": str(e)}
