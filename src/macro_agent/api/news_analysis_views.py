"""Owner-scoped, development-only retained-report analysis for inspection."""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound
from rest_framework.response import Response

from macro_agent.monitoring import analysis as service

from .news_analysis_serializers import (
    AnalyseNextRequestSerializer, NewsAnalysisResponseSerializer,
    NewsCatalogResponseSerializer, NewsReviewContextSerializer,
)
from .serializers import ErrorResponseSerializer
from .views import ERROR_RESPONSES, InvalidCommand, ThesisAPIView, _reject_query


class NewsServiceUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Internal news analysis unavailable."
    default_code = "unavailable"


class NewsAdmissionLimit(APIException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_detail = "Internal model admission limit reached."
    default_code = "admission_limit"


class NewsCommandConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The command conflicts with current approval, exposure, or saved analysis."
    default_code = "conflict"


def _call_service(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except PermissionError:
        raise NotFound("Internal news analysis unavailable.") from None
    except service.NewsUnavailable:
        raise NewsServiceUnavailable() from None
    except service.NewsBudgetExhausted:
        raise NewsAdmissionLimit() from None
    except service.NewsConflict:
        raise NewsCommandConflict() from None
    except (ValueError, TypeError):
        raise InvalidCommand("Invalid news-analysis command.") from None


class InternalNewsAPIView(ThesisAPIView):
    def initial(self, request, *args, **kwargs):
        try:
            service.gate()
        except service.NewsDisabled:
            raise NotFound("Internal news analysis unavailable.") from None
        super().initial(request, *args, **kwargs)


class NewsSourcesView(InternalNewsAPIView):
    @extend_schema(
        operation_id="news_source_catalog", tags=["internal news analysis"],
        responses={200: NewsCatalogResponseSerializer, 400: ErrorResponseSerializer,
                   403: ErrorResponseSerializer, 404: ErrorResponseSerializer},
        description=("Inspect available retained sources and bounded report counts. "
                     "Counts do not establish complete coverage, materiality or automatic monitoring."),
    )
    def get(self, request):
        _reject_query(request)
        return Response(_call_service(service.news_catalog, str(request.user.pk)))


class NewsReviewContextView(InternalNewsAPIView):
    @extend_schema(
        operation_id="news_review_context", tags=["internal news analysis"],
        responses={200: NewsReviewContextSerializer, 400: ErrorResponseSerializer,
                   403: ErrorResponseSerializer, 404: ErrorResponseSerializer,
                   409: ErrorResponseSerializer},
        description=("Inspect exact approved thesis meaning and the complete attached paper book. "
                     "The approval and exposure digest pin the subsequent command. "
                     "This is not a complete user portfolio or validated exposure mapping."),
    )
    def get(self, request, thesis_id):
        _reject_query(request)
        return Response(_call_service(service.review_context, str(request.user.pk), str(thesis_id)))


class AnalyseNextView(InternalNewsAPIView):
    @extend_schema(
        operation_id="analyse_next_report", tags=["internal news analysis"],
        request=AnalyseNextRequestSerializer,
        responses={200: NewsAnalysisResponseSerializer, **ERROR_RESPONSES,
                   429: ErrorResponseSerializer, 503: ErrorResponseSerializer},
        description=("Automatically select the next retained report from the chosen source and perform at most "
                     "one explicitly initiated model call. Inspect status even on HTTP 200. "
                     "Admission is saved before inference; command retries return history without another call. "
                     "Approved meaning, paper declarations, screening work and notification intents remain unchanged. "
                     "Attributed quotations are report claims; portfolio effects are unverified hypotheses. "
                     "This one-pass review is not a daemon, verified macro context or full coverage."),
    )
    def post(self, request, thesis_id):
        command = self.validated_command(request, AnalyseNextRequestSerializer)
        return Response(_call_service(service.analyse_next, str(request.user.pk), str(thesis_id), **command))


class NewsAnalysisDetailView(InternalNewsAPIView):
    @extend_schema(
        operation_id="get_news_analysis", tags=["internal news analysis"],
        responses={200: NewsAnalysisResponseSerializer, 400: ErrorResponseSerializer,
                   403: ErrorResponseSerializer, 404: ErrorResponseSerializer,
                   409: ErrorResponseSerializer},
        description=("Read owner-scoped immutable analysis history and its current dependency disposition. "
                     "Reading a running or unknown attempt never initiates inference or a retry."),
    )
    def get(self, request, thesis_id, attempt_id):
        _reject_query(request)
        return Response(_call_service(service.get_analysis, str(request.user.pk), str(thesis_id), str(attempt_id)))


class NewsCommandDetailView(InternalNewsAPIView):
    @extend_schema(
        operation_id="get_news_command_receipt", tags=["internal news analysis"],
        responses={200: NewsAnalysisResponseSerializer, 400: ErrorResponseSerializer,
                   403: ErrorResponseSerializer, 404: ErrorResponseSerializer,
                   409: ErrorResponseSerializer},
        description=("Recover an owner-scoped saved news command by its client-generated UUID. "
                     "This GET performs no model catalogue call, inference, approval or write fallback. "
                     "Inspect status and current disposition even on HTTP 200. "
                     "An absent or inaccessible receipt is opaque and does not authorize another paid attempt."),
    )
    def get(self, request, thesis_id, command_id):
        _reject_query(request)
        return Response(_call_service(service.get_news_command, str(request.user.pk), str(thesis_id), str(command_id)))
