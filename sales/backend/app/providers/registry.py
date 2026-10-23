"""Catalogue of every provider adapter, selected by configuration. Adapters
are imported lazily so a missing/broken adapter shows as UNAVAILABLE instead
of breaking the app."""
from __future__ import annotations

import importlib
import logging
from dataclasses import asdict

import httpx

from app.core.config import Settings
from app.providers.base import NOOP_RECORDER, Cache, ProviderKind, ProviderState, UsageRecorder

log = logging.getLogger("app.providers")

CATALOGUE: dict[ProviderKind, dict[str, str]] = {
    ProviderKind.SEARCH: {
        "brave": "app.providers.search.brave:BraveSearch",
        "tavily": "app.providers.search.tavily:TavilySearch",
    },
    ProviderKind.EMAIL_DISCOVERY: {"hunter": "app.providers.email.hunter:HunterEmailDiscovery"},
    ProviderKind.EMAIL_VERIFICATION: {
        "hunter": "app.providers.verification.hunter:HunterVerifier",
        "zerobounce": "app.providers.verification.zerobounce:ZeroBounceVerifier",
        "reoon": "app.providers.verification.reoon:ReoonVerifier",
    },
    ProviderKind.AI: {
        "gemini": "app.providers.ai.gemini:GeminiProvider",
        "anthropic": "app.providers.ai.anthropic:AnthropicProvider",
        "openai": "app.providers.ai.openai:OpenAIProvider",
    },
}

UNAVAILABLE = "UNAVAILABLE"


def load_class(path: str):
    """Returns the adapter class, or None if it can't be imported."""
    module, _, attr = path.partition(":")
    try:
        return getattr(importlib.import_module(module), attr)
    except (ImportError, AttributeError) as e:
        log.warning("provider adapter unavailable", extra={"provider": path, "error_type": type(e).__name__})
        return None


def selected(kind: ProviderKind, settings: Settings) -> tuple[str, str]:
    """(provider name, api key) chosen for `kind` by configuration."""
    if kind == ProviderKind.SEARCH:
        return settings.search_provider.strip().lower(), settings.search_api_key
    if kind == ProviderKind.EMAIL_DISCOVERY:
        return settings.email_discovery_provider.strip().lower(), settings.email_discovery_api_key
    if kind == ProviderKind.EMAIL_VERIFICATION:
        return settings.email_verification_provider.strip().lower(), settings.email_verification_api_key
    if kind == ProviderKind.AI:
        name = settings.llm_provider.strip().lower()
        key = {"gemini": settings.gemini_api_key, "anthropic": settings.anthropic_api_key,
               "openai": settings.openai_api_key}.get(name, "")
        return name, key
    return "", ""


def build_provider(kind: ProviderKind, settings: Settings, client: httpx.AsyncClient | None = None,
                   recorder: UsageRecorder = NOOP_RECORDER, cache: Cache | None = None,
                   model: str | None = None):
    """Configured provider instance for `kind`, or None when not configured
    (no provider chosen, unknown name, no key, or adapter unavailable)."""
    name, key = selected(kind, settings)
    path = CATALOGUE.get(kind, {}).get(name)
    if not path or not key:
        return None
    cls = load_class(path)
    if cls is None:
        return None
    kwargs = dict(client=client, recorder=recorder, cache=cache)
    if kind == ProviderKind.AI:
        kwargs["model"] = model
    instance = cls(key, **kwargs)
    return instance if instance.is_configured() else None


def describe_providers(settings: Settings) -> list[dict]:
    """Every catalogued provider with its configuration state — never includes keys.
    State is static (NOT_CONFIGURED / CONFIGURED / UNAVAILABLE); live CONNECTED/ERROR
    comes from test_connection()."""
    out = []
    for kind, entries in CATALOGUE.items():
        chosen, key = selected(kind, settings)
        for name, path in entries.items():
            cls = load_class(path)
            info = getattr(cls, "info", None) if cls else None
            if cls is None:
                state = UNAVAILABLE
            elif name == chosen and key:
                state = "CONFIGURED"
            else:
                state = ProviderState.NOT_CONFIGURED.value
            out.append({
                "kind": kind.value, "name": name, "selected": name == chosen,
                "display_name": info.display_name if info else name,
                "state": state,
                "info": {k: (v.value if hasattr(v, "value") else v) for k, v in asdict(info).items()} if info else None,
            })
    return out
