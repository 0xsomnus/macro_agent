from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from .session_views import session_identity, session_login, session_logout
from macro_agent.api.daily_publication_views import (
    CurrentDailyBriefView, DailyPublicationDetailView, DailyPublicationPreviewView,
    DailyReviewPublishView,
)


def health(request):
    return JsonResponse({"service": "macro-agent", "scope": "foundation"})


urlpatterns = [
    path("health/", health, name="health"),
    path("admin/", admin.site.urls),
    path("api/v1/session/", session_identity, name="session-identity"),
    path("api/v1/session/login/", session_login, name="session-login"),
    path("api/v1/session/logout/", session_logout, name="session-logout"),
    path("api/v1/theses/<uuid:thesis_id>/daily-brief/", CurrentDailyBriefView.as_view(), name="current-daily-brief"),
    path("api/v1/daily-publications/<uuid:publication_id>/", DailyPublicationDetailView.as_view(), name="daily-publication-detail"),
    path("api/v1/daily-reviews/<uuid:review_id>/publication-preview/", DailyPublicationPreviewView.as_view(), name="daily-publication-preview"),
    path("api/v1/daily-reviews/<uuid:review_id>/publish/", DailyReviewPublishView.as_view(), name="daily-review-publish"),
    path("api/v1/", include("macro_agent.api.urls")),
]
