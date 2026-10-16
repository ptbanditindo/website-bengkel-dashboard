"""Tests for conversation history management."""

from ai.context import ConversationHistory, ConversationStore


def test_history_trims_to_max():
    h = ConversationHistory(max_messages=3)
    for i in range(5):
        h.add("user", f"msg{i}")
    assert len(h.as_list()) == 3
    assert h.as_list()[0]["content"] == "msg2"


def test_history_clear():
    h = ConversationHistory()
    h.add("user", "hi")
    h.clear()
    assert h.as_list() == []


def test_store_isolates_users():
    store = ConversationStore()
    a = store.get(1)
    b = store.get(2)
    a.add("user", "hi from a")
    assert len(b.as_list()) == 0
    store.reset(1)
    assert store.get(1) is not a
