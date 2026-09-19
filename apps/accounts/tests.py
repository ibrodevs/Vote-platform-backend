from django.test import TestCase
from rest_framework.test import APIClient
from django.utils import timezone
from datetime import timedelta
from apps.accounts.models import AdminUser
from apps.universities.models import University
from apps.elections.models import Election
from apps.candidates.models import Candidate
from apps.students.models import Student

class ObserverAndStaffTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.uni_1 = University.objects.create(
            name="КГТУ им. И. Раззакова",
            name_ky="КМТУ",
            code="kstu",
            is_active=True
        )
        self.uni_2 = University.objects.create(
            name="КНУ им. Ж. Баласагына",
            name_ky="КУУ",
            code="knu",
            is_active=True
        )

        self.super_admin = AdminUser.objects.create_superuser(
            email="superadmin@platform.kg",
            password="adminpassword123",
            full_name="Главный Администратор"
        )

        self.observer_1 = AdminUser.objects.create_user(
            email="observer_kstu@platform.kg",
            password="observerpassword123",
            full_name="Сотрудник КГТУ",
            role=AdminUser.Role.OBSERVER,
            university=self.uni_1
        )

        self.election_1 = Election.objects.create(
            university=self.uni_1,
            title="Выборы КГТУ",
            status=Election.Status.DRAFT,
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(days=2)
        )
        self.candidate_1 = Candidate.objects.create(
            university=self.uni_1,
            election=self.election_1,
            full_name="Кандидат 1",
            course=3,
            position="Лидер"
        )

        self.election_2 = Election.objects.create(
            university=self.uni_2,
            title="Выборы КНУ",
            status=Election.Status.DRAFT,
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(days=2)
        )

    def test_super_admin_staff_management(self):
        self.client.force_authenticate(user=self.super_admin)

        # 1. List users
        res = self.client.get('/api/v1/auth/admin/users/')
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(len(res.data), 2)

        # 2. Create new observer for uni_2
        res_create = self.client.post('/api/v1/auth/admin/users/', {
            "email": "observer_knu@platform.kg",
            "password": "pass123456knu",
            "full_name": "Наблюдатель КНУ",
            "role": "observer",
            "university_id": str(self.uni_2.id)
        }, format='json')
        self.assertEqual(res_create.status_code, 201)
        created_id = res_create.data['id']
        self.assertEqual(res_create.data['role'], 'observer')
        self.assertEqual(str(res_create.data['university']), str(self.uni_2.id))

        # 3. Update staff user
        res_update = self.client.patch(f'/api/v1/auth/admin/users/{created_id}/', {
            "full_name": "Наблюдатель КНУ Обновленный"
        }, format='json')
        self.assertEqual(res_update.status_code, 200)
        self.assertEqual(res_update.data['full_name'], "Наблюдатель КНУ Обновленный")

        # 4. Delete staff user
        res_delete = self.client.delete(f'/api/v1/auth/admin/users/{created_id}/')
        self.assertEqual(res_delete.status_code, 204)
        self.assertFalse(AdminUser.objects.filter(id=created_id).exists())

    def test_observer_read_only_and_scoping(self):
        self.client.force_authenticate(user=self.observer_1)

        # 1. Observer can view elections for their uni
        res_elections = self.client.get('/api/v1/admin/elections/')
        self.assertEqual(res_elections.status_code, 200)
        election_ids = [e['id'] for e in res_elections.data.get('results', res_elections.data)]
        self.assertIn(str(self.election_1.id), election_ids)
        self.assertNotIn(str(self.election_2.id), election_ids)

        # 2. Observer CANNOT create election (POST blocked)
        res_create_elec = self.client.post('/api/v1/admin/elections/', {
            "title": "Новые выборы",
            "university_id": str(self.uni_1.id),
            "starts_at": timezone.now().isoformat(),
            "ends_at": (timezone.now() + timedelta(days=1)).isoformat()
        }, format='json')
        self.assertEqual(res_create_elec.status_code, 403)

        # 3. Observer CANNOT start election
        res_start = self.client.post(f'/api/v1/admin/elections/{self.election_1.id}/start/')
        self.assertEqual(res_start.status_code, 403)

        # 4. Observer CAN view turnout for own uni election
        res_turnout = self.client.get(f'/api/v1/admin/elections/{self.election_1.id}/turnout/')
        self.assertEqual(res_turnout.status_code, 200)

        # 5. Observer CANNOT view turnout for other uni election
        res_turnout_other = self.client.get(f'/api/v1/admin/elections/{self.election_2.id}/turnout/')
        self.assertEqual(res_turnout_other.status_code, 403)

        # 6. Observer can view students for own uni
        res_students = self.client.get('/api/v1/admin/students/')
        self.assertEqual(res_students.status_code, 200)

        # 7. Observer CANNOT upload students
        res_upload = self.client.post(f'/api/v1/admin/universities/{self.uni_1.id}/students/upload/', {})
        self.assertEqual(res_upload.status_code, 403)

        # 8. Observer CANNOT toggle registration
        res_toggle = self.client.post(f'/api/v1/admin/universities/{self.uni_1.id}/toggle-registration/')
        self.assertEqual(res_toggle.status_code, 403)
