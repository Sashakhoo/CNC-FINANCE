from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    demo_mode: bool = False

    database_url: str = "postgresql+asyncpg://crm:crm@postgres:5432/crm"
    redis_url: str = "redis://redis:6379/0"

    # Sign-in is owned by CNC Finance; this service validates Finance's
    # session cookie by calling Finance's /api/me.
    finance_internal_url: str = "http://finance:8000"
    finance_public_url: str = "https://finance.codencode.my"
    finance_session_cookie: str = "cnc_session"
    crm_integration_secret: str = ""
    session_cache_seconds: int = 60

    frontend_url: str = "https://crm.codencode.my"
    # Extra browser origins allowed to make writes, comma-separated (e.g. https://main.codencode.my).
    allowed_origins: str = ""
    # JSON per-provider quota overrides, e.g. {"brave": {"minute": 30, "month": 2000}}
    provider_limits: str = ""
    log_level: str = "INFO"

    search_provider: str = ""
    search_api_key: str = Field(default="", repr=False)
    email_discovery_provider: str = ""
    email_discovery_api_key: str = Field(default="", repr=False)
    email_verification_provider: str = ""
    email_verification_api_key: str = Field(default="", repr=False)
    llm_provider: str = ""
    openai_api_key: str = Field(default="", repr=False)
    anthropic_api_key: str = Field(default="", repr=False)
    gemini_api_key: str = Field(default="", repr=False)

    crawler_user_agent: str = "CodencodeLeadIntelligence/1.0 (+https://crm.codencode.my/bot)"
    crawler_max_pages_per_domain: int = 25
    crawler_max_depth: int = 2
    crawler_timeout_seconds: float = 15.0
    crawler_min_delay_seconds: float = 2.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
