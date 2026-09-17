from django.urls import path
from .views import (
    AdminStudentTemplateView,
    AdminStudentDetailView,
    AdminUniversityStudentsListView,
)

urlpatterns = [
    path('template/', AdminStudentTemplateView.as_view(), name='admin_students_template'),
    path('<uuid:pk>/', AdminStudentDetailView.as_view(), name='admin_students_detail'),
    path('', AdminUniversityStudentsListView.as_view(), name='admin_students_list'),
]
