"""Conversation orchestration: the DeepSeek tool-calling loop.

Read tools are executed immediately and their results fed back to the model.
Mutation tools produce a pending confirmation (a one-time token) that the bot
surfaces to the user; execution happens only after explicit confirmation.
"""

import json
import logging
import threading
from dataclasses import dataclass
from typing import Optional

from ai.context import ConversationHistory
from ai.errors import AIError, AIInvalidResponseError, AIProviderError
from ai.tools import (
    SYSTEM_PROMPT,
    TOOL_SCHEMAS,
    PendingAction,
    PendingConfirmation,
    PendingStore,
    ReadResult,
    execute_mutation,
    plan_tool,
)
from services.exceptions import ServiceError

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 6
MAX_TOOL_CALLS_PER_RESPONSE = 8


@dataclass
class OrchestratorResult:
    reply: str
    pending_action: Optional[PendingAction] = None


class AIOrchestrator:
    """Drives a single-turn tool-calling conversation against DeepSeek."""

    def __init__(self, provider, pending_store: Optional[PendingStore] = None):
        self._provider = provider
        self._pending = pending_store or PendingStore()
        # Serializes execute_pending so a double-click on the same confirmation
        # button (concurrent callback) cannot save the mutation twice.
        self._exec_lock = threading.Lock()

    @property
    def pending_store(self) -> PendingStore:
        return self._pending

    def _finalize_pending(self, user_id, history, user_text, pending_steps, pending_summaries) -> OrchestratorResult:
        summary = "\n\n".join(pending_summaries)
        action = self._pending.add(user_id, pending_steps, summary)
        history.add("user", user_text)
        return OrchestratorResult(reply=summary, pending_action=action)

    async def handle_message(self, user_text: str, session, history: ConversationHistory, user_id: int) -> OrchestratorResult:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history.as_list())
        messages.append({"role": "user", "content": user_text})

        pending_steps: list = []
        pending_summaries: list = []

        for _ in range(MAX_TOOL_ITERATIONS):
            try:
                response = await self._provider.chat(messages, tools=TOOL_SCHEMAS)
            except (AIProviderError, AIInvalidResponseError) as exc:
                return OrchestratorResult(reply=f"❌ {exc}")

            tool_calls = response.get("tool_calls") or []
            content = response.get("content") or ""

            if len(tool_calls) > MAX_TOOL_CALLS_PER_RESPONSE:
                return OrchestratorResult(reply="Terlalu banyak permintaan tool dalam satu pesan.")

            if not tool_calls:
                if pending_steps:
                    return self._finalize_pending(user_id, history, user_text, pending_steps, pending_summaries)
                history.add("user", user_text)
                history.add("assistant", content)
                return OrchestratorResult(reply=content)

            messages.append(
                {"role": "assistant", "content": content or None, "tool_calls": tool_calls}
            )

            for tc in tool_calls:
                name = tc["function"]["name"]
                try:
                    arguments = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    messages.append(
                        {"role": "tool", "tool_call_id": tc["id"], "content": "Error: argumen tool bukan JSON valid."}
                    )
                    continue

                try:
                    outcome = plan_tool(name, arguments, session)
                except ServiceError as exc:
                    outcome = ReadResult(f"Error: {exc}")

                if isinstance(outcome, PendingConfirmation):
                    pending_steps.append({"tool": outcome.tool_name, "arguments": outcome.arguments})
                    pending_summaries.append(outcome.summary)
                    messages.append(
                        {"role": "tool", "tool_call_id": tc["id"], "content": f"[Menunggu konfirmasi] {outcome.summary}"}
                    )
                else:
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": outcome.data})

            # H6A: record_service_visit is a complete atomic operation. Once it
            # is the only pending step, the model's subsequent final answer would
            # be discarded anyway, so return immediately without another model
            # round-trip. Legacy multi-step flows (create_vehicle +
            # add_service_record, etc.) are unaffected by this check.
            if pending_steps and all(s["tool"] == "record_service_visit" for s in pending_steps):
                return self._finalize_pending(user_id, history, user_text, pending_steps, pending_summaries)

        if pending_steps:
            return self._finalize_pending(user_id, history, user_text, pending_steps, pending_summaries)
        return OrchestratorResult(reply="Maaf, saya tidak dapat menyelesaikan permintaan ini.")

    def execute_pending(self, token: str, session, user_id: int) -> str:
        """Execute a confirmed pending action atomically (one or more steps).

        All steps run in a single transaction: on any failure the whole action
        is rolled back and the exception is re-raised, so callers can report
        failure accurately (never "success" on a failed execution). The token
        is removed only after a successful commit, so a failed save keeps the
        draft available for a retry instead of losing the user's input.
        """
        with self._exec_lock:
            action = self._pending.get(token, user_id)
            if action is None:
                raise AIError("Konfirmasi tidak valid, kedaluwarsa, atau bukan milik Anda.")

            results = []
            try:
                for step in action.steps:
                    tool_name = step["tool"]
                    arguments = step["arguments"]
                    result_text = execute_mutation(tool_name, arguments, session)
                    results.append(f"✅ {result_text}")
                session.commit()
            except ServiceError:
                session.rollback()
                raise
            except Exception:
                logger.exception("Gagal mengeksekusi pending action")
                session.rollback()
                raise

            # Remove only on success; a failed save keeps the draft for a retry.
            self._pending.pop(token, user_id)
            return "\n\n".join(results)
