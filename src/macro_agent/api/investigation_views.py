"""Explicitly initiated research, read-only command recovery and bounded continuation."""

from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from macro_agent.desk import investigation
from .compilation_views import InternalCompilationAPIView, _call_service
from .investigation_serializers import (
    ContinueResearchSerializer, ResearchRunResponseSerializer, StartResearchSerializer,
)
from .serializers import ErrorResponseSerializer
from .views import ERROR_RESPONSES, _reject_query


RESPONSES = {200: ResearchRunResponseSerializer, **ERROR_RESPONSES,
             429: ErrorResponseSerializer, 503: ErrorResponseSerializer}


class ResearchAPIView(InternalCompilationAPIView):
    def initial(self, request, *args, **kwargs):
        from django.conf import settings
        if getattr(settings, "MACRO_ENABLE_RESEARCH_DISCOVERY", False) is not True:
            raise NotFound("Internal research discovery unavailable.")
        super().initial(request, *args, **kwargs)


class ResearchStartView(ResearchAPIView):
    @extend_schema(operation_id="start_question_research", tags=["internal question research"],
        request=StartResearchSerializer, responses=RESPONSES,
        description=("Retain an exact rough question and bounded investigation. At most one planning and one compilation "
            "model admission; up to three metadata-only questions. Optional source_recovery pins bounded "
            "source-only attempts and shared pacing; omitted preserves the legacy one-shot contract. "
            "Creates no monitoring, approval or paper position. "
            "Initial command retries read saved state without advancing or resending paid work."))
    def post(self, request):
        command = self.validated_command(request, StartResearchSerializer)
        return Response(_call_service(investigation.start_research, str(request.user.pk), **command))


class ResearchDetailView(ResearchAPIView):
    @extend_schema(operation_id="get_question_research", tags=["internal question research"], responses=RESPONSES,
        description="Read saved research and present source disposition without a model, catalogue or search request.")
    def get(self, request, run_id):
        _reject_query(request)
        return Response(_call_service(investigation.get_research, str(request.user.pk), str(run_id)))


class ResearchCommandView(ResearchAPIView):
    @extend_schema(operation_id="get_question_research_command", tags=["internal question research"], responses=RESPONSES)
    def get(self, request, command_id):
        _reject_query(request)
        return Response(_call_service(investigation.get_research_command, str(request.user.pk), str(command_id)))


class ResearchContinueView(ResearchAPIView):
    @extend_schema(operation_id="continue_question_research", tags=["internal question research"],
        request=ContinueResearchSerializer, responses=RESPONSES,
        description=("Explicitly advance eligible research nodes or finish retained discovery receipts. "
            "Recovery-enabled runs may retry only eligible source GETs after their saved due time. "
            "An admitted uncertain model call is inspected and never resent. A not-yet-admitted compilation may incur a charge."))
    def post(self, request, run_id):
        self.validated_command(request, ContinueResearchSerializer)
        return Response(_call_service(investigation.continue_research, str(request.user.pk), str(run_id)))
