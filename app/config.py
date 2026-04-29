from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redis_url: str = "redis://localhost:6379/0"
    requests_per_minute: int = 60
    tokens_per_minute: int = 1000
    provider_mode: str = "mock"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    primary_fail_rate: float = 0.0
    fallback_fail_rate: float = 0.0
    provider_retries: int = 2
    provider_retry_base_ms: int = 200
    provider_retry_max_ms: int = 2000
    circuit_failure_threshold: int = 5
    circuit_reset_seconds: int = 30
    health_min_samples: int = 5
    health_error_threshold: float = 0.5
    cache_ttl_seconds: int = 300
    cors_origins: list[str] = ["http://localhost:3000"]
    api_key_secret: str = "dev-secret-change-in-production"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    model_free: str = "gpt-4o-mini"
    model_pro: str = "gpt-4o"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


settings = Settings()
