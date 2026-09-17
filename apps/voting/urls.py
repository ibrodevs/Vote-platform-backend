from django.urls import path
from .views import CastVoteView, VoteStatusView

urlpatterns = [
    path('cast/', CastVoteView.as_view(), name='voting_cast'),
    path('status/<uuid:election_id>/', VoteStatusView.as_view(), name='voting_status'),
]
