from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


DEFAULT_BOOTSTRAP_ADMIN_TOKEN = "bootstrap-admin-token"


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed_origins: list[str]
    primary_fail_rate: float = Field(ge=0.0, le=1.0)
    fallback_fail_rate: float = Field(ge=0.0, le=1.0)
    ollama_url: str = Field(min_length=1)
    ollama_model: str = Field(min_length=1)
    openai_api_key: str = ""
    provider_mode: str
    health_min_samples: int = Field(ge=1)
    health_error_threshold: float = Field(ge=0.0, le=1.0)
    requests_per_minute: int = Field(ge=1)
    tokens_per_minute: int = Field(ge=1)
    redis_url: str = Field(min_length=1)
    cache_ttl_seconds: int = Field(ge=1)
    cache_version: str = Field(min_length=1)
    prometheus_url: str = Field(min_length=1)
    grafana_url: str = Field(min_length=1)
    admin_api_key: str = ""
    api_key_pepper: str = ""
    bootstrap_admin_token: str = Field(min_length=16)
    allow_admin_reset: bool
    environment: str
    database_url: str = Field(min_length=1)

    @field_validator("provider_mode")
    @classmethod
    def validate_provider_mode(cls, value: str) -> str:
        if value not in {"mock", "ollama"}:
            raise ValueError("provider_mode must be one of: mock, ollama")
        return value

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        if value not in {"dev", "test", "stage", "prod"}:
            raise ValueError("environment must be one of: dev, test, stage, prod")
        return value

    @model_validator(mode="after")
    def validate_secret_defaults(self) -> Settings:
        if self.environment != "test" and self.bootstrap_admin_token == DEFAULT_BOOTSTRAP_ADMIN_TOKEN:
            raise ValueError("bootstrap_admin_token must not use the default value outside tests")
        if self.environment in {"stage", "prod"} and not self.api_key_pepper:
            raise ValueError("api_key_pepper is required in stage and prod")
        return self

    @classmethod
    def from_env(cls) -> Settings:
        allowed_origins = _parse_csv(os.getenv("ALLOWED_ORIGINS", "http://localhost:5173"))
        return cls(
            allowed_origins=allowed_origins or ["*"],
            primary_fail_rate=float(os.getenv("PRIMARY_FAIL_RATE", "0")),
            fallback_fail_rate=float(os.getenv("FALLBACK_FAIL_RATE", "0")),
            ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434"),
            ollama_model=os.getenv("OLLAMA_MODEL", "llama3.1:8b"),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            provider_mode=os.getenv("PROVIDER_MODE", "mock"),
            health_min_samples=int(os.getenv("HEALTH_MIN_SAMPLES", "5")),
            health_error_threshold=float(os.getenv("HEALTH_ERROR_THRESHOLD", "0.5")),
            requests_per_minute=int(os.getenv("REQUESTS_PER_MINUTE", "60")),
            tokens_per_minute=int(os.getenv("TOKENS_PER_MINUTE", "1000")),
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            cache_ttl_seconds=int(os.getenv("CACHE_TTL_SECONDS", "300")),
            cache_version=os.getenv("CACHE_VERSION", "v1"),
            prometheus_url=os.getenv("PROMETHEUS_URL", "http://prometheus:9090"),
            grafana_url=os.getenv("GRAFANA_URL", "http://grafana:3000"),
            admin_api_key=os.getenv("ADMIN_API_KEY", ""),
            api_key_pepper=os.getenv("API_KEY_PEPPER", ""),
            bootstrap_admin_token=os.getenv("BOOTSTRAP_ADMIN_TOKEN", ""),
            allow_admin_reset=_parse_bool(os.getenv("ALLOW_ADMIN_RESET"), default=False),
            environment=os.getenv("APP_ENV", "dev"),
            database_url=os.getenv(
                "DATABASE_URL",
                "postgresql+psycopg://llm:llm@localhost:1312/llm_gateway",
            ),
        )
