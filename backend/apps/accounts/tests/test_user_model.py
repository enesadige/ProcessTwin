import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.accounts.models import UserRole


@pytest.mark.django_db
def test_custom_user_defaults_to_viewer_role():
    user = get_user_model().objects.create_user(
        username="viewer-user",
        email="viewer@example.com",
        password="test-pass",
    )

    assert user.role == UserRole.VIEWER
    assert user.is_viewer is True
    assert user.has_role(UserRole.VIEWER)
    assert not user.has_role(UserRole.ADMIN)


@pytest.mark.django_db
def test_custom_user_can_represent_engineer_role():
    user = get_user_model().objects.create_user(
        username="engineer-user",
        email="engineer@example.com",
        password="test-pass",
        role=UserRole.ENGINEER,
    )

    assert user.is_engineer is True
    assert user.has_role(UserRole.ENGINEER, UserRole.ADMIN)


@pytest.mark.django_db
def test_auth_login_me_and_logout_use_session_and_expose_role():
    user = get_user_model().objects.create_user(
        username="analyst-user",
        email="analyst@example.com",
        password="correct-pass-123",
        role=UserRole.ANALYST,
    )
    client = Client(enforce_csrf_checks=True)
    client.get("/api/auth/csrf/")
    csrf = client.cookies["csrftoken"].value
    response = client.post(
        "/api/auth/login/",
        {"username": user.username, "password": "correct-pass-123"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert response.status_code == 200
    assert response.json()["user"]["role"] == UserRole.ANALYST
    assert client.get("/api/auth/me/").json()["user"]["username"] == user.username
    assert client.post(
        "/api/auth/logout/",
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    ).status_code == 200
    assert client.get("/api/auth/me/").status_code == 401


@pytest.mark.django_db
def test_auth_rejects_inactive_users():
    user = get_user_model().objects.create_user(
        username="inactive-user", password="correct-pass-123", is_active=False
    )
    response = Client().post(
        "/api/auth/login/",
        {"username": user.username, "password": "correct-pass-123"},
        content_type="application/json",
    )
    assert response.status_code == 401
