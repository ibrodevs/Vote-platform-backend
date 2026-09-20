"""Celery под тестами обязан быть синхронным.

При CELERY_TASK_ALWAYS_EAGER=False (docker-compose, CI) вызов .delay() в тесте
уходит в реальный брокер, и живой воркер ищет объект в реальной базе вместо
тестовой. Тест при этом может остаться зелёным, но трогает чужие данные.
"""
from django.conf import settings
from django.test import TestCase


class CeleryTestModeTest(TestCase):
    def test_tasks_are_eager_under_tests(self):
        self.assertTrue(
            settings.CELERY_TASK_ALWAYS_EAGER,
            "под тестами задачи Celery должны выполняться синхронно",
        )

    def test_upload_task_does_not_reach_broker(self):
        """Задача импорта выполняется в процессе теста и пишет в тестовую базу."""
        from apps.students.models import Student, UploadBatch
        from apps.students.tasks import process_student_upload_batch

        from tests.contract.factories import make_university

        uni = make_university(code="eager-check")
        batch = UploadBatch.objects.create(university=uni, file_name="x.csv")
        csv = (
            b"student_id,full_name,phone_number,faculty,course,email\n"
            b"EAG-001,Eager Test,+996700111222,IT,2,eager@test.kg\n"
        )
        process_student_upload_batch.delay(str(batch.id), csv, "x.csv")

        batch.refresh_from_db()
        self.assertEqual(batch.status, UploadBatch.Status.COMPLETED)
        self.assertEqual(batch.success_count, 1)
        self.assertTrue(Student.objects.filter(student_id="EAG-001").exists())
