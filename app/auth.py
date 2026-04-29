import hashlib
import hmac

from app.config import settings


def hash_api_key(raw_key: str) -> str:
    return hmac.new(
        settings.api_key_secret.encode("utf-8"),
        raw_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
