from django.urls import path
from .views import AdminCandidateDetailView

urlpatterns = [
    path('<uuid:pk>/', AdminCandidateDetailView.as_view(), name='admin_candidate_detail'),
]
