"""Contract-тесты голосования.

Самая чувствительная часть контракта: коды ошибок отсюда показываются
студенту фронтендом напрямую (lib/api.ts -> ApiError.code/message).
"""
from datetime import timedelta

from django.utils import timezone

from apps.elections.models import Election
from apps.voting.models import Ballot, VoteRecord

from .base import ContractTestCase
from .factories import (
    DEFAULT_ADMIN_PASSWORD,
    make_admin,
    make_candidate,
    make_election,
    make_student,
    make_university,
    unknown_uuid,
)


class CastVoteContractTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university(code="kstu")
        self.student = make_student(self.uni, student_id="S-1001")
        self.election = make_election(self.uni)
        self.candidate = make_candidate(self.election)
        self.as_student(self.student)

    def _cast(self, election_id=None, candidate_id=None):
        return self.client.post(
            "/api/v1/voting/cast/",
            {
                "election_id": str(election_id or self.election.id),
                "candidate_id": str(candidate_id or self.candidate.id),
            },
            format="json",
        )

    def test_cast_vote_success_shape(self):
        res = self._cast()
        # 200, НЕ 201 — контракт api.castVote()
        self.assertEqual(res.status_code, 200)
        self.assertKeys(res.data, {"success", "message"})
        self.assertTrue(res.data["success"])

    def test_cast_vote_creates_exactly_one_record_and_one_ballot(self):
        self._cast()
        self.assertEqual(VoteRecord.objects.filter(election=self.election).count(), 1)
        self.assertEqual(Ballot.objects.filter(election=self.election).count(), 1)

    def test_cast_vote_requires_student_auth(self):
        self.as_anonymous()
        res = self._cast()
        self.assertEqual(res.status_code, 403)

    def test_cast_vote_admin_token_rejected(self):
        admin = make_admin(email="a@test.kg")
        self.as_admin(admin, DEFAULT_ADMIN_PASSWORD)
        res = self._cast()
        self.assertEqual(res.status_code, 403)

    def test_cast_vote_already_voted(self):
        self._cast()
        res = self._cast()
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res, "already_voted")

    def test_cast_vote_election_not_active(self):
        self.election.status = Election.Status.FINISHED
        self.election.save(update_fields=["status"])
        res = self._cast()
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res, "election_not_active")

    def test_cast_vote_cancelled_election(self):
        self.election.status = Election.Status.CANCELLED
        self.election.save(update_fields=["status"])
        res = self._cast()
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res, "election_not_active")

    def test_cast_vote_before_starts_at(self):
        now = timezone.now()
        self.election.starts_at = now + timedelta(hours=1)
        self.election.ends_at = now + timedelta(hours=2)
        self.election.save(update_fields=["starts_at", "ends_at"])
        res = self._cast()
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res, "election_not_active")

    def test_cast_vote_after_ends_at(self):
        now = timezone.now()
        self.election.starts_at = now - timedelta(hours=2)
        self.election.ends_at = now - timedelta(hours=1)
        self.election.save(update_fields=["starts_at", "ends_at"])
        res = self._cast()
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res, "election_not_active")

    def test_cast_vote_other_university(self):
        other_uni = make_university(code="other")
        other_election = make_election(other_uni)
        other_candidate = make_candidate(other_election)
        res = self._cast(other_election.id, other_candidate.id)
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res, "ineligible_student")

    def test_cast_vote_candidate_from_other_election(self):
        second = make_election(self.uni, title="Другие выборы")
        foreign_candidate = make_candidate(second, full_name="Чужой")
        res = self._cast(self.election.id, foreign_candidate.id)
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res, "invalid_candidate")

    def test_cast_vote_unknown_election(self):
        res = self._cast(unknown_uuid(), self.candidate.id)
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res, "election_not_found")

    def test_cast_vote_malformed_body_400(self):
        res = self.client.post(
            "/api/v1/voting/cast/",
            {"election_id": str(self.election.id)},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res)

    def test_deactivated_student_can_still_vote_with_old_token(self):
        """D-04: CombinedJWTAuthentication не проверяет Student.is_active.

        Деактивированный студент с ранее выданным токеном продолжает голосовать.
        Фиксируется как факт; проверка is_active и механизм revoke (auth_version)
        добавляются на этапе 3.
        """
        self.student.is_active = False
        self.student.save(update_fields=["is_active"])
        res = self._cast()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(VoteRecord.objects.count(), 1)

    def test_failed_vote_leaves_no_partial_records(self):
        """Отклонённая попытка не должна оставлять ни VoteRecord, ни Ballot."""
        second = make_election(self.uni, title="Другие выборы")
        foreign_candidate = make_candidate(second, full_name="Чужой")
        self._cast(self.election.id, foreign_candidate.id)
        self.assertEqual(VoteRecord.objects.count(), 0)
        self.assertEqual(Ballot.objects.count(), 0)


class VoteStatusContractTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university(code="kstu")
        self.student = make_student(self.uni, student_id="S-1001")
        self.election = make_election(self.uni)
        self.candidate = make_candidate(self.election)

    def test_vote_status_requires_student_auth(self):
        res = self.client.get(f"/api/v1/voting/status/{self.election.id}/")
        self.assertEqual(res.status_code, 403)

    def test_vote_status_before_and_after(self):
        self.as_student(self.student)

        before = self.client.get(f"/api/v1/voting/status/{self.election.id}/")
        self.assertEqual(before.status_code, 200)
        self.assertKeys(before.data, {"has_voted", "voted_at"})
        self.assertFalse(before.data["has_voted"])
        self.assertIsNone(before.data["voted_at"])

        self.client.post(
            "/api/v1/voting/cast/",
            {"election_id": str(self.election.id), "candidate_id": str(self.candidate.id)},
            format="json",
        )

        after = self.client.get(f"/api/v1/voting/status/{self.election.id}/")
        self.assertEqual(after.status_code, 200)
        self.assertTrue(after.data["has_voted"])
        self.assertIsNotNone(after.data["voted_at"])

    def test_vote_status_unknown_election_reports_not_voted(self):
        """Текущее поведение: несуществующие выборы -> 200 has_voted=false, не 404."""
        self.as_student(self.student)
        res = self.client.get(f"/api/v1/voting/status/{unknown_uuid()}/")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["has_voted"])


class SecretBallotApiContractTest(ContractTestCase):
    """Тайна голосования на уровне API, а не только схемы."""

    def setUp(self):
        super().setUp()
        self.uni = make_university(code="kstu")
        self.student = make_student(self.uni, student_id="S-1001")
        self.election = make_election(self.uni)
        self.candidate = make_candidate(self.election)
        self.as_student(self.student)
        self.client.post(
            "/api/v1/voting/cast/",
            {"election_id": str(self.election.id), "candidate_id": str(self.candidate.id)},
            format="json",
        )

    def test_ballot_carries_no_student_reference(self):
        ballot_fields = {f.name for f in Ballot._meta.get_fields()}
        self.assertFalse(
            ballot_fields & {"student", "student_id", "vote_record", "voterecord"},
            f"Ballot не должен ссылаться на студента: {ballot_fields}",
        )

    def test_vote_record_carries_no_candidate_reference(self):
        record_fields = {f.name for f in VoteRecord._meta.get_fields()}
        self.assertFalse(
            record_fields & {"candidate", "candidate_id", "ballot"},
            f"VoteRecord не должен ссылаться на кандидата: {record_fields}",
        )

    def test_vote_status_response_never_exposes_candidate(self):
        res = self.client.get(f"/api/v1/voting/status/{self.election.id}/")
        self.assertNotIn("candidate", str(res.data).lower())
