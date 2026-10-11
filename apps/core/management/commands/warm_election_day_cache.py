"""Предварительно прогревает Redis principal-кэшем перед открытием голосования.

Запуск за 5–10 минут до пика убирает «холодный старт», когда первый
authenticated-запрос каждого из сотен тысяч студентов иначе делает SELECT
из PostgreSQL. Команда не кэширует пароли, email, телефон или выбор студента.
"""
from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError

from apps.core.cache_keys import student_principal
from apps.core.principals import StudentPrincipal
from apps.students.models import Student


class Command(BaseCommand):
    help = "Прогреть Redis principal-кэшем активных студентов перед выборами"

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='Сколько principal записывать одним cache.set_many (default: 1000)',
        )
        parser.add_argument(
            '--ttl',
            type=int,
            default=None,
            help='TTL секунд; по умолчанию AUTH_PRINCIPAL_CACHE_TTL',
        )
        parser.add_argument(
            '--university-id',
            type=str,
            default=None,
            help='Прогреть только один университет (UUID)',
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        ttl = options['ttl'] or settings.AUTH_PRINCIPAL_CACHE_TTL
        university_id = options['university_id']

        if batch_size < 100 or batch_size > 10000:
            raise CommandError('--batch-size должен быть от 100 до 10000')
        if ttl < 60:
            raise CommandError('--ttl должен быть не меньше 60 секунд')

        qs = Student.objects.filter(is_active=True)
        if university_id:
            qs = qs.filter(university_id=university_id)

        qs = qs.only(
            'id', 'student_id', 'university_id', 'full_name', 'is_active', 'auth_version'
        ).order_by('id')

        total = qs.count()
        self.stdout.write(
            f'Прогрев principal cache: students={total}, batch={batch_size}, ttl={ttl}s'
        )

        written = 0
        failed = 0
        payload = {}

        def flush():
            nonlocal written, failed, payload
            if not payload:
                return
            result = cache.set_many(payload, timeout=ttl)
            # django-redis возвращает список не записанных ключей; другие backend
            # могут вернуть None. В обоих случаях отсутствие exception означает,
            # что пакет принят backend-ом.
            failed_keys = result if isinstance(result, (list, tuple, set)) else ()
            failed += len(failed_keys)
            written += len(payload) - len(failed_keys)
            payload = {}

        try:
            for student in qs.iterator(chunk_size=batch_size):
                principal = StudentPrincipal.from_model(student)
                payload[student_principal(student.id)] = principal.to_cache()
                if len(payload) >= batch_size:
                    flush()
                    if written and written % 10000 < batch_size:
                        self.stdout.write(f'  cached={written:,}/{total:,}')
            flush()
        except Exception as exc:
            raise CommandError(f'Не удалось прогреть cache: {exc}') from exc

        if failed:
            raise CommandError(
                f'Прогрев неполный: cached={written}, failed={failed}, total={total}'
            )

        self.stdout.write(self.style.SUCCESS(f'Cache warmup OK: {written:,}/{total:,}'))
