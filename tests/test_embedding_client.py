from __future__ import annotations

from embedding_client import EmbeddingGemmaClient
from tests.http_test_server import run_json_server


def test_embed_query_formats_prompt_and_parses_llama_cpp_shape() -> None:
    def responder(path, body):
        assert path == "/embeddings"
        assert body == {
            "content": "task: search result | query: login form",
            "model": "embeddinggemma",
        }
        return [{"index": 0, "embedding": [[0.1, 0.2, 0.3]]}]

    with run_json_server(responder) as (base_url, state):
        client = EmbeddingGemmaClient(
            base_url=base_url,
            timeout=12.0,
        )
        vector = client.embed_query("login form")

    assert vector == [0.1, 0.2, 0.3]
    assert len(state.requests) == 1
    assert state.requests[0].path == "/embeddings"
    assert state.requests[0].headers["Content-Type"] == "application/json"


def test_embed_documents_formats_titles_and_accepts_openai_shape() -> None:
    responses = iter(
        [
            {"data": [{"embedding": [1, 2]}]},
            {"embedding": [3, 4]},
        ]
    )

    def responder(path, body):
        assert path == "/embeddings"
        return next(responses)

    with run_json_server(responder) as (base_url, state):
        client = EmbeddingGemmaClient(base_url=f"{base_url}/embeddings")
        vectors = client.embed_documents(
            ["first body", "second body"],
            titles=["alpha", "beta"],
        )

    assert vectors == [[1.0, 2.0], [3.0, 4.0]]
    assert state.requests[0].body["content"] == "title: alpha | text: first body"
    assert state.requests[1].body["content"] == "title: beta | text: second body"
    assert state.requests[0].path == "/embeddings"
