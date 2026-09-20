"""Contract-тесты админского CRUD: университеты, студенты, кандидаты, контент, пользователи."""
import unittest

from apps.accounts.models import AdminUser
from apps.candidates.models import Candidate
from apps.students.models import UploadBatch
from apps.universities.models import University

from .base import ContractTestCase
from .factories import (
    make_admin,
    make_candidate,
    make_election,
    make_faq,
    make_news,
    make_static_page,
    make_student,
    make_university,
)


class AdminUniversitiesContractTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university(code="kstu")
        self.superadmin = make_admin(email="super@test.kg")
        self.uni_admin = make_admin(
            email="uni@test.kg",
            role=AdminUser.Role.UNIVERSITY_ADMIN,
            university=self.uni,
        )

    def test_admin_universities_list(self):
        self.as_admin(self.superadmin)
        res = self.client.get("/api/v1/admin/universities/")
        results = self.assertPaginated(res)
        self.assertKeys(results[0], {
            "id", "name", "name_ky", "code", "logo", "is_active",
            "is_registration_open", "created_at",
            "students_count", "active_elections_count", "faculties",
        })

    def test_create_university_requires_superadmin(self):
        self.as_admin(self.uni_admin)
        res = self.client.post(
            "/api/v1/admin/universities/",
            {"name": "Новый", "name_ky": "Жаңы", "code": "new-uni"},
            format="json",
        )
        self.assertEqual(res.status_code, 403)

    def test_create_university_with_faculties_input(self):
        self.as_admin(self.superadmin)
        res = self.client.post(
            "/api/v1/admin/universities/",
            {
                "name": "Новый", "name_ky": "Жаңы", "code": "new-uni",
                "faculties_input": ["ФИТ", "ИЭФ"],
            },
            format="json",
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(res.data["faculties"]), 2)
        self.assertNotIn("faculties_input", res.data)

    def test_delete_university_requires_superadmin(self):
        self.as_admin(self.uni_admin)
        res = self.client.delete(f"/api/v1/admin/universities/{self.uni.id}/")
        self.assertEqual(res.status_code, 403)
        self.assertTrue(University.objects.filter(id=self.uni.id).exists())

    def test_toggle_registration_by_id(self):
        self.as_admin(self.superadmin)
        res = self.client.post(
            f"/api/v1/admin/universities/{self.uni.id}/toggle-registration/",
            {"is_registration_open": False},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertKeys(res.data, {"id", "name", "is_registration_open", "message"})
        self.assertFalse(res.data["is_registration_open"])

    def test_toggle_registration_all_requires_superadmin(self):
        self.as_admin(self.uni_admin)
        res = self.client.post(
            "/api/v1/admin/universities/toggle-registration/",
            {"all": True, "is_registration_open": False},
            format="json",
        )
        self.assertEqual(res.status_code, 403)
        self.assertErrorEnvelope(res, "forbidden")

    def test_toggle_registration_all_for_superadmin(self):
        self.as_admin(self.superadmin)
        res = self.client.post(
            "/api/v1/admin/universities/toggle-registration/",
            {"all": True, "is_registration_open": False},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertKeys(res.data, {"all", "is_registration_open", "message"})

    def test_create_and_delete_faculty(self):
        self.as_admin(self.superadmin)
        created = self.client.post(
            f"/api/v1/admin/universities/{self.uni.id}/faculties/",
            {"name": "Новый факультет"},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        self.assertKeys(created.data, {"id", "name", "name_ky", "code"})

        deleted = self.client.delete(
            f"/api/v1/admin/universities/{self.uni.id}/faculties/{created.data['id']}/"
        )
        self.assertEqual(deleted.status_code, 204)


class AdminStudentsContractTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university(code="kstu")
        self.other_uni = make_university(code="other")
        self.superadmin = make_admin(email="super@test.kg")
        self.uni_admin = make_admin(
            email="uni@test.kg",
            role=AdminUser.Role.UNIVERSITY_ADMIN,
            university=self.uni,
        )
        self.voter = make_student(self.uni, student_id="S-1001", full_name="Голосовавший Студент")
        self.non_voter = make_student(self.uni, student_id="S-1002", full_name="Не голосовавший")
        make_student(self.other_uni, student_id="S-2001", full_name="Чужой Студент")

        election = make_election(self.uni)
        candidate = make_candidate(election)
        self.as_student(self.voter)
        self.client.post(
            "/api/v1/voting/cast/",
            {"election_id": str(election.id), "candidate_id": str(candidate.id)},
            format="json",
        )
        self.as_anonymous()

    def test_admin_students_list_paginated(self):
        self.as_admin(self.superadmin)
        res = self.client.get("/api/v1/admin/students/")
        results = self.assertPaginated(res)
        self.assertKeys(results[0], {
            "id", "university", "university_name", "university_code",
            "student_id", "full_name", "phone_number", "email", "photo",
            "faculty", "group", "course", "is_active",
            "has_voted", "voted_at", "votes_count", "created_at",
        })

    def test_admin_students_scoped_to_own_university(self):
        self.as_admin(self.uni_admin)
        res = self.client.get("/api/v1/admin/students/")
        results = self.assertPaginated(res)
        codes = {s["student_id"] for s in results}
        self.assertEqual(codes, {"S-1001", "S-1002"})

    def test_admin_students_filter_voted(self):
        self.as_admin(self.superadmin)
        res = self.client.get("/api/v1/admin/students/?voted=true")
        results = self.assertPaginated(res)
        self.assertEqual([s["student_id"] for s in results], ["S-1001"])
        self.assertTrue(results[0]["has_voted"])
        self.assertEqual(results[0]["votes_count"], 1)

    def test_admin_students_filter_not_voted(self):
        self.as_admin(self.superadmin)
        res = self.client.get("/api/v1/admin/students/?voted=false")
        results = self.assertPaginated(res)
        self.assertNotIn("S-1001", {s["student_id"] for s in results})

    def test_admin_students_search(self):
        self.as_admin(self.superadmin)
        res = self.client.get("/api/v1/admin/students/?search=Чужой")
        results = self.assertPaginated(res)
        self.assertEqual([s["student_id"] for s in results], ["S-2001"])

    def test_students_scoped_by_university_path(self):
        self.as_admin(self.superadmin)
        res = self.client.get(f"/api/v1/admin/universities/{self.other_uni.id}/students/")
        results = self.assertPaginated(res)
        self.assertEqual([s["student_id"] for s in results], ["S-2001"])

    def test_student_upload_returns_202_batch_id(self):
        self.as_admin(self.superadmin)
        csv_bytes = (
            "student_id,full_name,phone_number,faculty,course,email\n"
            "S-3001,Импортов Студент,+996700123456,ФИТ,2,imp@kstu.kg\n"
        ).encode("utf-8")
        upload = self.client.post(
            f"/api/v1/admin/universities/{self.uni.id}/students/upload/",
            {"file": _as_upload("students.csv", csv_bytes)},
            format="multipart",
        )
        self.assertEqual(upload.status_code, 202)
        self.assertKeys(upload.data, {"batch_id", "message", "file_name"})
        self.assertEqual(upload.data["file_name"], "students.csv")

    def test_student_upload_without_file_400(self):
        self.as_admin(self.superadmin)
        res = self.client.post(
            f"/api/v1/admin/universities/{self.uni.id}/students/upload/",
            {},
            format="multipart",
        )
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res, "file_required")

    def test_batch_status_shape(self):
        self.as_admin(self.superadmin)
        batch = UploadBatch.objects.create(
            university=self.uni, file_name="x.csv", status=UploadBatch.Status.COMPLETED
        )
        res = self.client.get(f"/api/v1/admin/upload-batches/{batch.id}/status/")
        self.assertEqual(res.status_code, 200)
        self.assertKeys(res.data, {
            "id", "university", "university_name", "uploaded_by", "uploaded_by_name",
            "file_name", "total_rows", "success_count", "error_count",
            "errors_detail", "status", "created_at",
        })

    def test_students_template_defaults_to_csv(self):
        self.as_admin(self.superadmin)
        res = self.client.get("/api/v1/admin/students/template/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/csv", res["Content-Type"])
        self.assertIn("students_template.csv", res["Content-Disposition"])

    def test_students_template_format_param_is_swallowed_by_drf(self):
        """D-03: ?format=... перехватывается content negotiation DRF, а не view.

        URL_FORMAT_OVERRIDE по умолчанию равен 'format', поэтому DRF пытается
        подобрать рендерер 'csv'/'xlsx', не находит и отдаёт 404 раньше,
        чем AdminStudentTemplateView прочитает query_params.
        """
        self.as_admin(self.superadmin)
        for value in ("csv", "xlsx"):
            with self.subTest(format=value):
                res = self.client.get(f"/api/v1/admin/students/template/?format={value}")
                self.assertEqual(res.status_code, 404)

    @unittest.expectedFailure
    def test_students_template_xlsx_is_reachable(self):
        """D-03: намеренное поведение — xlsx-ветка view должна быть достижима.

        Сейчас недостижима ни при каком значении параметра. Снять
        expectedFailure после исправления (переименовать параметр или задать
        URL_FORMAT_OVERRIDE = None).
        """
        self.as_admin(self.superadmin)
        res = self.client.get("/api/v1/admin/students/template/?format=xlsx")
        self.assertEqual(res.status_code, 200)
        self.assertIn("spreadsheetml", res["Content-Type"])


class AdminCandidatesContractTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university(code="kstu")
        self.admin = make_admin(email="super@test.kg")
        self.election = make_election(self.uni)
        self.as_admin(self.admin)

    def test_admin_candidates_list_not_paginated(self):
        make_candidate(self.election)
        res = self.client.get(f"/api/v1/admin/elections/{self.election.id}/candidates/")
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.data, list)
        self.assertKeys(res.data[0], {
            "id", "election", "election_title", "university", "university_name",
            "full_name", "photo", "photo_url", "faculty", "course",
            "position", "position_ky", "short_bio", "short_bio_ky",
            "program", "program_ky", "order", "created_at",
        })

    def test_create_candidate_inherits_university(self):
        res = self.client.post(
            f"/api/v1/admin/elections/{self.election.id}/candidates/",
            {"full_name": "Новый кандидат"},
            format="json",
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["university"], self.uni.id)

    def test_candidate_bio_length_validation(self):
        res = self.client.post(
            f"/api/v1/admin/elections/{self.election.id}/candidates/",
            {"full_name": "Болтун", "short_bio": "я" * 101},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res)

    def test_reorder_candidates(self):
        first = make_candidate(self.election, full_name="Первый", order=0)
        second = make_candidate(self.election, full_name="Второй", order=1)
        res = self.client.post(
            f"/api/v1/admin/elections/{self.election.id}/candidates/reorder/",
            {"ordered_ids": [str(second.id), str(first.id)]},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertKeys(res.data, {"success", "message"})
        self.assertEqual(Candidate.objects.get(id=second.id).order, 0)
        self.assertEqual(Candidate.objects.get(id=first.id).order, 1)

    def test_update_and_delete_candidate(self):
        candidate = make_candidate(self.election)
        patched = self.client.patch(
            f"/api/v1/admin/candidates/{candidate.id}/",
            {"full_name": "Переименован"},
            format="json",
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.data["full_name"], "Переименован")

        deleted = self.client.delete(f"/api/v1/admin/candidates/{candidate.id}/")
        self.assertEqual(deleted.status_code, 204)


class AdminUsersAndLogsContractTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university(code="kstu")
        self.superadmin = make_admin(email="super@test.kg")
        self.uni_admin = make_admin(
            email="uni@test.kg",
            role=AdminUser.Role.UNIVERSITY_ADMIN,
            university=self.uni,
        )

    def test_admin_users_list_requires_superadmin(self):
        self.as_admin(self.uni_admin)
        res = self.client.get("/api/v1/auth/admin/users/")
        self.assertEqual(res.status_code, 403)

    def test_admin_users_list_paginated(self):
        self.as_admin(self.superadmin)
        res = self.client.get("/api/v1/auth/admin/users/")
        results = self.assertPaginated(res)
        self.assertKeys(results[0], {
            "id", "email", "full_name", "role", "university",
            "university_details", "is_active", "created_at",
        })

    def test_create_admin_user_accepts_university_id_alias(self):
        self.as_admin(self.superadmin)
        res = self.client.post(
            "/api/v1/auth/admin/users/",
            {
                "email": "observer@test.kg",
                "full_name": "Наблюдатель",
                "role": "observer",
                "university_id": str(self.uni.id),
                "password": "observerpass123",
            },
            format="json",
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["university"], self.uni.id)
        self.assertNotIn("password", res.data)

    def test_create_admin_user_without_university_for_scoped_role_400(self):
        self.as_admin(self.superadmin)
        res = self.client.post(
            "/api/v1/auth/admin/users/",
            {"email": "x@test.kg", "full_name": "X", "role": "university_admin"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res)

    def test_delete_admin_user(self):
        self.as_admin(self.superadmin)
        res = self.client.delete(f"/api/v1/auth/admin/users/{self.uni_admin.id}/")
        self.assertEqual(res.status_code, 204)

    def test_admin_logs_list(self):
        self.as_admin(self.superadmin)
        res = self.client.get("/api/v1/auth/admin/logs/")
        results = self.assertPaginated(res)
        self.assertKeys(results[0], {
            "id", "admin", "admin_email", "admin_name", "action",
            "target_type", "target_id", "details", "ip_address", "created_at",
        })


class AdminContentContractTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.superadmin = make_admin(email="super@test.kg")
        self.as_admin(self.superadmin)

    def test_admin_news_crud(self):
        created = self.client.post(
            "/api/v1/admin/content/news/",
            {"title": "Заголовок", "content": "Текст"},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        news_id = created.data["id"]

        patched = self.client.patch(
            f"/api/v1/admin/content/news/{news_id}/", {"title": "Новый"}, format="json"
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.data["title"], "Новый")

        deleted = self.client.delete(f"/api/v1/admin/content/news/{news_id}/")
        self.assertEqual(deleted.status_code, 204)

    def test_admin_faqs_crud(self):
        created = self.client.post(
            "/api/v1/admin/content/faqs/",
            {"question": "Вопрос?", "answer": "Ответ"},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        faq_id = created.data["id"]

        deleted = self.client.delete(f"/api/v1/admin/content/faqs/{faq_id}/")
        self.assertEqual(deleted.status_code, 204)

    def test_admin_static_pages_list_and_patch(self):
        page = make_static_page(slug="privacy")
        listed = self.client.get("/api/v1/admin/content/pages/")
        self.assertEqual(listed.status_code, 200)
        self.assertIsInstance(listed.data, list)

        patched = self.client.patch(
            f"/api/v1/admin/content/pages/{page.slug}/",
            {"content": "Обновлённый текст"},
            format="json",
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.data["content"], "Обновлённый текст")


def _as_upload(name, content):
    from django.core.files.uploadedfile import SimpleUploadedFile
    return SimpleUploadedFile(name, content, content_type="text/csv")
