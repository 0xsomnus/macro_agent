"""Thesis routes have explicit commands instead of generic model CRUD."""

from django.urls import path

from .views import (
    PrivateSchemaView, ThesisApprovalView, ThesisCollectionView, ThesisDetailView,
    ThesisHistoryView, ThesisProposalView,
)


app_name = "macro_api"
urlpatterns = [
    path("schema/", PrivateSchemaView.as_view(), name="schema"),
    path("theses/", ThesisCollectionView.as_view(), name="thesis-list"),
    path("theses/<uuid:thesis_id>/", ThesisDetailView.as_view(), name="thesis-detail"),
    path("theses/<uuid:thesis_id>/proposals/", ThesisProposalView.as_view(), name="thesis-propose"),
    path("theses/<uuid:thesis_id>/approvals/", ThesisApprovalView.as_view(), name="thesis-approve"),
    path("theses/<uuid:thesis_id>/history/", ThesisHistoryView.as_view(), name="thesis-history"),
]
