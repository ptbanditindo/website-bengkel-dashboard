"""Bounded, per-user conversation history.

History stores only user/assistant/tool messages (never API keys or secrets).
"""

from dataclasses import dataclass, field


@dataclass
class ConversationHistory:
    """A bounded list of conversation messages."""

    max_messages: int = 20
    messages: list = field(default_factory=list)

    def add(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})
        self._trim()

    def extend(self, items: list) -> None:
        self.messages.extend(items)
        self._trim()

    def _trim(self) -> None:
        overflow = len(self.messages) - self.max_messages
        if overflow > 0:
            del self.messages[0:overflow]

    def as_list(self) -> list:
        return list(self.messages)

    def clear(self) -> None:
        self.messages.clear()


class ConversationStore:
    """Per-user conversation history store (isolates users from each other)."""

    def __init__(self):
        self._histories = {}

    def get(self, user_id) -> ConversationHistory:
        if user_id not in self._histories:
            self._histories[user_id] = ConversationHistory()
        return self._histories[user_id]

    def reset(self, user_id) -> None:
        self._histories.pop(user_id, None)
