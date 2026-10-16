"""Runtime AI components (created once, shared across handlers)."""

from ai.context import ConversationStore
from ai.orchestrator import AIOrchestrator
from ai.providers import DeepSeekProvider, GeminiImageProvider
from ai.tools import PendingStore, PhotoDraftStore


class AIRuntime:
    def __init__(self):
        self.deepseek = DeepSeekProvider()
        self.gemini = GeminiImageProvider()
        self.pending_store = PendingStore()
        self.photo_drafts = PhotoDraftStore()
        self.orchestrator = AIOrchestrator(self.deepseek, self.pending_store)
        self.conversations = ConversationStore()


_runtime = AIRuntime()


def get_runtime() -> AIRuntime:
    return _runtime


def reset_runtime() -> None:
    global _runtime
    _runtime = AIRuntime()
