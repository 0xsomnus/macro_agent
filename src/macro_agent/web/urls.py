from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from .session_views import session_identity, session_login, session_logout


def health(request):
    return JsonResponse({"service": "macro-agent", "scope": "foundation"})


urlpatterns = [
    path("health/", health, name="health"),
    path("admin/", admin.site.urls),
    path("api/v1/session/", session_identity, name="session-identity"),
    path("api/v1/session/login/", session_login, name="session-login"),
    path("api/v1/session/logout/", session_logout, name="session-logout"),
    path("api/v1/", include("macro_agent.api.urls")),
]
