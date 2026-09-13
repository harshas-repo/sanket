"""Which model, if any, this process can actually reach.

`settings.has_model_credentials` only says a key exists. A key with no provider SDK
installed is not a working model - it is an exception forty seconds into a request. So
this module answers three separate questions and reports each on its own:

  are there credentials?  is the SDK importable?  did a call succeed?

The third is only known by trying, so `status()` does not try, and nothing here pretends
the answer is yes.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

from backend.app.config import settings

# Provider -> (module, class, package to name in the fix hint; None means strands has it).
# `bedrock` is the one shipped natively, so it needs no extra install - only AWS credentials.
# Every other provider wants its own SDK, which is why "a key exists" and "a model is
# reachable" are different questions here.
_PROVIDERS: dict[str, tuple[str, str, str | None]] = {
    "gemini": ("strands.models.gemini", "GeminiModel", "google-genai"),
    "anthropic": ("strands.models.anthropic", "AnthropicModel", "anthropic"),
    "openai": ("strands.models.openai", "OpenAIModel", "openai"),
    "bedrock": ("strands.models", "BedrockModel", None),
}

# Which environment variable holds which provider's key, for the messages that name it.
_KEY_ENV = {"gemini": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "llama": "LLAMA_API_KEY"}


@dataclass(frozen=True)
class ModelStatus:
    available: bool
    provider: str | None
    model_id: str | None
    reason: str | None
    credentials_present: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "provider": self.provider,
            "model": self.model_id,
            "credentials_present": self.credentials_present,
            "reason": self.reason,
            "fallback": (
                None
                if self.available
                else "The deterministic path answers from retrieved records only, and says so."
            ),
        }


def status() -> ModelStatus:
    provider = settings.model_provider
    if not provider:
        return ModelStatus(
            available=False,
            provider=None,
            model_id=None,
            reason=(
                "No model configured. Set LLM_PROVIDER=gemini and GEMINI_API_KEY (or "
                "ANTHROPIC_API_KEY, OPENAI_API_KEY, LLAMA_API_KEY, or AWS credentials) and "
                "LLM_MODEL to enable the language layer."
            ),
            credentials_present=False,
        )
    entry = _PROVIDERS.get(provider)
    if entry is None:
        return ModelStatus(
            available=False,
            provider=provider,
            model_id=settings.strands_model,
            reason=f"Sanket knows how to drive {provider!r}; it does not. Supported: {', '.join(_PROVIDERS)}.",
            credentials_present=bool(settings.api_key),
        )
    if provider != "bedrock" and not settings.api_key:
        # A named provider with no key is a configuration mistake, and saying so beats
        # importing an SDK only to fail on the first request.
        return ModelStatus(
            available=False,
            provider=provider,
            model_id=settings.strands_model,
            reason=(
                f"LLM_PROVIDER={provider} is set but {_KEY_ENV.get(provider, 'its key')} is empty, "
                "so there is nothing to authenticate with."
            ),
            credentials_present=False,
        )
    module_name, class_name, extra = entry
    try:
        importlib.import_module(module_name)
    except ImportError as exc:
        return ModelStatus(
            available=False,
            provider=provider,
            model_id=settings.strands_model,
            reason=(
                f"Credentials for {provider!r} are set but the provider package is missing "
                f"({exc.__class__.__name__}: {exc}). Install it: pip install {extra or 'the strands provider extra'}"
            ),
            credentials_present=True,
        )
    return ModelStatus(
        available=True,
        provider=provider,
        model_id=settings.strands_model,
        reason=None,
        credentials_present=True,
    )


def build_model() -> Any | None:
    """Construct the Strands model object, or None. Never raises: a caller that gets None
    runs the deterministic path, and a caller that gets an object may still fail on the
    first network call - which the caller reports as its own reason."""
    current = status()
    if not current.available:
        return None
    module_name, class_name, _ = _PROVIDERS[current.provider or ""]
    model_class = getattr(importlib.import_module(module_name), class_name)
    if current.provider == "bedrock":
        return model_class(
            model_id=current.model_id, region_name=settings.bedrock_aws_region
        )
    # Bedrock model ids carry a vendor prefix ("anthropic.claude-sonnet-4-5"); the direct
    # provider APIs do not want it.
    model_id = current.model_id or ""
    if current.provider in {"anthropic", "openai"} and "." in model_id:
        model_id = model_id.split(".", 1)[1]
    if current.provider == "gemini":
        # Gemini takes its credentials through the client, not through a `kwargs` bag.
        return model_class(model_id=model_id, client_args={"api_key": settings.api_key})
    return model_class(model_id=model_id, kwargs={"api_key": settings.api_key})
