"""Django session commands with CSRF checks including anonymous login."""

from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.middleware.csrf import get_token, rotate_token
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_POST
from rest_framework.exceptions import APIException, ParseError

from macro_agent.api.parsers import MAX_BODY_BYTES, decode_json_body, require_json_content_type
from macro_agent.api.serializers import EmptySerializer, LoginSerializer


def _identity(request):
    authenticated = request.user.is_authenticated
    return {
        "authenticated": authenticated,
        "user": {"id": str(request.user.pk), "username": request.user.get_username()} if authenticated else None,
        # The cookie is HttpOnly. Return Django's masked token for the same-origin UI.
        "csrf_token": get_token(request),
    }


def _body(request, serializer_class):
    require_json_content_type(request)
    if request.GET:
        raise ParseError("Query parameters are not accepted.")
    value = decode_json_body(request.read(MAX_BODY_BYTES + 1))
    serializer = serializer_class(data=value)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _invalid(exc):
    return JsonResponse({"detail": "Invalid request."}, status=exc.status_code)


@never_cache
@ensure_csrf_cookie
@require_GET
def session_identity(request):
    if request.GET:
        return JsonResponse({"detail": "Query parameters are not accepted."}, status=400)
    return JsonResponse(_identity(request))


@never_cache
@csrf_protect
@sensitive_post_parameters("password")
@require_POST
def session_login(request):
    try:
        credentials = _body(request, LoginSerializer)
    except APIException as exc:
        return _invalid(exc)
    user = authenticate(request, username=credentials["username"], password=credentials["password"])
    if user is None:
        return JsonResponse({"detail": "Invalid credentials."}, status=403)
    login(request, user)
    return JsonResponse(_identity(request))


@never_cache
@csrf_protect
@require_POST
def session_logout(request):
    try:
        _body(request, EmptySerializer)
    except APIException as exc:
        return _invalid(exc)
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=403)
    logout(request)
    rotate_token(request)
    return JsonResponse(_identity(request))
