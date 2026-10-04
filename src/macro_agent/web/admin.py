from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class DeskUserAdmin(UserAdmin):
    """Django's existing account controls; domain records use separate read-only views."""
    readonly_fields = ("id",)
