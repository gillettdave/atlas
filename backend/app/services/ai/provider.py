"""OpenAI-backed chat completion facade (env-key Phase A).

Future: BYOK, Anthropic, or hosted routing without rewriting call sites.
See ``docs/UNIFIED_PRODUCT_PLAN.md`` §3.4.
"""
from __future__ import annotations

from typing import Protocol, Sequence

from openai import OpenAI

from ...config import Settings


class AIProviderMisconfigured(RuntimeError):
    """Raised when code requests an LLM but no credentials are configured."""


class ChatCompleter(Protocol):
    """Minimal contract aligned with ported Jobr ``chat.completions`` usage."""

    def complete(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float = 0.2,
        model_override: str | None = None,
    ) -> str: ...


class _OpenAiCompleter:
    __slots__ = ("_settings", "_client")

    def __init__(self, settings: Settings) -> None:
        key = settings.openai_api_key or ""
        if not key.strip():
            raise AIProviderMisconfigured("OpenAI api key missing")
        self._settings = settings
        self._client = OpenAI(api_key=key.strip())

    def complete(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float = 0.2,
        model_override: str | None = None,
    ) -> str:
        model = (
            model_override.strip()
            if model_override and model_override.strip()
            else self._settings.openai_model
        )
        resp = self._client.chat.completions.create(
            model=model,
            messages=list(messages),
            temperature=temperature,
        )
        choice = resp.choices[0].message.content
        if choice is None:
            return ""
        return choice.strip()


class _UnsetCompleter:
    __slots__ = ()

    def complete(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float = 0.2,
        model_override: str | None = None,
    ) -> str:
        raise AIProviderMisconfigured(
            "LLM unavailable: set ATLAS_OPENAI_API_KEY in backend/.env "
            "(see .env.example). BYOK layering will plug in here."
        )


def get_chat_completer(settings: Settings) -> ChatCompleter:
    """Return OpenAI-backed completer when `ATLAS_OPENAI_API_KEY` is non-empty."""
    if settings.openai_api_key and str(settings.openai_api_key).strip():
        return _OpenAiCompleter(settings)
    return _UnsetCompleter()
