from __future__ import annotations

import argparse
import sys

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key", required=True)
    args = parser.parse_args()

    headers = {"Authorization": f"Bearer {args.api_key}"}
    with httpx.Client(base_url=args.base_url, timeout=10.0) as client:
        health = client.get("/health")
        ready = client.get("/ready")
        chat = client.post(
            "/v1/chat",
            headers=headers,
            json={"model": "mock-1", "messages": [{"role": "user", "content": "smoke"}]},
        )

    if health.status_code != 200 or ready.status_code != 200 or chat.status_code != 200:
        print({"health": health.status_code, "ready": ready.status_code, "chat": chat.status_code})
        return 1
    print({"health": "ok", "ready": ready.json(), "chat_provider": chat.headers.get("X-Provider")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
