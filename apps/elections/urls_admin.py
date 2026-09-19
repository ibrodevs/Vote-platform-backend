from django.urls import path
from .views import (
    AdminElectionListCreateView,
    AdminElectionDetailView,
    AdminElectionStartView,
    AdminElectionFinishView,
    AdminElectionCancelView,
    AdminElectionTurnoutView,
    AdminElectionResultsView,
    AdminElectionResultsExportView,
    AdminFeaturedElectionsManageView,
)
from apps.candidates.views import AdminElectionCandidatesListView, AdminCandidateReorderView

urlpatterns = [
    path('', AdminElectionListCreateView.as_view(), name='admin_elections_list_create'),
    path('featured/', AdminFeaturedElectionsManageView.as_view(), name='admin_featured_elections'),
    path('<uuid:pk>/featured/', AdminFeaturedElectionsManageView.as_view(), name='admin_featured_election_detail'),
    path('<uuid:pk>/', AdminElectionDetailView.as_view(), name='admin_election_detail'),
    path('<uuid:pk>/start/', AdminElectionStartView.as_view(), name='admin_election_start'),
    path('<uuid:pk>/finish/', AdminElectionFinishView.as_view(), name='admin_election_finish'),
    path('<uuid:pk>/cancel/', AdminElectionCancelView.as_view(), name='admin_election_cancel'),
    path('<uuid:pk>/turnout/', AdminElectionTurnoutView.as_view(), name='admin_election_turnout'),
    path('<uuid:pk>/results/', AdminElectionResultsView.as_view(), name='admin_election_results'),
    path('<uuid:pk>/results/export/', AdminElectionResultsExportView.as_view(), name='admin_election_results_export'),
    path('<uuid:election_id>/candidates/', AdminElectionCandidatesListView.as_view(), name='admin_election_candidates'),
    path('<uuid:election_id>/candidates/reorder/', AdminCandidateReorderView.as_view(), name='admin_election_candidates_reorder'),
]
