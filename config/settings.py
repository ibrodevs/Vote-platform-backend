import os
import sys
from pathlib import Path
from datetime import timedelta
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env if present
load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'vote-platform-secret-key-34e8bb-midnight-011c42')
DEBUG = os.getenv('DJANGO_DEBUG', 'True').lower() == 'true'

# Open to all hostnames by default for PythonAnywhere & multi-domain deployment
ALLOWED_HOSTS = ['*']

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
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
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
# DJANGO_ENV — явный маркер окружения. По умолчанию 'development', поэтому
# поведение существующих деплоев, которые эту переменную не задают, не меняется.
DJANGO_ENV = os.getenv('DJANGO_ENV', 'development').strip().lower()
IS_PRODUCTION = DJANGO_ENV == 'production'

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

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

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
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ),
    'EXCEPTION_HANDLER': 'apps.core.exceptions.custom_exception_handler',
    # D-03: по умолчанию DRF перехватывает ?format= для выбора рендерера, из-за
    # чего ?format=xlsx на /admin/students/template/ давал 404, не доходя до view.
    # Переименование освобождает ?format= для прикладного использования
    # и сохраняет возможность DRF под именем ?_format=.
    'URL_FORMAT_OVERRIDE': '_format',
}

# JWT Configuration
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': False,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# CORS - Open to all clients (Web, Mobile, Postman, Vercel, PythonAnywhere, Localhost)
CORS_ALLOW_ALL_ORIGINS = True
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
extra_csrf = os.getenv('DJANGO_CSRF_TRUSTED_ORIGINS', '')
if extra_csrf:
    CSRF_TRUSTED_ORIGINS.extend([origin.strip() for origin in extra_csrf.split(',') if origin.strip()])

X_FRAME_OPTIONS = 'ALLOWALL'

# ==============================================================================
# REDIS И КЭШ (ТЗ п.20, 23, 95)
# ==============================================================================
TESTING = 'test' in sys.argv

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
CELERY_TASK_ALWAYS_EAGER = os.getenv('CELERY_TASK_ALWAYS_EAGER', 'True').lower() == 'true'
CELERY_TASK_EAGER_PROPAGATES = True

# Под тестами задачи всегда выполняются синхронно, независимо от окружения.
# Иначе при CELERY_TASK_ALWAYS_EAGER=False (docker, CI) тест отправляет задачу
# в РЕАЛЬНЫЙ брокер, и живой воркер ищет объект в реальной базе вместо тестовой:
# задача падает с 'not found', мусорит в логах и трогает чужие данные.
if TESTING:
    CELERY_TASK_ALWAYS_EAGER = True

# SMS / OTP Verification
MOCK_SMS = os.getenv('MOCK_SMS', 'True').lower() == 'true'
SMS_OTP_EXPIRY_MINUTES = 10
SMS_MAX_ATTEMPTS = 5
DEMO_OTP_CODE = '123456'

