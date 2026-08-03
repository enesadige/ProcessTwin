from .base import *

SECRET_KEY = "test-secret-key"
DEBUG = False
RAG_EMBEDDING_PROVIDER = "mock"
RAG_ALLOW_MOCK_EMBEDDINGS = True

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
