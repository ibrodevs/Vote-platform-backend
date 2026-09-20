import io
import datetime
import jwt
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Max
from django.utils import timezone
from django.http import HttpResponse
from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter

from apps.core.filters import MinLengthSearchFilter

from django.contrib.auth.hashers import make_password, check_password
from .models import Student, UploadBatch, StudentAuthSession
from .serializers import (
    StudentSerializer, UploadBatchSerializer,
    StudentIdentifySerializer, StudentVerifySerializer,
    StudentRegisterSerializer, StudentPasswordLoginSerializer
)
from .services import clean_phone_number, send_student_otp
from .tasks import process_student_upload_batch
from apps.universities.models import University
from apps.accounts.models import AdminActionLog
from apps.core.permissions import IsAdminUserWithRole, IsUniversityAdmin, IsStudentAuthenticated, IsNotObserver

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    return request.META.get('REMOTE_ADDR')

# --- Student Auth Endpoints ---

class StudentIdentifyView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = StudentIdentifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        uni_code = data['university_code'].strip().lower()
        student_id = data['student_id'].strip()
        phone_input = clean_phone_number(data['phone_number'])

        try:
            university = University.objects.get(code__iexact=uni_code, is_active=True)
        except University.DoesNotExist:
            return Response(
                {"error": {"code": "university_not_found", "message": "Университет не найден или неактивен"}},
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            student = Student.objects.get(university=university, student_id__iexact=student_id, is_active=True)
        except Student.DoesNotExist:
            return Response(
                {"error": {"code": "student_not_found", "message": "Студент с таким ID не найден в списках университета"}},
                status=status.HTTP_404_NOT_FOUND
            )

        student_phone = clean_phone_number(student.phone_number)
        # Check last 9 digits of phone to tolerate country code variations
        if student_phone[-9:] != phone_input[-9:]:
            return Response(
                {"error": {"code": "phone_mismatch", "message": "Указанный номер телефона не совпадает с данными в базе"}},
                status=status.HTTP_400_BAD_REQUEST
            )

        auth_session = send_student_otp(student, phone_input)

        response_data = {
            "request_id": str(auth_session.id),
            "message": f"Код подтверждения отправлен на номер {phone_input[:5]}***{phone_input[-2:]}",
            "expires_in_seconds": int((auth_session.expires_at - timezone.now()).total_seconds())
        }

        # Include demo code in debug mode
        if settings.DEBUG:
            response_data["demo_code"] = auth_session.code

        return Response(response_data, status=status.HTTP_200_OK)

class StudentVerifyView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = StudentVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        request_id = data['request_id']
        code_input = data['code'].strip()

        try:
            auth_session = StudentAuthSession.objects.select_related('student', 'student__university').get(id=request_id)
        except StudentAuthSession.DoesNotExist:
            return Response(
                {"error": {"code": "invalid_session", "message": "Сессия авторизации не найдена"}},
                status=status.HTTP_400_BAD_REQUEST
            )

        if auth_session.is_verified:
            return Response(
                {"error": {"code": "already_verified", "message": "Данный код уже был использован"}},
                status=status.HTTP_400_BAD_REQUEST
            )

        if timezone.now() > auth_session.expires_at:
            return Response(
                {"error": {"code": "code_expired", "message": "Срок действия кода истёк. Запросите новый код"}},
                status=status.HTTP_400_BAD_REQUEST
            )

        if auth_session.attempts >= getattr(settings, 'SMS_MAX_ATTEMPTS', 5):
            return Response(
                {"error": {"code": "too_many_attempts", "message": "Превышено количество попыток. Запросите код заново"}},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        auth_session.attempts += 1
        auth_session.save(update_fields=['attempts'])

        if auth_session.code != code_input:
            return Response(
                {"error": {"code": "invalid_code", "message": f"Неверный код. Осталось попыток: {settings.SMS_MAX_ATTEMPTS - auth_session.attempts}"}},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Code is correct
        auth_session.is_verified = True
        auth_session.save(update_fields=['is_verified'])

        # D-01: раньше метод заканчивался здесь без return, DRF получал None
        # и поднимал AssertionError -> 500. Весь OTP-вход был нерабочим,
        # хотя фронтенд (app/vote/[code]/verify) его использует.
        return Response(
            build_student_auth_response(auth_session.student, request),
            status=status.HTTP_200_OK,
        )

def create_student_token(student):
    exp_time = timezone.now() + datetime.timedelta(days=7)
    payload = {
        'token_type': 'student',
        'student_id': str(student.id),
        'university_id': str(student.university.id),
        'student_code': student.student_id,
        'exp': int(exp_time.timestamp()),
        'iat': int(timezone.now().timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

def build_student_auth_response(student, request=None):
    """Единое тело ответа для register, login и verify.

    Вынесено, чтобы три точки выдачи токена не разъезжались: фронтенд
    одинаково разбирает ответ всех трёх (lib/api.ts).
    """
    photo_url = None
    if student.photo:
        try:
            photo_url = request.build_absolute_uri(student.photo.url) if request else student.photo.url
        except Exception:
            photo_url = None

    return {
        "student_token": create_student_token(student),
        "student": {
            "id": str(student.id),
            "student_id": student.student_id,
            "full_name": student.full_name,
            "email": student.email,
            "photo": photo_url,
            "group": student.group,
            "faculty": student.faculty,
            "course": student.course,
        },
        "university": {
            "id": str(student.university.id),
            "name": student.university.name,
            "name_ky": student.university.name_ky,
            "code": student.university.code,
        },
    }


class StudentRegisterView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = StudentRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        email = data['email'].strip().lower()
        university_id = data['university_id']

        try:
            university = University.objects.get(id=university_id, is_active=True)
        except University.DoesNotExist:
            return Response(
                {"error": {"code": "university_not_found", "message": "Университет не найден или неактивен"}},
                status=status.HTTP_404_NOT_FOUND
            )

        if not university.is_registration_open:
            return Response(
                {"error": {"code": "registration_closed", "message": "Регистрация новых студентов временно закрыта администратором. Доступен только вход в систему."}},
                status=status.HTTP_403_FORBIDDEN
            )

        if Student.objects.filter(email__iexact=email).exists():
            return Response(
                {"error": {"code": "email_already_exists", "message": "Студент с таким email уже зарегистрирован. Пожалуйста, выполните вход."}},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Проверка exists() выше — быстрый путь для обычного случая, но она
        # проигрывает гонке: два параллельных запроса пройдут её одновременно.
        # Последняя линия защиты — UNIQUE-констрейнт по LOWER(email) (ТЗ п.15).
        # Его срабатывание обязано выглядеть для клиента так же, как проверка,
        # а не как 500.
        try:
            with transaction.atomic():
                student = Student.objects.create(
                    university=university,
                    full_name=data['full_name'].strip(),
                    faculty=data.get('faculty', '').strip(),
                    course=data['course'],
                    group=data['group'].strip(),
                    email=email,
                    password=make_password(data['password']),
                    is_active=True
                )
        except IntegrityError:
            return Response(
                {"error": {"code": "email_already_exists",
                           "message": "Студент с таким email уже зарегистрирован. Пожалуйста, выполните вход."}},
                status=status.HTTP_400_BAD_REQUEST
            )

        token = create_student_token(student)

        return Response({
            "student_token": token,
            "student": {
                "id": str(student.id),
                "student_id": student.student_id,
                "full_name": student.full_name,
                "email": student.email,
                "photo": None,
                "group": student.group,
                "faculty": student.faculty,
                "course": student.course,
            },
            "university": {
                "id": str(student.university.id),
                "name": student.university.name,
                "name_ky": student.university.name_ky,
                "code": student.university.code,
            }
        }, status=status.HTTP_201_CREATED)

class StudentPasswordLoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = StudentPasswordLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        email = data['email'].strip().lower()
        password = data['password']

        student = Student.objects.select_related('university').filter(email__iexact=email, is_active=True).first()
        if not student:
            return Response(
                {"error": {"code": "invalid_credentials", "message": "Неверный email или пароль"}},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not student.password or not check_password(password, student.password):
            return Response(
                {"error": {"code": "invalid_credentials", "message": "Неверный email или пароль"}},
                status=status.HTTP_400_BAD_REQUEST
            )

        token = create_student_token(student)

        photo_url = None
        if student.photo:
            try:
                photo_url = request.build_absolute_uri(student.photo.url)
            except Exception:
                photo_url = None

        return Response({
            "student_token": token,
            "student": {
                "id": str(student.id),
                "student_id": student.student_id,
                "full_name": student.full_name,
                "email": student.email,
                "photo": photo_url,
                "group": student.group,
                "faculty": student.faculty,
                "course": student.course,
            },
            "university": {
                "id": str(student.university.id),
                "name": student.university.name,
                "name_ky": student.university.name_ky,
                "code": student.university.code,
            }
        }, status=status.HTTP_200_OK)

class StudentProfileView(APIView):
    permission_classes = [IsStudentAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        student = request.user.student
        photo_url = None
        if student.photo:
            try:
                photo_url = request.build_absolute_uri(student.photo.url)
            except Exception:
                photo_url = None

        return Response({
            "student": {
                "id": str(student.id),
                "student_id": student.student_id,
                "full_name": student.full_name,
                "email": student.email,
                "photo": photo_url,
                "group": student.group,
                "faculty": student.faculty,
                "course": student.course,
            },
            "university": {
                "id": str(student.university.id),
                "name": student.university.name,
                "name_ky": student.university.name_ky,
                "code": student.university.code,
            }
        }, status=status.HTTP_200_OK)

    def patch(self, request):
        student = request.user.student
        if 'photo' in request.FILES:
            student.photo = request.FILES['photo']
            student.save(update_fields=['photo'])
        if 'full_name' in request.data:
            student.full_name = request.data['full_name'].strip()
            student.save(update_fields=['full_name'])
        return self.get(request)

# --- Admin Student Management Endpoints ---

class AdminUniversityStudentsListView(generics.ListCreateAPIView):
    permission_classes = [IsAdminUserWithRole]
    serializer_class = StudentSerializer
    filter_backends = [DjangoFilterBackend, MinLengthSearchFilter, OrderingFilter]
    filterset_fields = ['faculty', 'course', 'is_active']
    search_fields = ['student_id', 'full_name', 'phone_number', 'email', 'faculty']
    ordering_fields = ['full_name', 'student_id', 'course', 'created_at']
    ordering = ['-created_at']

    def get_queryset(self):
        uni_id = self.kwargs.get('university_id') or self.request.query_params.get('university_id') or self.request.query_params.get('university')
        user = self.request.user
        if getattr(user, 'role', None) != 'super_admin' and not user.is_superuser:
            if user.university_id:
                qs = Student.objects.filter(university_id=user.university_id)
            else:
                return Student.objects.none()
        else:
            if uni_id:
                qs = Student.objects.filter(university_id=uni_id)
            else:
                qs = Student.objects.all()

        only_registered = self.request.query_params.get('only_registered')
        if only_registered and only_registered.lower() in ['true', '1', 'yes']:
            qs = qs.exclude(password='').exclude(password__isnull=True)

        # Аннотации вместо prefetch_related: сериализатору нужны только
        # количество и последняя дата, сами строки голосований не нужны.
        # distinct=True обязателен — фильтр по ?voted= делает JOIN,
        # и без него строки задвоились бы (ТЗ п.26).
        qs = qs.select_related('university').annotate(
            votes_count_annotated=Count('vote_records', distinct=True),
            last_voted_at_annotated=Max('vote_records__voted_at'),
        )

        voted_param = self.request.query_params.get('voted')
        if voted_param is not None:
            if voted_param.lower() in ['true', '1', 'yes']:
                qs = qs.filter(vote_records__isnull=False).distinct()
            elif voted_param.lower() in ['false', '0', 'no']:
                qs = qs.filter(vote_records__isnull=True).distinct()

        return qs

    def perform_create(self, serializer):
        uni_id = self.kwargs.get('university_id')
        university = University.objects.get(id=uni_id)
        student = serializer.save(university=university)
        AdminActionLog.objects.create(
            admin=self.request.user,
            action="create_student",
            target_type="student",
            target_id=str(student.id),
            details={"student_id": student.student_id, "university": university.code},
            ip_address=get_client_ip(self.request)
        )

class AdminStudentDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAdminUserWithRole]
    serializer_class = StudentSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    queryset = Student.objects.all()

class AdminStudentUploadView(APIView):
    permission_classes = [IsAdminUserWithRole, IsNotObserver]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, university_id):
        try:
            university = University.objects.get(id=university_id)
        except University.DoesNotExist:
            return Response({"error": {"code": "not_found", "message": "Университет не найден"}}, status=status.HTTP_404_NOT_FOUND)

        user = request.user
        if getattr(user, 'role', None) != 'super_admin' and not user.is_superuser:
            if str(user.university_id) != str(university_id):
                return Response({"error": {"code": "forbidden", "message": "Нет доступа к данному вузу"}}, status=status.HTTP_403_FORBIDDEN)

        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({"error": {"code": "file_required", "message": "Файл списка студентов обязателен"}}, status=status.HTTP_400_BAD_REQUEST)

        file_bytes = file_obj.read()
        batch = UploadBatch.objects.create(
            university=university,
            uploaded_by=user,
            file_name=file_obj.name,
            status=UploadBatch.Status.PROCESSING
        )

        AdminActionLog.objects.create(
            admin=user,
            action="upload_students_file",
            target_type="upload_batch",
            target_id=str(batch.id),
            details={"file_name": file_obj.name, "university": university.code},
            ip_address=get_client_ip(request)
        )

        # Dispatch Celery task (runs synchronously if CELERY_TASK_ALWAYS_EAGER is True)
        process_student_upload_batch.delay(str(batch.id), file_bytes, file_obj.name)

        return Response({
            "batch_id": str(batch.id),
            "message": "Файл принят в обработку",
            "file_name": file_obj.name
        }, status=status.HTTP_202_ACCEPTED)

class AdminUploadBatchStatusView(APIView):
    permission_classes = [IsAdminUserWithRole]

    def get(self, request, pk):
        try:
            batch = UploadBatch.objects.select_related('university').get(id=pk)
            serializer = UploadBatchSerializer(batch)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except UploadBatch.DoesNotExist:
            return Response({"error": {"code": "not_found", "message": "Пакет загрузки не найден"}}, status=status.HTTP_404_NOT_FOUND)

class AdminStudentTemplateView(APIView):
    permission_classes = [IsAdminUserWithRole]

    def get(self, request):
        format_type = request.query_params.get('format', 'csv').lower()
        if format_type == 'xlsx':
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Студенты"
            headers = ["student_id", "full_name", "phone_number", "faculty", "course", "email"]
            ws.append(headers)
            ws.append(["20230101", "Асанов Асан Асанович", "+996700123456", "Информационные технологии", 2, "asan@stud.kg"])
            ws.append(["20230102", "Бектурова Айпери Алмазовна", "+996555987654", "Экономика и бизнес", 3, "aiperi@stud.kg"])
            ws.append(["20230103", "Иванов Иван Иванович", "+996777654321", "Инженерия", 1, "ivan@stud.kg"])
            output = io.BytesIO()
            wb.save(output)
            output.seek(0)
            response = HttpResponse(output.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = 'attachment; filename="students_template.xlsx"'
            return response
        else:
            # CSV template
            content = "student_id,full_name,phone_number,faculty,course,email\n" \
                      "20230101,Асанов Асан Асанович,+996700123456,Информационные технологии,2,asan@stud.kg\n" \
                      "20230102,Бектурова Айпери Алмазовна,+996555987654,Экономика и бизнес,3,aiperi@stud.kg\n" \
                      "20230103,Иванов Иван Иванович,+996777654321,Инженерия,1,ivan@stud.kg\n"
            response = HttpResponse(content.encode('utf-8-sig'), content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = 'attachment; filename="students_template.csv"'
            return response
