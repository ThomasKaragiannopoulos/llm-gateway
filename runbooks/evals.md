
# Eval Runbook

## Run local evals
```bash
python evals/run_eval.py --mode fixture
```

## Run against a live gateway
```bash
python evals/run_eval.py --mode api --base-url http://localhost:8000 --api-key <key> --model mock-1
```

## Thresholds
- Minimum accuracy: `--min-accuracy`
- Max p95 latency: `--max-p95-latency-ms`
- Max average cost: `--max-avg-cost-usd`
