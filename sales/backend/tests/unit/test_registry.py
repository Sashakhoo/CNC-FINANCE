from app.core.config import Settings
from app.providers import registry
from app.providers.base import ProviderKind
from app.providers.search.brave import BraveSearch
from app.providers.search.tavily import TavilySearch

SECRET = "sk-should-never-appear"


def settings(**kw):
    return Settings(_env_file=None, **kw)


def test_builds_configured_search_provider():
    p = registry.build_provider(ProviderKind.SEARCH, settings(search_provider="Brave", search_api_key=SECRET))
    assert isinstance(p, BraveSearch)
    p = registry.build_provider(ProviderKind.SEARCH, settings(search_provider="tavily", search_api_key=SECRET))
    assert isinstance(p, TavilySearch)


def test_not_configured_cases_return_none():
    assert registry.build_provider(ProviderKind.SEARCH, settings(search_provider="brave", search_api_key="")) is None
    assert registry.build_provider(ProviderKind.SEARCH, settings(search_provider="", search_api_key=SECRET)) is None
    assert registry.build_provider(ProviderKind.SEARCH, settings(search_provider="nope", search_api_key=SECRET)) is None


def test_unavailable_adapter_returns_none(monkeypatch):
    monkeypatch.setitem(registry.CATALOGUE, ProviderKind.SEARCH, {"brave": "app.providers.search.missing:Nope"})
    assert registry.build_provider(ProviderKind.SEARCH, settings(search_provider="brave", search_api_key=SECRET)) is None


def test_ai_key_selected_by_provider_name():
    s = settings(llm_provider="anthropic", anthropic_api_key="a-key", gemini_api_key="g-key")
    assert registry.selected(ProviderKind.AI, s) == ("anthropic", "a-key")


def test_describe_providers_lists_all_without_secrets(monkeypatch):
    monkeypatch.setitem(registry.CATALOGUE, ProviderKind.AI, {"gemini": "app.providers.ai.missing:Nope"})
    out = registry.describe_providers(settings(search_provider="brave", search_api_key=SECRET, llm_provider="gemini",
                                               gemini_api_key=SECRET))
    assert SECRET not in str(out)
    brave = next(p for p in out if p["name"] == "brave")
    assert brave["state"] == "CONFIGURED" and brave["selected"] and brave["info"]["access_method"] == "API"
    assert next(p for p in out if p["name"] == "gemini")["state"] == registry.UNAVAILABLE
    kinds = {p["kind"] for p in out}
    assert {"SEARCH", "EMAIL_DISCOVERY", "EMAIL_VERIFICATION", "AI"} <= kinds
