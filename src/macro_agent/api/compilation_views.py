"""Private development-only model proposals through explicit session services."""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound
from rest_framework.response import Response

from macro_agent.theses import compilation as service
from macro_agent.theses import service as theses

from .compilation_serializers import (
    CompilationResponseSerializer, CompileThesisRequestSerializer,
    ModelCatalogResponseSerializer, RefinementResponseSerializer,
    SaveRefinementRequestSerializer,
)
from .serializers import ErrorResponseSerializer
from .views import CommandConflict, ERROR_RESPONSES, InvalidCommand, ThesisAPIView, _reject_query


class CompilationServiceUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Internal compilation service unavailable."
    default_code = "unavailable"


class CompilationAdmissionLimit(APIException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_detail = "Internal compilation admission limit reached."
    default_code = "admission_limit"


def _call_service(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except service.CompilationDisabled:
        raise NotFound("Internal compilation unavailable.") from None
    except service.CompilationUnavailable:
        raise CompilationServiceUnavailable() from None
    except service.CompilationBudgetExhausted:
        raise CompilationAdmissionLimit() from None
    except theses.ThesisUnavailable:
        raise NotFound("Internal compilation unavailable.") from None
    except theses.ThesisConflict:
        raise CommandConflict() from None
    except (ValueError, TypeError):
        raise InvalidCommand("Invalid compilation command.") from None


class InternalCompilationAPIView(ThesisAPIView):
    def initial(self, request, *args, **kwargs):
        # Hide disabled internal routes before authentication, including from
        # anonymous requests. No synthetic-source permission is required here.
        try:
            service._gate()
        except service.CompilationDisabled:
            raise NotFound("Internal compilation unavailable.") from None
        super().initial(request, *args, **kwargs)


class ModelCatalogView(InternalCompilationAPIView):
    @extend_schema(
        operation_id="compilation_model_catalog", tags=["internal compilation"],
        responses={200: ModelCatalogResponseSerializer, 400: ErrorResponseSerializer,
                   403: ErrorResponseSerializer, 404: ErrorResponseSerializer,
                   503: ErrorResponseSerializer},
        description=("Development-only explicit model catalogue from the configured provider. Requires local settings, "
                     "the model-compilation gate and a development/test database. Prices are advertised "
                     "metadata, not final charges. The API key is never returned. No model is selected automatically."),
    )
    def get(self, request):
        _reject_query(request)
        return Response(_call_service(service.model_catalog, str(request.user.pk)))


class CompilationView(InternalCompilationAPIView):
    @extend_schema(
        operation_id="compile_thesis", tags=["internal compilation"],
        request=CompileThesisRequestSerializer,
        responses={200: CompilationResponseSerializer, **ERROR_RESPONSES,
                   429: ErrorResponseSerializer, 503: ErrorResponseSerializer},
        description=("Development-only one-call text-grounded compilation using an explicit catalogue model. "
                     "The authenticated owner supplies no credentials or provider configuration in this request. "
                     "The result is a suggested draft interpretation with separate unverified questions and hypotheses. "
                     "Exact thesis text and current approval remain unchanged. Explicit user approval is still required. "
                     "There are no fact sources, current macro context, model tools or monitoring daemon. "
                     "Inspect status even on HTTP 200; saved command retries do not initiate another model call."),
    )
    def post(self, request, thesis_id):
        command = self.validated_command(request, CompileThesisRequestSerializer)
        result = _call_service(service.compile_thesis, str(request.user.pk), str(thesis_id), **command)
        return Response(result)


class CompilationDetailView(InternalCompilationAPIView):
    @extend_schema(
        operation_id="get_compilation", tags=["internal compilation"],
        responses={200: CompilationResponseSerializer, 400: ErrorResponseSerializer,
                   403: ErrorResponseSerializer, 404: ErrorResponseSerializer,
                   409: ErrorResponseSerializer},
        description=("Read an owner-scoped saved compilation attempt and its current draft disposition. "
                     "A running or unknown attempt is visible without initiating inference or retries. "
                     "The response does not assert factual verification, approval or continuous monitoring."),
    )
    def get(self, request, thesis_id, attempt_id):
        _reject_query(request)
        return Response(_call_service(service.get_compilation, str(request.user.pk),
                                      str(thesis_id), str(attempt_id)))


class CompilationCommandView(InternalCompilationAPIView):
    @extend_schema(
        operation_id="get_compilation_command", tags=["internal compilation"],
        responses={200: CompilationResponseSerializer, **ERROR_RESPONSES},
        description=("Read-only recovery by the command UUID saved before transmission. "
                     "No provider credentials, catalogue lookup, inference or POST fallback. "
                     "Historical results are shown alongside current draft disposition."),
    )
    def get(self, request, thesis_id, command_id):
        _reject_query(request)
        return Response(_call_service(service.get_compilation_command, str(request.user.pk),
                                      str(thesis_id), str(command_id)))


class RefinementView(InternalCompilationAPIView):
    @extend_schema(
        operation_id="save_thesis_refinement", tags=["internal compilation"],
        request=SaveRefinementRequestSerializer,
        responses={200: RefinementResponseSerializer, **ERROR_RESPONSES},
        description=("Save exact answers against questions from a current retained proposal, "
                     "without a provider request, paid-call admission or thesis approval. "
                     "The service derives question wording and bounded cumulative history. "
                     "A new explicit compilation may reference this submission later."),
    )
    def post(self, request, thesis_id):
        command = self.validated_command(request, SaveRefinementRequestSerializer)
        return Response(_call_service(service.save_refinement, str(request.user.pk),
                                      str(thesis_id), **command))


class RefinementDetailView(InternalCompilationAPIView):
    @extend_schema(
        operation_id="get_thesis_refinement", tags=["internal compilation"],
        responses={200: RefinementResponseSerializer, **ERROR_RESPONSES},
        description="Read an owner-scoped saved answer submission without provider work or activation.",
    )
    def get(self, request, thesis_id, refinement_id):
        _reject_query(request)
        return Response(_call_service(service.get_refinement, str(request.user.pk),
                                      str(thesis_id), str(refinement_id)))


class RefinementCommandView(InternalCompilationAPIView):
    @extend_schema(
        operation_id="get_thesis_refinement_command", tags=["internal compilation"],
        responses={200: RefinementResponseSerializer, **ERROR_RESPONSES},
        description=("Read-only answer-submission recovery by saved command UUID. "
                     "No catalogue, credentials, model request or POST fallback."),
    )
    def get(self, request, thesis_id, command_id):
        _reject_query(request)
        return Response(_call_service(service.get_refinement_command, str(request.user.pk),
                                      str(thesis_id), str(command_id)))
