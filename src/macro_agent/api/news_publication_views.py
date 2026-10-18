"""Session publication and recovery never start inference or external delivery."""

import re
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from django.core.exceptions import PermissionDenied

from macro_agent.monitoring import publication
from macro_agent.desk import service as desk
from macro_agent.theses import service as theses
from .daily_publication_views import READ_ERRORS
from .news_publication_serializers import (
    POLICY, CurrentNewsBriefSerializer, NewsPublicationDetailSerializer,
    NewsPublicationPreviewSerializer, PublishNewsSerializer,
)
from .serializers import ErrorResponseSerializer
from .views import CommandConflict, InvalidCommand, ThesisAPIView, _reject_query


def _call_service(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (PermissionError, PermissionDenied, theses.ThesisUnavailable):
        raise NotFound("Internal driver publication unavailable.") from None
    except theses.ThesisConflict:
        raise CommandConflict("Driver publication conflicts with the retained or reviewed state.") from None
    except (ValueError, TypeError):
        raise InvalidCommand("Invalid driver-publication command or query.") from None


class DriverPublicationAPIView(ThesisAPIView):
    def initial(self, request, *args, **kwargs):
        try:
            desk.gate()
        except (PermissionError, PermissionDenied):
            raise NotFound("Internal driver publication unavailable.") from None
        super().initial(request, *args, **kwargs)


class NewsPublicationPreviewView(DriverPublicationAPIView):
    @extend_schema(operation_id="preview_news_publication", tags=["internal driver publication"],
        parameters=[OpenApiParameter("fanout_limit", OpenApiTypes.INT, required=True),
                    OpenApiParameter("policy_version", OpenApiTypes.STR, required=True, enum=[POLICY])],
        responses={200: NewsPublicationPreviewSerializer, **READ_ERRORS},
        description="Read the exact cumulative driver analysis, generation and explicit qualified-review policy. Makes no publication or inference call.")
    def get(self, request, analysis_id):
        _reject_query(request, ("fanout_limit", "policy_version"))
        raw = request.query_params.get("fanout_limit", "")
        policy = request.query_params.get("policy_version", "")
        if not re.fullmatch(r"[0-9]{1,4}", raw) or not 1 <= int(raw) <= 1000 or policy != POLICY:
            raise serializers.ValidationError("An explicit bounded fanout and supported review policy are required.")
        return Response(_call_service(publication.preview_publication,
            str(request.user.pk), str(analysis_id), int(raw), policy))


class NewsPublishView(DriverPublicationAPIView):
    @extend_schema(operation_id="publish_driver_news", tags=["internal driver publication"],
        request=PublishNewsSerializer,
        responses={200: NewsPublicationDetailSerializer, **READ_ERRORS, 415: ErrorResponseSerializer},
        description=("Publish an exact retained cumulative driver analysis under protected dependencies. "
            "A separate explicit policy determines qualified internal review intent. "
            "Saved decisions cannot reactivate and no external delivery or inference occurs."))
    def post(self, request, analysis_id):
        command = self.validated_command(request, PublishNewsSerializer)
        return Response(_call_service(publication.publish_analysis,
            str(request.user.pk), str(analysis_id), **command))


class NewsPublicationDetailView(DriverPublicationAPIView):
    @extend_schema(operation_id="get_news_publication", tags=["internal driver publication"],
        responses={200: NewsPublicationDetailSerializer, **READ_ERRORS})
    def get(self, request, publication_id):
        _reject_query(request)
        return Response(_call_service(publication.inspect_publication,
            str(request.user.pk), str(publication_id)))


class NewsPublicationCommandView(DriverPublicationAPIView):
    @extend_schema(operation_id="get_news_publication_command", tags=["internal driver publication"],
        responses={200: NewsPublicationDetailSerializer, **READ_ERRORS})
    def get(self, request, thesis_id, command_id):
        _reject_query(request)
        return Response(_call_service(publication.get_publication_command,
            str(request.user.pk), str(thesis_id), str(command_id)))


class CurrentNewsBriefView(DriverPublicationAPIView):
    @extend_schema(operation_id="get_current_news_brief", tags=["internal driver publication"],
        responses={200: CurrentNewsBriefSerializer, **READ_ERRORS},
        description="Protected current driver-news pointer only, with no historical fallback or external delivery.")
    def get(self, request, thesis_id):
        _reject_query(request)
        return Response(_call_service(publication.get_current_brief,
            str(request.user.pk), str(thesis_id)))
