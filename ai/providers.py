"""AI providers: DeepSeek + OpenRouter (chat/tool calling).

Both use the OpenAI-compatible SDK. API keys are read from environment
variables only; they are never logged.
"""

import logging
import os
import time

from openai import AsyncOpenAI

from ai.errors import AIConfigError, AIInvalidResponseError, AIProviderError

logger = logging.getLogger(__name__)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"


def _pick_token(usage, name):
    """Read a usage field defensively (OpenAI SDK object or plain dict)."""
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage.get(name)
    return getattr(usage, name, None)


def _usage_meta(provider_name, model, usage):
    """Normalize provider usage metadata without fabricating token counts."""
    return {
        "provider": provider_name,
        "model": model,
        "prompt_tokens": _pick_token(usage, "prompt_tokens"),
        "completion_tokens": _pick_token(usage, "completion_tokens"),
        "total_tokens": _pick_token(usage, "total_tokens"),
    }


class DeepSeekProvider:
    """DeepSeek chat provider with OpenAI-compatible tool calling."""

    def __init__(self, api_key=None, model=None, timeout=15.0, max_retries=0):
        self._api_key = api_key if api_key is not None else os.getenv("DEEPSEEK_API_KEY")
        self._model = model or os.getenv("DEEPSEEK_MODEL") or DEFAULT_DEEPSEEK_MODEL
        self._configured = bool(self._api_key)
        self._client = None
        if self._configured:
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=DEEPSEEK_BASE_URL,
                timeout=timeout,
                max_retries=max_retries,
            )

    @property
    def configured(self) -> bool:
        return self._configured

    @property
    def model(self) -> str:
        return self._model

    async def chat(self, messages, tools=None) -> dict:
        """Return ``{"content": str, "tool_calls": [...]}`` or raise AIProviderError."""
        if not self._configured:
            raise AIConfigError("DeepSeek tidak dikonfigurasi (DEEPSEEK_API_KEY kosong).")

        kwargs = {"model": self._model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        started = time.perf_counter()
        logger.info("[debug-deepseek] request model=%s messages=%d tools=%d configured=%s", self._model, len(messages), len(tools or []), self._configured)
        try:
            response = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - provider errors are surfaced to the user
            logger.error("[debug-deepseek] error duration_ms=%d type=%s", int((time.perf_counter() - started) * 1000), type(exc).__name__)
            logger.error("DeepSeek API error: %s", exc)
            raise AIProviderError(f"DeepSeek API gagal: {exc}") from exc

        logger.info("[debug-deepseek] response duration_ms=%d choices=%d", int((time.perf_counter() - started) * 1000), len(response.choices or []))

        choice = response.choices[0].message if response.choices else None
        if choice is None:
            raise AIInvalidResponseError("DeepSeek mengembalikan respons kosong.")

        tool_calls = []
        for tc in choice.tool_calls or []:
            tool_calls.append(
                {
                    "id": tc.id,
                    "type": getattr(tc, "type", None) or "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
            )
        usage = _usage_meta("deepseek", self._model, getattr(response, "usage", None))
        return {"content": choice.content or "", "tool_calls": tool_calls, "usage": usage}


class OpenRouterProvider:
    """OpenRouter chat provider with OpenAI-compatible tool calling."""

    def __init__(self, api_key=None, model=None, timeout=15.0, max_retries=0):
        self._api_key = api_key if api_key is not None else os.getenv("OPENROUTER_API_KEY")
        self._model = model or os.getenv("OPENROUTER_CHAT_MODEL") or ""
        self._configured = bool(self._api_key)
        self._client = None
        if self._configured:
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=OPENROUTER_BASE_URL,
                timeout=timeout,
                max_retries=max_retries,
            )

    @property
    def configured(self) -> bool:
        return self._configured

    @property
    def model(self) -> str:
        return self._model

    async def chat(self, messages, tools=None) -> dict:
        """Return ``{"content": str, "tool_calls": [...]}`` or raise AIProviderError."""
        if not self._configured:
            raise AIConfigError("OpenRouter tidak dikonfigurasi (OPENROUTER_API_KEY kosong).")
        if not self._model:
            raise AIConfigError("Model chat OpenRouter belum disetel (OPENROUTER_CHAT_MODEL kosong).")

        kwargs = {"model": self._model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        started = time.perf_counter()
        logger.info("[debug-openrouter] request model=%s messages=%d tools=%d configured=%s", self._model, len(messages), len(tools or []), self._configured)
        try:
            response = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - provider errors are surfaced to the user
            logger.error("[debug-openrouter] error duration_ms=%d type=%s", int((time.perf_counter() - started) * 1000), type(exc).__name__)
            logger.error("OpenRouter API error: %s", exc)
            raise AIProviderError(f"OpenRouter API gagal: {exc}") from exc

        logger.info("[debug-openrouter] response duration_ms=%d choices=%d", int((time.perf_counter() - started) * 1000), len(response.choices or []))

        choice = response.choices[0].message if response.choices else None
        if choice is None:
            raise AIInvalidResponseError("OpenRouter mengembalikan respons kosong.")

        tool_calls = []
        for tc in choice.tool_calls or []:
            tool_calls.append(
                {
                    "id": tc.id,
                    "type": getattr(tc, "type", None) or "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
            )
        usage = _usage_meta("openrouter", self._model, getattr(response, "usage", None))
        return {"content": choice.content or "", "tool_calls": tool_calls, "usage": usage}


def build_chat_provider():
    """Return the chat provider selected by ``AI_PROVIDER`` (default: deepseek)."""
    provider = (os.getenv("AI_PROVIDER") or "deepseek").strip().lower()
    if provider == "deepseek":
        return DeepSeekProvider()
    if provider == "openrouter":
        return OpenRouterProvider()
    raise AIConfigError(f"AI_PROVIDER tidak dikenal: {provider!r} (gunakan 'deepseek' atau 'openrouter').")
