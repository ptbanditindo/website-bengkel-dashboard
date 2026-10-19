"""OpenRouter image-analysis provider (Telegram-specific).

OpenAI-compatible vision endpoint used by the Telegram photo-draft flow.
API key is read from the environment variable only; never logged.
"""

import base64
import logging
import os

from openai import AsyncOpenAI

from ai.errors import AIConfigError, AIInvalidResponseError, AIProviderError
from ai.providers import OPENROUTER_BASE_URL

logger = logging.getLogger(__name__)


class OpenRouterImageProvider:
    """OpenRouter vision provider (OpenAI-compatible multimodal endpoint)."""

    def __init__(self, api_key=None, model=None, timeout=60.0):
        self._api_key = api_key if api_key is not None else os.getenv("OPENROUTER_API_KEY")
        self._model = model or os.getenv("OPENROUTER_VISION_MODEL") or ""
        self._configured = bool(self._api_key)
        self._client = None
        if self._configured:
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=OPENROUTER_BASE_URL,
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
            raise AIConfigError("OpenRouter tidak dikonfigurasi (OPENROUTER_API_KEY kosong).")
        if not self._model:
            raise AIConfigError("Model vision OpenRouter belum disetel (OPENROUTER_VISION_MODEL kosong).")

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
            logger.error("OpenRouter vision error: %s", exc)
            raise AIProviderError(f"OpenRouter vision gagal: {exc}") from exc

        choice = response.choices[0].message if response.choices else None
        if choice is None or not choice.content:
            raise AIInvalidResponseError("OpenRouter mengembalikan respons kosong.")
        return choice.content


def build_vision_provider():
    """Return the vision provider used by the Telegram photo-draft flow."""
    return OpenRouterImageProvider()
