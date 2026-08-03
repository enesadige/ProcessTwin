import math

from django.conf import settings

from apps.rag.providers.base import (
    DOCUMENT_MODEL,
    EMBEDDING_DIMENSIONS,
    EmbeddingProvider,
    EmbeddingProviderError,
)


class GeminiEmbeddingProvider(EmbeddingProvider):
    provider_name = "gemini"
    model_name = DOCUMENT_MODEL

    def __init__(self):
        api_key = getattr(settings, "GEMINI_API_KEY", "")
        if not api_key:
            raise EmbeddingProviderError("gemini_api_key_missing")
        try:
            from google import genai
        except ImportError as exc:
            raise EmbeddingProviderError("gemini_sdk_unavailable") from exc
        self._client = genai.Client(
            api_key=api_key,
            http_options={"timeout": getattr(settings, "RAG_GEMINI_TIMEOUT_MS", 10000)},
        )

    def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        if not text.strip():
            raise EmbeddingProviderError("embedding_input_empty")
        try:
            from google.genai import types

            task_type = "RETRIEVAL_QUERY" if is_query else "RETRIEVAL_DOCUMENT"
            values = None
            last_error = None
            for _attempt in range(3):
                try:
                    response = self._client.models.embed_content(
                        model=self.model_name,
                        contents=text,
                        config=types.EmbedContentConfig(
                            taskType=task_type,
                            outputDimensionality=EMBEDDING_DIMENSIONS,
                        ),
                    )
                    values = getattr(response.embeddings[0], "values", None)
                    break
                except Exception as exc:
                    last_error = exc
            if values is None:
                raise last_error or RuntimeError("empty_gemini_response")
        except Exception as exc:
            raise EmbeddingProviderError("gemini_request_failed") from exc
        if not values or len(values) != EMBEDDING_DIMENSIONS:
            raise EmbeddingProviderError("gemini_invalid_dimensions")
        result = [float(value) for value in values]
        if not all(math.isfinite(value) for value in result):
            raise EmbeddingProviderError("gemini_invalid_values")
        return result
