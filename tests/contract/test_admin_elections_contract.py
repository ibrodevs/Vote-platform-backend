"""Contract-тесты админского жизненного цикла выборов."""
import unittest
from datetime import timedelta

from django.utils import timezone

from apps.accounts.models import AdminUser
from apps.elections.models import Election

from .base import ContractTestCase
from .factories import (
    make_admin,
    make_candidate,
    make_election,
    make_student,
    make_university,
    unknown_uuid,
)

ELECTION_KEYS = {
    "id", "university", "university_details", "title", "title_ky",
    "description", "description_ky", "status", "starts_at", "ends_at",
    "results_visible_to_admin_before_finish",
    "is_featured", "featured_order", "cover_image", "cover_image_url",
    "created_by", "created_by_name",
    "candidates_count", "is_voting_open", "created_at", "updated_at",
}


class AdminAuthContractTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university(code="kstu")
        self.admin = make_admin(email="super@test.kg")

    def test_admin_login_returns_access_refresh_user(self):
        res = self.client.post(
            "/api/v1/auth/admin/login/",
            {"email": "super@test.kg", "password": "adminpass123"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertKeys(res.data, {"access", "refresh", "user"})
        self.assertKeys(res.data["user"], {
            "id", "email", "full_name", "role", "university",
            "university_details", "is_active", "created_at",
        })
        self.assertEqual(res.data["user"]["role"], "super_admin")

    def test_admin_login_wrong_password(self):
        res = self.client.post(
            "/api/v1/auth/admin/login/",
            {"email": "super@test.kg", "password": "nope"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res)

    def test_admin_login_inactive_account(self):
        self.admin.is_active = False
        self.admin.save(update_fields=["is_active"])
        res = self.client.post(
            "/api/v1/auth/admin/login/",
            {"email": "super@test.kg", "password": "adminpass123"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res)

    def test_admin_me(self):
        self.as_admin(self.admin)
        res = self.client.get("/api/v1/auth/admin/me/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["email"], "super@test.kg")


class AdminElectionCrudContractTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university(code="kstu")
        self.admin = make_admin(email="super@test.kg")
        self.as_admin(self.admin)

    def test_elections_list_is_paginated(self):
        make_election(self.uni)
        res = self.client.get("/api/v1/admin/elections/")
        results = self.assertPaginated(res)
        self.assertKeys(results[0], ELECTION_KEYS)

    def test_election_create_shape(self):
        now = timezone.now()
        res = self.client.post(
            "/api/v1/admin/elections/",
            {
                "university": str(self.uni.id),
                "title": "Новые выборы",
                "title_ky": "Жаңы шайлоо",
                "starts_at": (now + timedelta(days=1)).isoformat(),
                "ends_at": (now + timedelta(days=2)).isoformat(),
            },
            format="json",
        )
        self.assertEqual(res.status_code, 201)
        self.assertKeys(res.data, ELECTION_KEYS)
        self.assertEqual(res.data["candidates_count"], 0)
        self.assertEqual(res.data["cover_image"], "")
        self.assertEqual(res.data["status"], "draft")

    def test_election_detail_patch(self):
        election = make_election(self.uni)
        res = self.client.patch(
            f"/api/v1/admin/elections/{election.id}/",
            {"title": "Переименованные"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["title"], "Переименованные")

    def test_delete_draft_election_204(self):
        election = make_election(self.uni, status=Election.Status.DRAFT)
        res = self.client.delete(f"/api/v1/admin/elections/{election.id}/")
        self.assertEqual(res.status_code, 204)
        self.assertFalse(Election.objects.filter(id=election.id).exists())

    def test_delete_active_election_is_rejected(self):
        """D-02 исправлен на этапе 2: было 204 при неудалённых выборах."""
        election = make_election(self.uni, status=Election.Status.ACTIVE)
        res = self.client.delete(f"/api/v1/admin/elections/{election.id}/")
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res, "active_election")
        self.assertTrue(Election.objects.filter(id=election.id).exists())


class AdminElectionLifecycleContractTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university(code="kstu")
        self.admin = make_admin(email="super@test.kg")
        self.election = make_election(self.uni, status=Election.Status.DRAFT)
        self.candidate = make_candidate(self.election)
        self.as_admin(self.admin)

    def test_start_election_returns_success_status(self):
        res = self.client.post(f"/api/v1/admin/elections/{self.election.id}/start/")
        self.assertEqual(res.status_code, 200)
        self.assertKeys(res.data, {"success", "message", "status"})
        self.assertEqual(res.data["status"], "active")

    def test_start_election_without_candidates_400(self):
        empty = make_election(self.uni, status=Election.Status.DRAFT)
        res = self.client.post(f"/api/v1/admin/elections/{empty.id}/start/")
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res, "no_candidates")

    def test_finish_election(self):
        res = self.client.post(f"/api/v1/admin/elections/{self.election.id}/finish/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], "finished")

    def test_cancel_election(self):
        res = self.client.post(f"/api/v1/admin/elections/{self.election.id}/cancel/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], "cancelled")

    def test_lifecycle_endpoints_404_for_unknown_id(self):
        for action in ("start", "finish", "cancel"):
            with self.subTest(action=action):
                res = self.client.post(f"/api/v1/admin/elections/{unknown_uuid()}/{action}/")
                self.assertEqual(res.status_code, 404)
                self.assertErrorEnvelope(res, "not_found")

    def test_lifecycle_endpoints_403_for_foreign_university_admin(self):
        other_uni = make_university(code="other")
        foreign_admin = make_admin(
            email="foreign@test.kg",
            role=AdminUser.Role.UNIVERSITY_ADMIN,
            university=other_uni,
        )
        self.as_admin(foreign_admin)
        for action in ("start", "finish", "cancel"):
            with self.subTest(action=action):
                res = self.client.post(f"/api/v1/admin/elections/{self.election.id}/{action}/")
                self.assertEqual(res.status_code, 403)
                self.assertErrorEnvelope(res, "forbidden")


class AdminTurnoutAndResultsContractTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university(code="kstu")
        self.admin = make_admin(email="super@test.kg")
        self.election = make_election(self.uni)
        self.leader = make_candidate(self.election, full_name="Лидер", order=0)
        self.outsider = make_candidate(self.election, full_name="Аутсайдер", order=1)
        self.voter = make_student(self.uni, student_id="S-1001")
        self.non_voter = make_student(self.uni, student_id="S-1002")

        self.as_student(self.voter)
        self.client.post(
            "/api/v1/voting/cast/",
            {"election_id": str(self.election.id), "candidate_id": str(self.leader.id)},
            format="json",
        )
        self.as_admin(self.admin)

    def test_turnout_shape_and_counts(self):
        res = self.client.get(f"/api/v1/admin/elections/{self.election.id}/turnout/")
        self.assertEqual(res.status_code, 200)
        self.assertKeys(res.data, {
            "election_id", "election_title", "status", "starts_at", "ends_at",
            "total_eligible", "total_voted", "turnout_percent",
        })
        self.assertEqual(res.data["total_eligible"], 2)
        self.assertEqual(res.data["total_voted"], 1)
        self.assertEqual(res.data["turnout_percent"], 50.0)

    def test_results_hidden_before_finish(self):
        res = self.client.get(f"/api/v1/admin/elections/{self.election.id}/results/")
        self.assertEqual(res.status_code, 403)
        self.assertErrorEnvelope(res, "results_hidden")

    def test_results_visible_when_flag_enabled(self):
        self.election.results_visible_to_admin_before_finish = True
        self.election.save(update_fields=["results_visible_to_admin_before_finish"])
        res = self.client.get(f"/api/v1/admin/elections/{self.election.id}/results/")
        self.assertEqual(res.status_code, 200)

    def test_results_shape_after_finish(self):
        self.election.status = Election.Status.FINISHED
        self.election.save(update_fields=["status"])
        res = self.client.get(f"/api/v1/admin/elections/{self.election.id}/results/")
        self.assertEqual(res.status_code, 200)
        self.assertKeys(res.data, {
            "election_id", "election_title", "university_name",
            "total_eligible", "total_voted", "turnout_percent", "candidates",
        })
        self.assertKeys(res.data["candidates"][0], {
            "candidate_id", "full_name", "photo", "photo_url",
            "faculty", "course", "position", "votes", "percent",
        })

    def test_results_sorted_by_votes_desc(self):
        self.election.status = Election.Status.FINISHED
        self.election.save(update_fields=["status"])
        res = self.client.get(f"/api/v1/admin/elections/{self.election.id}/results/")
        names = [c["full_name"] for c in res.data["candidates"]]
        self.assertEqual(names[0], "Лидер")
        self.assertEqual(res.data["candidates"][0]["votes"], 1)
        self.assertEqual(res.data["candidates"][0]["percent"], 100.0)

    def test_results_export_returns_xlsx(self):
        self.election.status = Election.Status.FINISHED
        self.election.save(update_fields=["status"])
        res = self.client.post(f"/api/v1/admin/elections/{self.election.id}/results/export/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("spreadsheetml", res["Content-Type"])
        self.assertEqual(
            res["Content-Disposition"],
            f'attachment; filename="results_{self.election.id}.xlsx"',
        )

    def test_results_export_hidden_before_finish_403(self):
        res = self.client.post(f"/api/v1/admin/elections/{self.election.id}/results/export/")
        self.assertEqual(res.status_code, 403)
        self.assertErrorEnvelope(res, "results_hidden")


class AdminFeaturedElectionsContractTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university(code="kstu")
        self.superadmin = make_admin(email="super@test.kg")
        self.election = make_election(self.uni)

    def test_featured_list_requires_superadmin(self):
        uni_admin = make_admin(
            email="uni@test.kg",
            role=AdminUser.Role.UNIVERSITY_ADMIN,
            university=self.uni,
        )
        self.as_admin(uni_admin)
        res = self.client.get("/api/v1/admin/elections/featured/")
        self.assertEqual(res.status_code, 403)

    def test_featured_list_for_superadmin(self):
        self.as_admin(self.superadmin)
        res = self.client.get("/api/v1/admin/elections/featured/")
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.data, list)

    def test_featured_patch_toggles_flag(self):
        self.as_admin(self.superadmin)
        res = self.client.patch(
            f"/api/v1/admin/elections/{self.election.id}/featured/",
            {"is_featured": True, "featured_order": 3},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["is_featured"])
        self.assertEqual(res.data["featured_order"], 3)
