
from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import dataclass

import httpx

from app.pricing import cost_usd


@dataclass
class EvalCase:
    case_id: str
    prompt: str
    expected_contains: list[str]
    expected_answer: str | None = None


def load_cases(path: str) -> list[EvalCase]:
    cases: list[EvalCase] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            payload = json.loads(line)
            cases.append(
                EvalCase(
                    case_id=payload["id"],
                    prompt=payload["prompt"],
                    expected_contains=payload.get("expected_contains", []),
                    expected_answer=payload.get("expected_answer"),
                )
            )
    return cases


def score_response(response: str, expected_contains: list[str]) -> bool:
    text = response.lower()
    return all(token.lower() in text for token in expected_contains)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def call_api(base_url: str, api_key: str, model: str, prompt: str) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = httpx.post(f"{base_url}/v1/chat", json=payload, headers=headers, timeout=60.0)
    resp.raise_for_status()
    return resp.json()["content"]


def run_eval(cases: list[EvalCase], mode: str, base_url: str, api_key: str, model: str):
    results = []
    for case in cases:
        start = time.perf_counter()
        if mode == "fixture":
            response = case.expected_answer or " ".join(case.expected_contains)
        else:
            response = call_api(base_url, api_key, model, case.prompt)
        latency_ms = int((time.perf_counter() - start) * 1000)
        passed = score_response(response, case.expected_contains)
        token_estimate = estimate_tokens(case.prompt + response)
        cost = cost_usd(model, token_estimate)
        results.append(
            {
                "id": case.case_id,
                "passed": passed,
                "latency_ms": latency_ms,
                "cost_usd": cost,
            }
        )
    return results


def summarize(results: list[dict]) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    accuracy = passed / total if total else 0.0
    latencies = [r["latency_ms"] for r in results]
    costs = [r["cost_usd"] for r in results]
    p95_latency = statistics.quantiles(latencies, n=20)[-1] if latencies else 0.0
    avg_cost = sum(costs) / total if total else 0.0
    return {
        "total": total,
        "passed": passed,
        "accuracy": accuracy,
        "p95_latency_ms": p95_latency,
        "avg_cost_usd": avg_cost,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="evals/dataset.jsonl")
    parser.add_argument("--mode", choices=["fixture", "api"], default="fixture")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--model", default="mock-1")
    parser.add_argument("--min-accuracy", type=float, default=0.6)
    parser.add_argument("--max-p95-latency-ms", type=int, default=2000)
    parser.add_argument("--max-avg-cost-usd", type=float, default=0.01)
    args = parser.parse_args()

    if args.mode == "api" and not args.api_key:
        raise SystemExit("--api-key is required for api mode")

    cases = load_cases(args.dataset)
    results = run_eval(cases, args.mode, args.base_url, args.api_key, args.model)
    summary = summarize(results)

    print(json.dumps({"summary": summary, "results": results}, indent=2))

    if summary["accuracy"] < args.min_accuracy:
        raise SystemExit("accuracy below threshold")
    if summary["p95_latency_ms"] > args.max_p95_latency_ms:
        raise SystemExit("latency above threshold")
    if summary["avg_cost_usd"] > args.max_avg_cost_usd:
        raise SystemExit("cost above threshold")


if __name__ == "__main__":
    main()
