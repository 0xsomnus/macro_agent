"""Owner-scoped, view-only diagnostics, never an alternative domain write path."""

from django.contrib import admin
from django.core.exceptions import PermissionDenied

from .models import (AssessmentRecord, AuditTransition, BriefStateRecord, BriefVersion,
                     CurrentAssessment, DependencyHead, DependencyVersion, NotificationIntent,
                     ReassessmentWork)


class OwnerReadonlyAdmin(admin.ModelAdmin):
    actions = None
    owner_lookup = "brief__owner"

    def get_queryset(self, request):
        return super().get_queryset(request).filter(**{self.owner_lookup: request.user})

    def has_view_permission(self, request, obj=None):
        if not super().has_view_permission(request, obj):
            return False
        if obj is None:
            return True
        owner_id = obj.owner_id if isinstance(obj, BriefStateRecord) else obj.brief.owner_id
        return owner_id == request.user.pk

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        raise PermissionDenied("Domain records cannot be written through administration")

    def delete_model(self, request, obj):
        raise PermissionDenied("Domain history cannot be deleted through administration")

    def delete_queryset(self, request, queryset):
        raise PermissionDenied("Domain history cannot be deleted through administration")


@admin.register(BriefStateRecord)
class BriefAdmin(OwnerReadonlyAdmin):
    owner_lookup = "owner"
    list_display = ("brief_id", "generation", "changed_at")


for model in (AssessmentRecord, AuditTransition, BriefVersion, CurrentAssessment,
              DependencyHead, DependencyVersion, NotificationIntent, ReassessmentWork):
    admin.site.register(model, OwnerReadonlyAdmin)
