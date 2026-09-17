import jwt
from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed

class StudentUserWrapper:
    """Wrapper to present a Student instance as request.user for DRF."""
    def __init__(self, student):
        self.student = student
        self.id = student.id
        self.student_id = student.student_id
        self.full_name = student.full_name
        self.university = student.university
        self.university_id = student.university_id
        self.is_student = True
        self.is_authenticated = True
        self.is_staff = False
        self.is_superuser = False

    def __str__(self):
        return f"Student: {self.full_name} ({self.student_id})"

class CombinedJWTAuthentication(BaseAuthentication):
    """
    Handles both Admin User SimpleJWT and Student JWT tokens seamlessly.
    """
    def __init__(self):
        self.simplejwt_auth = JWTAuthentication()

    def authenticate(self, request):
        header = request.headers.get('Authorization')
        if not header:
            return None

        parts = header.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            return None

        raw_token = parts[1]

        # First attempt: check if it's a student token
        try:
            payload = jwt.decode(raw_token, settings.SECRET_KEY, algorithms=['HS256'])
            if payload.get('token_type') == 'student':
                from apps.students.models import Student
                student_id = payload.get('student_id')
                try:
                    student = Student.objects.select_related('university').get(id=student_id)
                    return (StudentUserWrapper(student), raw_token)
                except Student.DoesNotExist:
                    raise AuthenticationFailed("Студент не найден")
        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed("Срок действия студенческого токена истёк")
        except jwt.InvalidTokenError:
            pass  # Could be an admin token, try SimpleJWT below

        # Second attempt: check if it's an AdminUser token via SimpleJWT
        try:
            validated_token = self.simplejwt_auth.get_validated_token(raw_token)
            user = self.simplejwt_auth.get_user(validated_token)
            user.is_student = False
            return (user, validated_token)
        except Exception as e:
            raise AuthenticationFailed(f"Недействительный токен авторизации: {str(e)}")
