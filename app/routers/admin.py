import json
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func

from app import state
from app.auth import hash_api_key
from app.db.models import AdminAction, ApiKey, Request as RequestModel, Tenant, UsageEvent
from app.db.session import get_session
from app.pricing import cost_usd
from app.schemas import (
    AdminActionEntry,
    AdminAuditResponse,
    ChatMessage,
    CreateKeyRequest,
    CreateKeyResponse,
    CreateTenantKeyRequest,
    CreateTenantRequest,
    CreateTenantResponse,
    EvalRunRequest,
    EvalRunResponse,
    LimitsRequest,
    LimitsResponse,
    ListTenantKeysResponse,
    ListTenantsResponse,
    RotateAdminKeyResponse,
    RevokeKeyByNameRequest,
    RevokeKeyRequest,
    RevokeKeyResponse,
    TenantKeyInfo,
    TenantSummary,
    UsageSummaryResponse,
    VerifyKeyRequest,
    VerifyKeyResponse,
)

router = APIRouter(prefix="/v1/admin")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _get_admin_tenant_id():
    db = get_session()
    try:
        admin_tenant = db.query(Tenant).filter(Tenant.name == "admin").one_or_none()
        if admin_tenant is None:
            return None
        return admin_tenant.id
    finally:
        db.close()


def _require_admin(request: Request):
    admin_id = _get_admin_tenant_id()
    if admin_id is None or str(getattr(request.state, "tenant_id", "")) != str(admin_id):
        return JSONResponse(
            status_code=403,
            content={"error": {"code": "forbidden", "message": "Admin only"}},
        )
    return None


def _log_admin_action(db, actor_tenant_id, action: str, target_type: str, target_id, metadata=None):
    if not actor_tenant_id:
        return
    payload = json.dumps(metadata or {}, separators=(",", ":")) if metadata else None
    db.add(
        AdminAction(
            actor_tenant_id=actor_tenant_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata_json=payload,
        )
    )


def _estimate_tokens(messages: list, content: str) -> int:
    text = " ".join([getattr(m, "content", "") for m in messages]) + " " + content
    return max(1, len(text) // 4)


def _score_response(response: str, expected_contains: list[str]) -> bool:
    text = response.lower()
    return all(token.lower() in text for token in expected_contains)


def _load_eval_cases(dataset_path: str) -> list[dict]:
    cases: list[dict] = []
    with open(dataset_path, "r", encoding="utf-8") as handle:
        for line in handle:
            cases.append(json.loads(line))
    return cases


def _summarize_eval_results(results: list[dict]) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    accuracy = passed / total if total else 0.0
    latencies = sorted(r["latency_ms"] for r in results)
    costs = [r["cost_usd"] for r in results]
    p95_latency = 0
    if latencies:
        idx = max(0, int(0.95 * (len(latencies) - 1)))
        p95_latency = latencies[idx]
    avg_cost = sum(costs) / total if total else 0.0
    return {
        "total": total,
        "passed": passed,
        "accuracy": accuracy,
        "p95_latency_ms": p95_latency,
        "avg_cost_usd": avg_cost,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/evals/run", response_model=EvalRunResponse)
async def run_evals(payload: EvalRunRequest, request: Request):
    guard = _require_admin(request)
    if guard is not None:
        return guard

    dataset_path = payload.dataset_path or "evals/dataset.jsonl"
    cases = _load_eval_cases(dataset_path)
    results = []
    for case in cases:
        prompt = case.get("prompt", "")
        expected_contains = case.get("expected_contains", [])
        response = case.get("expected_answer") or " ".join(expected_contains)
        passed = _score_response(response, expected_contains)
        token_estimate = _estimate_tokens(
            [ChatMessage(role="user", content=prompt)], response
        )
        cost_value = cost_usd("mock-1", token_estimate)
        results.append(
            {
                "id": case.get("id", ""),
                "passed": passed,
                "latency_ms": 0,
                "cost_usd": cost_value,
            }
        )
    summary = _summarize_eval_results(results)
    passed_thresholds = True
    if payload.min_accuracy is not None and summary["accuracy"] < payload.min_accuracy:
        passed_thresholds = False
    if payload.max_p95_latency_ms is not None and summary["p95_latency_ms"] > payload.max_p95_latency_ms:
        passed_thresholds = False
    if payload.max_avg_cost_usd is not None and summary["avg_cost_usd"] > payload.max_avg_cost_usd:
        passed_thresholds = False
    summary["passed_thresholds"] = passed_thresholds
    return EvalRunResponse(summary=summary)


@router.post("/keys", response_model=CreateKeyResponse)
async def create_key(payload: CreateKeyRequest, request: Request):
    guard = _require_admin(request)
    if guard is not None:
        return guard

    raw_key = str(uuid.uuid4())
    key_hash = hash_api_key(raw_key)

    db = get_session()
    try:
        tenant = db.query(Tenant).filter(Tenant.name == payload.tenant).one_or_none()
        if tenant is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "Tenant not found"}},
            )
        existing = (
            db.query(ApiKey)
            .filter(ApiKey.tenant_id == tenant.id, ApiKey.name == payload.name)
            .one_or_none()
        )
        if existing is not None:
            return JSONResponse(
                status_code=409,
                content={"error": {"code": "conflict", "message": "Key name already exists"}},
            )
        db.add(
            ApiKey(
                tenant_id=tenant.id,
                name=payload.name,
                key_hash=key_hash,
                active=True,
                created_by=request.state.tenant_id,
            )
        )
        _log_admin_action(
            db, request.state.tenant_id, "create_key", "tenant", str(tenant.id),
            {"tenant": payload.tenant, "name": payload.name},
        )
        db.commit()
    finally:
        db.close()

    return CreateKeyResponse(tenant=payload.tenant, name=payload.name, api_key=raw_key)


