from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.core.models import TimeStampedModel


class UserRole(models.TextChoices):
    VIEWER = "viewer", "Viewer"
    ANALYST = "analyst", "Analyst"
    ENGINEER = "engineer", "Engineer"
    ADMIN = "admin", "Admin"


class User(AbstractUser, TimeStampedModel):
    role = models.CharField(max_length=24, choices=UserRole.choices, default=UserRole.VIEWER)

    class Meta:
        db_table = "accounts_user"
        ordering = ["username"]

    @property
    def is_viewer(self) -> bool:
        return self.role == UserRole.VIEWER

    @property
    def is_analyst(self) -> bool:
        return self.role == UserRole.ANALYST

    @property
    def is_engineer(self) -> bool:
        return self.role == UserRole.ENGINEER

    @property
    def is_domain_admin(self) -> bool:
        return self.role == UserRole.ADMIN

    def has_role(self, *roles: UserRole | str) -> bool:
        return self.role in {str(role) for role in roles}
