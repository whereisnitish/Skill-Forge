"""AI mentor providers behind a small, vendor-neutral interface.

* `AnthropicProvider` calls Claude through the official SDK with a JSON-schema
  constrained response, a hard timeout, no SDK-level retries (Celery owns
  retries) and explicit handling of refusals and truncated output.
* `CuratedProvider` builds deterministic guidance from curated content. It is
  used whenever no AI provider is configured and is always labelled as
  curated guidance in the UI — never presented as model output.

Providers only produce *explanations*. Scores and mastery come exclusively
from the deterministic evaluators; nothing here can change them.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from django.conf import settings

logger = logging.getLogger(__name__)

SERVER_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "One-sentence takeaway."},
        "explanation": {"type": "string", "description": "Markdown, at most four short paragraphs."},
        "key_points": {"type": "array", "items": {"type": "string"}, "description": "2-5 concise points."},
        "suggested_practice": {
            "type": "array",
            "items": {"type": "string"},
            "description": "1-3 concrete follow-up practice ideas.",
        },
    },
    "required": ["headline", "explanation", "key_points", "suggested_practice"],
    "additionalProperties": False,
}

LIMITS = {"headline": 240, "explanation": 5000, "item": 400, "items": 6}


class MentorError(Exception):
    """Provider failure with a stable code: timeout, rate_limited, unavailable, malformed, refused, auth."""

    TRANSIENT = {"timeout", "rate_limited", "unavailable"}

    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)

    @property
    def transient(self) -> bool:
        return self.code in self.TRANSIENT


@dataclass(frozen=True)
class MentorPrompt:
    kind: str
    system: str
    content: str


@dataclass
class MentorResult:
    data: dict[str, Any]
    source: str  # live | fallback
    provider: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    meta: dict[str, Any] = field(default_factory=dict)


class Provider(Protocol):
    name: str

    def generate(self, prompt: MentorPrompt) -> MentorResult: ...


def validate_payload(payload: Any) -> dict[str, Any]:
    """Validate and normalise structured output; raise MentorError('malformed') otherwise."""
    if not isinstance(payload, dict):
        raise MentorError("malformed", "Response was not an object.")
    headline = payload.get("headline")
    explanation = payload.get("explanation")
    if not isinstance(headline, str) or not headline.strip():
        raise MentorError("malformed", "Missing headline.")
    if not isinstance(explanation, str) or not explanation.strip():
        raise MentorError("malformed", "Missing explanation.")

    def items(key: str) -> list[str]:
        value = payload.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise MentorError("malformed", f"{key} must be a list of strings.")
        return [v.strip()[: LIMITS["item"]] for v in value if v.strip()][: LIMITS["items"]]

    return {
        "headline": headline.strip()[: LIMITS["headline"]],
        "explanation": explanation.strip()[: LIMITS["explanation"]],
        "key_points": items("key_points"),
        "suggested_practice": items("suggested_practice"),
    }


def mentor_is_live() -> bool:
    return settings.AI_PROVIDER == "anthropic" and bool(settings.AI_API_KEY)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, client=None):
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(
                api_key=settings.AI_API_KEY, timeout=settings.AI_TIMEOUT_SECONDS, max_retries=0
            )
        return self._client

    def generate(self, prompt: MentorPrompt) -> MentorResult:
        import anthropic

        model = settings.AI_MODEL
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": settings.AI_MAX_OUTPUT_TOKENS,
            "system": prompt.system,
            "messages": [{"role": "user", "content": prompt.content}],
            "output_config": {
                "effort": settings.AI_EFFORT,
                "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
            },
        }
        if settings.AI_USE_SERVER_FALLBACKS and model in SERVER_FALLBACK_MODELS:
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = "default"

        started = time.monotonic()
        try:
            response = self.client.beta.messages.create(**kwargs)
        except anthropic.APITimeoutError as exc:
            raise MentorError("timeout") from exc
        except anthropic.RateLimitError as exc:
            raise MentorError("rate_limited") from exc
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise MentorError("auth") from exc
        except anthropic.BadRequestError as exc:
            logger.warning("mentor.bad_request", extra={"status": getattr(exc, "status_code", None)})
            raise MentorError("bad_request") from exc
        except anthropic.APIStatusError as exc:
            raise MentorError("unavailable" if exc.status_code >= 500 else "bad_request") from exc
        except anthropic.APIConnectionError as exc:
            raise MentorError("unavailable") from exc
        latency_ms = int((time.monotonic() - started) * 1000)

        if response.stop_reason == "refusal":
            raise MentorError("refused")
        if response.stop_reason == "max_tokens":
            raise MentorError("malformed", "Response was truncated.")
        text = next((block.text for block in response.content if block.type == "text"), "")
        try:
            data = validate_payload(json.loads(text))
        except json.JSONDecodeError as exc:
            raise MentorError("malformed", "Response was not valid JSON.") from exc
        usage = response.usage
        return MentorResult(
            data=data,
            source="live",
            provider=self.name,
            model=getattr(response, "model", model) or model,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            latency_ms=latency_ms,
        )


def get_live_provider() -> Provider | None:
    if mentor_is_live():
        return AnthropicProvider()
    return None
