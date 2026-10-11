"""Проверки production-конфигурации (ТЗ п.102, 103).

Небезопасная конфигурация не должна запускаться молча. Проверки используются
как Django system checks и командой production_check для CI/pre-deploy.
"""
import os

from django.conf import settings

LEAKED_SECRET_KEY = 'vote-platform-secret-key-34e8bb-midnight-011c42'
MIN_SECRET_KEY_BYTES = 32


class CheckResult:
    __slots__ = ('ok', 'code', 'message', 'hint')

    def __init__(self, ok, code, message, hint=''):
        self.ok = ok
        self.code = code
        self.message = message
        self.hint = hint


def _fail(code, message, hint=''):
    return CheckResult(False, code, message, hint)


def _pass(code, message):
    return CheckResult(True, code, message)


def check_debug():
    if settings.DEBUG:
        return _fail('debug_enabled', 'DEBUG=True в production',
                     'Выставьте DJANGO_DEBUG=False. С DEBUG=True Django отдаёт '
                     'трейсбеки со значениями переменных, включая секреты.')
    return _pass('debug_enabled', 'DEBUG выключен')


def check_secret_key():
    key = settings.SECRET_KEY or ''
    if not key:
        return _fail('secret_key_missing', 'DJANGO_SECRET_KEY не задан',
                     'Сгенерируйте: python -c "import secrets; print(secrets.token_urlsafe(64))"')
    if key == LEAKED_SECRET_KEY:
        return _fail('secret_key_leaked',
                     'Используется ключ из репозитория — он скомпрометирован',
                     'Этим ключом подписываются студенческие JWT: зная его, '
                     'можно выпустить токен любого студента. Смените немедленно.')
    if len(key.encode('utf-8')) < MIN_SECRET_KEY_BYTES:
        return _fail('secret_key_too_short',
                     f'DJANGO_SECRET_KEY короче {MIN_SECRET_KEY_BYTES} байт '
                     f'({len(key.encode("utf-8"))})',
                     'Этим ключом подписываются JWT по HMAC SHA256; '
                     'короткий ключ дешевле перебрать.')
    return _pass('secret_key', 'SECRET_KEY задан и достаточной длины')


def check_database_engine():
    engine = settings.DATABASES['default']['ENGINE']
    if 'postgresql' not in engine:
        return _fail('database_engine', f'В production используется {engine}',
                     'Только PostgreSQL (ТЗ п.12): у SQLite другая модель '
                     'конкуррентности и нет advisory locks.')
    return _pass('database_engine', 'PostgreSQL')


def check_allowed_hosts():
    hosts = list(settings.ALLOWED_HOSTS or [])
    if not hosts:
        return _fail('allowed_hosts_empty', 'ALLOWED_HOSTS пуст',
                     'Задайте DJANGO_ALLOWED_HOSTS через запятую.')
    if '*' in hosts:
        return _fail('allowed_hosts_wildcard', 'ALLOWED_HOSTS содержит "*"',
                     'Wildcard открывает Host header injection: ссылки '
                     'в письмах и redirect будут вести на чужой домен.')
    return _pass('allowed_hosts', f'ALLOWED_HOSTS: {", ".join(hosts)}')


def check_cors():
    if getattr(settings, 'CORS_ALLOW_ALL_ORIGINS', False):
        return _fail('cors_open', 'CORS_ALLOW_ALL_ORIGINS=True',
                     'Вместе с CORS_ALLOW_CREDENTIALS это позволяет любому '
                     'сайту делать запросы от имени залогиненного студента. '
                     'Задайте DJANGO_CORS_ALLOWED_ORIGINS.')
    origins = getattr(settings, 'CORS_ALLOWED_ORIGINS', [])
    if not origins:
        return _fail('cors_empty', 'CORS_ALLOWED_ORIGINS пуст',
                     'Фронтенд не сможет обратиться к API.')
    return _pass('cors', f'CORS: {len(origins)} origin(s)')


