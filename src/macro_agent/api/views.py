"""Authenticated commands routed through explicit thesis application services."""

import re

from drf_spectacular.utils import OpenApiParameter, extend_schema
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.views import SpectacularAPIView
from rest_framework import serializers, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import APIException, NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView, exception_handler as drf_exception_handler

from macro_agent.theses import service

from .parsers import StrictJSONParser, require_json_content_type
from .serializers import (
    ApproveThesisSerializer, CreateThesisSerializer, ErrorResponseSerializer,
    ProposeThesisSerializer, ThesisCommandResponseSerializer,
    ThesisDetailSerializer, ThesisHistorySerializer, ThesisListSerializer,
)


class CommandConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The command conflicts with the current thesis revision or saved command."
    default_code = "conflict"


class InvalidCommand(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Invalid thesis command."
    default_code = "invalid"


ERROR_RESPONSES = {
    400: ErrorResponseSerializer, 403: ErrorResponseSerializer,
    404: ErrorResponseSerializer, 409: ErrorResponseSerializer,
    415: ErrorResponseSerializer,
}


def exception_handler(exc, context):
    """Bounded errors without including application exception payloads."""
    response = drf_exception_handler(exc, context)
    if response is not None and isinstance(exc, serializers.ValidationError):
        response.data = {"detail": "Invalid request.", "errors": response.data}
    return response


def _call_service(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except service.ThesisUnavailable:
        # Foreign-owner and missing IDs deliberately share the same response.
        raise NotFound("Thesis unavailable.") from None
    except service.ThesisConflict:
        raise CommandConflict() from None
    except (ValueError, TypeError):
        raise InvalidCommand() from None


def _reject_query(request, allowed=()):
    if set(request.query_params) - set(allowed) or any(
            len(request.query_params.getlist(name)) != 1 for name in request.query_params):
        raise serializers.ValidationError("Unknown or repeated query parameters are not accepted.")


def _pagination(request):
    _reject_query(request, ("limit", "offset"))
    values = {}
    for name, default, lower, upper in (("limit", 20, 1, 100), ("offset", 0, 0, 1000000)):
        raw = request.query_params.get(name, str(default))
        if not re.fullmatch(r"[0-9]{1,7}", raw):
            raise serializers.ValidationError({name: ["A bounded decimal integer is required."]})
        value = int(raw)
        if not lower <= value <= upper:
            raise serializers.ValidationError({name: [f"Must be between {lower} and {upper}."]})
        values[name] = value
    return values


class ThesisAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [StrictJSONParser]
    renderer_classes = [JSONRenderer]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response

    def validated_command(self, request, serializer_class):
        _reject_query(request)
        require_json_content_type(request)
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data


class ThesisCollectionView(ThesisAPIView):
    @extend_schema(
        operation_id="list_theses", tags=["theses"],
        parameters=[
            OpenApiParameter("limit", OpenApiTypes.INT, description="Page size from 1 to 100; default 20."),
            OpenApiParameter("offset", OpenApiTypes.INT, description="Offset from 0 to 1000000; default 0."),
        ],
        responses={200: ThesisListSerializer, 400: ErrorResponseSerializer, 403: ErrorResponseSerializer},
    )
    def get(self, request):
        result = _call_service(service.list_theses, str(request.user.pk), **_pagination(request))
        return Response(result)

    @extend_schema(
        operation_id="create_thesis", tags=["theses"], request=CreateThesisSerializer,
        description="Save exact thesis text and a user-supplied interpretation preview. This creates a draft only.",
        responses={201: ThesisCommandResponseSerializer, **ERROR_RESPONSES},
    )
    def post(self, request):
        command = self.validated_command(request, CreateThesisSerializer)
        result = _call_service(service.create_thesis, str(request.user.pk), **command)
        return Response(result, status=status.HTTP_201_CREATED)


class ThesisDetailView(ThesisAPIView):
    @extend_schema(
        operation_id="get_thesis", tags=["theses"],
        responses={200: ThesisDetailSerializer, 400: ErrorResponseSerializer,
                   403: ErrorResponseSerializer, 404: ErrorResponseSerializer},
    )
    def get(self, request, thesis_id):
        _reject_query(request)
        return Response(_call_service(service.get_thesis, str(request.user.pk), str(thesis_id)))


class ThesisProposalView(ThesisAPIView):
    @extend_schema(
        operation_id="propose_thesis", tags=["theses"], request=ProposeThesisSerializer,
        description="Save a new immutable draft. Approved text and interpretation remain active until explicit approval.",
        responses={201: ThesisCommandResponseSerializer, **ERROR_RESPONSES},
    )
    def post(self, request, thesis_id):
        command = self.validated_command(request, ProposeThesisSerializer)
        result = _call_service(service.propose_thesis, str(request.user.pk), str(thesis_id), **command)
        return Response(result, status=status.HTTP_201_CREATED)


class ThesisApprovalView(ThesisAPIView):
    @extend_schema(
        operation_id="approve_thesis", tags=["theses"], request=ApproveThesisSerializer,
        description="Explicitly approve the exact displayed draft and interpretation by version and digest.",
        responses={200: ThesisCommandResponseSerializer, **ERROR_RESPONSES},
    )
    def post(self, request, thesis_id):
        command = self.validated_command(request, ApproveThesisSerializer)
        result = _call_service(service.approve_thesis, str(request.user.pk), str(thesis_id), **command)
        return Response(result)


class ThesisHistoryView(ThesisAPIView):
    @extend_schema(
        operation_id="thesis_history", tags=["theses"],
        description=("Read approval-effective-time history for the internal prototype. Each history category "
                     "is bounded to 100 records; truncated is explicit. This is not full operational known-at replay."),
        responses={200: ThesisHistorySerializer, 400: ErrorResponseSerializer,
                   403: ErrorResponseSerializer, 404: ErrorResponseSerializer},
    )
    def get(self, request, thesis_id):
        _reject_query(request)
        return Response(_call_service(service.thesis_history, str(request.user.pk), str(thesis_id)))


class PrivateSchemaView(SpectacularAPIView):
    """Authenticated thesis schema only; session operations use Django views."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer]

    @extend_schema(exclude=True)
    def get(self, request, *args, **kwargs):
        _reject_query(request)
        return super().get(request, *args, **kwargs)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response
