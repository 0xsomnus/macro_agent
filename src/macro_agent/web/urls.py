from django.contrib import admin
from django.http import JsonResponse
from django.urls import path


def health(request):
    return JsonResponse({"service": "macro-agent", "scope": "foundation"})


urlpatterns = [path("health/", health, name="health"), path("admin/", admin.site.urls)]
