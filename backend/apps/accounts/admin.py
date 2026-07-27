from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.accounts.models import User


@admin.register(User)
class ProcessTwinUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("ProcessTwin", {"fields": ("role",)}),
    )
    list_display = ("username", "email", "role", "is_staff", "is_active")
    list_filter = UserAdmin.list_filter + ("role",)
