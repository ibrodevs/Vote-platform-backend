import concurrent.futures
from datetime import timedelta
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from apps.universities.models import University
from apps.students.models import Student
from apps.elections.models import Election
from apps.candidates.models import Candidate
from apps.voting.models import VoteRecord, Ballot
from apps.voting.services import cast_secret_ballot, AlreadyVotedError, ElectionNotActiveError

class SecretBallotArchitectureTest(TestCase):
    def test_ballot_model_has_no_student_association(self):
        """
        Проверка архитектурного требования 5.1:
        Таблица Ballot физически не содержит student_id или FK на VoteRecord.
        """
        ballot_fields = [f.name for f in Ballot._meta.get_fields()]
        self.assertNotIn('student', ballot_fields)
        self.assertNotIn('student_id', ballot_fields)
        self.assertNotIn('vote_record', ballot_fields)
        self.assertNotIn('voterecord', ballot_fields)

    def test_vote_record_model_has_no_candidate_association(self):
        """
        Проверка архитектурного требования 5.1:
        Таблица VoteRecord не содержит информации о выборе/кандидате.
        """
        vote_record_fields = [f.name for f in VoteRecord._meta.get_fields()]
        self.assertNotIn('candidate', vote_record_fields)
        self.assertNotIn('candidate_id', vote_record_fields)
        self.assertNotIn('ballot', vote_record_fields)

class SecretBallotVotingServiceTest(TransactionTestCase):
    def setUp(self):
        self.uni = University.objects.create(
            name="КГТУ",
            name_ky="КМТУ",
            code="kstu_test"
        )
        self.student = Student.objects.create(
            university=self.uni,
            student_id="TEST202601",
            full_name="Тестов Студент",
            phone_number="+996700000001",
            faculty="ФИТ",
            course=2
        )
        now = timezone.now()
        self.election = Election.objects.create(
            university=self.uni,
            title="Тестовые выборы",
            title_ky="Сыноо шайлоо",
            status=Election.Status.ACTIVE,
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(hours=1)
        )
        self.candidate1 = Candidate.objects.create(
            election=self.election,
            university=self.uni,
            full_name="Кандидат 1",
            faculty="ФИТ",
            course=3,
            order=0
        )
        self.candidate2 = Candidate.objects.create(
            election=self.election,
            university=self.uni,
            full_name="Кандидат 2",
            faculty="ИЭФ",
            course=4,
            order=1
        )

    def test_successful_cast_and_duplicate_rejection(self):
        """Обычное голосование и блокировка повторной попытки."""
        success = cast_secret_ballot(self.student, str(self.election.id), str(self.candidate1.id))
        self.assertTrue(success)

        # Verify 1 participation record and 1 ballot created
        self.assertEqual(VoteRecord.objects.filter(election=self.election, student=self.student).count(), 1)
        self.assertEqual(Ballot.objects.filter(election=self.election, candidate=self.candidate1).count(), 1)

        # Attempt to vote again should immediately fail
        with self.assertRaises(AlreadyVotedError):
            cast_secret_ballot(self.student, str(self.election.id), str(self.candidate2.id))

        # Ballot count should remain exactly 1
        self.assertEqual(Ballot.objects.filter(election=self.election).count(), 1)

    def test_concurrency_race_condition_protection(self):
        """
        Проверка устойчивости к параллельным запросам (race condition).
        Несколько одновременных потоков голосуют за одного и того же студента.
        Ровно ОДИН запрос должен быть зафиксирован, остальные должны быть отклонены.
        """
        student2 = Student.objects.create(
            university=self.uni,
            student_id="TEST202602",
            full_name="Параллельный Студент",
            phone_number="+996700000002",
            faculty="ФИТ",
            course=3
        )

        results = []
        errors = []

        def attempt_vote():
            from django.db import connection
            connection.close()  # New DB connection per thread
            try:
                res = cast_secret_ballot(student2, str(self.election.id), str(self.candidate1.id))
                results.append(res)
            except Exception as e:
                errors.append(e)

        # Run 5 concurrent threads
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(attempt_vote) for _ in range(5)]
            concurrent.futures.wait(futures)

        # Exactly 1 vote must have succeeded
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 4)

        # In database: exactly 1 VoteRecord and 1 Ballot
        self.assertEqual(VoteRecord.objects.filter(election=self.election, student=student2).count(), 1)
        self.assertEqual(Ballot.objects.filter(election=self.election).count(), 1)

    def test_cannot_vote_in_inactive_election(self):
        self.election.status = Election.Status.FINISHED
        self.election.save()

        with self.assertRaises(ElectionNotActiveError):
            cast_secret_ballot(self.student, str(self.election.id), str(self.candidate1.id))
