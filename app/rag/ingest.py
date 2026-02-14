
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.db.models import Document, DocumentChunk, Tenant
from app.db.session import get_session
from app.rag.chunking import chunk_text
from app.rag.embeddings import get_embedding_client


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest documents into the vector store")
    parser.add_argument("--tenant", default="default")
    parser.add_argument("--source", default="file")
    parser.add_argument("--title", default=None)
    parser.add_argument("--source-id", default=None)
    parser.add_argument("--file", required=True)
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--overlap", type=int, default=200)
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        raise SystemExit(f"file not found: {path}")

    content = path.read_text(encoding="utf-8")
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    source_id = args.source_id or str(path)

    db = get_session()
    try:
        tenant = db.query(Tenant).filter(Tenant.name == args.tenant).one_or_none()
        if tenant is None:
            tenant = Tenant(name=args.tenant)
            db.add(tenant)
            db.commit()
            db.refresh(tenant)

        doc = (
            db.query(Document)
            .filter(
                Document.tenant_id == tenant.id,
                Document.source == args.source,
                Document.source_id == source_id,
            )
            .one_or_none()
        )
        if doc and doc.content_hash == content_hash:
            print("document unchanged; skipping")
            return

        metadata = {"source": args.source, "source_id": source_id, "title": args.title}
        metadata_json = json.dumps(metadata, separators=(",", ":"))

        if doc is None:
            doc = Document(
                tenant_id=tenant.id,
                source=args.source,
                source_id=source_id,
                title=args.title,
                content_hash=content_hash,
                metadata_json=metadata_json,
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)
        else:
            doc.title = args.title
            doc.content_hash = content_hash
            doc.metadata_json = metadata_json
            db.add(doc)
            db.commit()
            db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).delete()
            db.commit()

        chunks = chunk_text(content, chunk_size=args.chunk_size, overlap=args.overlap)
        embedding_client = get_embedding_client()
        vectors = embedding_client.embed([chunk.content for chunk in chunks])

        if vectors.dim != 768:
            raise SystemExit("embedding dim mismatch: expected 768; update schema or EMBEDDING_DIM")
        for vector in vectors.vectors:
            if len(vector) != vectors.dim:
                raise SystemExit("embedding vector length mismatch")

        for chunk, vector in zip(chunks, vectors.vectors):
            db.add(
                DocumentChunk(
                    document_id=doc.id,
                    chunk_index=chunk.index,
                    content=chunk.content,
                    token_count=None,
                    metadata_json=metadata_json,
                    embedding=vector,
                    embedding_model=vectors.model,
                    embedding_dim=vectors.dim,
                )
            )
        db.commit()
        print(f"ingested {len(chunks)} chunks")
    finally:
        db.close()


if __name__ == "__main__":
    main()
