"""Tests for authorization helpers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.auth import is_authorized, require_auth


def test_is_authorized(monkeypatch):
    monkeypatch.setenv("AUTHORIZED_USER_ID", "123,456")
    assert is_authorized(123) is True
    assert is_authorized("456") is True
    assert is_authorized(789) is False


def test_is_authorized_when_unset(monkeypatch):
    monkeypatch.setenv("AUTHORIZED_USER_ID", "")
    assert is_authorized(123) is False


def test_is_authorized_strips_whitespace(monkeypatch):
    monkeypatch.setenv("AUTHORIZED_USER_ID", "111, 222 , 333")
    assert is_authorized(222) is True
    assert is_authorized("333") is True
    assert is_authorized(444) is False


@pytest.mark.asyncio
async def test_require_auth_blocks_unauthorized(monkeypatch):
    monkeypatch.setattr("bot.auth.is_authorized", lambda uid: False)

    called = False

    @require_auth
    async def handler(update, context):
        nonlocal called
        called = True
        return "OK"

    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 123
    update.callback_query = None
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()

    result = await handler(update, MagicMock())

    assert result is None
    assert called is False
    update.message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_require_auth_allows_authorized(monkeypatch):
    monkeypatch.setattr("bot.auth.is_authorized", lambda uid: True)

    @require_auth
    async def handler(update, context):
        return "OK"

    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 123
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()

    result = await handler(update, MagicMock())

    assert result == "OK"
    update.message.reply_text.assert_not_awaited()
