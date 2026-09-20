import os
import sys
from pathlib import Path
from datetime import timedelta
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env if present
load_dotenv(BASE_DIR / '.env')

# DJANGO_ENV объявлен раньше остальных настроек: от него зависят значения
# по умолчанию. Без него поведение остаётся прежним — живой деплой не ломается.
DJANGO_ENV = os.getenv('DJANGO_ENV', 'development').strip().lower()
IS_PRODUCTION = DJANGO_ENV == 'production'

# Ключ из репозитория оставлен как fallback ТОЛЬКО для разработки.
# В production его отсутствие валит старт: этим ключом подписываются
# студенческие JWT, и знание ключа позволяет выпустить токен любого
# студента (ТЗ п.32, 33).
_DEV_SECRET_KEY = 'vote-platform-secret-key-34e8bb-midnight-011c42'
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', '' if IS_PRODUCTION else _DEV_SECRET_KEY)
if IS_PRODUCTION and not SECRET_KEY:
    raise ImproperlyConfigured(
        'DJANGO_SECRET_KEY обязателен в production. '
        'Сгенерируйте: python -c "import secrets; print(secrets.token_urlsafe(64))"'
    )

DEBUG = os.getenv('DJANGO_DEBUG', 'False' if IS_PRODUCTION else 'True').lower() == 'true'
if IS_PRODUCTION and DEBUG:
    raise ImproperlyConfigured(
        'DJANGO_DEBUG=True недопустим в production: Django отдаёт трейсбеки '
        'со значениями переменных, включая секреты и токены.'
    )


# Флаг тестового прогона нужен нескольким блокам настроек ниже
TESTING = 'test' in sys.argv


def _env_list(name, default=''):
    return [item.strip() for item in os.getenv(name, default).split(',') if item.strip()]


# ALLOWED_HOSTS: в production wildcard запрещён — он открывает
# Host header injection (ТЗ п.32).
ALLOWED_HOSTS = _env_list('DJANGO_ALLOWED_HOSTS') or (['*'] if not IS_PRODUCTION else [])
if IS_PRODUCTION:
    if not ALLOWED_HOSTS:
        raise ImproperlyConfigured('DJANGO_ALLOWED_HOSTS обязателен в production.')
    if '*' in ALLOWED_HOSTS:
        raise ImproperlyConfigured('ALLOWED_HOSTS не может содержать "*" в production.')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party
    'corsheaders',
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'django_filters',

    # Local apps
    'apps.core',
    'apps.accounts',
    'apps.universities',
    'apps.students',
    'apps.candidates',
    'apps.elections',
    'apps.voting',
    'apps.content',
]

MIDDLEWARE = [
    # Первым: идентификатор нужен всем последующим слоям и обработчику ошибок
    'apps.core.middleware.RequestIDMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # ТЗ п.60, 96: приватные ответы не должны попадать в общий кэш.
    # По умолчанию private/no-store, публичным быть надо заслужить.
    'apps.core.middleware.CacheControlMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# ==============================================================================
# DATABASE (ТЗ п.12, 13, 102)
# ==============================================================================
# В production поддерживается только PostgreSQL. SQLite и MySQL остаются
# доступными для локальной разработки, но в production приложение обязано
# падать на старте, а не молча работать на непригодной базе.
DB_ENGINE = os.getenv('DB_ENGINE', 'postgresql' if IS_PRODUCTION else 'sqlite').strip().lower()

if IS_PRODUCTION and DB_ENGINE != 'postgresql':
    raise ImproperlyConfigured(
        f"DJANGO_ENV=production требует DB_ENGINE=postgresql, получено {DB_ENGINE!r}. "
        "SQLite и MySQL не поддерживаются в production (ТЗ п.12)."
    )

# CONN_MAX_AGE=0 по умолчанию осознанно: за PgBouncer в transaction pooling
# persistent-соединения Django вредны. Значение настраивается на этапе 7.
DB_CONN_MAX_AGE = int(os.getenv('DB_CONN_MAX_AGE', '0'))
DB_CONNECT_TIMEOUT = int(os.getenv('DB_CONNECT_TIMEOUT', '10'))

if DB_ENGINE == 'postgresql':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('DB_NAME', 'vote_db'),
            'USER': os.getenv('DB_USER', 'postgres'),
            'PASSWORD': os.getenv('DB_PASSWORD', ''),
            'HOST': os.getenv('DB_HOST', '127.0.0.1'),
            'PORT': os.getenv('DB_PORT', '5432'),
            'CONN_MAX_AGE': DB_CONN_MAX_AGE,
            'OPTIONS': {
                # Не позволять одному зависшему соединению занять воркер (ТЗ п.95)
                'connect_timeout': DB_CONNECT_TIMEOUT,
            },
        }
    }
