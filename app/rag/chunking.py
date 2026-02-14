
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    index: int
    content: str


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[TextChunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    text = text.strip()
    chunks: list[TextChunk] = []
    start = 0
    idx = 0
    length = len(text)
    while start < length:
        end = min(start + chunk_size, length)
        content = text[start:end].strip()
        if content:
            chunks.append(TextChunk(index=idx, content=content))
            idx += 1
        if end == length:
            break
        start = max(0, end - overlap)
    return chunks
