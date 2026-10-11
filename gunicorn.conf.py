"""Конфигурация Gunicorn (ТЗ п.37, 38, 44, 45).

ПОЧЕМУ НЕ runserver
-------------------
`manage.py runserver` однопоточен по сути, не переживает нагрузку,
перезапускает себя при изменении файлов и сам предупреждает, что для
production не предназначен.

ПОЧЕМУ WSGI, А НЕ ASGI
----------------------
Замена WSGI на ASGI сама по себе не делает синхронный Django ORM способным
на десятки тысяч динамических RPS. Узкие места измеряются бенчмарком:
CPU Python, round trips в Redis/PostgreSQL, сериализация и пулы соединений.

ВСЁ ИЗ ОКРУЖЕНИЯ
----------------
Ни одно значение не захардкожено под конкретную машину.
"""
import multiprocessing
import os


def _int_env(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _access_log_env():
    """`off`/`none` действительно выключают access log, а не создают файл off."""
    value = os.getenv('GUNICORN_ACCESS_LOG', '-').strip()
    if value.lower() in {'off', 'none', 'false', '0', ''}:
        return None
    return value


bind = os.getenv('GUNICORN_BIND', '0.0.0.0:8000')

# Формула (2 x CPU + 1) — отправная точка, не истина. Для CCX33 election-day
# compose задаёт измеренный baseline, а следующие значения сравниваются load test.
workers = _int_env('WEB_CONCURRENCY', multiprocessing.cpu_count() * 2 + 1)
threads = _int_env('GUNICORN_THREADS', 4)
worker_class = os.getenv('GUNICORN_WORKER_CLASS', 'gthread')

timeout = _int_env('GUNICORN_TIMEOUT', 30)
graceful_timeout = _int_env('GUNICORN_GRACEFUL_TIMEOUT', 30)

max_requests = _int_env('GUNICORN_MAX_REQUESTS', 2000)
max_requests_jitter = _int_env('GUNICORN_MAX_REQUESTS_JITTER', 200)
backlog = _int_env('GUNICORN_BACKLOG', 1024)
keepalive = _int_env('GUNICORN_KEEPALIVE', 5)

# На пике один access-log line на каждый запрос сам становится нагрузкой.
# Nginx сохраняет безопасный буферизированный edge-log; Gunicorn access log
# можно отключить через GUNICORN_ACCESS_LOG=off.
accesslog = _access_log_env()
errorlog = os.getenv('GUNICORN_ERROR_LOG', '-')
loglevel = os.getenv('GUNICORN_LOG_LEVEL', 'info')

# Формат не содержит заголовков и тела запроса: Authorization и выбор
# студента никогда не должны попадать в access log.
access_log_format = '%(h)s %(m)s %(U)s %(s)s %(b)s %(D)sus'

preload_app = os.getenv('GUNICORN_PRELOAD', 'True').lower() == 'true'
worker_tmp_dir = os.getenv('GUNICORN_WORKER_TMP_DIR', '/dev/shm')


# ==============================================================================
# МЕТРИКИ В МНОГОПРОЦЕССНОМ РЕЖИМЕ
# ==============================================================================
_METRICS_DIR = os.getenv('PROMETHEUS_MULTIPROC_DIR', '/dev/shm/prometheus')


def on_starting(server):
    """Чистит метрики предыдущего запуска."""
    import glob

    os.environ.setdefault('PROMETHEUS_MULTIPROC_DIR', _METRICS_DIR)
    os.makedirs(_METRICS_DIR, exist_ok=True)
    for stale in glob.glob(os.path.join(_METRICS_DIR, '*.db')):
        try:
            os.unlink(stale)
        except OSError:
            pass
    server.log.info("Запуск: воркеров=%s потоков=%s класс=%s", workers, threads, worker_class)


def child_exit(server, worker):
    """Убирает multiprocess-файлы завершившегося воркера."""
    try:
        from prometheus_client import multiprocess
        multiprocess.mark_process_dead(worker.pid)
    except Exception:
        pass


def worker_int(worker):
    worker.log.info("Воркер %s получил сигнал остановки", worker.pid)
