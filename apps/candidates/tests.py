from django.test import TestCase
from rest_framework.test import APIClient
from apps.accounts.models import AdminUser
from apps.universities.models import University
from apps.elections.models import Election
from apps.candidates.models import Candidate
from django.utils import timezone
from datetime import timedelta

class CandidateCreationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = AdminUser.objects.create_superuser(
            email="admin@test.com",
            password="adminpassword123",
            role="super_admin"
        )
        self.client.force_authenticate(user=self.admin)

        self.university = University.objects.create(
            name="Тестовый ВУЗ",
            code="testuni",
            is_active=True
        )

        self.election = Election.objects.create(
            university=self.university,
            title="Выборы студсовета 2026",
            status=Election.Status.DRAFT,
            starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(days=7)
        )

    def test_create_candidate_minimal_fields(self):
        # 1. Post to election candidates without election in body
        data = {
            "full_name": "Айбек Исаков",
            "short_bio": "Активист университета"
        }
        res = self.client.post(f'/api/v1/admin/elections/{self.election.id}/candidates/', data, format='json')
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data['full_name'], "Айбек Исаков")
        self.assertEqual(res.data['short_bio'], "Активист университета")
        self.assertEqual(str(res.data['election']), str(self.election.id))

    def test_create_candidate_with_election_in_body(self):
        # 2. Post to election candidates with election and university in body
        data = {
            "election": str(self.election.id),
            "university": str(self.university.id),
            "full_name": "Марат Беков",
            "short_bio": "Староста группы"
        }
        res = self.client.post(f'/api/v1/admin/elections/{self.election.id}/candidates/', data, format='json')
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data['full_name'], "Марат Беков")
