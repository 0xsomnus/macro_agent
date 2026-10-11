"""Session-scoped daily publication without source fetches or model calls."""

import re

from django.core.exceptions import PermissionDenied
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from macro_agent.desk import publication, service
from macro_agent.theses import service as theses

from .daily_publication_serializers import (
    CurrentDailyBriefSerializer, DailyPublicationDetailSerializer,
    DailyPublicationPreviewSerializer, PublishDailyReviewSerializer,
)
from .serializers import ErrorResponseSerializer
from .views import CommandConflict, InvalidCommand, ThesisAPIView, _reject_query


READ_ERRORS = {400: ErrorResponseSerializer, 403: ErrorResponseSerializer,
               404: ErrorResponseSerializer, 409: ErrorResponseSerializer}


def _call_service(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (PermissionError, PermissionDenied, theses.ThesisUnavailable):
        raise NotFound("Internal daily publication unavailable.") from None
    except theses.ThesisConflict:
        raise CommandConflict("Daily publication conflicts with the reviewed or retained state.") from None
    except (ValueError, TypeError):
        raise InvalidCommand("Invalid daily-publication command or query.") from None


class InternalDailyPublicationAPIView(ThesisAPIView):
    def initial(self, request, *args, **kwargs):
        try:
            service.gate()
        except (PermissionError, PermissionDenied):
            raise NotFound("Internal daily publication unavailable.") from None
        super().initial(request, *args, **kwargs)


class CurrentDailyBriefView(InternalDailyPublicationAPIView):
    @extend_schema(operation_id="get_current_daily_brief", tags=["internal daily publication"],
        responses={200: CurrentDailyBriefSerializer, **READ_ERRORS},
        description=("Read the protected owner-scoped current daily brief in a read-only snapshot. "
            "An absent or invalidated pointer returns null without a historical fallback. "
            "No source fetch, model call, publication write or external delivery."))
    def get(self, request, thesis_id):
        _reject_query(request)
        return Response(_call_service(publication.get_current_brief,
                                      str(request.user.pk), str(thesis_id)))


class DailyPublicationDetailView(InternalDailyPublicationAPIView):
    @extend_schema(operation_id="get_daily_publication", tags=["internal daily publication"],
        responses={200: DailyPublicationDetailSerializer, **READ_ERRORS},
        description=("Read an immutable publication decision and exact retained review, with present "
            "disposition and notification-intent state observed separately in a read-only snapshot. "
            "No source fetch, model call, publication write or external delivery."))
    def get(self, request, publication_id):
        _reject_query(request)
        return Response(_call_service(publication.inspect_publication,
                                      str(request.user.pk), str(publication_id)))


class DailyPublicationPreviewView(InternalDailyPublicationAPIView):
    @extend_schema(operation_id="preview_daily_publication", tags=["internal daily publication"],
        parameters=[OpenApiParameter("fanout_limit", OpenApiTypes.INT, required=True,
            description="Explicit publication fanout limit from 1 to 1000; no inferred default.")],
        responses={200: DailyPublicationPreviewSerializer, **READ_ERRORS},
        description=("Read exact review digest and current generation for explicit publication review. "
            "Preview makes no state changes, source requests, model calls or notification intents."))
    def get(self, request, review_id):
        _reject_query(request, ("fanout_limit",))
        raw = request.query_params.get("fanout_limit", "")
        if not re.fullmatch(r"[0-9]{1,4}", raw) or not 1 <= int(raw) <= 1000:
            raise serializers.ValidationError({"fanout_limit": ["An integer from 1 to 1000 is required."]})
        return Response(_call_service(publication.preview_publication,
            str(request.user.pk), str(review_id), int(raw)))


class DailyReviewPublishView(InternalDailyPublicationAPIView):
    @extend_schema(operation_id="publish_daily_review", tags=["internal daily publication"],
        request=PublishDailyReviewSerializer,
        responses={200: DailyPublicationDetailSerializer, **READ_ERRORS, 415: ErrorResponseSerializer},
        description=("Explicit one-off session/CSRF publication of the exact review digest at the expected "
            "generation under the requested fanout bound. Compare dependencies, publication pointer and "
            "atomic internal notification intent in one protected transaction. Saved-command replay retains "
            "the original decision. This does not enroll automatic publication or enable external delivery."))
    def post(self, request, review_id):
        command = self.validated_command(request, PublishDailyReviewSerializer)
        return Response(_call_service(publication.publish_review,
                                      str(request.user.pk), str(review_id), **command))
