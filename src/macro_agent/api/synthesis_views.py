"""Explicit paid synthesis and read-only private recovery over retained reviews."""

from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from macro_agent.desk import synthesis
from .compilation_views import InternalCompilationAPIView, _call_service
from .synthesis_serializers import SynthesizeReviewSerializer, SynthesisResponseSerializer
from .serializers import ErrorResponseSerializer
from .views import ERROR_RESPONSES, _reject_query


class SynthesisAPIView(InternalCompilationAPIView):
    def initial(self, request, *args, **kwargs):
        try:
            synthesis.gate()
        except PermissionError:
            raise NotFound("Internal daily synthesis unavailable.") from None
        super().initial(request, *args, **kwargs)


class SynthesizeReviewView(SynthesisAPIView):
    @extend_schema(operation_id="synthesise_daily_review", tags=["daily synthesis"],
        request=SynthesizeReviewSerializer, responses={200: SynthesisResponseSerializer, **ERROR_RESPONSES,
            429: ErrorResponseSerializer, 503: ErrorResponseSerializer},
        description="One explicitly selected model call over an exact retained digest. It preserves digest publication and creates no new publication or external notification authority. Exact retries inspect durable admission without another provider request.")
    def post(self, request, review_id):
        command = self.validated_command(request, SynthesizeReviewSerializer)
        return Response(_call_service(synthesis.synthesize_review, str(request.user.pk), str(review_id), **command))


class SynthesisDetailView(SynthesisAPIView):
    @extend_schema(operation_id="get_daily_synthesis", tags=["daily synthesis"],
        responses={200: SynthesisResponseSerializer, **ERROR_RESPONSES})
    def get(self, request, synthesis_id):
        _reject_query(request)
        return Response(_call_service(synthesis.inspect_synthesis, str(request.user.pk), str(synthesis_id)))


class SynthesisCommandView(SynthesisAPIView):
    @extend_schema(operation_id="get_daily_synthesis_command", tags=["daily synthesis"],
        responses={200: SynthesisResponseSerializer, **ERROR_RESPONSES},
        description="Saved-command inspection without keys, catalogue requests or POST fallback.")
    def get(self, request, review_id, command_id):
        _reject_query(request)
        return Response(_call_service(synthesis.get_synthesis_command, str(request.user.pk), str(review_id), str(command_id)))
