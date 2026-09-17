from django.urls import path
from .views import (
    StudentIdentifyView, StudentVerifyView,
    StudentRegisterView, StudentPasswordLoginView, StudentProfileView
)

urlpatterns = [
    path('identify/', StudentIdentifyView.as_view(), name='student_identify'),
    path('verify/', StudentVerifyView.as_view(), name='student_verify'),
    path('register/', StudentRegisterView.as_view(), name='student_register'),
    path('login/', StudentPasswordLoginView.as_view(), name='student_login'),
    path('me/', StudentProfileView.as_view(), name='student_me'),
]
