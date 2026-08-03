from abc import ABC, abstractmethod

EMBEDDING_DIMENSIONS = 768
EMBEDDING_VERSION = "asymmetric-retrieval-v1"
PROMPT_VERSION = "rag-embedding-prompt-v1"
DOCUMENT_MODEL = "gemini-embedding-2"


def document_embedding_input(document_title: str, heading: str, text: str) -> str:
    heading_text = heading.strip() or "(başlıksız bölüm)"
    return f"title: {document_title} | text: {heading_text}\n{text}"


def query_embedding_input(query: str) -> str:
    return f"task: search result | query: {query.strip()}"


class EmbeddingProviderError(Exception):
    """Safe, user-facing embedding provider failure."""


class EmbeddingProvider(ABC):
    provider_name: str
    model_name: str
    embedding_version = EMBEDDING_VERSION
    prompt_version = PROMPT_VERSION
    dimensions = EMBEDDING_DIMENSIONS

    @abstractmethod
    def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        raise NotImplementedError

    def metadata(self) -> dict[str, str | int]:
        return {
            "provider": self.provider_name,
            "model": self.model_name,
            "embedding_version": self.embedding_version,
            "prompt_version": self.prompt_version,
            "dimensions": self.dimensions,
        }
