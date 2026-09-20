# Vote Platform Backend

Backend платформы студенческих выборов: тайное голосование, управление
университетами, студентами, выборами и кандидатами.

Django 5.2 · DRF · PostgreSQL · Celery · Redis

---

## Главные инварианты

Эти правила важнее производительности и удобства. Изменение, нарушающее любое
из них, недопустимо, даже если ускоряет систему.

1. **Тайна голосования.** `VoteRecord` хранит только факт «студент X участвовал
   в выборах Y», `Ballot` — только «в выборах Y подан голос за кандидата Z».
   Прямой связи `Student → Candidate` не существует нигде: ни в схеме, ни в логах,
   ни в метриках, ни в трейсах.
2. **Атомарность голоса.** `VoteRecord` и `Ballot` создаются в одной транзакции.
   Успешный HTTP-ответ возвращается только после фактического COMMIT.
3. **Один голос на студента в выборах** — гарантируется констрейнтом базы данных,
   а не проверкой в Python.
4. **Голос не уходит в очередь.** Запись голоса синхронна. Celery — для импортов,
   экспортов, уведомлений и обслуживания.

Подробнее: [docs/API_CONTRACT.md](docs/API_CONTRACT.md).

---

## Локальная разработка

### Вариант 1: без Docker (быстро)

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

По умолчанию используется SQLite — этого достаточно для работы над обычными
endpoint'ами. Для всего, что связано с конкуррентностью и блокировками,
нужен PostgreSQL (см. ниже).

### Вариант 2: Docker Compose (ближе к production)

Поднимает PostgreSQL, Redis, Django и Celery worker:

```bash
cp .env.docker.example .env
docker compose up --build
docker compose exec web python manage.py migrate
```

Все порты публикуются только на `127.0.0.1`: в compose используются слабые
dev-пароли и Redis без аутентификации, поэтому сервисы не должны быть видны
из локальной сети.

---

## Конфигурация

Переменные окружения читаются из `.env` (см. `.env.example`).

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DJANGO_ENV` | `development` | `production` включает строгие проверки |
| `DB_ENGINE` | `sqlite` (в production — `postgresql`) | движок базы |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | — | подключение к БД |
| `DB_CONN_MAX_AGE` | `0` | persistent-соединения; `0` корректно для PgBouncer |
| `DB_CONNECT_TIMEOUT` | `10` | таймаут подключения к БД, секунды |
| `CELERY_BROKER_URL` | `redis://127.0.0.1:6379/0` | брокер Celery |
| `CELERY_TASK_ALWAYS_EAGER` | `True` | в production обязан быть `False` |

**В production поддерживается только PostgreSQL.** При `DJANGO_ENV=production`
и любом другом движке приложение не стартует — это намеренное поведение,
а не сбой.

---

## Тесты

```bash
# SQLite — быстрый прогон для локальной разработки
python manage.py test

# PostgreSQL — обязателен для integration- и concurrency-тестов
DJANGO_SETTINGS_MODULE=config.settings_test python manage.py test
```

Прогон на SQLite **не является доказательством корректности**: у него другая
модель конкуррентности, другие блокировки, другие планы запросов, и он не
поддерживает advisory locks PostgreSQL. CI гоняет тесты на PostgreSQL.

Текущее состояние набора и список известных дефектов —
[docs/BASELINE.md](docs/BASELINE.md).

### Структура тестов

| Путь | Назначение |
|---|---|
| `apps/*/tests.py` | тесты приложений, включая структурные проверки тайны голосования |
| `tests/contract/` | contract-тесты: фиксируют API-контракт для фронтенда |
| `tests/config/` | тесты конфигурации: production не стартует на SQLite/MySQL |

Contract-тесты закрепляют текущее поведение API. Если такой тест упал после
рефакторинга — сломан контракт для фронтенда, а не тест.

---

## Полезные команды

```bash
# Аудит данных перед миграцией или добавлением констрейнтов (read-only)
python manage.py audit_db_data
python manage.py audit_db_data --fail-on-issues

# Проверка конфигурации и миграций
python manage.py check
python manage.py makemigrations --check --dry-run
```

---

## Документация

| Документ | Содержание |
|---|---|
| [docs/API_CONTRACT.md](docs/API_CONTRACT.md) | все endpoints, схемы ответов, реестр `error.code` |
| [docs/FRONTEND_USAGE.md](docs/FRONTEND_USAGE.md) | какие вызовы делает фронтенд и что он ожидает |
| [docs/BASELINE.md](docs/BASELINE.md) | состояние тестов и реестр известных дефектов |
| [docs/SQLITE_TO_POSTGRES.md](docs/SQLITE_TO_POSTGRES.md) | процедура переноса базы и отката |
| [docs/superpowers/plans/](docs/superpowers/plans/) | план high-load оптимизации по этапам |

---

## Статус работ

Идёт поэтапная переработка под высокую нагрузку. План и порядок этапов —
[docs/superpowers/plans/2026-09-20-highload-roadmap.md](docs/superpowers/plans/2026-09-20-highload-roadmap.md).

Выполнено: этап 0 (фиксация API-контракта), этап 1 (PostgreSQL и окружение).

Характеристики производительности **не измерялись**. Никаких заявлений о
пропускной способности здесь не будет, пока не появятся результаты нагрузочных
тестов с зафиксированным окружением (этап 10).
