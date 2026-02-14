
# RAG Debugging Runbook

## Symptoms
- No context injected (`X-RAG: miss` or `error`).
- Retrieval latency spikes in Grafana.

## Checklist
1. Confirm vector store is healthy (`pgvector` extension exists).
2. Validate embeddings with `python -m app.rag.ingest` and inspect rows in `document_chunks`.
3. Check Grafana panels for `rag_retrieval_total` and latency.
4. Verify `RAG_ENABLED=true` and embedding model matches schema dimension.

## Fallback behavior
If retrieval fails, requests proceed without context and return `X-RAG: error`.
