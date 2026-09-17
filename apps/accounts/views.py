from rest_framework import status, permissions, generics
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework.pagination import PageNumberPagination
from .models import AdminUser, AdminActionLog
from .serializers import AdminLoginSerializer, AdminUserSerializer, AdminActionLogSerializer
from apps.core.permissions import IsSuperAdmin, IsAdminUserWithRole

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    return request.META.get('REMOTE_ADDR')

class AdminLoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = AdminLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user_data = data['user']
        admin = AdminUser.objects.get(id=user_data['id'])
        AdminActionLog.objects.create(
            admin=admin,
            action="login",
            target_type="auth",
            target_id=str(admin.id),
            details={"email": admin.email},
            ip_address=get_client_ip(request)
        )

        return Response(data, status=status.HTTP_200_OK)

class AdminMeView(APIView):
    permission_classes = [IsAdminUserWithRole]

    def get(self, request):
        serializer = AdminUserSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

class AdminUsersListView(generics.ListCreateAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = AdminUserSerializer
    queryset = AdminUser.objects.all().order_by('-created_at')

    def perform_create(self, serializer):
        user = serializer.save()
        AdminActionLog.objects.create(
            admin=self.request.user,
            action="create_admin_user",
            target_type="admin_user",
            target_id=str(user.id),
            details={"email": user.email, "role": user.role},
            ip_address=get_client_ip(self.request)
        )

class AdminActionLogsListView(generics.ListAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = AdminActionLogSerializer
    queryset = AdminActionLog.objects.all().order_by('-created_at')
    pagination_class = PageNumberPagination
