#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
import psycopg
import redis
from google import genai

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str


def load_env_file() -> None:
    if not ENV_FILE.exists():
        return

    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ[key.strip()] = value.strip()


def check_postgres() -> CheckResult:
    database_url = os.environ.get("DATABASE_URL", "postgres://localhost:5432/processtwin")
    try:
        with psycopg.connect(database_url, connect_timeout=3) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select current_database(), current_user")
                database, user = cursor.fetchone()
        return CheckResult("postgresql", "ok", f"database={database}, user={user}")
    except Exception as exc:
        return CheckResult("postgresql", "error", str(exc))


def check_pgvector() -> CheckResult:
    database_url = os.environ.get("DATABASE_URL", "postgres://localhost:5432/processtwin")
    try:
        with psycopg.connect(database_url, connect_timeout=3) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select extversion from pg_extension where extname = 'vector'")
                row = cursor.fetchone()
        if row is None:
            return CheckResult("pgvector", "error", "vector extension is not installed")
        return CheckResult("pgvector", "ok", f"version={row[0]}")
    except Exception as exc:
        return CheckResult("pgvector", "error", str(exc))


def check_redis() -> CheckResult:
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    try:
        client = redis.Redis.from_url(redis_url, socket_connect_timeout=3)
        response = client.ping()
        return CheckResult("redis", "ok", f"ping={response}")
    except Exception as exc:
        return CheckResult("redis", "error", str(exc))


def check_ollama() -> CheckResult:
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    try:
        response = httpx.get(f"{base_url}/api/tags", timeout=5)
        response.raise_for_status()
        models = [item["name"] for item in response.json().get("models", [])]
        detail = "models=" + ",".join(models) if models else "no models found"
        return CheckResult("ollama", "ok", detail)
    except Exception as exc:
        return CheckResult("ollama", "error", str(exc))


def sanitize_error(exc: Exception) -> str:
    message = str(exc)
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if api_key:
        message = message.replace(api_key, "[redacted]")
    return message.splitlines()[0][:300]


def check_gemini_config() -> CheckResult:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "")
    if not api_key:
        return CheckResult("gemini", "skipped", "GEMINI_API_KEY is not set")
    if not model or model == "<gemini-model-name>":
        return CheckResult("gemini", "skipped", "LLM_MODEL is not set to a real Gemini model")
    try:
        client = genai.Client(api_key=api_key)
        interaction = client.interactions.create(
            model=model,
            input="Reply with exactly: gemini-ok",
        )
        output_text = interaction.output_text.strip()
        if "gemini-ok" not in output_text:
            return CheckResult("gemini", "error", f"unexpected output={output_text[:80]}")
        return CheckResult("gemini", "ok", f"model={model}")
    except Exception as exc:
        return CheckResult("gemini", "error", sanitize_error(exc))


def check_mock_provider() -> CheckResult:
    return CheckResult("mock-provider", "ok", "static provider smoke check passed")


def main() -> int:
    load_env_file()
    results = [
        check_postgres(),
        check_pgvector(),
        check_redis(),
        check_ollama(),
        check_gemini_config(),
        check_mock_provider(),
    ]

    print(json.dumps([result.__dict__ for result in results], indent=2))

    has_error = any(result.status == "error" for result in results)
    return 1 if has_error else 0


if __name__ == "__main__":
    sys.exit(main())
