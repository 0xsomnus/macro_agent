"""Explicit consent and owner-scoped inspection for internal research workers."""

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from macro_agent.desk import research_jobs

from .compilation_views import _call_service
from .investigation_views import ResearchAPIView
from .research_job_serializers import (
    EnrollResearchBackgroundSerializer, ResearchBackgroundResponseSerializer,
    RevokeResearchBackgroundSerializer,
)
from .serializers import ErrorResponseSerializer
from .views import ERROR_RESPONSES, _reject_query


RESPONSES = {200: ResearchBackgroundResponseSerializer, **ERROR_RESPONSES,
             429: ErrorResponseSerializer, 503: ErrorResponseSerializer}


class ResearchBackgroundView(ResearchAPIView):
    def initial(self, request, *args, **kwargs):
        # Disabling execution must not hide retained consent or prevent reads.
        if (request.method == "POST"
                and getattr(settings, "MACRO_ENABLE_RESEARCH_BACKGROUND", False) is not True):
            raise NotFound("Internal background research unavailable.")
        super().initial(request, *args, **kwargs)

    @extend_schema(operation_id="get_research_background", tags=["internal question research"],
        responses=RESPONSES,
        description=("Read owner-scoped retained background consent and lease outcomes. "
            "Makes no catalogue, source or model request and does not advance work. "
            "Available when background execution is disabled, subject to the internal research gates."))
    def get(self, request, run_id):
        _reject_query(request)
        return Response(_call_service(research_jobs.inspect_job, str(request.user.pk), str(run_id)))

    @extend_schema(operation_id="enroll_research_background", tags=["internal question research"],
        request=EnrollResearchBackgroundSerializer, responses=RESPONSES,
        description=("Explicitly opt one exact saved research request into bounded background continuation. "
            "Pins its existing provider and model configuration. Enrollment itself makes no source, catalogue "
            "or model request. Saved enrollment retries cannot restart revoked or completed work. "
            "Requires the independent background-execution gate; creates no monitoring or publication authority."))
    def post(self, request, run_id):
        command = self.validated_command(request, EnrollResearchBackgroundSerializer)
        return Response(_call_service(research_jobs.enroll, str(request.user.pk), str(run_id), **command))


class ResearchBackgroundRevokeView(ResearchAPIView):
    @extend_schema(operation_id="revoke_research_background", tags=["internal question research"],
        request=RevokeResearchBackgroundSerializer, responses=RESPONSES,
        description=("Revoke the saved research continuation consent without any catalogue, source or model "
            "request. Available when background execution is disabled. Revocation fences later admissions; "
            "it cannot cancel an already transmitted upstream request or refund an uncertain charge."))
    def post(self, request, run_id):
        command = self.validated_command(request, RevokeResearchBackgroundSerializer)
        return Response(_call_service(research_jobs.revoke, str(request.user.pk), str(run_id), **command))
