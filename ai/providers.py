"""AI providers: DeepSeek (chat/tool calling) and Gemini (image), both via the
OpenAI-compatible SDK.

API keys are read from environment variables only; they are never logged.
"""

import base64
import logging
import os

from openai import AsyncOpenAI

from ai.errors import AIConfigError, AIInvalidResponseError, AIProviderError

logger = logging.getLogger(__name__)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

DEFAULT_DEEPSEEK_MODEL = "deepseek-flash"
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"


class DeepSeekProvider:
    """DeepSeek chat provider with OpenAI-compatible tool calling."""

    def __init__(self, api_key=None, model=None, timeout=30.0, max_retries=2):
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
        try:
            response = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - provider errors are surfaced to the user
            logger.error("DeepSeek API error: %s", exc)
            raise AIProviderError(f"DeepSeek API gagal: {exc}") from exc

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
        return {"content": choice.content or "", "tool_calls": tool_calls}


class GeminiImageProvider:
    """Gemini image-analysis provider (OpenAI-compatible vision endpoint)."""

    def __init__(self, api_key=None, model=None, timeout=60.0):
        self._api_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY")
        self._model = model or os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL
        self._configured = bool(self._api_key)
        self._client = None
        if self._configured:
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=GEMINI_BASE_URL,
                timeout=timeout,
                max_retries=1,
            )

    @property
    def configured(self) -> bool:
        return self._configured

    @property
    def model(self) -> str:
        return self._model

    async def extract(self, image_bytes: bytes, mime_type: str, prompt: str) -> str:
        """Return the model's text response for an image, or raise AIProviderError."""
        if not self._configured:
            raise AIConfigError("Gemini tidak dikonfigurasi (GEMINI_API_KEY kosong).")

        data_uri = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ]
        try:
            response = await self._client.chat.completions.create(
                model=self._model, messages=messages
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Gemini API error: %s", exc)
            raise AIProviderError(f"Gemini API gagal: {exc}") from exc

        choice = response.choices[0].message if response.choices else None
        if choice is None or not choice.content:
            raise AIInvalidResponseError("Gemini mengembalikan respons kosong.")
        return choice.content
