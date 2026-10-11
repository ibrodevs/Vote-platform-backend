from django.urls import path

from .student_hot_views import (
    StudentAvailableElectionsHotView,
    StudentElectionDetailHotView,
)
from .views import PublicRecentElectionsView
from apps.candidates.views import StudentElectionCandidatesListView

urlpatterns = [
    path('recent/', PublicRecentElectionsView.as_view(), name='public_recent_elections'),
    path('public/', PublicRecentElectionsView.as_view(), name='public_elections_list'),
    path('available/', StudentAvailableElectionsHotView.as_view(), name='student_available_elections'),
    path('<uuid:pk>/', StudentElectionDetailHotView.as_view(), name='student_election_detail'),
    path('<uuid:election_id>/candidates/', StudentElectionCandidatesListView.as_view(), name='student_election_candidates'),
]
