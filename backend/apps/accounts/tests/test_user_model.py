import pytest
from django.contrib.auth import get_user_model

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