elif DB_ENGINE == 'mysql':
    # Только локальная разработка. В production отвергается проверкой выше.
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.getenv('DB_NAME', 'vote_db'),
            'USER': os.getenv('DB_USER', 'root'),
            'PASSWORD': os.getenv('DB_PASSWORD', ''),
            'HOST': os.getenv('DB_HOST', '127.0.0.1'),
            'PORT': os.getenv('DB_PORT', '3306'),
        }
    }
else:
    # Только локальная разработка. Конкуррентность, блокировки и планы запросов
    # у SQLite другие — зелёный прогон здесь не доказывает корректность в production
    # (ТЗ п.107). Тесты на PostgreSQL: config/settings_test.py
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
            'TIMEOUT': 30,
        }
    }

AUTH_USER_MODEL = 'accounts.AdminUser'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 6}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'ru-ru'
TIME_ZONE = 'Asia/Bishkek'
USE_I18N = True
USE_TZ = True

# ==============================================================================
# СТАТИКА И МЕДИА (ТЗ п.31)
# ==============================================================================
# В production Django не должен раздавать файлы: каждый запрос за фотографией
# кандидата занимает воркер, который мог бы принять голос.
#
# ОГРАНИЧЕНИЕ ФРОНТЕНДА: getMediaUrl() в lib/api.ts приклеивает относительный
# путь к origin API. Поэтому при переезде на внешнее хранилище бэкенд обязан
# отдавать АБСОЛЮТНЫЕ URL — их фронтенд возвращает как есть. Относительный
# путь к чужому домену собрал бы битую ссылку (docs/FRONTEND_USAGE.md).
STATIC_URL = os.getenv('DJANGO_STATIC_URL', '/static/')
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'

MEDIA_URL = os.getenv('DJANGO_MEDIA_URL', '/media/')
MEDIA_ROOT = BASE_DIR / 'media'

# S3-совместимое хранилище включается заданием бакета. Без него —
# локальная файловая система, как и раньше.
AWS_STORAGE_BUCKET_NAME = os.getenv('AWS_STORAGE_BUCKET_NAME', '')
if AWS_STORAGE_BUCKET_NAME:
    INSTALLED_APPS = INSTALLED_APPS + ['storages']
    STORAGES = {
        'default': {'BACKEND': 'storages.backends.s3.S3Storage'},
        'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
    }
    AWS_S3_ENDPOINT_URL = os.getenv('AWS_S3_ENDPOINT_URL', '') or None
    AWS_S3_CUSTOM_DOMAIN = os.getenv('AWS_S3_CUSTOM_DOMAIN', '') or None
    AWS_S3_REGION_NAME = os.getenv('AWS_S3_REGION_NAME', '') or None
    AWS_QUERYSTRING_AUTH = False
    AWS_DEFAULT_ACL = None

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Reverse Proxy & SSL (Crucial for PythonAnywhere HTTPS and proper request.build_absolute_uri generation)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'apps.core.authentication.CombinedJWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    # ТЗ п.93: размер страницы настраивается клиентом, но ограничен сверху —
    # иначе ?page_size=1000000 выгрузил бы всю таблицу студентов одним ответом.
    'DEFAULT_PAGINATION_CLASS': 'apps.core.pagination.DefaultPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
        # ТЗ п.94: поиск короче 3 символов игнорируется — он совпадает
        # почти со всей таблицей и стоит полного скана при нулевой пользе.
        'apps.core.filters.MinLengthSearchFilter',
        'rest_framework.filters.OrderingFilter',
    ),
    'EXCEPTION_HANDLER': 'apps.core.exceptions.custom_exception_handler',
    # Классы троттлинга назначаются на конкретных вьюхах: глобальный лимит
    # по IP заблокировал бы университет за одним NAT (ТЗ п.36).
    'DEFAULT_THROTTLE_CLASSES': (),
    # D-03: по умолчанию DRF перехватывает ?format= для выбора рендерера, из-за
    # чего ?format=xlsx на /admin/students/template/ давал 404, не доходя до view.
    # Переименование освобождает ?format= для прикладного использования
    # и сохраняет возможность DRF под именем ?_format=.
    'URL_FORMAT_OVERRIDE': '_format',
}

