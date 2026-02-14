
from __future__ import annotations

import re


def rerank(query: str, chunks: list[dict], limit: int) -> list[dict]:
    tokens = _tokenize(query)
    if not tokens:
        return chunks[:limit]
    scored = []
    for chunk in chunks:
        content = chunk.get("content", "")
        overlap = _overlap_score(tokens, content)
        scored.append((overlap, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored[:limit]]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _overlap_score(tokens: list[str], content: str) -> float:
    content_tokens = set(_tokenize(content))
    if not content_tokens:
        return 0.0
    hits = sum(1 for t in tokens if t in content_tokens)
    return hits / max(1, len(tokens))
