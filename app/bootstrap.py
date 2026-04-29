from __future__ import annotations

import json
import logging
import os

from app.auth import hash_api_key
from app.db.models import ApiKey, Tenant
from app.runtime import get_session


logger = logging.getLogger("llm-gateway")


def ensure_admin_key() -> None:
    admin_key = os.getenv("ADMIN_API_KEY")
    if not admin_key:
        logger.warning(json.dumps({"message": "admin_key_missing"}))
        return

    db = get_session()
    try:
        admin_tenant = db.query(Tenant).filter(Tenant.name == "admin").one_or_none()
        if admin_tenant is None:
            admin_tenant = Tenant(name="admin")
            db.add(admin_tenant)
            db.commit()
            db.refresh(admin_tenant)

        key_hash = hash_api_key(admin_key)
        existing = db.query(ApiKey).filter(ApiKey.key_hash == key_hash).one_or_none()
        if existing is not None:
            return

        named = (
            db.query(ApiKey)
            .filter(ApiKey.tenant_id == admin_tenant.id, ApiKey.name == "admin-env")
            .one_or_none()
        )
        active_admin_keys = (
            db.query(ApiKey)
            .filter(ApiKey.tenant_id == admin_tenant.id, ApiKey.active.is_(True))
            .count()
        )
        if named is None:
            db.add(
                ApiKey(
                    tenant_id=admin_tenant.id,
                    name="admin-env",
                    key_hash=key_hash,
                    active=True,
                )
            )
            db.commit()
            return

        if active_admin_keys > 0 and named.key_hash != key_hash:
            logger.warning(json.dumps({"message": "admin_key_env_mismatch"}))
            return

        named.key_hash = key_hash
        named.active = True
        db.add(named)
        db.commit()
    finally:
        db.close()