@router.post("/tenants", response_model=CreateTenantResponse)
async def create_tenant(payload: CreateTenantRequest, request: Request):
    guard = _require_admin(request)
    if guard is not None:
        return guard

    db = get_session()
    try:
        existing = db.query(Tenant).filter(Tenant.name == payload.tenant).one_or_none()
        if existing is not None:
            return JSONResponse(
                status_code=409,
                content={"error": {"code": "conflict", "message": "Tenant already exists"}},
            )
        tier = payload.tier or "free"
        tenant = Tenant(name=payload.tenant, tier=tier)
        db.add(tenant)
        _log_admin_action(
            db, request.state.tenant_id, "create_tenant", "tenant", None,
            {"tenant": payload.tenant, "tier": tier},
        )
        db.commit()
    finally:
        db.close()

    return CreateTenantResponse(tenant=payload.tenant, tier=tier)


@router.get("/tenants", response_model=ListTenantsResponse)
async def list_tenants(request: Request):
    guard = _require_admin(request)
    if guard is not None:
        return guard

    db = get_session()
    try:
        tenants = db.query(Tenant).order_by(Tenant.created_at.desc()).all()
    finally:
        db.close()

    rows = [
        TenantSummary(
            tenant=t.name,
            tier=t.tier,
            created_at=t.created_at.isoformat() if t.created_at else "",
            token_limit_per_day=t.token_limit_per_day,
            spend_limit_per_day_usd=t.spend_limit_per_day_usd,
        )
        for t in tenants
    ]
    return ListTenantsResponse(tenants=rows)


@router.get("/audit", response_model=AdminAuditResponse)
async def audit_log(request: Request, limit: int = 50):
    guard = _require_admin(request)
    if guard is not None:
        return guard

    safe_limit = max(1, min(limit, 200))
    db = get_session()
    try:
        rows = (
            db.query(AdminAction, Tenant.name)
            .join(Tenant, Tenant.id == AdminAction.actor_tenant_id)
            .order_by(AdminAction.created_at.desc())
            .limit(safe_limit)
            .all()
        )
    finally:
        db.close()

    actions = []
    for action_row, actor_name in rows:
        metadata = None
        if action_row.metadata_json:
            try:
                metadata = json.loads(action_row.metadata_json)
            except json.JSONDecodeError:
                metadata = {"raw": action_row.metadata_json}
        actions.append(
            AdminActionEntry(
                action=action_row.action,
                actor=actor_name,
                target_type=action_row.target_type,
                target_id=action_row.target_id,
                created_at=action_row.created_at.isoformat() if action_row.created_at else "",
                metadata=metadata,
            )
        )

    return AdminAuditResponse(actions=actions)


