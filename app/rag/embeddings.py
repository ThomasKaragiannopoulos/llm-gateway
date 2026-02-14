
from __future__ import annotations

import hashlib
import math
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

DEFAULT_DIM = int(os.getenv("EMBEDDING_DIM", "768"))


class EmbeddingError(RuntimeError):
    pass


@dataclass(frozen=True)
class EmbeddingBatch:
    model: str
    dim: int
    vectors: list[list[float]]


class EmbeddingClient(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> EmbeddingBatch:
        raise NotImplementedError


class OllamaEmbeddingClient(EmbeddingClient):
    def __init__(self, base_url: str, model: str, timeout_s: float = 30.0) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout_s)
        self._model = model

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        vectors: list[list[float]] = []
        for text in texts:
            payload = {"model": self._model, "prompt": text}
            resp = self._client.post("/api/embeddings", json=payload)
            if resp.status_code >= 400:
                raise EmbeddingError(
                    f"ollama embeddings failed: {resp.status_code} {resp.text}"
                )
            data = resp.json()
            vec = data.get("embedding")
            if not isinstance(vec, list):
                raise EmbeddingError("ollama response missing embedding")
            vectors.append([float(v) for v in vec])
        dim = len(vectors[0]) if vectors else DEFAULT_DIM
        return EmbeddingBatch(model=self._model, dim=dim, vectors=vectors)


class DeterministicEmbeddingClient(EmbeddingClient):
    def __init__(self, model: str = "deterministic", dim: int = DEFAULT_DIM) -> None:
        self._model = model
        self._dim = dim

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        vectors = [self._embed_one(text) for text in texts]
        return EmbeddingBatch(model=self._model, dim=self._dim, vectors=vectors)

    def _embed_one(self, text: str) -> list[float]:
        seed = text.encode("utf-8")
        values: list[float] = []
        for i in range(self._dim):
            digest = hashlib.sha256(seed + i.to_bytes(4, "big")).digest()
            raw = int.from_bytes(digest[:8], "big")
            value = (raw / 2**64) * 2 - 1
            values.append(float(value))
        return _normalize(values)


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def get_embedding_client() -> EmbeddingClient:
    provider = os.getenv("EMBEDDINGS_PROVIDER", "")
    if not provider:
        provider = "ollama" if os.getenv("PROVIDER_MODE") == "ollama" else "mock"
    provider = provider.lower()
    if provider == "ollama":
        base_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        model = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
        return OllamaEmbeddingClient(base_url=base_url, model=model)
    return DeterministicEmbeddingClient()
