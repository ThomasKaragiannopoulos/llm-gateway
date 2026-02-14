
import os

import pytest
from sqlalchemy import text

from app.db.models import Document, DocumentChunk, Tenant
from app.db.session import get_session
from app.rag.embeddings import DeterministicEmbeddingClient
from app.rag.retrieval import retrieve_chunks


def test_retrieve_chunks_integration():
    if os.getenv("RUN_RAG_INTEGRATION") != "1":
        pytest.skip("integration test disabled")

    db = get_session()
    try:
        try:
            db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            db.commit()
        except Exception:
            pytest.skip("pgvector not available")

        tenant = Tenant(name="rag-integration")
        db.add(tenant)
        db.commit()
        db.refresh(tenant)

        doc = Document(
            tenant_id=tenant.id,
            source="file",
            source_id="integration",
            title="integration",
            content_hash="hash",
            metadata_json="{}",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        embedder = DeterministicEmbeddingClient(dim=768)
        vector = embedder.embed(["hello world"]).vectors[0]

        chunk = DocumentChunk(
            document_id=doc.id,
            chunk_index=0,
            content="hello world",
            token_count=None,
            metadata_json="{}",
            embedding=vector,
            embedding_model="deterministic",
            embedding_dim=768,
        )
        db.add(chunk)
        db.commit()

        results = retrieve_chunks(db, embedder, str(tenant.id), "hello", top_k=1)
        assert results
        assert "hello" in results[0].content
    finally:
        try:
            db.query(DocumentChunk).delete()
            db.query(Document).delete()
            db.query(Tenant).filter(Tenant.name == "rag-integration").delete()
            db.commit()
        finally:
            db.close()