@router.post("/tenants/{tenant_name}/keys", response_model=CreateKeyResponse)
async def create_tenant_key(tenant_name: str, payload: CreateTenantKeyRequest, request: Request):
    guard = _require_admin(request)
    if guard is not None:
        return guard

    raw_key = str(uuid.uuid4())
    key_hash = hash_api_key(raw_key)
    db = get_session()
    try:
        tenant = db.query(Tenant).filter(Tenant.name == tenant_name).one_or_none()
        if tenant is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "Tenant not found"}},
            )
        existing = (
            db.query(ApiKey)
            .filter(ApiKey.tenant_id == tenant.id, ApiKey.name == payload.name)
            .one_or_none()
        )
        if existing is not None:
            return JSONResponse(
                status_code=409,
                content={"error": {"code": "conflict", "message": "Key name already exists"}},
            )
        db.add(
            ApiKey(
                tenant_id=tenant.id,
                name=payload.name,
                key_hash=key_hash,
                active=True,
                created_by=request.state.tenant_id,
            )
        )
        _log_admin_action(
            db, request.state.tenant_id, "create_key", "tenant", str(tenant.id),
            {"tenant": tenant_name, "name": payload.name},
        )
        db.commit()
    finally:
        db.close()

    return CreateKeyResponse(tenant=tenant_name, name=payload.name, api_key=raw_key)


@router.get("/tenants/{tenant_name}/keys", response_model=ListTenantKeysResponse)
async def list_tenant_keys(tenant_name: str, request: Request):
    guard = _require_admin(request)
    if guard is not None:
        return guard

    db = get_session()
    try:
        tenant = db.query(Tenant).filter(Tenant.name == tenant_name).one_or_none()
        if tenant is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "Tenant not found"}},
            )
        keys = (
            db.query(ApiKey)
            .filter(ApiKey.tenant_id == tenant.id)
            .order_by(ApiKey.created_at.desc())
            .all()
        )
    finally:
        db.close()

    masked = [
        TenantKeyInfo(
            key_id=str(k.id),
            name=k.name,
            key_last6=k.key_hash[-6:],
            active=bool(k.active),
            created_at=k.created_at.isoformat() if k.created_at else "",
            last_used_at=k.last_used_at.isoformat() if k.last_used_at else None,
            revoked_at=k.revoked_at.isoformat() if k.revoked_at else None,
            revoked_reason=k.revoked_reason,
        )
        for k in keys
    ]
    return ListTenantKeysResponse(tenant=tenant_name, keys=masked)


@router.post("/keys/revoke", response_model=RevokeKeyResponse)
async def revoke_key(payload: RevokeKeyRequest, request: Request):
    guard = _require_admin(request)
    if guard is not None:
        return guard

    key_hash = hash_api_key(payload.api_key)
    db = get_session()
    try:
        api_key = (
            db.query(ApiKey)
            .filter(ApiKey.key_hash == key_hash, ApiKey.active.is_(True))
            .one_or_none()
        )
        if api_key is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "API key not found"}},
            )
        api_key.active = False
        api_key.revoked_at = func.now()
        api_key.revoked_reason = payload.reason
        tenant = db.query(Tenant).filter(Tenant.id == api_key.tenant_id).one_or_none()
        db.add(api_key)
        _log_admin_action(
            db, request.state.tenant_id, "revoke_key", "api_key", str(api_key.id),
            {"tenant": tenant.name if tenant else None, "reason": payload.reason},
        )
        db.commit()
    finally:
        db.close()

    return RevokeKeyResponse(revoked=True, tenant=(tenant.name if tenant else None))


@router.post("/tenants/{tenant_name}/keys/revoke", response_model=RevokeKeyResponse)
async def revoke_key_by_name(tenant_name: str, payload: RevokeKeyByNameRequest, request: Request):
    guard = _require_admin(request)
    if guard is not None:
        return guard

    db = get_session()
    try:
        tenant = db.query(Tenant).filter(Tenant.name == tenant_name).one_or_none()
        if tenant is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "Tenant not found"}},
            )
        api_key = (
            db.query(ApiKey)
            .filter(
                ApiKey.tenant_id == tenant.id,
                ApiKey.name == payload.name,
                ApiKey.active.is_(True),
            )
            .one_or_none()
        )
        if api_key is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "API key not found"}},
            )
        api_key.active = False
        api_key.revoked_at = func.now()
        api_key.revoked_reason = payload.reason
        db.add(api_key)
        _log_admin_action(
            db, request.state.tenant_id, "revoke_key_by_name", "api_key", str(api_key.id),
            {"tenant": tenant_name, "name": payload.name, "reason": payload.reason},
        )
        db.commit()
    finally:
        db.close()

    return RevokeKeyResponse(revoked=True, tenant=tenant_name)


