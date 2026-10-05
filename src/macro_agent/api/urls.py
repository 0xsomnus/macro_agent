"""Thesis and paper-position routes expose explicit application commands."""

from django.urls import path

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
