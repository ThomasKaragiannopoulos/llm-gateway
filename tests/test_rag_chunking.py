
from app.rag.chunking import chunk_text


def test_chunk_text_splits_and_overlaps():
    text = "a" * 1200
    chunks = chunk_text(text, chunk_size=500, overlap=100)
    assert len(chunks) >= 3
    assert chunks[0].content
    assert chunks[1].content
