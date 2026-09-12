"""Configuration. Every external credential is optional by construction.

Spec §3: the build must be verifiable before any credential exists, so a missing
key is a normal state that selects a fixture transport — never a crash.
"""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore",
                                      case_sensitive=False)

    # database
    database_url: str = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
    supabase_url: str | None = Field(default=None, alias="NEXT_PUBLIC_SUPABASE_URL")
    supabase_anon_key: str | None = Field(default=None, alias="NEXT_PUBLIC_SUPABASE_ANON_KEY")
    supabase_service_role_key: str | None = None
    supabase_jwt_secret: str | None = None

    # llm
    llm_provider: str = "groq"
    groq_api_key: str | None = None
    llm_model_reasoning: str | None = None
    llm_model_fast: str | None = None
    llm_model_fallback: str | None = None

    # retrieval
    brave_api_key: str | None = None
    tavily_api_key: str | None = None
    exa_api_key: str | None = None
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    producthunt_token: str | None = None

    # infra
    upstash_redis_rest_url: str | None = None
    upstash_redis_rest_token: str | None = None

    app_base_url: str = "http://localhost:3000"
    jury_offline: int | None = None

    @property
    def offline(self) -> bool:
        """Explicit JURY_OFFLINE wins; otherwise offline iff no LLM key exists."""
        if self.jury_offline is not None:
            return bool(self.jury_offline)
        return self.groq_api_key is None


settings = Settings()
