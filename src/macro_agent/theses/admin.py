"""Read-only owner-scoped inspection; commands are the only write boundary."""

from django.contrib import admin
from django.core.exceptions import PermissionDenied

from .models import (
    ApprovalRecord, AuditTransition, CommandReceipt, InterpretationRecord,
    TextVersionRecord, ThesisRecord,
)


class ThesisReadonlyAdmin(admin.ModelAdmin):
    actions = None
    owner_lookup = "thesis__owner"

    def get_queryset(self, request):
        return super().get_queryset(request).filter(**{self.owner_lookup: request.user})

    def has_view_permission(self, request, obj=None):
        if not super().has_view_permission(request, obj):
            return False
        if obj is None:
            return True
        owner_id = obj.owner_id if isinstance(obj, (ThesisRecord, CommandReceipt)) else obj.thesis.owner_id
        return owner_id == request.user.pk

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        raise PermissionDenied("Thesis commands cannot be written through administration")

    def delete_model(self, request, obj):
        raise PermissionDenied("Thesis history cannot be deleted through administration")

    def delete_queryset(self, request, queryset):
        raise PermissionDenied("Thesis history cannot be deleted through administration")


@admin.register(ThesisRecord)
class ThesisAdmin(ThesisReadonlyAdmin):
    owner_lookup = "owner"
    list_display = ("id", "revision", "created_at", "changed_at")


for model in (TextVersionRecord, InterpretationRecord, ApprovalRecord, CommandReceipt, AuditTransition):
    admin.site.register(model, ThesisReadonlyAdmin)
