"""Authenticated paper-position commands through owner-scoped services."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound
from rest_framework.response import Response

from macro_agent.positions import service

from .position_serializers import (
    ClosePositionSerializer, CreatePositionSerializer, PositionCommandResponseSerializer,
    PositionDetailSerializer, PositionHistorySerializer, PositionListSerializer,
    RevisePositionSerializer,
)
from .serializers import ErrorResponseSerializer
from .views import ERROR_RESPONSES, InvalidCommand, ThesisAPIView, _pagination, _reject_query


class PositionCommandConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The command conflicts with the current position, thesis approval, or saved command."
    default_code = "conflict"


def _call_service(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except service.PositionUnavailable:
        raise NotFound("Position unavailable.") from None
    except service.PositionConflict:
        raise PositionCommandConflict() from None
    except (ValueError, TypeError):
        raise InvalidCommand("Invalid paper-position command.") from None


class PositionCollectionView(ThesisAPIView):
    @extend_schema(
        operation_id="list_positions", tags=["paper positions"],
        parameters=[
            OpenApiParameter("limit", OpenApiTypes.INT, description="Page size from 1 to 100; default 20."),
            OpenApiParameter("offset", OpenApiTypes.INT, description="Offset from 0 to 1000000; default 0."),
        ],
        responses={200: PositionListSerializer, 400: ErrorResponseSerializer,
                   403: ErrorResponseSerializer, 404: ErrorResponseSerializer},
    )
    def get(self, request, thesis_id):
        result = _call_service(service.list_positions, str(request.user.pk), str(thesis_id),
                               **_pagination(request))
        return Response(result)

    @extend_schema(
        operation_id="create_position", tags=["paper positions"], request=CreatePositionSerializer,
        description=("Attach a user-declared paper position to the exact current thesis approval. "
                     "Missing mapping or sizing information remains explicit; no broker execution or coverage is implied."),
        responses={201: PositionCommandResponseSerializer, **ERROR_RESPONSES},
    )
    def post(self, request, thesis_id):
        command = self.validated_command(request, CreatePositionSerializer)
        result = _call_service(service.create_position, str(request.user.pk), str(thesis_id), **command)
        return Response(result, status=status.HTTP_201_CREATED)


class PositionDetailView(ThesisAPIView):
    @extend_schema(
        operation_id="get_position", tags=["paper positions"],
        responses={200: PositionDetailSerializer, 400: ErrorResponseSerializer,
                   403: ErrorResponseSerializer, 404: ErrorResponseSerializer},
    )
    def get(self, request, position_id):
        _reject_query(request)
        return Response(_call_service(service.get_position, str(request.user.pk), str(position_id)))


class PositionRevisionView(ThesisAPIView):
    @extend_schema(
        operation_id="revise_position", tags=["paper positions"], request=RevisePositionSerializer,
        description=("Save a complete new immutable paper declaration after comparing the current position revision "
                     "and reviewed thesis approval. A closed position cannot be reopened."),
        responses={201: PositionCommandResponseSerializer, **ERROR_RESPONSES},
    )
    def post(self, request, position_id):
        command = self.validated_command(request, RevisePositionSerializer)
        result = _call_service(service.revise_position, str(request.user.pk), str(position_id), **command)
        return Response(result, status=status.HTTP_201_CREATED)


class PositionCloseView(ThesisAPIView):
    @extend_schema(
        operation_id="close_position", tags=["paper positions"], request=ClosePositionSerializer,
        description=("Explicitly close the paper position after comparing its current revision and thesis approval. "
                     "This saves history only and does not send a broker order."),
        responses={200: PositionCommandResponseSerializer, **ERROR_RESPONSES},
    )
    def post(self, request, position_id):
        command = self.validated_command(request, ClosePositionSerializer)
        result = _call_service(service.close_position, str(request.user.pk), str(position_id), **command)
        return Response(result)


class PositionHistoryView(ThesisAPIView):
    @extend_schema(
        operation_id="position_history", tags=["paper positions"],
        description=("Read one consistent effective-time history snapshot. Each category is capped at 100 records "
                     "with explicit truncation. This is not durable known-at replay or a complete export when truncated."),
        responses={200: PositionHistorySerializer, 400: ErrorResponseSerializer,
                   403: ErrorResponseSerializer, 404: ErrorResponseSerializer},
    )
    def get(self, request, position_id):
        _reject_query(request)
        return Response(_call_service(service.position_history, str(request.user.pk), str(position_id)))
