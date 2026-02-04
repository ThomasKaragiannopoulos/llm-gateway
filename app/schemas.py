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
    tenant: str = Field(min_length=1)


class CreateKeyResponse(BaseModel):
    tenant: str
    api_key: str


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
