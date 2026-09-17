from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from .models import University
from .serializers import UniversitySerializer, UniversityPublicSerializer
from apps.core.permissions import IsSuperAdmin, IsAdminUserWithRole
from apps.accounts.models import AdminActionLog

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    return request.META.get('REMOTE_ADDR')

class UniversityAdminListCreateView(generics.ListCreateAPIView):
    serializer_class = UniversitySerializer

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsSuperAdmin()]
        return [IsAdminUserWithRole()]

    def get_queryset(self):
        user = self.request.user
        if getattr(user, 'role', None) == 'super_admin' or user.is_superuser:
            return University.objects.all().order_by('name')
        # University admin only sees their own
        if user.university:
            return University.objects.filter(id=user.university.id)
        return University.objects.none()

    def perform_create(self, serializer):
        uni = serializer.save()
        AdminActionLog.objects.create(
            admin=self.request.user,
            action="create_university",
            target_type="university",
            target_id=str(uni.id),
            details={"name": uni.name, "code": uni.code},
            ip_address=get_client_ip(self.request)
        )

class UniversityAdminDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = UniversitySerializer
    queryset = University.objects.all()

    def get_permissions(self):
        if self.request.method in ['DELETE']:
            return [IsSuperAdmin()]
        return [IsAdminUserWithRole()]

    def perform_update(self, serializer):
        uni = serializer.save()
        AdminActionLog.objects.create(
            admin=self.request.user,
            action="update_university",
            target_type="university",
            target_id=str(uni.id),
            details={"name": uni.name, "code": uni.code},
            ip_address=get_client_ip(self.request)
        )

    def perform_destroy(self, instance):
        AdminActionLog.objects.create(
            admin=self.request.user,
            action="delete_university",
            target_type="university",
            target_id=str(instance.id),
            details={"name": instance.name, "code": instance.code},
            ip_address=get_client_ip(self.request)
        )
        instance.delete()

# Public views
class UniversityPublicListView(generics.ListAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = UniversityPublicSerializer
    queryset = University.objects.filter(is_active=True).order_by('name')
    pagination_class = None

class UniversityPublicDetailByCodeView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, code):
        try:
            uni = University.objects.get(code=code, is_active=True)
            serializer = UniversityPublicSerializer(uni)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except University.DoesNotExist:
            return Response(
                {"error": {"code": "not_found", "message": "Университет не найден"}},
                status=status.HTTP_404_NOT_FOUND
            )

class UniversityFacultyListCreateView(generics.ListCreateAPIView):
    from .serializers import FacultySerializer
    from .models import Faculty
    serializer_class = FacultySerializer

    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.AllowAny()]
        return [IsAdminUserWithRole()]

    def get_queryset(self):
        from .models import Faculty
        uni_id = self.kwargs.get('university_id')
        return Faculty.objects.filter(university_id=uni_id).order_by('name')

    def perform_create(self, serializer):
        uni_id = self.kwargs.get('university_id')
        university = University.objects.get(id=uni_id)
        serializer.save(university=university)

class UniversityFacultyDetailView(generics.RetrieveUpdateDestroyAPIView):
    from .serializers import FacultySerializer
    from .models import Faculty
    permission_classes = [IsAdminUserWithRole]
    serializer_class = FacultySerializer

    def get_queryset(self):
        from .models import Faculty
        uni_id = self.kwargs.get('university_id')
        return Faculty.objects.filter(university_id=uni_id)
