from __future__ import annotations

import chromadb

from chroma_embedding import build_chroma_embedding_function
from tests.http_test_server import run_json_server


def test_chroma_embedding_function_uses_document_and_query_formats() -> None:
    def responder(path, body):
        assert path == "/embeddings"
        content = body["content"]
        if content == "title: snippet | text: alpha document":
            return {"embedding": [1.0, 0.0]}
        if content == "title: snippet | text: beta document":
            return {"embedding": [0.0, 1.0]}
        if content == "task: search result | query: alpha search":
            return {"embedding": [1.0, 0.0]}
        raise AssertionError(f"unexpected content: {content}")

    with run_json_server(responder) as (base_url, state):
        embedding_function = build_chroma_embedding_function(
            base_url=base_url,
            default_title="snippet",
        )
        client = chromadb.EphemeralClient()
        collection = client.create_collection(
            "test_collection_real",
            embedding_function=embedding_function,
        )
        collection.add(
            ids=["doc-alpha", "doc-beta"],
            documents=["alpha document", "beta document"],
        )
        result = collection.query(query_texts=["alpha search"], n_results=1)

    assert result["ids"] == [["doc-alpha"]]
    assert state.requests[0].body["content"] == "title: snippet | text: alpha document"
    assert state.requests[1].body["content"] == "title: snippet | text: beta document"
    assert state.requests[2].body["content"] == "task: search result | query: alpha search"