# Путь к Django admin (ТЗ п.98). Стандартный /admin/ сканеры находят
# за минуты; вынос на нестандартный путь убирает админку из общего шума.
# Настоящее ограничение доступа (VPN, allowlist по IP) — на уровне Nginx.
DJANGO_ADMIN_PATH = os.getenv('DJANGO_ADMIN_PATH', 'admin-django').strip('/')

# ==============================================================================
# ОГРАНИЧЕНИЕ ЧАСТОТЫ ЗАПРОСОВ (ТЗ п.36)
# ==============================================================================
# Выключается целиком для нагрузочного тестирования: иначе бенчмарк этапа 10
# измерял бы работу троттлера, а не приложения.
# Под тестами выключено: сотни тестов логинятся с одного адреса и упёрлись бы
# в лимит, измеряя работу троттлера вместо проверяемого поведения.
# Сами лимиты проверяются в tests/contract/test_rate_limiting.py явным
# включением через override_settings.
RATE_LIMIT_ENABLED = (
    not TESTING and os.getenv('RATE_LIMIT_ENABLED', 'True').lower() == 'true'
)

# Пороги. Ключ для student_action и vote — идентификатор студента,
# для auth_attempt и otp_verify — IP. Разница принципиальна: лимит по IP
# на голосовании заблокировал бы весь университет за одним NAT.
RATE_LIMITS = {
    'auth_attempt': os.getenv('RATE_LIMIT_AUTH', '20/min'),
    'otp_verify': os.getenv('RATE_LIMIT_OTP_VERIFY', '10/min'),
    'student_action': os.getenv('RATE_LIMIT_STUDENT', '120/min'),
    'vote': os.getenv('RATE_LIMIT_VOTE', '20/min'),
}

# JWT Configuration
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': False,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# CORS (ТЗ п.32). Открытый CORS вместе с ALLOW_CREDENTIALS позволяет любому
# сайту делать запросы от имени залогиненного студента — в системе
# голосования это недопустимо.
CORS_ALLOWED_ORIGINS = _env_list('DJANGO_CORS_ALLOWED_ORIGINS')
CORS_ALLOW_ALL_ORIGINS = not IS_PRODUCTION and not CORS_ALLOWED_ORIGINS
if IS_PRODUCTION and not CORS_ALLOWED_ORIGINS:
    raise ImproperlyConfigured(
        'DJANGO_CORS_ALLOWED_ORIGINS обязателен в production: '
        'без него фронтенд не сможет обратиться к API.'
    )
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_PRIVATE_NETWORK = True
CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]
from corsheaders.defaults import default_headers
CORS_ALLOW_HEADERS = list(default_headers) + [
    'accept-encoding',
    'authorization',
    'cache-control',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]
CORS_EXPOSE_HEADERS = [
    'content-type',
    'x-csrftoken',
]

