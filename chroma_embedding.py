from __future__ import annotations

from typing import Any

from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

from embedding_client import EmbeddingGemmaClient


DEFAULT_EMBEDDING_BASE_URL = os.environ.get("EMBED_BASE_URL", "http://localhost:8081/v1")
DEFAULT_EMBEDDING_MODEL = "embeddinggemma"
DEFAULT_TIMEOUT = 30.0


class EmbeddingGemmaFunction(EmbeddingFunction[Documents]):
    def __init__(
        self,
        client: EmbeddingGemmaClient,
        *,
        default_title: str = "none",
    ) -> None:
        self.client = client
        self.default_title = default_title

    def __call__(self, input: Documents) -> Embeddings:
        return self.client.embed_documents(list(input), default_title=self.default_title)

    def embed_query(self, input: Documents) -> Embeddings:
        return self.client.embed_queries(list(input))

    @staticmethod
    def name() -> str:
        return "embedding_gemma_http"

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "EmbeddingGemmaFunction":
        return EmbeddingGemmaFunction(
            EmbeddingGemmaClient(
                base_url=str(config.get("base_url") or DEFAULT_EMBEDDING_BASE_URL),
                model=str(config.get("model") or DEFAULT_EMBEDDING_MODEL),
                timeout=float(config.get("timeout") or DEFAULT_TIMEOUT),
            ),
            default_title=str(config.get("default_title") or "none"),
        )

    def get_config(self) -> dict[str, Any]:
        return {
            "base_url": self.client.base_url,
            "model": self.client.model,
            "timeout": self.client.timeout,
            "default_title": self.default_title,
        }


def build_chroma_embedding_function(
    client: EmbeddingGemmaClient | None = None,
    *,
    default_title: str = "none",
    base_url: str = DEFAULT_EMBEDDING_BASE_URL,
    model: str = DEFAULT_EMBEDDING_MODEL,
    timeout: float = DEFAULT_TIMEOUT,
) -> EmbeddingGemmaFunction:
    embedding_client = client or EmbeddingGemmaClient(
        base_url=base_url,
        model=model,
        timeout=timeout,
    )
    return EmbeddingGemmaFunction(
        embedding_client,
        default_title=default_title,
    )


ChromaEmbeddingFunction = EmbeddingGemmaFunction