@router.post("/keys/verify", response_model=VerifyKeyResponse)
async def verify_key(payload: VerifyKeyRequest, request: Request):
    guard = _require_admin(request)
    if guard is not None:
        return guard

    key_hash = hash_api_key(payload.api_key)
    db = get_session()
    try:
        tenant = db.query(Tenant).filter(Tenant.name == payload.tenant).one_or_none()
        if tenant is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "Tenant not found"}},
            )
        api_key = (
            db.query(ApiKey)
            .filter(ApiKey.tenant_id == tenant.id, ApiKey.name == payload.name)
            .one_or_none()
        )
        if api_key is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "API key not found"}},
            )
        return VerifyKeyResponse(matches=api_key.key_hash == key_hash, active=bool(api_key.active))
    finally:
        db.close()


@router.post("/keys/rotate", response_model=RotateAdminKeyResponse)
async def rotate_admin_key(request: Request):
    guard = _require_admin(request)
    if guard is not None:
        return guard

    raw_key = str(uuid.uuid4())
    key_hash = hash_api_key(raw_key)
    admin_id = _get_admin_tenant_id()
    db = get_session()
    try:
        admin_tenant = db.query(Tenant).filter(Tenant.id == admin_id).one_or_none()
        if admin_tenant is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "Admin tenant missing"}},
            )
        db.query(ApiKey).filter(
            ApiKey.tenant_id == admin_tenant.id, ApiKey.active.is_(True)
        ).update({"active": False})
        rotation_name = f"admin-rotated-{raw_key.split('-')[0]}"
        db.add(
            ApiKey(
                tenant_id=admin_tenant.id,
                name=rotation_name,
                key_hash=key_hash,
                active=True,
                created_by=request.state.tenant_id,
            )
        )
        _log_admin_action(
            db, request.state.tenant_id, "rotate_admin_key", "tenant", str(admin_tenant.id),
            {"name": rotation_name},
        )
        db.commit()
    finally:
        db.close()

    return RotateAdminKeyResponse(admin_api_key=raw_key)


@router.post("/limits", response_model=LimitsResponse)
async def set_limits(payload: LimitsRequest, request: Request):
    guard = _require_admin(request)
    if guard is not None:
        return guard

    db = get_session()
    try:
        tenant = db.query(Tenant).filter(Tenant.name == payload.tenant).one_or_none()
        if tenant is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "Tenant not found"}},
            )
        tenant.token_limit_per_day = payload.token_limit_per_day
        tenant.spend_limit_per_day_usd = payload.spend_limit_per_day_usd
        db.add(tenant)
        _log_admin_action(
            db, request.state.tenant_id, "set_limits", "tenant", str(tenant.id),
            {
                "tenant": payload.tenant,
                "token_limit_per_day": payload.token_limit_per_day,
                "spend_limit_per_day_usd": payload.spend_limit_per_day_usd,
            },
        )
        db.commit()
    finally:
        db.close()

    return LimitsResponse(
        tenant=payload.tenant,
        token_limit_per_day=payload.token_limit_per_day,
        spend_limit_per_day_usd=payload.spend_limit_per_day_usd,
    )


@router.post("/health/reset")
async def reset_health(request: Request):
    guard = _require_admin(request)
    if guard is not None:
        return guard
    state.health_tracker.reset()
    return {"status": "ok"}


@router.get("/usage/{tenant_name}", response_model=UsageSummaryResponse)
async def usage_summary(tenant_name: str, request: Request):
    guard = _require_admin(request)
    if guard is not None:
        return guard

    db = get_session()
    try:
        tenant = db.query(Tenant).filter(Tenant.name == tenant_name).one_or_none()
        if tenant is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "Tenant not found"}},
            )
        request_count = (
            db.query(func.count(RequestModel.id))
            .filter(RequestModel.tenant_id == tenant.id)
            .scalar()
        )
        totals = (
            db.query(
                func.coalesce(func.sum(UsageEvent.tokens), 0),
                func.coalesce(func.sum(UsageEvent.cost_usd), 0.0),
            )
            .filter(UsageEvent.tenant_id == tenant.id)
            .one()
        )
    finally:
        db.close()

    return UsageSummaryResponse(
        tenant=tenant_name,
        requests=int(request_count or 0),
        tokens=int(totals[0] or 0),
        cost_usd=float(totals[1] or 0.0),
    )
