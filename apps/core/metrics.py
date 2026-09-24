"""Метрики Prometheus (ТЗ п.62, 63).

ПРИВАТНОСТЬ ВАЖНЕЕ ПОДРОБНОСТИ
------------------------------
`candidate_id` меткой НЕ используется. Причины две, и обе достаточные:

1. Тайна голосования. Счётчик `votes{candidate_id=...}`, растущий в ту же
   секунду, что и запись об участии студента X, сужает круг до одного
   человека. Метрики хранятся дольше логов и доступны шире.
2. Кардинальность. Каждое сочетание значений меток — отдельный временной
   ряд. Сотни кандидатов × десятки выборов превращаются в тысячи рядов
   на один счётчик.

`election_id` меткой допустим (ТЗ п.63 это прямо разрешает): выборов
десятки, а знание их числа голосов тайну не нарушает — оно и так публично
после завершения.

`student_id` не используется нигде и ни при каких условиях.

КАРДИНАЛЬНОСТЬ МАРШРУТОВ
------------------------
Меткой идёт ШАБЛОН маршрута (`/api/v1/elections/<uuid:pk>/`), а не путь
с подставленным идентификатором. Иначе каждый просмотр новых выборов
создавал бы новый временной ряд, и Prometheus умер бы за сутки.
"""
import os

from prometheus_client import Counter, Gauge, Histogram

# ==============================================================================
# МНОГОПРОЦЕССНЫЙ РЕЖИМ
# ==============================================================================
# prometheus_client обращается к PROMETHEUS_MULTIPROC_DIR уже при создании
# первой метрики, то есть при импорте этого модуля. Если директории нет,
# процесс падает с FileNotFoundError ещё до старта приложения.
#
# Создавать её в хуке gunicorn недостаточно: под preload_app приложение
# импортируется раньше, а celery и management-команды хуков вообще не имеют.
# Поэтому директория создаётся здесь — единственном месте, которое
# гарантированно выполняется перед первой метрикой.
_MULTIPROC_DIR = os.environ.get('PROMETHEUS_MULTIPROC_DIR')
if _MULTIPROC_DIR:
    os.makedirs(_MULTIPROC_DIR, exist_ok=True)

# --- HTTP ---

http_requests_total = Counter(
    'vote_http_requests_total',
    'Количество HTTP-запросов',
    ['method', 'route', 'status'],
)

http_request_duration_seconds = Histogram(
    'vote_http_request_duration_seconds',
    'Длительность обработки HTTP-запроса',
    ['method', 'route'],
    # Границы подобраны под целевые SLO из ТЗ п.85:
    # cached read p95 < 250 мс, authenticated read p95 < 300 мс, vote p95 < 500 мс
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

http_requests_in_progress = Gauge(
    'vote_http_requests_in_progress',
    'Запросы в обработке прямо сейчас',
)

# --- Голосование (ТЗ п.62) ---
# Метки: только election_id и результат. Ни студента, ни кандидата.

vote_attempts_total = Counter(
    'vote_attempts_total',
    'Попытки голосования',
    ['election_id', 'outcome'],
)

vote_duration_seconds = Histogram(
    'vote_duration_seconds',
    'Длительность транзакции голосования',
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)

# --- База данных ---

db_errors_total = Counter(
    'vote_db_errors_total',
    'Ошибки базы данных',
    ['kind'],
)

db_deadlocks_total = Gauge(
    'vote_db_deadlocks',
    'Взаимоблокировки по данным pg_stat_database',
)

# --- Кэш ---

cache_operations_total = Counter(
    'vote_cache_operations_total',
    'Операции с кэшем',
    ['operation', 'result'],
)

# --- Celery ---

celery_tasks_total = Counter(
    'vote_celery_tasks_total',
    'Выполненные задачи Celery',
    ['task', 'result'],
)


def record_vote_attempt(election_id, outcome: str) -> None:
    """Фиксирует попытку голосования.

    `outcome` — одно из: accepted, already_voted, election_not_active,
    ineligible_student, invalid_candidate, error.

    Кандидат сюда не передаётся и передаваться не должен.
    """
    vote_attempts_total.labels(election_id=str(election_id), outcome=outcome).inc()
