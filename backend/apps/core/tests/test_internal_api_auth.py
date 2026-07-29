import logging

import pytest
from django.test import override_settings

SERVICE_TOKEN = "test-internal-service-token"


@override_settings(INTERNAL_API_SERVICE_TOKEN=SERVICE_TOKEN)
def test_internal_health_rejects_missing_token(client):
    response = client.get("/api/internal/v1/health/")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_failed"
    assert "X-Correlation-ID" in response.headers


@override_settings(INTERNAL_API_SERVICE_TOKEN=SERVICE_TOKEN)
def test_internal_health_rejects_wrong_token(client):
    response = client.get(
        "/api/internal/v1/health/",
        HTTP_AUTHORIZATION="Bearer wrong-token",
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_failed"


@override_settings(INTERNAL_API_SERVICE_TOKEN=SERVICE_TOKEN)
def test_internal_health_accepts_correct_bearer_token(client):
    response = client.get(
        "/api/internal/v1/health/",
        HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}",
        HTTP_X_CORRELATION_ID="req-039-ok",
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "internal-api",
    }
    assert response.headers["X-Correlation-ID"] == "req-039-ok"


@override_settings(INTERNAL_API_SERVICE_TOKEN="")
def test_internal_health_fails_closed_when_backend_token_is_not_configured(client):
    response = client.get(
        "/api/internal/v1/health/",
        HTTP_AUTHORIZATION="Bearer any-token",
    )

    assert response.status_code == 401


@override_settings(INTERNAL_API_SERVICE_TOKEN=SERVICE_TOKEN)
def test_internal_health_does_not_accept_query_or_body_token(client):
    query_response = client.get(f"/api/internal/v1/health/?token={SERVICE_TOKEN}")
    body_response = client.post(
        "/api/internal/v1/health/",
        data={"token": SERVICE_TOKEN},
        content_type="application/json",
    )

    assert query_response.status_code == 401
    assert body_response.status_code == 401


@override_settings(INTERNAL_API_SERVICE_TOKEN=SERVICE_TOKEN)
def test_internal_health_round_trips_valid_correlation_id(client):
    response = client.get(
        "/api/internal/v1/health/",
        HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}",
        HTTP_X_CORRELATION_ID="req-039_ABC:123.ok",
    )

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "req-039_ABC:123.ok"


@override_settings(INTERNAL_API_SERVICE_TOKEN=SERVICE_TOKEN)
@pytest.mark.parametrize(
    "correlation_id",
    [
        "bad id with spaces",
        "x" * 129,
        "../not-allowed",
    ],
)
def test_internal_health_rejects_invalid_correlation_id(client, correlation_id):
    response = client.get(
        "/api/internal/v1/health/",
        HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}",
        HTTP_X_CORRELATION_ID=correlation_id,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert "X-Correlation-ID" not in response.headers


@override_settings(INTERNAL_API_SERVICE_TOKEN=SERVICE_TOKEN)
def test_internal_auth_does_not_log_authorization_header_or_token(client, caplog):
    logger = logging.getLogger("apps.core.internal_api")

    with caplog.at_level(logging.INFO):
        logger.info("internal auth test started")
        response = client.get(
            "/api/internal/v1/health/",
            HTTP_AUTHORIZATION="Bearer wrong-token",
            HTTP_X_CORRELATION_ID="req-039-log-check",
        )

    assert response.status_code == 401
    assert SERVICE_TOKEN not in caplog.text
    assert "wrong-token" not in caplog.text
    assert "Authorization" not in caplog.text


def test_public_health_endpoint_is_not_affected_by_internal_auth(client):
    response = client.get("/api/health/")

    assert response.status_code == 200
    assert response.json() == {
        "status": "exact",
        "service": "backend",
    }
