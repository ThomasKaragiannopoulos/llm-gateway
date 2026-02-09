from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    model: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)
    stream: bool = False


class ChatResponse(BaseModel):
    id: str
    model: str
    created: int
    content: str


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class CreateKeyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    tenant: str | None = Field(default=None, min_length=1)


class CreateKeyResponse(BaseModel):
    tenant: str
    api_key: str


class ApiKeyInfo(BaseModel):
    id: str
    name: str | None
    tenant: str
    active: bool
    created_at: str


class ApiKeyListResponse(BaseModel):
    keys: list[ApiKeyInfo]


class LimitsRequest(BaseModel):
    tenant: str = Field(min_length=1)
    token_limit_per_day: int | None = Field(default=None, gt=0)
    spend_limit_per_day_usd: float | None = Field(default=None, gt=0)


class LimitsResponse(BaseModel):
    tenant: str
    token_limit_per_day: int | None
    spend_limit_per_day_usd: float | None


class UsageSummaryResponse(BaseModel):
    tenant: str
    requests: int
    tokens: int
    cost_usd: float


class PricingItem(BaseModel):
    model: str = Field(min_length=1)
    input_per_1k: float = Field(ge=0)
    output_per_1k: float = Field(ge=0)
    cached_per_1k: float = Field(ge=0)


class PricingResponse(BaseModel):
    items: list[PricingItem]


class ObservabilitySummaryResponse(BaseModel):
    request_rate_per_s: float
    error_rate: float
    p95_latency_ms: float
    cache_hit_rate: float
    rate_limited_per_s: float
    tokens_total: float
    cost_total: float
    scope: str
    tenant: str | None = None
