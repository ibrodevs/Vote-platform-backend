"""Проверка готовности к production (ТЗ п.103).

    python manage.py production_check
    python manage.py production_check --skip check_migrations

Возвращает ненулевой код при любой найденной проблеме — пригодно
для CI и для шага перед деплоем.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.core.system_checks import run_all


class Command(BaseCommand):
    help = "Проверяет, что конфигурация пригодна для production."

    def add_arguments(self, parser):
        parser.add_argument('--skip', nargs='*', default=[],
                            help='Имена проверок, которые пропустить.')
        parser.add_argument('--warn-only', action='store_true',
                            help='Не возвращать ненулевой код при проблемах.')

    def handle(self, *args, **opts):
        results = run_all(skip=set(opts['skip']))
        failures = [r for r in results if not r.ok]

        self.stdout.write(self.style.MIGRATE_HEADING('Проверка production-конфигурации'))
        for result in results:
            mark = self.style.SUCCESS('  OK  ') if result.ok else self.style.ERROR(' FAIL ')
            self.stdout.write(f'{mark} {result.message}')
            if not result.ok and result.hint:
                for line in result.hint.split('\n'):
                    self.stdout.write(f'        {line}')

        self.stdout.write('')
        if not failures:
            self.stdout.write(self.style.SUCCESS(
                f'Все {len(results)} проверок пройдены.'))
            return

        summary = f'Проблем: {len(failures)} из {len(results)}.'
        if opts['warn_only']:
            self.stdout.write(self.style.WARNING(summary))
            return
        raise CommandError(summary + ' Деплой в production небезопасен.')
