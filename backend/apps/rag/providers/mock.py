import hashlib
import math

from apps.rag.providers.base import (
    EMBEDDING_DIMENSIONS,
    EmbeddingProvider,
    EmbeddingProviderError,
)


class MockEmbeddingProvider(EmbeddingProvider):
    provider_name = "mock"
    model_name = "mock-embedding-768"

    def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        if not text.strip():
            raise EmbeddingProviderError("embedding_input_empty")
        values = []
        for index in range(EMBEDDING_DIMENSIONS):
            digest = hashlib.sha256(f"mock-v1:{index}:{text}".encode()).digest()
            integer = int.from_bytes(digest[:8], "big")
            values.append((integer / 2**63) - 1.0)
        norm = math.sqrt(sum(value * value for value in values))
        if not math.isfinite(norm) or norm == 0:
            raise EmbeddingProviderError("mock_embedding_invalid")
        return [value / norm for value in values]
