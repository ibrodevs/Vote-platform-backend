from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from apps.universities.models import University
from apps.students.models import Student

class StudentAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.university = University.objects.create(
            name="КГТУ им. И. Раззакова",
            name_ky="КМТУ",
            code="kstu",
            is_active=True
        )

    def test_student_registration_and_login(self):
        # 1. Register student
        reg_data = {
            "full_name": "Азамат Исаков",
            "university_id": str(self.university.id),
            "course": 3,
            "group": "ПИ-1-21",
            "email": "azamat@kstu.kg",
            "password": "secretpassword123"
        }
        res = self.client.post('/api/v1/students/auth/register/', reg_data, format='json')
        self.assertEqual(res.status_code, 201)
        self.assertIn('student_token', res.data)
        self.assertEqual(res.data['student']['full_name'], "Азамат Исаков")
        self.assertEqual(res.data['student']['group'], "ПИ-1-21")
        self.assertEqual(res.data['student']['course'], 3)
        self.assertEqual(res.data['student']['email'], "azamat@kstu.kg")

        # 2. Duplicate registration should fail
        res_dup = self.client.post('/api/v1/students/auth/register/', reg_data, format='json')
        self.assertEqual(res_dup.status_code, 400)

        # 3. Login with correct credentials
        login_data = {
            "email": "azamat@kstu.kg",
            "password": "secretpassword123"
        }
        res_login = self.client.post('/api/v1/students/auth/login/', login_data, format='json')
        self.assertEqual(res_login.status_code, 200)
        token = res_login.data['student_token']
        self.assertTrue(bool(token))

        # 4. Login with wrong password should fail
        res_wrong = self.client.post('/api/v1/students/auth/login/', {
            "email": "azamat@kstu.kg",
            "password": "wrongpassword"
        }, format='json')
        self.assertEqual(res_wrong.status_code, 400)

        # 5. Access profile with token
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        res_profile = self.client.get('/api/v1/students/auth/me/')
        self.assertEqual(res_profile.status_code, 200)
        self.assertEqual(res_profile.data['student']['full_name'], "Азамат Исаков")
        self.assertEqual(res_profile.data['student']['group'], "ПИ-1-21")

    def test_student_election_flow(self):
        from apps.elections.models import Election
        from apps.candidates.models import Candidate
        from django.utils import timezone
        from datetime import timedelta

        # 1. Create active election with candidate
        election = Election.objects.create(
            university=self.university,
            title="Выборы председателя студсовета",
            status=Election.Status.ACTIVE,
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(days=2)
        )
        candidate = Candidate.objects.create(
            university=self.university,
            election=election,
            full_name="Белек Осмонов",
            faculty="ФИТ",
            course=3,
            position="Председатель СС"
        )

        # 2. Public view of election and candidates (unauthenticated)
        res_elec = self.client.get(f'/api/v1/elections/{election.id}/')
        self.assertEqual(res_elec.status_code, 200)
        self.assertEqual(res_elec.data['title'], election.title)

        res_cand = self.client.get(f'/api/v1/elections/{election.id}/candidates/')
        self.assertEqual(res_cand.status_code, 200)
        self.assertEqual(len(res_cand.data), 1)
        self.assertEqual(res_cand.data[0]['full_name'], "Белек Осмонов")

        # 3. Register student
        reg_res = self.client.post('/api/v1/students/auth/register/', {
            "full_name": "Айпери Жумабекова",
            "university_id": str(self.university.id),
            "course": 2,
            "group": "ИВТ-2-22",
            "email": "aiperi@kstu.kg",
            "password": "password456"
        }, format='json')
        self.assertEqual(reg_res.status_code, 201)
        token = reg_res.data['student_token']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        # 4. Check available elections in cabinet
        res_avail = self.client.get('/api/v1/elections/available/?all=true')
        self.assertEqual(res_avail.status_code, 200)
        self.assertEqual(len(res_avail.data), 1)
        self.assertFalse(res_avail.data[0]['has_voted'])

        # 5. Cast vote
        res_vote = self.client.post('/api/v1/voting/cast/', {
            "election_id": str(election.id),
            "candidate_id": str(candidate.id)
        }, format='json')
        self.assertEqual(res_vote.status_code, 200)

        # 6. Double vote must be blocked
        res_vote2 = self.client.post('/api/v1/voting/cast/', {
            "election_id": str(election.id),
            "candidate_id": str(candidate.id)
        }, format='json')
        self.assertEqual(res_vote2.status_code, 400)

        # 7. Check has_voted is now True in cabinet
        res_avail_after = self.client.get('/api/v1/elections/available/?all=true')
        self.assertEqual(res_avail_after.status_code, 200)
        self.assertTrue(res_avail_after.data[0]['has_voted'])