# CSRF - Trusted origins allowing cross-domain POST/PUT/DELETE
CSRF_TRUSTED_ORIGINS = [
    'https://*.pythonanywhere.com',
    'http://*.pythonanywhere.com',
    'https://*.vercel.app',
    'https://*.netlify.app',
    'https://*.ngrok-free.app',
    'https://*.loca.lt',
    'http://localhost:3000',
    'https://localhost:3000',
    'http://127.0.0.1:3000',
    'http://localhost:8000',
    'http://127.0.0.1:8000',
]
extra_csrf = _env_list('DJANGO_CSRF_TRUSTED_ORIGINS')
if extra_csrf:
    CSRF_TRUSTED_ORIGINS.extend(extra_csrf)
if IS_PRODUCTION:
    # В production доверяются только явно перечисленные origin'ы:
    # список для разработки содержит wildcard-домены хостингов.
    CSRF_TRUSTED_ORIGINS = extra_csrf or list(CORS_ALLOWED_ORIGINS)

# ==============================================================================
# БЕЗОПАСНОСТЬ ТРАНСПОРТА И ЗАГОЛОВКИ (ТЗ п.32, 97)
# ==============================================================================
# ALLOWALL позволял встроить интерфейс голосования в iframe на чужом сайте
# и провести clickjacking. В production — DENY.
X_FRAME_OPTIONS = 'DENY' if IS_PRODUCTION else 'SAMEORIGIN'

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

SESSION_COOKIE_SECURE = IS_PRODUCTION
CSRF_COOKIE_SECURE = IS_PRODUCTION
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'

# HSTS включается отдельной переменной: выставить его случайно на домене
# без валидного TLS — значит сделать сайт недоступным на месяцы.
SECURE_SSL_REDIRECT = IS_PRODUCTION and os.getenv('DJANGO_SSL_REDIRECT', 'True').lower() == 'true'
SECURE_HSTS_SECONDS = int(os.getenv('DJANGO_HSTS_SECONDS', '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv('DJANGO_HSTS_SUBDOMAINS', 'False').lower() == 'true'
SECURE_HSTS_PRELOAD = os.getenv('DJANGO_HSTS_PRELOAD', 'False').lower() == 'true'

# ==============================================================================
# ДОВЕРЕННЫЕ ПРОКСИ (ТЗ п.60)
# ==============================================================================
# X-Forwarded-For подделывается тривиально. Доверять ему можно только если
# приложение физически недоступно напрямую и стоит за известным прокси.
TRUSTED_PROXY_COUNT = int(os.getenv('TRUSTED_PROXY_COUNT', '1'))
USE_X_FORWARDED_FOR = os.getenv('USE_X_FORWARDED_FOR', 'True').lower() == 'true'

# ==============================================================================
# REDIS И КЭШ (ТЗ п.20, 23, 95)
# ==============================================================================
REDIS_URL = os.getenv('REDIS_URL', '')
# Таймауты намеренно короткие: при недоступном Redis мы просто идём в PostgreSQL,
# и ждать его секундами недопустимо — один зависший кэш занял бы воркер (ТЗ п.95).
REDIS_CONNECT_TIMEOUT = float(os.getenv('REDIS_CONNECT_TIMEOUT', '0.2'))
REDIS_SOCKET_TIMEOUT = float(os.getenv('REDIS_SOCKET_TIMEOUT', '0.2'))

# Время жизни личности студента в кэше. Отзыв токена работает не по истечении
# TTL, а через явную инвалидацию (apps/students/signals.py); TTL — вторая
# линия защиты на случай, если инвалидация не дошла (ТЗ п.24).
AUTH_PRINCIPAL_CACHE_TTL = int(os.getenv('AUTH_PRINCIPAL_CACHE_TTL', '900'))

if REDIS_URL and not TESTING:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_URL,
            'OPTIONS': {
                'socket_connect_timeout': REDIS_CONNECT_TIMEOUT,
                'socket_timeout': REDIS_SOCKET_TIMEOUT,
            },
        }
    }
