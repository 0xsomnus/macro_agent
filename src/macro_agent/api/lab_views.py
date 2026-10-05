"""Authenticated development-only recorded example, with explicit source gate."""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound
from rest_framework.response import Response

from macro_agent.lab import recorded_news as service

from .lab_serializers import RecordedNewsRequestSerializer, RecordedNewsResponseSerializer
from .views import ERROR_RESPONSES, InvalidCommand, ThesisAPIView


class RecordedNewsCommandConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Current approval or publication context changed. Inspect it before retrying the example."
    default_code = "conflict"


class RecordedNewsView(ThesisAPIView):
    def initial(self, request, *args, **kwargs):
        if not service.enabled():
            raise NotFound("Recorded example unavailable.")
        super().initial(request, *args, **kwargs)

    @extend_schema(
        operation_id="recorded_news", tags=["development examples"],
        request=RecordedNewsRequestSerializer, responses={200: RecordedNewsResponseSerializer, **ERROR_RESPONSES},
        description=("Development-only fictional event against your committed approval and paper declarations. "
                     "Requires explicit local settings, synthetic setup permission and a development/test database. "
                     "No model, live source, inferred portfolio impact, external delivery or continuous monitoring is provided. "
                     "Repeating the same current context returns its existing notice without another interruption."),
    )
    def post(self, request, thesis_id):
        command = self.validated_command(request, RecordedNewsRequestSerializer)
        try:
            result = service.recorded_news(str(request.user.pk), str(thesis_id), **command)
        except service.RecordedNewsUnavailable:
            raise NotFound("Recorded example unavailable.") from None
        except service.RecordedNewsConflict:
            raise RecordedNewsCommandConflict() from None
        except (ValueError, TypeError):
            raise InvalidCommand("Invalid recorded-example command.") from None
        return Response(result)
