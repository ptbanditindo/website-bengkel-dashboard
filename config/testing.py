"""Backend connection tests for Telegram / DeepSeek / Gemini (real calls).

Automated tests must monkeypatch these functions; they never run against real
accounts or production keys.
"""

import asyncio
import json
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


def test_gemini_key(key: str) -> dict:
    key = (key or "").strip()
    if not key:
        return {"valid": False, "error": "API key kosong."}
    try:
        import os
        from openai import AsyncOpenAI
        model = os.getenv("GEMINI_MODEL") or "gemini-2.0-flash"
        client = AsyncOpenAI(api_key=key, base_url="https://generativelanguage.googleapis.com/v1beta/openai/", timeout=15.0)
        asyncio.run(client.chat.completions.create(model=model, messages=[{"role": "user", "content": "ping"}]))
        return {"valid": True}
    except Exception as e:
        return {"valid": False, "error": str(e)}
