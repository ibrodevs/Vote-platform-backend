from django.urls import path
from .views import CandidatePublicDetailView

urlpatterns = [
    path('<uuid:pk>/', CandidatePublicDetailView.as_view(), name='candidate_public_detail'),
]
