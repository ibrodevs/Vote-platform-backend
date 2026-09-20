"""Тесты переходов состояния выборов (ТЗ п.8, 17, 52, 66).

Терминальные статусы (finished, cancelled) покидать нельзя: иначе завершённые
выборы переоткрываются и голосование идёт поверх готовых результатов.
Повторный вызов той же операции остаётся идемпотентным — админ, дважды нажавший
кнопку, не должен получать ошибку.
"""
from apps.elections.models import Election
from apps.elections.services import ElectionStateError, finish_election, start_election
from apps.voting.models import Ballot, VoteRecord

from .base import ContractTestCase
from .factories import make_admin, make_candidate, make_election, make_student, make_university


class ElectionTransitionServiceTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university()
        self.election = make_election(self.uni, status=Election.Status.DRAFT)
        make_candidate(self.election)

    def test_start_from_draft(self):
        start_election(self.election)
        self.election.refresh_from_db()
        self.assertEqual(self.election.status, Election.Status.ACTIVE)

    def test_start_is_idempotent_for_active(self):
        self.election.status = Election.Status.ACTIVE
        self.election.save(update_fields=["status"])
        start_election(self.election)
        self.election.refresh_from_db()
        self.assertEqual(self.election.status, Election.Status.ACTIVE)

    def test_start_rejects_finished(self):
        """D-07: переоткрытие завершённых выборов — голосование поверх результатов."""
        self.election.status = Election.Status.FINISHED
        self.election.save(update_fields=["status"])
        with self.assertRaises(ElectionStateError) as ctx:
            start_election(self.election)
        self.assertEqual(ctx.exception.code, "invalid_status_transition")

    def test_start_rejects_cancelled(self):
        self.election.status = Election.Status.CANCELLED
        self.election.save(update_fields=["status"])
        with self.assertRaises(ElectionStateError):
            start_election(self.election)

    def test_start_requires_candidates(self):
        empty = make_election(self.uni, status=Election.Status.DRAFT, title="Пустые")
        with self.assertRaises(ElectionStateError) as ctx:
            start_election(empty)
        self.assertEqual(ctx.exception.code, "no_candidates")

    def test_finish_rejects_cancelled(self):
        self.election.status = Election.Status.CANCELLED
        self.election.save(update_fields=["status"])
        with self.assertRaises(ElectionStateError):
            finish_election(self.election)

    def test_finish_is_idempotent(self):
        self.election.status = Election.Status.FINISHED
        self.election.save(update_fields=["status"])
        finish_election(self.election)
        self.election.refresh_from_db()
        self.assertEqual(self.election.status, Election.Status.FINISHED)


class ElectionLifecycleApiTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university()
        self.admin = make_admin(email="super@test.kg")
        self.election = make_election(self.uni, status=Election.Status.DRAFT)
        make_candidate(self.election)
        self.as_admin(self.admin)

    def test_start_finished_election_returns_400(self):
        self.election.status = Election.Status.FINISHED
        self.election.save(update_fields=["status"])
        res = self.client.post(f"/api/v1/admin/elections/{self.election.id}/start/")
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res, "invalid_status_transition")

    def test_start_cancelled_election_returns_400(self):
        self.election.status = Election.Status.CANCELLED
        self.election.save(update_fields=["status"])
        res = self.client.post(f"/api/v1/admin/elections/{self.election.id}/start/")
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res, "invalid_status_transition")

    def test_finished_election_keeps_its_results(self):
        """Переоткрытие запрещено — значит результаты завершённых выборов неизменны."""
        student = make_student(self.uni, student_id="S-1")
        candidate = self.election.candidates.first()
        start = self.client.post(f"/api/v1/admin/elections/{self.election.id}/start/")
        self.assertEqual(start.status_code, 200)

        self.as_student(student)
        self.client.post(
            "/api/v1/voting/cast/",
            {"election_id": str(self.election.id), "candidate_id": str(candidate.id)},
            format="json",
        )
        self.as_admin(self.admin)
        self.client.post(f"/api/v1/admin/elections/{self.election.id}/finish/")

        reopen = self.client.post(f"/api/v1/admin/elections/{self.election.id}/start/")
        self.assertEqual(reopen.status_code, 400)
        self.assertEqual(VoteRecord.objects.filter(election=self.election).count(), 1)
        self.assertEqual(Ballot.objects.filter(election=self.election).count(), 1)

    def test_delete_active_election_returns_400_and_keeps_it(self):
        """D-02: раньше отдавался 204 при неудалённых выборах."""
        self.election.status = Election.Status.ACTIVE
        self.election.save(update_fields=["status"])
        res = self.client.delete(f"/api/v1/admin/elections/{self.election.id}/")
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res, "active_election")
        self.assertTrue(Election.objects.filter(id=self.election.id).exists())

    def test_delete_finished_election_succeeds(self):
        self.election.status = Election.Status.FINISHED
        self.election.save(update_fields=["status"])
        res = self.client.delete(f"/api/v1/admin/elections/{self.election.id}/")
        self.assertEqual(res.status_code, 204)
        self.assertFalse(Election.objects.filter(id=self.election.id).exists())
