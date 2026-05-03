from app.auth import hash_api_key


def test_hash_api_key_is_deterministic():
    raw = "test-key"
    assert hash_api_key(raw) == hash_api_key(raw)


def test_hash_api_key_changes_with_input():
    assert hash_api_key("a") != hash_api_key("b")
