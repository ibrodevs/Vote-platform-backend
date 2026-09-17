from django.urls import path
from .views import UniversityPublicListView, UniversityPublicDetailByCodeView

urlpatterns = [
    path('', UniversityPublicListView.as_view(), name='public_universities_list'),
    path('<slug:code>/info/', UniversityPublicDetailByCodeView.as_view(), name='public_university_info'),
]
