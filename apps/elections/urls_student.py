from django.urls import path
from .views import StudentAvailableElectionsView, StudentElectionDetailView
from apps.candidates.views import StudentElectionCandidatesListView

urlpatterns = [
    path('available/', StudentAvailableElectionsView.as_view(), name='student_available_elections'),
    path('<uuid:pk>/', StudentElectionDetailView.as_view(), name='student_election_detail'),
    path('<uuid:election_id>/candidates/', StudentElectionCandidatesListView.as_view(), name='student_election_candidates'),
]
