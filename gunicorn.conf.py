"""Конфигурация Gunicorn (ТЗ п.37, 38, 44, 45).

ПОЧЕМУ НЕ runserver
-------------------
`manage.py runserver` однопоточен по сути, не переживает нагрузку,
перезапускает себя при изменении файлов и сам предупреждает, что для
production не предназначен.

ПОЧЕМУ WSGI, А НЕ ASGI
----------------------
ТЗ п.38 прямо предупреждает: замена WSGI на ASGI сама по себе не делает
Django ORM способным на 40k RPS. Узкие места — round trips в базу,
блокировки, сериализация, пулы соединений; всё это одинаково в обоих
режимах, потому что ORM здесь синхронный. Выбор модели воркеров —
предмет бенчмарка этапа 10, а не вкуса. До появления измерений
используется WSGI с потоками: он предсказуем и не требует переписывания
кода под async.

ВСЁ ИЗ ОКРУЖЕНИЯ
----------------
Ни одно значение не захардкожено под конкретную машину (ТЗ п.37).
"""
import multiprocessing
import os


def _int_env(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


bind = os.getenv('GUNICORN_BIND', '0.0.0.0:8000')

# Формула (2 x CPU + 1) — отправная точка, а не истина: правильное число
# определяется бенчмарком под реальной нагрузкой (ТЗ п.38).
workers = _int_env('WEB_CONCURRENCY', multiprocessing.cpu_count() * 2 + 1)

# Потоки имеют смысл потому, что воркер большую часть времени ждёт
# PostgreSQL и Redis, а не считает.
threads = _int_env('GUNICORN_THREADS', 4)
worker_class = os.getenv('GUNICORN_WORKER_CLASS', 'gthread')

# Таймаут запроса. Держать соединение десятками секунд хуже, чем честно
# ответить ошибкой: зависшие запросы съедают воркеров и роняют всё (ТЗ п.45).
timeout = _int_env('GUNICORN_TIMEOUT', 30)

# Сколько ждать завершения текущих запросов при остановке.
# Транзакция голосования не должна обрываться посреди деплоя (ТЗ п.44).
graceful_timeout = _int_env('GUNICORN_GRACEFUL_TIMEOUT', 30)

# Периодический перезапуск воркеров лечит утечки памяти, которые иначе
# копились бы неделями. Jitter разводит перезапуски во времени, иначе все
# воркеры уйдут на перезапуск одновременно и сервис просядет.
max_requests = _int_env('GUNICORN_MAX_REQUESTS', 2000)
max_requests_jitter = _int_env('GUNICORN_MAX_REQUESTS_JITTER', 200)

# Очередь ожидающих соединений. Слишком большая очередь маскирует перегрузку:
# клиент ждёт вместо того, чтобы получить отказ и повторить (ТЗ п.45).
backlog = _int_env('GUNICORN_BACKLOG', 1024)

keepalive = _int_env('GUNICORN_KEEPALIVE', 5)

accesslog = os.getenv('GUNICORN_ACCESS_LOG', '-')
errorlog = os.getenv('GUNICORN_ERROR_LOG', '-')
loglevel = os.getenv('GUNICORN_LOG_LEVEL', 'info')

# Формат лога намеренно НЕ содержит заголовков и тела запроса:
# в Authorization лежит токен, а в теле POST /vote — выбор студента
# (ТЗ п.4, 59, 61).
access_log_format = '%(h)s %(m)s %(U)s %(s)s %(b)s %(D)sus'

# Предзагрузка кода экономит память за счёт copy-on-write, но ломает
# горячую перезагрузку. Для production это верный размен.
preload_app = os.getenv('GUNICORN_PRELOAD', 'True').lower() == 'true'

# Временные файлы Gunicorn на диске контейнера могут упереться в медленный
# слой overlayfs; /dev/shm — память.
worker_tmp_dir = os.getenv('GUNICORN_WORKER_TMP_DIR', '/dev/shm')


# ==============================================================================
# МЕТРИКИ В МНОГОПРОЦЕССНОМ РЕЖИМЕ (ТЗ п.62)
# ==============================================================================
# У каждого воркера свой реестр в памяти. Без общей директории скрейп
# попадает в один случайный воркер и показывает его долю — при четырёх
# воркерах примерно четверть реального трафика. Ошибка тихая: цифры
# выглядят правдоподобно.
_METRICS_DIR = os.getenv('PROMETHEUS_MULTIPROC_DIR', '/dev/shm/prometheus')


def on_starting(server):
    """Чистит метрики предыдущего запуска.

    Саму директорию создаёт apps/core/metrics.py при импорте: под
    preload_app приложение импортируется раньше этого хука, и полагаться
    на него нельзя.

    Файлы от прошлого запуска содержат счётчики умерших процессов
    и дали бы двойной учёт после рестарта.
    """
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
    """Убирает файлы метрик завершившегося воркера.

    Без этого при max_requests счётчики перезапущенных воркеров копились бы
    вечно, и /metrics рос бы неограниченно.
    """
    try:
        from prometheus_client import multiprocess
        multiprocess.mark_process_dead(worker.pid)
    except Exception:  # метрики не должны мешать остановке воркера
        pass


def worker_int(worker):
    """Логирует получение SIGINT воркером — помогает разбирать деплои."""
    worker.log.info("Воркер %s получил сигнал остановки", worker.pid)
