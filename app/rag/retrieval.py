
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import Document, DocumentChunk
from app.rag.embeddings import EmbeddingClient


@dataclass(frozen=True)
class RagChunk:
    chunk_id: str
    document_id: str
    content: str
    score: float
    source: str | None
    source_id: str | None
    title: str | None
    metadata: dict
    chunk_index: int


def retrieve_chunks(
    db: Session,
    embedding_client: EmbeddingClient,
    tenant_id: str,
    query: str,
    top_k: int,
) -> list[RagChunk]:
    batch = embedding_client.embed([query])
    query_vec = batch.vectors[0]
    distance = DocumentChunk.embedding.cosine_distance(query_vec).label("distance")
    rows = (
        db.query(DocumentChunk, Document, distance)
        .join(Document, Document.id == DocumentChunk.document_id)
        .filter(Document.tenant_id == tenant_id)
        .order_by(distance.asc())
        .limit(top_k)
        .all()
    )
    chunks: list[RagChunk] = []
    for chunk, doc, dist in rows:
        metadata = {}
        if chunk.metadata_json:
            metadata.update(json.loads(chunk.metadata_json))
        if doc.metadata_json:
            metadata.update(json.loads(doc.metadata_json))
        score = 1.0 - float(dist or 0.0)
        chunks.append(
            RagChunk(
                chunk_id=str(chunk.id),
                document_id=str(doc.id),
                content=chunk.content,
                score=score,
                source=doc.source,
                source_id=doc.source_id,
                title=doc.title,
                metadata=metadata,
                chunk_index=chunk.chunk_index,
            )
        )
    return chunks
