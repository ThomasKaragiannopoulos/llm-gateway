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
    name: str = Field(min_length=1)


class CreateKeyResponse(BaseModel):
    tenant: str
    name: str
    api_key: str


class CreateTenantRequest(BaseModel):
    tenant: str = Field(min_length=1)
    tier: str | None = Field(default=None)


class CreateTenantResponse(BaseModel):
    tenant: str
    tier: str


class CreateTenantKeyRequest(BaseModel):
    name: str = Field(min_length=1)


class TenantSummary(BaseModel):
    tenant: str
    tier: str
    created_at: str
    token_limit_per_day: int | None
    spend_limit_per_day_usd: float | None


class ListTenantsResponse(BaseModel):
    tenants: list[TenantSummary]


class AdminActionEntry(BaseModel):
    action: str
    actor: str
    target_type: str
    target_id: str | None
    created_at: str
    metadata: dict | None = None


class AdminAuditResponse(BaseModel):
    actions: list[AdminActionEntry]


class TenantKeyInfo(BaseModel):
    key_id: str
    name: str
    key_last6: str
    active: bool
    created_at: str
    last_used_at: str | None = None
    revoked_at: str | None = None
    revoked_reason: str | None = None


class ListTenantKeysResponse(BaseModel):
    tenant: str
    keys: list[TenantKeyInfo]


class RevokeKeyRequest(BaseModel):
    api_key: str = Field(min_length=1)
    reason: str | None = Field(default=None, max_length=300)


class RevokeKeyByNameRequest(BaseModel):
    name: str = Field(min_length=1)
    reason: str | None = Field(default=None, max_length=300)


class RevokeKeyResponse(BaseModel):
    revoked: bool
    tenant: str | None = None


class VerifyKeyRequest(BaseModel):
    tenant: str = Field(min_length=1)
    name: str = Field(min_length=1)
    api_key: str = Field(min_length=1)


class VerifyKeyResponse(BaseModel):
    matches: bool
    active: bool


class RotateAdminKeyResponse(BaseModel):
    admin_api_key: str


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
