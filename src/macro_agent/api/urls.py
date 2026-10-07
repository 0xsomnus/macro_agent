"""Thesis and paper-position routes expose explicit application commands."""

from django.urls import path
from .compilation_views import ModelCatalogView, CompilationView, CompilationDetailView
from .news_analysis_views import (
    AnalyseNextView, NewsAnalysisDetailView, NewsCommandDetailView,
    NewsReviewContextView, NewsSourcesView,
)

from .lab_views import RecordedNewsView
from .position_views import (
    PositionCloseView, PositionCollectionView, PositionDetailView,
    PositionHistoryView, PositionRevisionView,
)
from .views import (
    PrivateSchemaView, ThesisApprovalView, ThesisCollectionView, ThesisDetailView,
    ThesisHistoryView, ThesisProposalView,
)


app_name = "macro_api"
urlpatterns = [
    path("news/sources/", NewsSourcesView.as_view(), name="news-sources"),
    path("theses/<uuid:thesis_id>/news-context/", NewsReviewContextView.as_view(), name="news-context"),
    path("theses/<uuid:thesis_id>/analyse-next/", AnalyseNextView.as_view(), name="news-analyse-next"),
    path("theses/<uuid:thesis_id>/news-analyses/<uuid:attempt_id>/", NewsAnalysisDetailView.as_view(), name="news-analysis-detail"),
    path("theses/<uuid:thesis_id>/news-commands/<uuid:command_id>/", NewsCommandDetailView.as_view(), name="news-command-detail"),
    path("models/", ModelCatalogView.as_view(), name="model-catalog"),
    path("theses/<uuid:thesis_id>/compile/", CompilationView.as_view(), name="thesis-compile"),
    path("theses/<uuid:thesis_id>/compilations/<uuid:attempt_id>/", CompilationDetailView.as_view(), name="compilation-detail"),
    path("lab/theses/<uuid:thesis_id>/recorded-news/", RecordedNewsView.as_view(), name="recorded-news"),
    path("schema/", PrivateSchemaView.as_view(), name="schema"),
    path("theses/", ThesisCollectionView.as_view(), name="thesis-list"),
    path("theses/<uuid:thesis_id>/", ThesisDetailView.as_view(), name="thesis-detail"),
    path("theses/<uuid:thesis_id>/proposals/", ThesisProposalView.as_view(), name="thesis-propose"),
    path("theses/<uuid:thesis_id>/approvals/", ThesisApprovalView.as_view(), name="thesis-approve"),
    path("theses/<uuid:thesis_id>/history/", ThesisHistoryView.as_view(), name="thesis-history"),
    path("theses/<uuid:thesis_id>/positions/", PositionCollectionView.as_view(), name="position-list"),
    path("positions/<uuid:position_id>/", PositionDetailView.as_view(), name="position-detail"),
    path("positions/<uuid:position_id>/revisions/", PositionRevisionView.as_view(), name="position-revise"),
    path("positions/<uuid:position_id>/close/", PositionCloseView.as_view(), name="position-close"),
    path("positions/<uuid:position_id>/history/", PositionHistoryView.as_view(), name="position-history"),
]
