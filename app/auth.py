from __future__ import annotations

import hashlib

PBKDF2_ITERATIONS = 390000


def legacy_hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def hash_api_key(raw_key: str, pepper: str = "") -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        raw_key.encode("utf-8"),
        pepper.encode("utf-8"),
        PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${digest.hex()}"


def candidate_api_key_hashes(raw_key: str, pepper: str = "") -> tuple[str, str]:
    return hash_api_key(raw_key, pepper), legacy_hash_api_key(raw_key)
