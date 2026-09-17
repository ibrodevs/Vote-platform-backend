from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import AdminLoginView, AdminMeView, AdminUsersListView, AdminActionLogsListView

urlpatterns = [
    path('admin/login/', AdminLoginView.as_view(), name='admin_login'),
    path('admin/refresh/', TokenRefreshView.as_view(), name='admin_refresh'),
    path('admin/me/', AdminMeView.as_view(), name='admin_me'),
    path('admin/users/', AdminUsersListView.as_view(), name='admin_users'),
    path('admin/logs/', AdminActionLogsListView.as_view(), name='admin_logs'),
]
