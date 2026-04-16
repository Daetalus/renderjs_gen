from __future__ import annotations

from typing import Any, Sequence

import requests


DEFAULT_EMBEDDING_BASE_URL = "http://localhost"
DEFAULT_EMBEDDING_MODEL = "embeddinggemma"
DEFAULT_TIMEOUT = 30.0


class EmbeddingClientError(RuntimeError):
    pass


class EmbeddingGemmaClient:
    def __init__(
        self,
        base_url: str = DEFAULT_EMBEDDING_BASE_URL,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        model: str = DEFAULT_EMBEDDING_MODEL,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.model = model
        self.session = session or requests.Session()

    @property
    def embedding_url(self) -> str:
        if self.base_url.endswith("/embeddings") or self.base_url.endswith("/v1/embeddings"):
            return self.base_url
        return f"{self.base_url}/embeddings"

    @staticmethod
    def format_query(text: str) -> str:
        return f"task: search result | query: {text}"

    @staticmethod
    def format_document(text: str, title: str = "none") -> str:
        return f"title: {title} | text: {text}"

    def embed_query(self, text: str) -> list[float]:
        return self._embed_text(self.format_query(text))

    def embed_document(self, text: str, title: str = "none") -> list[float]:
        return self._embed_text(self.format_document(text, title=title))

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_documents(
        self,
        texts: Sequence[str],
        *,
        titles: Sequence[str] | None = None,
        default_title: str = "none",
    ) -> list[list[float]]:
        if titles is not None and len(titles) != len(texts):
            raise ValueError("titles length must match texts length")
        embeddings: list[list[float]] = []
        for index, text in enumerate(texts):
            title = default_title if titles is None else titles[index]
            embeddings.append(self.embed_document(text, title=title))
        return embeddings

    def _embed_text(self, text: str) -> list[float]:
        response = self.session.post(
            self.embedding_url,
            json={"content": text, "model": self.model},
            headers={"Content-Type": "application/json"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return self._extract_embedding(response.json())

    @staticmethod
    def _extract_embedding(body: Any) -> list[float]:
        if isinstance(body, dict):
            if "embedding" in body:
                return EmbeddingGemmaClient._normalize_embedding(body["embedding"])
            if "data" in body and isinstance(body["data"], list) and body["data"]:
                return EmbeddingGemmaClient._normalize_embedding(body["data"][0].get("embedding"))
        if isinstance(body, list) and body:
            first = body[0]
            if isinstance(first, dict) and "embedding" in first:
                return EmbeddingGemmaClient._normalize_embedding(first["embedding"])
        raise EmbeddingClientError(f"Unexpected embedding response: {body!r}")

    @staticmethod
    def _normalize_embedding(value: Any) -> list[float]:
        if isinstance(value, list) and value and isinstance(value[0], list):
            value = value[0]
        if not isinstance(value, list):
            raise EmbeddingClientError(f"Unexpected embedding payload: {value!r}")
        return [float(item) for item in value]
