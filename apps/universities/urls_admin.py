from django.urls import path
from .views import (
    UniversityAdminListCreateView,
    UniversityAdminDetailView,
    UniversityFacultyListCreateView,
    UniversityFacultyDetailView,
)
from apps.students.views import AdminUniversityStudentsListView, AdminStudentUploadView

urlpatterns = [
    path('', UniversityAdminListCreateView.as_view(), name='admin_universities_list_create'),
    path('<uuid:pk>/', UniversityAdminDetailView.as_view(), name='admin_universities_detail'),
    path('<uuid:university_id>/faculties/', UniversityFacultyListCreateView.as_view(), name='admin_university_faculties'),
    path('<uuid:university_id>/faculties/<uuid:pk>/', UniversityFacultyDetailView.as_view(), name='admin_university_faculty_detail'),
    path('<uuid:university_id>/students/', AdminUniversityStudentsListView.as_view(), name='admin_university_students'),
    path('<uuid:university_id>/students/upload/', AdminStudentUploadView.as_view(), name='admin_university_students_upload'),
]

