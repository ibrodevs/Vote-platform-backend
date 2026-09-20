"""Contract-тесты публичных endpoints.

Фиксируют ТЕКУЩЕЕ поведение. Если тест здесь падает после рефакторинга —
сломан контракт для фронтенда, а не тест.
"""
from datetime import timedelta

from django.utils import timezone

from apps.elections.models import Election

from .base import ContractTestCase
from .factories import (
    make_candidate,
    make_election,
    make_faculty,
    make_faq,
    make_news,
    make_static_page,
    make_university,
    unknown_uuid,
)


class ServiceEndpointsContractTest(ContractTestCase):
    def test_health_endpoint(self):
        res = self.client.get("/api/health/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"status": "healthy", "service": "dobush-backend"})

    def test_api_root_lists_endpoints(self):
        res = self.client.get("/api/")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["status"], "online")
        self.assertIn("version", body)
        self.assertIn("endpoints", body)


class PublicUniversitiesContractTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university(code="kstu", name="КГТУ")
        make_faculty(self.uni, name="ФИТ")

    def test_universities_list_is_bare_array(self):
        res = self.client.get("/api/v1/universities/")
        self.assertEqual(res.status_code, 200)
        # НЕ пагинировано — контракт api.getUniversities()
        self.assertIsInstance(res.data, list)
        self.assertKeys(res.data[0], {
            "id", "name", "name_ky", "code", "logo",
            "is_active", "is_registration_open", "faculties",
        })

    def test_universities_list_excludes_inactive(self):
        make_university(code="dead-uni", is_active=False)
        res = self.client.get("/api/v1/universities/")
        codes = {u["code"] for u in res.data}
        self.assertIn("kstu", codes)
        self.assertNotIn("dead-uni", codes)

    def test_university_info_by_code(self):
        res = self.client.get("/api/v1/universities/kstu/info/")
        self.assertEqual(res.status_code, 200)
        self.assertKeys(res.data, {
            "id", "name", "name_ky", "code", "logo",
            "is_active", "is_registration_open", "faculties",
        })
        self.assertEqual(res.data["faculties"][0]["name"], "ФИТ")

    def test_university_info_unknown_code_404(self):
        res = self.client.get("/api/v1/universities/nope/info/")
        self.assertEqual(res.status_code, 404)
        self.assertErrorEnvelope(res, "not_found")

    def test_university_faculties_public_is_paginated(self):
        res = self.client.get(f"/api/v1/universities/{self.uni.id}/faculties/")
        results = self.assertPaginated(res)
        self.assertKeys(results[0], {"id", "name", "name_ky", "code"})


class PublicElectionsContractTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university(code="kstu")
        self.election = make_election(self.uni, title="Выборы президента")
        self.candidate_b = make_candidate(self.election, full_name="Бета", order=1)
        self.candidate_a = make_candidate(self.election, full_name="Альфа", order=0)

    def test_recent_elections_is_bare_array(self):
        res = self.client.get("/api/v1/elections/recent/")
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.data, list)
        self.assertKeys(res.data[0], {
            "id", "university", "university_details", "title", "title_ky",
            "description", "description_ky", "status", "starts_at", "ends_at",
            "results_visible_to_admin_before_finish",
            "is_featured", "featured_order", "cover_image", "cover_image_url",
            "created_by", "created_by_name",
            "candidates_count", "is_voting_open", "created_at", "updated_at",
        })
        self.assertEqual(res.data[0]["candidates_count"], 2)
        self.assertTrue(res.data[0]["is_voting_open"])
        self.assertEqual(res.data[0]["cover_image"], "")

    def test_recent_elections_excludes_cancelled(self):
        make_election(self.uni, title="Отменённые", status=Election.Status.CANCELLED)
        res = self.client.get("/api/v1/elections/recent/")
        titles = {e["title"] for e in res.data}
        self.assertIn("Выборы президента", titles)
        self.assertNotIn("Отменённые", titles)

    def test_elections_public_alias_matches_recent(self):
        recent = self.client.get("/api/v1/elections/recent/")
        public = self.client.get("/api/v1/elections/public/")
        self.assertEqual(public.status_code, 200)
        self.assertEqual(
            [e["id"] for e in public.data],
            [e["id"] for e in recent.data],
        )

    def test_election_detail_anonymous(self):
        res = self.client.get(f"/api/v1/elections/{self.election.id}/")
        self.assertEqual(res.status_code, 200)
        self.assertKeys(res.data, {
            "id", "university", "university_name", "university_name_ky",
            "title", "title_ky", "description", "description_ky",
            "status", "starts_at", "ends_at", "candidates",
            "has_voted", "is_eligible",
        })
        self.assertFalse(res.data["has_voted"])
        self.assertIsNone(res.data["is_eligible"])
        self.assertEqual(len(res.data["candidates"]), 2)

    def test_election_detail_not_found(self):
        res = self.client.get(f"/api/v1/elections/{unknown_uuid()}/")
        self.assertEqual(res.status_code, 404)
        self.assertErrorEnvelope(res, "not_found")

    def test_election_candidates_public_ordered(self):
        res = self.client.get(f"/api/v1/elections/{self.election.id}/candidates/")
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.data, list)
        self.assertEqual([c["full_name"] for c in res.data], ["Альфа", "Бета"])
        self.assertKeys(res.data[0], {
            "id", "election", "election_title", "university", "university_name",
            "full_name", "photo", "photo_url", "faculty", "course",
            "position", "position_ky", "short_bio", "short_bio_ky",
            "program", "program_ky", "order",
        })

    def test_election_candidates_unknown_election_404(self):
        res = self.client.get(f"/api/v1/elections/{unknown_uuid()}/candidates/")
        self.assertEqual(res.status_code, 404)
        self.assertErrorEnvelope(res, "not_found")

    def test_candidate_public_detail(self):
        res = self.client.get(f"/api/v1/candidates/{self.candidate_a.id}/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["full_name"], "Альфа")
        self.assertEqual(res.data["election_title"], "Выборы президента")

    def test_candidate_public_detail_not_found(self):
        res = self.client.get(f"/api/v1/candidates/{unknown_uuid()}/")
        self.assertEqual(res.status_code, 404)
        self.assertErrorEnvelope(res)


class PublicContentContractTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.article = make_news(title="Первая новость")
        make_faq(question="Как голосовать?")
        make_static_page(slug="regulations")

    def test_news_list_is_paginated(self):
        res = self.client.get("/api/v1/news/")
        results = self.assertPaginated(res)
        self.assertEqual(results[0]["title"], "Первая новость")

    def test_news_recent_is_bare_array(self):
        res = self.client.get("/api/v1/news/recent/")
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.data, list)

    def test_news_detail(self):
        res = self.client.get(f"/api/v1/news/{self.article.id}/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["title"], "Первая новость")

    def test_faqs_list_is_bare_array(self):
        res = self.client.get("/api/v1/faqs/")
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.data, list)
        self.assertEqual(res.data[0]["question"], "Как голосовать?")

    def test_static_page_by_slug(self):
        res = self.client.get("/api/v1/pages/regulations/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["slug"], "regulations")

    def test_static_page_unknown_slug_404(self):
        res = self.client.get("/api/v1/pages/nope/")
        self.assertEqual(res.status_code, 404)
        self.assertErrorEnvelope(res)