def check_celery():
    if getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False):
        return _fail('celery_eager', 'CELERY_TASK_ALWAYS_EAGER=True',
                     'Импорт списка студентов выполнится внутри web-процесса '
                     'и заблокирует воркер на всё время (ТЗ п.40).')
    return _pass('celery', 'Celery работает через брокер')


def check_demo_otp():
    if getattr(settings, 'MOCK_SMS', False):
        return _fail('demo_otp_enabled', 'MOCK_SMS=True — OTP всегда один и тот же',
                     'В этом режиме код подтверждения равен DEMO_OTP_CODE '
                     'для всех студентов: войти можно под любым (ТЗ п.34).')
    return _pass('demo_otp', 'Demo-OTP выключен')


def check_clickjacking():
    if getattr(settings, 'X_FRAME_OPTIONS', '').upper() == 'ALLOWALL':
        return _fail('x_frame_allowall', 'X_FRAME_OPTIONS=ALLOWALL',
                     'Любой сайт сможет встроить интерфейс голосования '
                     'в iframe и провести clickjacking.')
    return _pass('x_frame_options', f'X_FRAME_OPTIONS: {settings.X_FRAME_OPTIONS}')


def check_ssl_settings():
    stage = getattr(settings, 'DEPLOYMENT_STAGE', 'production')
    is_bootstrap = getattr(settings, 'IS_BOOTSTRAP', False) or stage == 'bootstrap'
    if is_bootstrap:
        return _pass(
            'secure_cookies_bootstrap',
            'Bootstrap-режим (HTTP over IP): проверка Secure-кук и SSL-редиректа временно пропущена до подключения TLS'
        )
    problems = []
    if not getattr(settings, 'SESSION_COOKIE_SECURE', False):
        problems.append('SESSION_COOKIE_SECURE')
    if not getattr(settings, 'CSRF_COOKIE_SECURE', False):
        problems.append('CSRF_COOKIE_SECURE')
    if not getattr(settings, 'SECURE_SSL_REDIRECT', False):
        problems.append('SECURE_SSL_REDIRECT')
    if problems:
        return _fail(
            'insecure_cookies',
            f'Небезопасная конфигурация SSL/кук: {", ".join(problems)}',
            'В production режиме куки должны быть Secure и включён SSL-редирект (SECURE_SSL_REDIRECT=True).'
        )
    return _pass('secure_cookies', 'Куки помечены Secure, SSL-редирект включён')


def check_migrations():
    from django.db import connections
    from django.db.migrations.executor import MigrationExecutor

    try:
        executor = MigrationExecutor(connections['default'])
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    except Exception as exc:
        return _fail('migrations_unknown', f'Не удалось проверить миграции: {exc}')
    if plan:
        names = ', '.join(f'{m.app_label}.{m.name}' for m, _ in plan[:5])
        return _fail('migrations_pending', f'Не применены миграции: {names}',
                     'Выполните python manage.py migrate.')
    return _pass('migrations', 'Все миграции применены')


def check_redis_configured():
    if not getattr(settings, 'REDIS_URL', ''):
        return _fail('redis_not_configured', 'REDIS_URL не задан',
                     'Без Redis аутентификация будет ходить в PostgreSQL '
                     'на каждый запрос. Система работать будет, но медленнее.')
    return _pass('redis', 'Redis настроен')


