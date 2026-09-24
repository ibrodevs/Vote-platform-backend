"""Экспорт данных для нагрузочных сценариев (ТЗ п.78).

ЗАЧЕМ ОТДЕЛЬНАЯ КОМАНДА
-----------------------
Профили B, C и D требуют аутентифицированных запросов от РАЗНЫХ студентов.
Логиниться внутри k6 нельзя: логин — сам по себе тяжёлая операция
(проверка пароля через pbkdf2), и профиль измерял бы её, а не то,
ради чего запускался.

Поэтому токены выпускаются заранее одной командой.

БЕЗОПАСНОСТЬ
------------
Файл содержит действующие JWT. Он пишется только для синтетических
студентов, создаётся с правами 600 и добавлен в .gitignore. Для настоящих
студентов команда работать отказывается.

    python manage.py export_loadtest_fixtures --output /fixtures/loadtest.json
"""
import json
import os
import stat

from django.core.management.base import BaseCommand, CommandError

from apps.candidates.models import Candidate
from apps.elections.models import Election
from apps.students.models import Student
from apps.students.services_auth import create_student_token

SYNTHETIC_PREFIX = 'synthetic-'


class Command(BaseCommand):
    help = "Готовит JSON с токенами и выборами для сценариев k6."

    def add_arguments(self, parser):
        parser.add_argument('--output', default='loadtests/fixtures/loadtest.json')
        parser.add_argument('--students', type=int, default=5000,
                            help='Сколько токенов выпустить.')
        parser.add_argument('--allow-real-students', action='store_true',
                            help='НЕ используйте на боевых данных: выпустит токены реальных студентов.')

    def handle(self, *args, **opts):
        students_qs = Student.objects.filter(is_active=True)

        if not opts['allow_real_students']:
            students_qs = students_qs.filter(student_id__startswith=SYNTHETIC_PREFIX)
            if not students_qs.exists():
                raise CommandError(
                    "Синтетических студентов нет. Сначала:\n"
                    "  python manage.py generate_test_data --students 200000\n"
                    "Выпуск токенов реальных студентов требует --allow-real-students "
                    "и на боевых данных недопустим."
                )

        students = list(
            students_qs.only('id', 'student_id', 'university_id')[: opts['students']]
        )
        if not students:
            raise CommandError("Нет подходящих студентов")

        # Выборы берутся того же вуза, что и студенты: голос в чужой вуз
        # отклоняется, и профиль D измерял бы отказы вместо записей
        university_ids = {s.university_id for s in students}
        elections = list(
            Election.objects.filter(
                university_id__in=university_ids, status=Election.Status.ACTIVE
            ).prefetch_related('candidates')
        )
        if not elections:
            raise CommandError(
                "Нет активных выборов в вузах выбранных студентов. "
                "Проверьте generate_test_data."
            )

        payload = {
            'students': [
                {
                    'id': str(s.id),
                    'code': s.student_id,
                    'university_id': str(s.university_id),
                    'token': create_student_token(s),
                }
                for s in students
            ],
            'elections': [
                {
                    'id': str(e.id),
                    'university_id': str(e.university_id),
                    'candidates': [str(c.id) for c in e.candidates.all()],
                }
                for e in elections
                if e.candidates.exists()
            ],
        }

        output = opts['output']
        os.makedirs(os.path.dirname(output) or '.', exist_ok=True)
        with open(output, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle)
        # Файл содержит действующие токены
        os.chmod(output, stat.S_IRUSR | stat.S_IWUSR)

        self.stdout.write(self.style.SUCCESS(
            f"Записано в {output}: студентов {len(payload['students'])}, "
            f"выборов {len(payload['elections'])}"
        ))
        self.stdout.write(
            "Файл содержит действующие JWT — в Git он не попадает (.gitignore)."
        )
