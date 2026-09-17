from django.urls import path
from .views import UniversityPublicListView, UniversityPublicDetailByCodeView, UniversityFacultyListCreateView

urlpatterns = [
    path('', UniversityPublicListView.as_view(), name='public_universities_list'),
    path('<slug:code>/info/', UniversityPublicDetailByCodeView.as_view(), name='public_university_info'),
    path('<uuid:university_id>/faculties/', UniversityFacultyListCreateView.as_view(), name='public_university_faculties'),
]