else:
    # Без REDIS_URL и под тестами — локальная память: прогон не должен
    # требовать живого Redis, иначе тесты станут флаки.
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'voteplatform-locmem',
        }
    }

# Токены, выпущенные до появления claim auth_version, должны продолжать
# работать, пока не истечёт их срок (7 дней). Выключать только после того,
# как migration period заведомо закончился.
STUDENT_TOKEN_ALLOW_MISSING_AUTH_VERSION = os.getenv(
    'STUDENT_TOKEN_ALLOW_MISSING_AUTH_VERSION', 'True'
).lower() == 'true'

# Celery & Redis
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://127.0.0.1:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
# Always eager fallback in case redis is not available in dev or PythonAnywhere free tier
CELERY_TASK_ALWAYS_EAGER = os.getenv(
    'CELERY_TASK_ALWAYS_EAGER', 'False' if IS_PRODUCTION else 'True'
).lower() == 'true'
CELERY_TASK_EAGER_PROPAGATES = True

# ==============================================================================
# ОЧЕРЕДИ CELERY (ТЗ п.40, 42)
# ==============================================================================
# Импорт списка студентов и выгрузка Excel — тяжёлые операции. В одной очереди
# с уведомлениями они заблокировали бы их на минуты, а запущенные на тех же
# воркерах, что обслуживают приложение, конкурировали бы с приёмом голосов.
#
# Воркеры разводятся по очередям при запуске:
#   celery -A config worker -Q default,notifications -c 4
#   celery -A config worker -Q imports,maintenance   -c 2
CELERY_TASK_DEFAULT_QUEUE = 'default'
CELERY_TASK_ROUTES = {
    'apps.students.tasks.process_student_upload_batch': {'queue': 'imports'},
    'apps.students.tasks.*': {'queue': 'imports'},
    'apps.notifications.*': {'queue': 'notifications'},
    'apps.core.tasks.*': {'queue': 'maintenance'},
}

# Задача забирается воркером по одной: длинный импорт не должен
# «застолбить» за собой пачку следующих задач.
CELERY_WORKER_PREFETCH_MULTIPLIER = int(os.getenv('CELERY_PREFETCH', '1'))

# Подтверждение после выполнения: если воркер умрёт посреди импорта,
# задача вернётся в очередь, а не потеряется.
CELERY_TASK_ACKS_LATE = True

# Жёсткие лимиты: зависшая задача не должна держать воркер вечно.
CELERY_TASK_SOFT_TIME_LIMIT = int(os.getenv('CELERY_SOFT_TIME_LIMIT', '600'))
CELERY_TASK_TIME_LIMIT = int(os.getenv('CELERY_TIME_LIMIT', '900'))

CELERY_BROKER_TRANSPORT_OPTIONS = {
    'socket_connect_timeout': REDIS_CONNECT_TIMEOUT,
    'socket_timeout': 5,
}

# Под тестами задачи всегда выполняются синхронно, независимо от окружения.
# Иначе при CELERY_TASK_ALWAYS_EAGER=False (docker, CI) тест отправляет задачу
# в РЕАЛЬНЫЙ брокер, и живой воркер ищет объект в реальной базе вместо тестовой:
# задача падает с 'not found', мусорит в логах и трогает чужие данные.
if TESTING:
    CELERY_TASK_ALWAYS_EAGER = True

# SMS / OTP Verification
# В production demo-режим SMS выключен по умолчанию: в нём код подтверждения
# одинаков для всех студентов, и войти можно под любым (ТЗ п.34).
MOCK_SMS = os.getenv('MOCK_SMS', 'False' if IS_PRODUCTION else 'True').lower() == 'true'
SMS_OTP_EXPIRY_MINUTES = 10
SMS_MAX_ATTEMPTS = 5
DEMO_OTP_CODE = '123456'

