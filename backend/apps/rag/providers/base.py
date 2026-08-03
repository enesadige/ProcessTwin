from abc import ABC, abstractmethod

EMBEDDING_DIMENSIONS = 768
EMBEDDING_VERSION = "asymmetric-retrieval-v1"
PROMPT_VERSION = "rag-section-aware-document-v2"
QUERY_PROMPT_VERSION = "gemini-search-query-v1"
DOCUMENT_MODEL = "gemini-embedding-2"


def section_path_text(section_path: list[str] | str | None) -> str:
    if isinstance(section_path, list):
        return " > ".join(part.strip() for part in section_path if part.strip())
    return (section_path or "").strip()


def content_without_repeated_heading(text: str, heading: str) -> str:
    lines = text.splitlines()
    if not lines:
        return text
    first = lines[0].lstrip("#").strip()
    if first.casefold() != heading.strip().casefold():
        return text
    return "\n".join(lines[1:]).lstrip("\n")


def document_embedding_input(
    document_title: str,
    document_code: str,
    section_path: list[str] | str | None,
    heading: str,
    text: str,
) -> str:
    heading_text = heading.strip() or "(başlıksız bölüm)"
    section_text = section_path_text(section_path) or heading_text
    content_text = content_without_repeated_heading(text, heading_text)
    return (
        f"document_title: {document_title.strip()}\n"
        f"document_code: {document_code.strip()}\n"
        f"section_path: {section_text}\n"
        f"section_heading: {heading_text}\n"
        f"content:\n{content_text}"
    )


def query_embedding_input(query: str) -> str:
    return f"task: search result | query: {query.strip()}"


class EmbeddingProviderError(Exception):
    """Safe, user-facing embedding provider failure."""


class EmbeddingProvider(ABC):
    provider_name: str
    model_name: str
    embedding_version = EMBEDDING_VERSION
    document_prompt_version = PROMPT_VERSION
    query_prompt_version = QUERY_PROMPT_VERSION
    dimensions = EMBEDDING_DIMENSIONS
    production_semantic_allowed = True

    @abstractmethod
    def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        raise NotImplementedError

    def embed_many(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        return [self.embed(text, is_query=is_query) for text in texts]

    def document_input(
        self,
        document_title: str,
        document_code: str,
        section_path: list[str] | str | None,
        heading: str,
        text: str,
    ) -> str:
        return document_embedding_input(
            document_title,
            document_code,
            section_path,
            heading,
            text,
        )

    def query_input(self, query: str) -> str:
        return query_embedding_input(query)

    def validate_ready(self) -> None:
        return None

    def metadata(self) -> dict[str, str | int]:
        return {
            "provider": self.provider_name,
            "model": self.model_name,
            "embedding_version": self.embedding_version,
            "prompt_version": self.document_prompt_version,
            "document_prompt_version": self.document_prompt_version,
            "query_prompt_version": self.query_prompt_version,
            "dimensions": self.dimensions,
        }
