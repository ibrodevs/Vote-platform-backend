from django.db.models import Count, Prefetch, Q
from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from apps.core.db_replica import eventual
from .models import University
from .serializers import UniversitySerializer, UniversityPublicSerializer
from apps.core.cache_invalidation import invalidate_university
from apps.core.permissions import IsSuperAdmin, IsAdminUserWithRole, IsNotObserver
from apps.accounts.models import AdminActionLog

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    return request.META.get('REMOTE_ADDR')

def _university_queryset():
    """Университеты со счётчиками и факультетами, посчитанными в базе.

    filter=Q(...) внутри Count даёт условный счётчик без второго запроса;
    distinct=True нужен потому, что два JOIN'а (students и elections)
    перемножают строки.
    """
    return University.objects.prefetch_related('faculties').annotate(
        students_count_annotated=Count('students', distinct=True),
        active_elections_count_annotated=Count(
            'elections', filter=Q(elections__status='active'), distinct=True
        ),
    )


class UniversityAdminListCreateView(generics.ListCreateAPIView):
    serializer_class = UniversitySerializer

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsSuperAdmin()]
        return [IsAdminUserWithRole()]

    def get_queryset(self):
        user = self.request.user
        if getattr(user, 'role', None) == 'super_admin' or user.is_superuser:
            return _university_queryset().order_by('name')
        # University admin only sees their own
        if user.university:
            return _university_queryset().filter(id=user.university.id)
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
    queryset = _university_queryset()

    def get_permissions(self):
        if self.request.method in ['DELETE']:
            return [IsSuperAdmin()]
        return [IsAdminUserWithRole()]

    def perform_update(self, serializer):
        uni = serializer.save()
        invalidate_university(uni.id)
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
    # Справочник вузов меняется редко и к голосованию отношения не имеет:
    # отставание реплики здесь безопасно (ТЗ п.46).
    queryset = eventual(
        University.objects.filter(is_active=True).prefetch_related('faculties')
    ).order_by('name')
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

class UniversityToggleRegistrationView(APIView):
    permission_classes = [IsAdminUserWithRole, IsNotObserver]

    def post(self, request, pk=None):
        user = request.user

        # Support toggling for ALL universities if requested by super admin
        if request.data.get('all') is True or str(request.data.get('university_id', '')).lower() == 'all':
            if getattr(user, 'role', None) != 'super_admin' and not user.is_superuser:
                return Response(
                    {"error": {"code": "forbidden", "message": "Только супер-администратор может менять статус для всех вузов"}},
                    status=status.HTTP_403_FORBIDDEN
                )
            is_open = request.data.get('is_registration_open')
            if is_open is None:
                is_open = not University.objects.filter(is_registration_open=True).exists()
            University.objects.all().update(is_registration_open=bool(is_open))
            return Response({
                "all": True,
                "is_registration_open": bool(is_open),
                "message": f"Регистрация студентов для всех вузов {'открыта' if is_open else 'закрыта'}"
            })

        uni_id = pk or request.data.get('university_id')
        if not uni_id:
            if getattr(user, 'university', None):
                uni_id = user.university.id
            else:
                return Response(
                    {"error": {"code": "missing_university", "message": "Укажите ID университета"}},
                    status=status.HTTP_400_BAD_REQUEST
                )

        try:
            uni = University.objects.get(id=uni_id)
        except University.DoesNotExist:
            return Response(
                {"error": {"code": "university_not_found", "message": "Университет не найден"}},
                status=status.HTTP_404_NOT_FOUND
            )

        if getattr(user, 'role', None) != 'super_admin' and not user.is_superuser:
            if not user.university or str(user.university.id) != str(uni.id):
                return Response(
                    {"error": {"code": "forbidden", "message": "Нет прав на изменение настроек этого университета"}},
                    status=status.HTTP_403_FORBIDDEN
                )

        if 'is_registration_open' in request.data:
            uni.is_registration_open = bool(request.data['is_registration_open'])
        else:
            uni.is_registration_open = not uni.is_registration_open

        uni.save(update_fields=['is_registration_open'])

        AdminActionLog.objects.create(
            admin=user,
            action="toggle_registration",
            target_type="university",
            target_id=str(uni.id),
            details={"is_registration_open": uni.is_registration_open, "university": uni.name},
            ip_address=get_client_ip(request)
        )

        return Response({
            "id": str(uni.id),
            "name": uni.name,
            "is_registration_open": uni.is_registration_open,
            "message": f"Регистрация студентов {'открыта' if uni.is_registration_open else 'закрыта'}"
        })
