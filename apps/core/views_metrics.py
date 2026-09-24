"""Экспорт метрик (ТЗ п.62).

ДОСТУП ОГРАНИЧЕН
----------------
`/metrics` показывает число голосов по выборам, объёмы трафика и внутренние
маршруты. Публичный доступ — это и разведка перед атакой, и утечка
предварительных итогов голосования до их объявления.

Защита двухслойная: токен здесь и ограничение по сети на Nginx. Токен нужен
потому, что сетевое ограничение легко забыть при переезде.

МНОГОПРОЦЕССНЫЙ РЕЖИМ — ОБЯЗАТЕЛЕН ПОД GUNICORN
------------------------------------------------
Gunicorn запускает несколько воркеров, и у каждого свой реестр в памяти.
Без multiprocess-режима скрейп попадает в ОДИН случайный воркер и показывает
его долю: при четырёх воркерах — примерно четверть реального трафика.
Ошибка тихая, цифры выглядят правдоподобно, и обнаруживается она только
при сверке с независимым источником.

Режим включается переменной PROMETHEUS_MULTIPROC_DIR; её выставляет
gunicorn.conf.py. В однопроцессном запуске (runserver, тесты) используется
обычный глобальный реестр.
"""
import os

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseNotFound
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest, multiprocess


def _collect() -> bytes:
    multiproc_dir = os.environ.get('PROMETHEUS_MULTIPROC_DIR')
    if multiproc_dir:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry)
    return generate_latest()


def metrics_view(request):
    if not settings.METRICS_ENABLED:
        return HttpResponseNotFound()

    expected = settings.METRICS_TOKEN
    if expected:
        provided = request.headers.get('Authorization', '')
        if provided != f'Bearer {expected}':
            return HttpResponseForbidden('Требуется токен доступа к метрикам')

    return HttpResponse(_collect(), content_type=CONTENT_TYPE_LATEST)
