"""Настройки для прогона тестов на PostgreSQL (ТЗ п.107).

SQLite имеет другую модель конкуррентности, другие блокировки, другие планы
запросов и не поддерживает PostgreSQL advisory locks. Зелёный прогон на SQLite
не является доказательством корректности в production — поэтому критические
integration- и concurrency-тесты обязаны идти на PostgreSQL.

Использование:
    DJANGO_SETTINGS_MODULE=config.settings_test python3 manage.py test

Переменные можно переопределить извне (в CI они приходят из окружения job'а).
"""
import os

os.environ.setdefault('DB_ENGINE', 'postgresql')
os.environ.setdefault('DB_NAME', 'vote_db')
os.environ.setdefault('DB_USER', os.getenv('USER', 'postgres'))
os.environ.setdefault('DB_PASSWORD', '')
os.environ.setdefault('DB_HOST', '127.0.0.1')
os.environ.setdefault('DB_PORT', '5432')

from config.settings import *  # noqa: F401,F403,E402
