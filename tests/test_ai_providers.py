"""Tests for AI provider selection (DeepSeek + OpenRouter) with mocks.

No real API calls are made: provider SDK clients are replaced with scripted
fakes after construction (construction itself performs no network I/O).
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai.errors import AIConfigError, AIInvalidResponseError, AIProviderError
from ai.providers import DeepSeekProvider, OpenRouterProvider, build_chat_provider
from bot.ai.image_provider import OpenRouterImageProvider, build_vision_provider


def _chat_response(content="halo", tool_calls=None):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _tool_call(tc_id, name, arguments):
    fn = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(id=tc_id, type="function", function=fn)


def _install_client(provider):
    """Replace a provider's SDK client with a scripted fake; return its create()."""
    create = AsyncMock()
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return create


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------

def test_build_chat_provider_defaults_to_deepseek(monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert isinstance(build_chat_provider(), DeepSeekProvider)


def test_build_chat_provider_selects_deepseek_explicit(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert isinstance(build_chat_provider(), DeepSeekProvider)


def test_build_chat_provider_selects_openrouter(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert isinstance(build_chat_provider(), OpenRouterProvider)


def test_build_chat_provider_rejects_unknown(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    with pytest.raises(AIConfigError):
        build_chat_provider()


# ---------------------------------------------------------------------------
# OpenRouter chat
# ---------------------------------------------------------------------------

def test_openrouter_not_configured_without_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert OpenRouterProvider().configured is False


def test_openrouter_works_without_deepseek_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    p = OpenRouterProvider(model="openai/gpt-4o-mini")
    assert p.configured is True
    assert p.model == "openai/gpt-4o-mini"


def test_openrouter_chat_uses_chat_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    p = OpenRouterProvider(model="openai/gpt-4o-mini")
    create = _install_client(p)
    create.return_value = _chat_response("ok")

    out = asyncio.run(p.chat([{"role": "user", "content": "ping"}]))

    assert out["content"] == "ok"
    assert create.await_args.kwargs["model"] == "openai/gpt-4o-mini"


def test_openrouter_chat_requires_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    p = OpenRouterProvider(model="")
    _install_client(p)

    with pytest.raises(AIConfigError):
        asyncio.run(p.chat([{"role": "user", "content": "ping"}]))


def test_openrouter_chat_normalizes_tool_calls(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    p = OpenRouterProvider(model="openai/gpt-4o-mini")
    create = _install_client(p)
    create.return_value = _chat_response(None, tool_calls=[_tool_call("t1", "lookup", '{"x": 1}')])

    out = asyncio.run(p.chat([{"role": "user", "content": "x"}], tools=[{"type": "function"}]))

    assert out["content"] == ""
    assert out["tool_calls"][0]["id"] == "t1"
    assert out["tool_calls"][0]["function"]["name"] == "lookup"
    assert create.await_args.kwargs["tool_choice"] == "auto"
    assert create.await_args.kwargs["tools"] == [{"type": "function"}]


def test_openrouter_chat_api_error(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    p = OpenRouterProvider(model="openai/gpt-4o-mini")
    create = _install_client(p)
    create.side_effect = Exception("timeout")

    with pytest.raises(AIProviderError):
        asyncio.run(p.chat([{"role": "user", "content": "x"}]))


def test_openrouter_chat_empty_response(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    p = OpenRouterProvider(model="openai/gpt-4o-mini")
    create = _install_client(p)
    create.return_value = SimpleNamespace(choices=[])

    with pytest.raises(AIInvalidResponseError):
        asyncio.run(p.chat([{"role": "user", "content": "x"}]))


# ---------------------------------------------------------------------------
# OpenRouter vision
# ---------------------------------------------------------------------------

def test_build_vision_provider_returns_openrouter(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    assert isinstance(build_vision_provider(), OpenRouterImageProvider)


def test_vision_provider_uses_vision_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    p = OpenRouterImageProvider(model="openai/gpt-4o-vision")
    assert p.model == "openai/gpt-4o-vision"


def test_vision_extract_sends_image_payload(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    p = OpenRouterImageProvider(model="openai/gpt-4o-vision")
    create = _install_client(p)
    create.return_value = _chat_response('{"plat": "B 1 ABC"}')

    out = asyncio.run(p.extract(b"\xff\xd8\xff", "image/jpeg", "baca nota"))

    assert out == '{"plat": "B 1 ABC"}'
    sent = create.await_args.kwargs
    assert sent["model"] == "openai/gpt-4o-vision"
    content = sent["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert content[0]["text"] == "baca nota"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_vision_extract_requires_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    p = OpenRouterImageProvider(model="")
    _install_client(p)

    with pytest.raises(AIConfigError):
        asyncio.run(p.extract(b"\xff\xd8\xff", "image/jpeg", "baca"))


def test_vision_extract_api_error(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    p = OpenRouterImageProvider(model="openai/gpt-4o-vision")
    create = _install_client(p)
    create.side_effect = Exception("boom")

    with pytest.raises(AIProviderError):
        asyncio.run(p.extract(b"\xff\xd8\xff", "image/jpeg", "baca"))
