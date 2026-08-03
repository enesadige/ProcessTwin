import hashlib
import unicodedata


def normalize_markdown(content: str) -> str:
    normalized = unicodedata.normalize("NFC", content.replace("\r\n", "\n").replace("\r", "\n"))
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    return normalized.rstrip("\n") + "\n"


def content_hash(content: str) -> str:
    return hashlib.sha256(normalize_markdown(content).encode("utf-8")).hexdigest()
