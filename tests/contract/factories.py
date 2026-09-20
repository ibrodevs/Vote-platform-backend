"""Фабрики доменных объектов для contract-тестов.

Единственное место, знающее, как собрать валидный объект каждой модели.
Тесты не создают модели напрямую — иначе изменение схемы правит десятки файлов.
"""
import datetime
import uuid
from datetime import timedelta

import jwt
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.utils import timezone

from apps.accounts.models import AdminUser
from apps.candidates.models import Candidate
from apps.content.models import FAQItem, NewsArticle, StaticPage
from apps.elections.models import Election
from apps.students.models import Student, StudentAuthSession
from apps.universities.models import Faculty, University

DEFAULT_ADMIN_PASSWORD = "adminpass123"
DEFAULT_STUDENT_PASSWORD = "studentpass123"


def make_university(code="test-uni", **kw):
    defaults = {
        "name": "Тестовый университет",
        "name_ky": "Сыноо университети",
        "code": code,
        "is_active": True,
        "is_registration_open": True,
    }
    defaults.update(kw)
    return University.objects.create(**defaults)


def make_faculty(university, name="ФИТ", **kw):
    defaults = {"university": university, "name": name, "name_ky": "", "code": ""}
    defaults.update(kw)
    return Faculty.objects.create(**defaults)


def make_student(university, *, student_id="S-0001", email=None, password=None, **kw):
    defaults = {
        "university": university,
        "student_id": student_id,
        "full_name": "Тестов Тест Тестович",
        "phone_number": "+996700000001",
        "faculty": "ФИТ",
        "group": "ПИ-1-21",
        "course": 2,
        "is_active": True,
    }
    defaults.update(kw)
    if email is not None:
        defaults["email"] = email
    if password is not None:
        defaults["password"] = make_password(password)
    return Student.objects.create(**defaults)


def make_admin(*, email="admin@test.kg", password=DEFAULT_ADMIN_PASSWORD,
               role=AdminUser.Role.SUPER_ADMIN, university=None, **kw):
    defaults = {
        "email": email,
        "full_name": "Администратор Тестовый",
        "role": role,
        "university": university,
        "is_active": True,
    }
    defaults.update(kw)
    return AdminUser.objects.create_user(password=password, **defaults)


def make_election(university, *, status=Election.Status.ACTIVE,
                  starts_at=None, ends_at=None, **kw):
    now = timezone.now()
    defaults = {
        "university": university,
        "title": "Тестовые выборы",
        "title_ky": "Сыноо шайлоо",
        "description": "Описание",
        "description_ky": "Сүрөттөмө",
        "status": status,
        "starts_at": starts_at if starts_at is not None else now - timedelta(hours=1),
        "ends_at": ends_at if ends_at is not None else now + timedelta(hours=1),
    }
    defaults.update(kw)
    return Election.objects.create(**defaults)


def make_candidate(election, *, full_name="Кандидат Кандидатов", order=0, **kw):
    defaults = {
        "election": election,
        "university": election.university,
        "full_name": full_name,
        "faculty": "ФИТ",
        "course": 3,
        "position": "Кандидат",
        "order": order,
    }
    defaults.update(kw)
    return Candidate.objects.create(**defaults)


def make_auth_session(student, *, code="123456", expires_in_minutes=10, **kw):
    defaults = {
        "student": student,
        "phone_number": student.phone_number,
        "code": code,
        "expires_at": timezone.now() + timedelta(minutes=expires_in_minutes),
    }
    defaults.update(kw)
    return StudentAuthSession.objects.create(**defaults)


def make_news(**kw):
    defaults = {"title": "Новость", "content": "Текст новости", "is_published": True}
    defaults.update(kw)
    return NewsArticle.objects.create(**defaults)


def make_faq(**kw):
    defaults = {"question": "Вопрос?", "answer": "Ответ.", "is_active": True, "order": 0}
    defaults.update(kw)
    return FAQItem.objects.create(**defaults)


def make_static_page(slug="regulations", **kw):
    defaults = {"slug": slug, "title": "Регламент", "content": "Текст", "is_published": True}
    defaults.update(kw)
    return StaticPage.objects.create(**defaults)


def student_token(student):
    """JWT студента.

    Payload намеренно продублирован, а не импортирован из
    apps/students/views.py::create_student_token: тест обязан ломаться,
    если формат токена изменят молча.
    """
    now = timezone.now()
    payload = {
        "token_type": "student",
        "student_id": str(student.id),
        "university_id": str(student.university_id),
        "student_code": student.student_id,
        "exp": int((now + datetime.timedelta(days=7)).timestamp()),
        "iat": int(now.timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def unknown_uuid():
    """UUID, которого гарантированно нет в базе."""
    return str(uuid.uuid4())
