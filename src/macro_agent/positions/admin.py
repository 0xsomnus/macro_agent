"""Read-only private inspection, including staff and superuser accounts."""

from django.contrib import admin
from django.core.exceptions import PermissionDenied

from .models import AuditTransition, CommandReceipt, PositionRecord, PositionVersion


class PositionReadonlyAdmin(admin.ModelAdmin):
    actions = None
    owner_lookup = "owner"

    def get_queryset(self, request):
        return super().get_queryset(request).filter(**{self.owner_lookup: request.user})

    def has_view_permission(self, request, obj=None):
        if not super().has_view_permission(request, obj):
            return False
        if obj is None:
            return True
        owner_id = obj.position.owner_id if isinstance(obj, AuditTransition) else obj.owner_id
        return owner_id == request.user.pk

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        raise PermissionDenied("Paper position commands cannot be written through administration")

    def delete_model(self, request, obj):
        raise PermissionDenied("Paper position history cannot be deleted through administration")

    def delete_queryset(self, request, queryset):
        raise PermissionDenied("Paper position history cannot be deleted through administration")


@admin.register(PositionRecord)
class PositionAdmin(PositionReadonlyAdmin):
    list_display = ("id", "thesis", "revision", "created_at", "changed_at")


admin.site.register(PositionVersion, PositionReadonlyAdmin)
admin.site.register(CommandReceipt, PositionReadonlyAdmin)


@admin.register(AuditTransition)
class PositionAuditAdmin(PositionReadonlyAdmin):
    owner_lookup = "position__owner"
