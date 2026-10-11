"""Election-day correctness/performance tests for authenticated reads."""
from django.core.cache import caches
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.students.services_auth import create_student_token
from apps.voting.models import Ballot, VoteRecord

from .base import ContractTestCase
from .factories import make_candidate, make_election, make_student, make_university

SERVICE_MARKERS = ("SAVEPOINT", "RELEASE", "ROLLBACK", "pg_advisory", "BEGIN", "COMMIT")


def real_sql(captured):
    return [q["sql"] for q in captured if not any(m in q["sql"] for m in SERVICE_MARKERS)]


class AvailableElectionHotPathTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        caches['default'].clear()
        self.uni = make_university(code='hot-path')
        self.election = make_election(self.uni, title='Election day')
        self.candidate = make_candidate(self.election, full_name='Candidate A')
        self.voted = make_student(self.uni, student_id='HOT-VOTED')
        self.unvoted = make_student(
            self.uni,
            student_id='HOT-UNVOTED',
            phone_number='+996700000002',
        )
        VoteRecord.objects.create(election=self.election, student=self.voted)
        Ballot.objects.create(election=self.election, candidate=self.candidate)

    @staticmethod
    def _headers(student):
        return {'HTTP_AUTHORIZATION': f'Bearer {create_student_token(student)}'}

    def _get(self, student):
        return self.client.get(
            '/api/v1/elections/available/',
            **self._headers(student),
        )

    def _detail(self, student):
        return self.client.get(
            f'/api/v1/elections/{self.election.id}/',
            **self._headers(student),
        )

    def test_shared_catalog_never_leaks_personal_vote_state(self):
        """Один Redis catalog обслуживает университет, но has_voted не общий."""
        unvoted_response = self._get(self.unvoted)
        self.assertEqual(unvoted_response.status_code, 200)
        unvoted_ids = {str(row['id']) for row in unvoted_response.data}
        self.assertIn(str(self.election.id), unvoted_ids)
        row = next(row for row in unvoted_response.data if str(row['id']) == str(self.election.id))
        self.assertFalse(row['has_voted'])

        voted_response = self._get(self.voted)
        self.assertEqual(voted_response.status_code, 200)
        voted_ids = {str(row['id']) for row in voted_response.data}
        self.assertNotIn(str(self.election.id), voted_ids)

        again = self._get(self.unvoted)
        again_ids = {str(row['id']) for row in again.data}
        self.assertIn(str(self.election.id), again_ids)

    def test_warm_request_only_needs_personal_vote_lookup(self):
        """After principal+catalog warmup the hot path stays O(1) SQL."""
        self._get(self.unvoted)

        with CaptureQueriesContext(connection) as ctx:
            response = self._get(self.unvoted)

        self.assertEqual(response.status_code, 200)
        statements = real_sql(ctx.captured_queries)
        self.assertLessEqual(
            len(statements),
            2,
            'warm /elections/available/ should only need the small personal '
            'VoteRecord lookup; SQL:\n  ' + '\n  '.join(statements),
        )
        sql = '\n'.join(statements).lower()
        self.assertNotIn('from "elections_election"', sql)
        self.assertNotIn('from "candidates_candidate"', sql)

    def test_all_true_keeps_existing_history_contract(self):
        response = self.client.get(
            '/api/v1/elections/available/?all=true',
            **self._headers(self.voted),
        )
        self.assertEqual(response.status_code, 200)
        ids = {str(row['id']) for row in response.data}
        self.assertIn(str(self.election.id), ids)
        row = next(row for row in response.data if str(row['id']) == str(self.election.id))
        self.assertTrue(row['has_voted'])

    def test_shared_detail_never_leaks_has_voted_between_students(self):
        first = self._detail(self.unvoted)
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.data['has_voted'])
        self.assertTrue(first.data['is_eligible'])

        second = self._detail(self.voted)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.data['has_voted'])
        self.assertTrue(second.data['is_eligible'])

        again = self._detail(self.unvoted)
        self.assertFalse(again.data['has_voted'])

    def test_warm_detail_does_not_reload_election_or_candidates(self):
        self._detail(self.unvoted)

        with CaptureQueriesContext(connection) as ctx:
            response = self._detail(self.unvoted)

        self.assertEqual(response.status_code, 200)
        statements = real_sql(ctx.captured_queries)
        self.assertLessEqual(len(statements), 2)
        sql = '\n'.join(statements).lower()
        self.assertNotIn('from "elections_election"', sql)
        self.assertNotIn('from "candidates_candidate"', sql)
