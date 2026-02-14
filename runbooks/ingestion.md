
# Ingestion Runbook

## Prepare the vector store
1. Ensure Postgres runs with pgvector (see docker-compose).
2. Run Alembic migrations: `alembic upgrade head`.

## Ingest a document
Example command:
```bash
python -m app.rag.ingest --tenant default --source file --file docs/manual.txt
```

## Common failures
- Embedding dimension mismatch: update `EMBEDDING_DIM` and re-migrate the vector schema.
- Missing pgvector: confirm the Postgres image is `pgvector/pgvector`.
