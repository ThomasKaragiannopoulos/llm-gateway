
from app.rag.rerank import rerank


def test_rerank_prefers_overlap():
    chunks = [
        {"content": "alpha beta", "score": 0.1},
        {"content": "gamma delta", "score": 0.9},
    ]
    reranked = rerank("alpha", chunks, limit=2)
    assert reranked[0]["content"] == "alpha beta"
