"""Session-scoped evidence preparation without inference or thesis approval."""

from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from macro_agent.desk import evidence
from .compilation_views import InternalCompilationAPIView, _call_service
from .research_serializers import PrepareEvidenceSerializer, EvidenceResponseSerializer
from .views import ERROR_RESPONSES, _reject_query


class PrepareEvidenceView(InternalCompilationAPIView):
    @extend_schema(operation_id="prepare_research_evidence", tags=["research evidence"],
        request=PrepareEvidenceSerializer, responses={200: EvidenceResponseSerializer, **ERROR_RESPONSES},
        description="Freeze explicitly selected current captured revisions and permission versions. No model call or approval. Selection is not complete macro coverage.")
    def post(self, request, thesis_id):
        command = self.validated_command(request, PrepareEvidenceSerializer)
        return Response(_call_service(evidence.prepare_evidence, str(request.user.pk), str(thesis_id), **command))


class EvidenceDetailView(InternalCompilationAPIView):
    @extend_schema(operation_id="get_research_evidence", tags=["research evidence"],
        responses={200: EvidenceResponseSerializer, **ERROR_RESPONSES})
    def get(self, request, thesis_id, context_id):
        _reject_query(request)
        return Response(_call_service(evidence.get_evidence, str(request.user.pk), str(thesis_id), str(context_id)))


class EvidenceCommandView(InternalCompilationAPIView):
    @extend_schema(operation_id="get_research_evidence_command", tags=["research evidence"],
        responses={200: EvidenceResponseSerializer, **ERROR_RESPONSES},
        description="Read the saved evidence command without network requests, inference or POST fallback.")
    def get(self, request, thesis_id, command_id):
        _reject_query(request)
        return Response(_call_service(evidence.get_evidence_command, str(request.user.pk), str(thesis_id), str(command_id)))
