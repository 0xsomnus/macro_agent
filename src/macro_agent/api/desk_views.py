"""Authenticated internal inspection of retained reviews, without paid work."""

from django.core.exceptions import PermissionDenied
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from macro_agent.desk import reading, service
from macro_agent.theses import service as theses

from .desk_serializers import DailyReviewDetailSerializer, DailyReviewListSerializer
from .serializers import ErrorResponseSerializer
from .views import CommandConflict, InvalidCommand, ThesisAPIView, _pagination, _reject_query


READ_ERRORS = {400: ErrorResponseSerializer, 403: ErrorResponseSerializer,
               404: ErrorResponseSerializer, 409: ErrorResponseSerializer}


def _call_service(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (PermissionError, PermissionDenied):
        raise NotFound("Internal daily review unavailable.") from None
    except theses.ThesisConflict:
        raise CommandConflict("Daily review observation conflicts with retained or present state.") from None
    except (ValueError, TypeError):
        raise InvalidCommand("Invalid daily-review query.") from None


class InternalDeskReadAPIView(ThesisAPIView):
    def initial(self, request, *args, **kwargs):
        try:
            service.gate()
        except (PermissionError, PermissionDenied):
            raise NotFound("Internal daily review unavailable.") from None
        super().initial(request, *args, **kwargs)


class DailyReviewCollectionView(InternalDeskReadAPIView):
    @extend_schema(
        operation_id="list_daily_reviews", tags=["internal daily reviews"],
        parameters=[
            OpenApiParameter("limit", OpenApiTypes.INT, description="Page size from 1 to 100; default 20."),
            OpenApiParameter("offset", OpenApiTypes.INT, description="Offset from 0 to 1000000; default 0."),
        ],
        responses={200: DailyReviewListSerializer, **READ_ERRORS},
        description=(
            "Read owner-scoped summaries in descending cutoff and ID order. Count, page and present "
            "dependency disposition share one repeatable-read, read-only snapshot. Subsequent requests "
            "get a new snapshot; offset pagination is not a historical cursor. Original outcome stays "
            "separate from present disposition. No full context, current publication claim, source fetch, "
            "model catalogue call, inference or write fallback."
        ),
    )
    def get(self, request, thesis_id):
        return Response(_call_service(reading.list_reviews, str(request.user.pk), str(thesis_id),
                                      **_pagination(request)))


class DailyReviewDetailView(InternalDeskReadAPIView):
    @extend_schema(
        operation_id="get_daily_review", tags=["internal daily reviews"],
        responses={200: DailyReviewDetailSerializer, **READ_ERRORS},
        description=(
            "Read an owner-scoped immutable daily evidence review, verifying its saved content digest. "
            "Exact original outcome and inputs remain unchanged when present dependencies are stale. "
            "Present disposition is observed separately in one read-only snapshot. This is not a published "
            "current morning brief and grants no notification or retry authority. No source fetch, model "
            "catalogue call, inference or write fallback."
        ),
    )
    def get(self, request, review_id):
        _reject_query(request)
        return Response(_call_service(service.inspect_review, str(request.user.pk), str(review_id)))
