"""Runtime AI components (created once, shared across handlers)."""

from bot.ai.context import ConversationStore
from bot.ai.orchestrator import AIOrchestrator
from ai.providers import build_chat_provider
from bot.ai.image_provider import build_vision_provider
from bot.ai.tools import PendingStore, PhotoDraftStore


class AIRuntime:
    def __init__(self):
        self.chat = build_chat_provider()
        self.vision = build_vision_provider()
        self.pending_store = PendingStore()
        self.photo_drafts = PhotoDraftStore()
        self.orchestrator = AIOrchestrator(self.chat, self.pending_store)
        self.conversations = ConversationStore()


_runtime = AIRuntime()


def get_runtime() -> AIRuntime:
    return _runtime


def reset_runtime() -> None:
    global _runtime
    _runtime = AIRuntime()
