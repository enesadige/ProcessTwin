import math

import httpx
from django.conf import settings

from apps.rag.providers.base import (
    EmbeddingProvider,
    EmbeddingProviderError,
    content_without_repeated_heading,
    section_path_text,
)


class OllamaEmbeddingProvider(EmbeddingProvider):
    provider_name = "ollama"
    model_name = "nomic-embed-text-v2-moe"
    dimensions = 768
    embedding_version = "nomic-embed-v2-moe-768-v1"
    document_prompt_version = "nomic-section-aware-document-v1"
    query_prompt_version = "nomic-search-query-v1"
    production_semantic_allowed = True
    include_output_options = False

    def __init__(self):
        self.base_url = getattr(
            settings,
            "OLLAMA_BASE_URL",
            "http://127.0.0.1:11434",
        ).rstrip("/")
        self.timeout = getattr(settings, "RAG_OLLAMA_TIMEOUT_SECONDS", 30.0)
        self.bulk_timeout = getattr(settings, "RAG_OLLAMA_BULK_TIMEOUT_SECONDS", 300.0)
        self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout)

    def document_input(
        self,
        document_title: str,
        document_code: str,
        section_path: list[str] | str | None,
        heading: str,
        text: str,
    ) -> str:
        if isinstance(section_path, list):
            path = " > ".join(part.strip() for part in section_path if part.strip())
        else:
            path = (section_path or "").strip()
        return (
            f"search_document: document_title: {document_title.strip()}\n"
            f"document_code: {document_code.strip()}\n"
            f"section_path: {path or heading.strip()}\n"
            f"section_heading: {heading.strip()}\n"
            f"content: {text}"
        )

    def query_input(self, query: str) -> str:
        return f"search_query: {query.strip()}"

    def validate_ready(self) -> None:
        response = self._request("GET", "/api/tags")
        try:
            names = {item["name"] for item in response.json().get("models", [])}
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise EmbeddingProviderError("ollama_invalid_response") from exc
        if self.model_name not in names and f"{self.model_name}:latest" not in names:
            raise EmbeddingProviderError("ollama_model_missing")

    def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        return self.embed_many([text], is_query=is_query)[0]

    def embed_many(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        if not texts or any(not text.strip() for text in texts):
            raise EmbeddingProviderError("embedding_input_empty")
        response = self._request(
            "POST",
            "/api/embed",
            json=self.request_payload(texts),
            timeout=self.timeout if is_query else self.bulk_timeout,
        )
        try:
            payload = response.json()
            response_model = payload.get("model")
            embeddings = payload["embeddings"]
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise EmbeddingProviderError("ollama_invalid_response") from exc
        if response_model not in (None, self.model_name, f"{self.model_name}:latest"):
            raise EmbeddingProviderError("ollama_invalid_response")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise EmbeddingProviderError("ollama_invalid_response")
        results = []
        for values in embeddings:
            if not isinstance(values, list) or len(values) != self.dimensions:
                raise EmbeddingProviderError("ollama_dimension_mismatch")
            result = [float(value) for value in values]
            if not all(math.isfinite(value) for value in result):
                raise EmbeddingProviderError("ollama_invalid_response")
            results.append(result)
        return results

    def request_payload(self, texts: list[str]) -> dict:
        payload = {"model": self.model_name, "input": texts}
        if self.include_output_options:
            payload.update({"dimensions": self.dimensions, "truncate": False})
        return payload

    def _request(self, method: str, path: str, **kwargs):
        for attempt in range(3):
            try:
                response = self._client.request(method, path, **kwargs)
            except httpx.TimeoutException as exc:
                if attempt == 2:
                    raise EmbeddingProviderError("ollama_timeout") from exc
                continue
            except httpx.RequestError as exc:
                if attempt == 2:
                    raise EmbeddingProviderError("ollama_unavailable") from exc
                continue
            if response.status_code >= 500:
                if attempt == 2:
                    raise EmbeddingProviderError("ollama_request_failed")
                continue
            if response.status_code == 404:
                raise EmbeddingProviderError("ollama_model_missing")
            if response.status_code >= 400:
                raise EmbeddingProviderError("ollama_request_failed")
            return response
        raise EmbeddingProviderError("ollama_request_failed")


class Qwen3EmbeddingProvider(OllamaEmbeddingProvider):
    embedding_version: str
    document_prompt_version = "qwen3-section-document-v1"
    query_prompt_version = "qwen3-telecom-query-v1"
    include_output_options = True
    unload_after_response = True
    query_instruction = (
        "Given a Turkish telecom operations query, retrieve the most relevant "
        "document section that directly answers the query."
    )

    def document_input(
        self,
        document_title: str,
        document_code: str,
        section_path: list[str] | str | None,
        heading: str,
        text: str,
    ) -> str:
        heading_text = heading.strip()
        path = section_path_text(section_path)
        content = content_without_repeated_heading(text, heading_text)
        return (
            f"document_title: {document_title.strip()}\n"
            f"document_code: {document_code.strip()}\n"
            f"section_path: {path or heading_text}\n"
            f"section_heading: {heading_text}\n"
            f"content: {content}"
        )

    def query_input(self, query: str) -> str:
        return f"Instruct: {self.query_instruction}\nQuery: {query.strip()}"

    def request_payload(self, texts: list[str]) -> dict:
        payload = super().request_payload(texts)
        if self.unload_after_response:
            payload["keep_alive"] = 0
        return payload


class Qwen3Embedding06BProvider(Qwen3EmbeddingProvider):
    model_name = "qwen3-embedding:0.6b"
    embedding_version = "qwen3-embedding-0.6b-768-v1"


class Qwen3Embedding4BProvider(Qwen3EmbeddingProvider):
    model_name = "qwen3-embedding:4b"
    embedding_version = "qwen3-embedding-4b-768-v1"


class Qwen3Embedding4BBaselineProvider(Qwen3Embedding4BProvider):
    query_prompt_version = "qwen3-query-baseline-v1"

    def query_input(self, query: str) -> str:
        return query.strip()