def check_conn_max_age():
    """Проверяет безопасную пару Django connections + PgBouncer transaction pool.

    Persistent client connection Django -> PgBouncer не закрепляет PostgreSQL
    backend за воркером: transaction pooling всё равно возвращает server
    connection в пул после COMMIT. Опасны server-side cursors, потому что
    именованный cursor живёт внутри конкретной PostgreSQL session и следующий
    fetch может попасть уже в другую session.

    Поэтому за transaction PgBouncer допускается DB_CONN_MAX_AGE > 0 только
    при DISABLE_SERVER_SIDE_CURSORS=True. На web hot path это убирает лишние
    Django->PgBouncer handshakes, не ослабляя transaction pooling.
    """
    conn_max_age = getattr(settings, 'DB_CONN_MAX_AGE', 0)
    behind_pgbouncer = getattr(settings, 'DB_BEHIND_PGBOUNCER', False)
    disable_cursors = settings.DATABASES.get('default', {}).get(
        'DISABLE_SERVER_SIDE_CURSORS', False
    )

    if behind_pgbouncer and not disable_cursors:
        return _fail(
            'server_side_cursors_with_pgbouncer',
            'PgBouncer transaction pooling заявлен, но server-side cursors включены',
            'Установите DB_DISABLE_SERVER_SIDE_CURSORS=True. Именованный cursor '
            'нельзя безопасно продолжить на другой PostgreSQL session.',
        )

    if not behind_pgbouncer and conn_max_age == 0:
        return _fail(
            'conn_max_age_zero_without_pooler',
            'DB_CONN_MAX_AGE=0 и PgBouncer не заявлен: новое соединение с '
            'PostgreSQL на каждый запрос',
            'Для прямого подключения задайте DB_CONN_MAX_AGE=60 (или другое '
            'измеренное ненулевое значение), либо явно используйте PgBouncer.',
        )

    if behind_pgbouncer:
        return _pass(
            'conn_max_age',
            f'PgBouncer transaction pool: CONN_MAX_AGE={conn_max_age}, '
            'server-side cursors отключены',
        )
    return _pass('conn_max_age', f'Прямое подключение, CONN_MAX_AGE={conn_max_age}')


def check_shared_cache():
    """Кэш обязан быть общим для всех реплик приложения (ТЗ п.99)."""
    backend = settings.CACHES.get('default', {}).get('BACKEND', '')
    if 'locmem' in backend.lower():
        return _fail(
            'cache_not_shared',
            'Кэш по умолчанию — LocMemCache, он локален для процесса',
            'С несколькими репликами у каждой будет свой кэш и свои счётчики '
            'ограничения частоты. Задайте REDIS_URL.',
        )
    if 'dummy' in backend.lower():
        return _fail(
            'cache_disabled',
            'Кэш отключён (DummyCache)',
            'Аутентификация пойдёт в PostgreSQL на каждый запрос. Задайте REDIS_URL.',
        )
    return _pass('cache_shared', f'Кэш общий для реплик: {backend.rsplit(".", 1)[-1]}')


def check_media_storage():
    """Медиафайлы не должны лежать на диске одной ноды (ТЗ п.99)."""
    if getattr(settings, 'AWS_STORAGE_BUCKET_NAME', ''):
        return _pass('media_storage', 'Медиа в объектном хранилище')
    if os.getenv('DJANGO_MEDIA_SHARED', 'False').strip().lower() == 'true':
        return _pass('media_storage', 'Медиа на общем сетевом диске (заявлено явно)')
    return _fail(
        'media_storage_local',
        'Медиафайлы хранятся на локальном диске ноды',
        'При нескольких репликах загрузка, попавшая на одну ноду, не видна '
        'остальным. Задайте AWS_STORAGE_BUCKET_NAME для объектного хранилища '
        'либо DJANGO_MEDIA_SHARED=True, если каталог media общий для всех нод.',
    )


ALL_CHECKS = (
    check_debug,
    check_secret_key,
    check_database_engine,
    check_allowed_hosts,
    check_cors,
    check_celery,
    check_demo_otp,
    check_clickjacking,
    check_ssl_settings,
    check_redis_configured,
    check_conn_max_age,
    check_shared_cache,
    check_media_storage,
    check_migrations,
)


def run_all(skip=()):
    """Выполняет все проверки. Возвращает список CheckResult."""
    return [check() for check in ALL_CHECKS if check.__name__ not in skip]
