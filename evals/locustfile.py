"""
Locust load test for llm-gateway.

Usage:
    pip install locust
    locust -f evals/locustfile.py --host http://localhost:8000

Then open http://localhost:8089, set users / spawn rate, and start.

The script bootstraps a dedicated load-test tenant and API key on startup
using ADMIN_API_KEY from the environment, so no manual setup is needed.
"""

import json
import os
import urllib.request
import uuid

from locust import HttpUser, between, events, task

ADMIN_KEY = os.getenv("ADMIN_API_KEY", "changeme")
_TENANT_NAME = f"loadtest-{uuid.uuid4().hex[:8]}"
_KEY_NAME = "locust"
_TENANT_API_KEY: str | None = None


# ---------------------------------------------------------------------------
# Bootstrap: create a one-off tenant + key before the test starts
# ---------------------------------------------------------------------------

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    global _TENANT_API_KEY

    host = environment.host.rstrip("/")

    headers = {
        "Authorization": f"Bearer {ADMIN_KEY}",
        "Content-Type": "application/json",
    }

    def _post(path: str, body: dict) -> dict:
        data = json.dumps(body).encode()
        req = urllib.request.Request(f"{host}{path}", data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    try:
        _post("/v1/admin/tenants", {"tenant": _TENANT_NAME, "tier": "pro"})
        result = _post("/v1/admin/keys", {"tenant": _TENANT_NAME, "name": _KEY_NAME})
        _TENANT_API_KEY = result["api_key"]
        print(f"[locust] bootstrapped tenant={_TENANT_NAME} key=...{_TENANT_API_KEY[-6:]}")
    except Exception as exc:
        print(f"[locust] bootstrap failed: {exc}. Using ADMIN_API_KEY as fallback.")
        _TENANT_API_KEY = ADMIN_KEY


# ---------------------------------------------------------------------------
# User class
# ---------------------------------------------------------------------------

CHAT_BODY = {
    "model": "ignored-by-router",
    "messages": [{"role": "user", "content": "What is a circuit breaker in software?"}],
    "temperature": 0,
}

STREAM_BODY = {
    "model": "ignored-by-router",
    "stream": True,
    "messages": [{"role": "user", "content": "Name three benefits of caching."}],
}


class GatewayUser(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self):
        self.tenant_headers = {
            "Authorization": f"Bearer {_TENANT_API_KEY}",
            "Content-Type": "application/json",
        }

    # --- tasks (weights reflect realistic traffic shape) ---

    @task(7)
    def chat(self):
        with self.client.post(
            "/v1/chat",
            json=CHAT_BODY,
            headers=self.tenant_headers,
            catch_response=True,
            name="/v1/chat",
        ) as resp:
            if resp.status_code == 429:
                resp.success()   # expected under rate-limit; don't count as failure
            elif resp.status_code >= 500:
                resp.failure(f"server error {resp.status_code}")

    @task(2)
    def chat_stream(self):
        with self.client.post(
            "/v1/chat/stream",
            json=STREAM_BODY,
            headers=self.tenant_headers,
            catch_response=True,
            stream=True,
            name="/v1/chat/stream",
        ) as resp:
            if resp.status_code == 429:
                resp.success()
            elif resp.status_code >= 500:
                resp.failure(f"server error {resp.status_code}")
            else:
                # drain the SSE stream so the connection closes cleanly
                for _ in resp.iter_lines():
                    pass

    @task(1)
    def health(self):
        self.client.get("/health", name="/health")
