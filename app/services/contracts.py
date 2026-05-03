from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

DisconnectChecker = Callable[[], Awaitable[bool]]


@dataclass(frozen=True)
class RequestContext:
    method: str
    path: str
    request_id: str
    tenant_id: uuid.UUID | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True)
class RawRequestContext:
    method: str
    path: str
    request_id: str
    headers: Mapping[str, str]
    idempotency_key: str | None = None


@dataclass(frozen=True)
class AuthenticatedContext:
    tenant_id: uuid.UUID
    api_key_id: uuid.UUID

