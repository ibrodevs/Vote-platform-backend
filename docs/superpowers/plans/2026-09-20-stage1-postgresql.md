# Этап 1 — PostgreSQL как production-база + dev/test окружение: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сделать PostgreSQL единственной production-базой, перевести весь тестовый набор
на PostgreSQL и дать разработчику воспроизводимое окружение — чтобы этап 2 (advisory locks
и concurrency-тесты) вообще стал проверяемым.

**Architecture:** Конфигурация БД становится env-driven с явным маркером окружения
`DJANGO_ENV`. В production невозможны SQLite и MySQL — приложение падает на старте
(ТЗ п.12). Локально по умолчанию остаётся SQLite, но весь тестовый набор умеет и обязан
прогоняться на PostgreSQL. Зависимости фиксируются парой `requirements.in` → `requirements.txt`
(полный pin через `uv pip compile`), формат `pip install -r requirements.txt` сохраняется.
Docker Compose поднимает PostgreSQL + Redis + Django + Celery одной командой.

**Tech Stack:** Django 5.2.17, psycopg 3, PostgreSQL 16, Redis 7, uv 0.9.17,
Docker Compose, GitHub Actions.

**Spec:** `docs/superpowers/plans/2026-09-20-highload-roadmap.md` (этап 1);
ТЗ п.12, 13 (подготовка), 55, 56, 58, 68, 69, 107.

---

## Global Constraints

Полный список — в roadmap. Для этого этапа критично:

1. **Живой деплой не ломать.** Фронтенд обращается к `voteplatformbackend.pythonanywhere.com`,
   `.env.example` рекомендует там `DB_ENGINE=sqlite`. Значит: поведение по умолчанию
   (без новых переменных окружения) должно остаться **ровно прежним**. Строгий режим
   включается только явным `DJANGO_ENV=production`.
2. **Contract-тесты этапа 0 остаются зелёными** и на SQLite, и на PostgreSQL.
   139 тестов, 3 expected failures (D-01, D-02, D-03) — числа не должны измениться.
3. **Никаких исправлений дефектов D-01…D-07 на этом этапе.** Они чинятся на этапах 2, 3, 7, 8.
   Если тест на PostgreSQL падает из-за дефекта — дефект документируется, а не чинится.
4. **Никаких destructive-операций с данными.** Команда аудита только читает и сообщает.
   Ни одного автоматического удаления или слияния записей (ТЗ п.15, 54).
5. **Приложение остаётся работоспособным на SQLite для локальной разработки** (ТЗ п.12).

---

## Исходные условия (проверено 2026-09-20)

| Факт | Значение | Следствие для плана |
|---|---|---|
| PostgreSQL | 16.15 (Homebrew), запущен, роль `adminbaike` | тесты на PG прогоняются **реально** |
| Docker | 29.8.0 / Compose v5.5.1 — установлен позже, окружение **проверено запуском** | все 4 сервиса подняты, 163 теста зелёные в контейнере, Celery-воркер исполняет задачи |
| Redis | бинарника нет | на этапе 1 не нужен; объявляется в compose, используется с этапа 3 |
| uv | 0.9.17 | инструмент lock-стратегии |
| Python | 3.11.9, глобальный site-packages (venv в проекте нет) | `psycopg 3.3.4` уже доступен |
| Текущая прод-БД | SQLite на PythonAnywhere | см. Global Constraint 1 |
| `DB_ENGINE` | по умолчанию `sqlite`, есть ветки `mysql` и `postgresql` | ветки сохраняются, но запрещаются в production |

---

## File Structure

- Create `requirements.in` — прямые зависимости с минимальными ограничениями.
- Modify `requirements.txt` — полностью запиненный результат `uv pip compile`.
- Modify `config/settings.py` — `DJANGO_ENV`, env-driven DB, fail-fast, `CONN_MAX_AGE`.
- Create `config/settings_test.py` — тонкая обёртка, принудительно включающая PostgreSQL для тестов.
- Create `docker-compose.yml` — postgres + redis + web + celery для локальной разработки.
- Create `Dockerfile.dev` — образ для разработки (production-Dockerfile переделывается на этапе 7).
- Create `.dockerignore`.
- Modify `.gitignore` — добавить `db.sqlite3`, `.env`, media/staticfiles.
- Create `apps/core/management/commands/audit_db_data.py` — проверка данных перед миграцией.
- Create `docs/SQLITE_TO_POSTGRES.md` — процедура переноса и отката.
- Create `.github/workflows/ci.yml` — CI на PostgreSQL + Redis.
- Modify `docs/BASELINE.md` — обновить раздел baseline числами прогона на PostgreSQL.

---

### Task 1: Воспроизводимые зависимости + psycopg 3

**Files:**
- Create: `requirements.in`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `pip install -r requirements.txt` ставит идентичный, протестированный набор
  для любого клона репозитория на одном и том же коммите.

- [ ] **Step 1: Зафиксировать текущие прямые зависимости в `requirements.in`**

```
# Прямые зависимости. Запиненный результат — в requirements.txt.
# Пересборка: uv pip compile requirements.in -o requirements.txt
django>=5.2,<6.0
djangorestframework>=3.16
djangorestframework-simplejwt>=5.5
django-cors-headers>=4.9
django-filter>=25.1
psycopg[binary]>=3.2      # ТЗ п.12: официальный драйвер PostgreSQL
openpyxl>=3.1
celery>=5.5
redis>=5.0
pillow>=11.0
whitenoise>=6.6
python-dotenv>=1.0
PyJWT>=2.9
```

- [ ] **Step 2: Сгенерировать запиненный `requirements.txt`**

Run: `uv pip compile requirements.in -o requirements.txt`
Expected: файл с полным списком, включая транзитивные зависимости, каждая с `==`.

- [ ] **Step 3: Проверить, что набор устанавливается**

Run: `uv pip install --dry-run -r requirements.txt`
Expected: резолвер отрабатывает без конфликтов.

- [ ] **Step 4: Убедиться, что Django стартует с этим набором**

Run: `python3 manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 5: Commit**

```bash
git add requirements.in requirements.txt
git commit -m "build: pin dependencies with uv, add psycopg 3"
```

---

### Task 2: Env-driven конфигурация БД и fail-fast в production

**Files:**
- Modify: `config/settings.py` (блок `DATABASES`, строки ~70–105)
- Test: `tests/config/test_settings_database.py` (создать вместе с `tests/config/__init__.py`)

**Interfaces:**
- Produces:
  - `settings.DJANGO_ENV: str` — `"development"` (по умолчанию) | `"production"`
  - `settings.IS_PRODUCTION: bool`
  - `settings.DATABASES["default"]` — собирается из `DB_ENGINE`, `DB_NAME`, `DB_USER`,
    `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_CONN_MAX_AGE`
  - при `IS_PRODUCTION` и `DB_ENGINE != "postgresql"` — `ImproperlyConfigured` на импорте settings

- [ ] **Step 1: Написать падающий тест**

```python
# tests/config/test_settings_database.py
import importlib
import os
import unittest
from unittest import mock

from django.core.exceptions import ImproperlyConfigured


class DatabaseConfigTest(unittest.TestCase):
    def _reload_settings(self, **env):
        with mock.patch.dict(os.environ, env, clear=False):
            import config.settings as s
            return importlib.reload(s)

    def test_production_rejects_sqlite(self):
        with self.assertRaises(ImproperlyConfigured):
            self._reload_settings(DJANGO_ENV="production", DB_ENGINE="sqlite")
```

- [ ] **Step 2: Прогнать — убедиться, что падает**

Run: `python3 manage.py test tests.config.test_settings_database -v 2`
Expected: FAIL — `ImproperlyConfigured` не поднимается, сейчас SQLite разрешён везде.

- [ ] **Step 3: Реализовать в `config/settings.py`**

Заменить текущий блок `DB_ENGINE = os.getenv(...)` / `if/elif/else` на:

```python
from django.core.exceptions import ImproperlyConfigured

DJANGO_ENV = os.getenv('DJANGO_ENV', 'development').strip().lower()
IS_PRODUCTION = DJANGO_ENV == 'production'

# ТЗ п.12: production работает только на PostgreSQL. SQLite и MySQL допустимы
# исключительно для локальной разработки и должны падать на старте в production.
DB_ENGINE = os.getenv('DB_ENGINE', 'postgresql' if IS_PRODUCTION else 'sqlite').strip().lower()

if IS_PRODUCTION and DB_ENGINE != 'postgresql':
    raise ImproperlyConfigured(
        f"DJANGO_ENV=production требует DB_ENGINE=postgresql, получено {DB_ENGINE!r}. "
        "SQLite и MySQL не поддерживаются в production (ТЗ п.12)."
    )

DB_CONN_MAX_AGE = int(os.getenv('DB_CONN_MAX_AGE', '0'))
```

Ветки `postgresql` / `mysql` / `sqlite` сохраняются, у postgres добавляются
`CONN_MAX_AGE: DB_CONN_MAX_AGE` и `OPTIONS: {'connect_timeout': DB_CONNECT_TIMEOUT}`.
Значение по умолчанию `DB_CONN_MAX_AGE=0` выбрано осознанно: при PgBouncer в
transaction pooling persistent-соединения Django вредны (ТЗ п.13, настраивается на этапе 7).

- [ ] **Step 4: Прогнать — тест должен пройти**

Run: `python3 manage.py test tests.config.test_settings_database -v 2`
Expected: PASS.

- [ ] **Step 5: Дописать остальные кейсы и прогнать**

`test_production_rejects_mysql`, `test_production_accepts_postgresql`,
`test_development_defaults_to_sqlite`, `test_production_defaults_to_postgresql`,
`test_conn_max_age_from_env`.

Run: `python3 manage.py test tests.config -v 2`
Expected: все PASS.

- [ ] **Step 6: Проверить, что поведение по умолчанию не изменилось**

Run: `python3 manage.py test -v 1`
Expected: `Ran 14x tests ... OK (expected failures=3)` — прежние 139 плюс новые тесты настроек,
по-прежнему на SQLite, потому что `DJANGO_ENV` не задан.

- [ ] **Step 7: Commit**

```bash
git add config/settings.py tests/config/
git commit -m "feat: env-driven database config, fail fast on non-postgres in production"
```

---

### Task 3: Прогон всего набора на PostgreSQL

**Files:**
- Create: `config/settings_test.py`
- Modify: `docs/BASELINE.md` (раздел 1 — добавить колонку PostgreSQL)

**Interfaces:**
- Consumes: `config.settings` из Task 2.
- Produces: команда `DJANGO_SETTINGS_MODULE=config.settings_test python3 manage.py test`,
  выполняющая весь набор на PostgreSQL.

- [ ] **Step 1: Создать базу для тестов**

```bash
createdb vote_db_test_owner 2>/dev/null; psql -c "SELECT 1" >/dev/null && echo "postgres доступен"
```

- [ ] **Step 2: Написать `config/settings_test.py`**

```python
"""Настройки для прогона тестов на PostgreSQL (ТЗ п.107).

SQLite имеет другую модель конкуррентности, другие блокировки и не поддерживает
PostgreSQL advisory locks. Результат теста на SQLite не является доказательством
корректности в production.

Использование:
    DJANGO_SETTINGS_MODULE=config.settings_test python3 manage.py test
"""
import os

os.environ.setdefault('DB_ENGINE', 'postgresql')
os.environ.setdefault('DB_NAME', 'vote_db')
os.environ.setdefault('DB_USER', os.getenv('USER', 'postgres'))
os.environ.setdefault('DB_PASSWORD', '')
os.environ.setdefault('DB_HOST', os.getenv('DB_HOST', '127.0.0.1'))
os.environ.setdefault('DB_PORT', '5432')

from config.settings import *  # noqa: F401,F403,E402
```

- [ ] **Step 3: Прогнать весь набор на PostgreSQL**

Run: `DJANGO_SETTINGS_MODULE=config.settings_test python3 manage.py test -v 1`
Expected: столько же тестов, сколько на SQLite.

**Если есть падения** — разобрать каждое по существу. Ожидаемые классы расхождений:
- `unique_together` с `NULL` в `email`: PostgreSQL считает `NULL` различными, SQLite тоже,
  но поведение `iexact` и сортировки отличается;
- порядок строк без явного `ORDER BY` в PostgreSQL не гарантирован — тест, который на это
  опирался, чинится добавлением сортировки **в тест**, а не в приложение;
- строгая типизация PostgreSQL может отвергнуть данные, которые SQLite принимал.

Каждое падение классифицировать: «дефект теста» (чинить тест) или «дефект приложения»
(записать в `docs/BASELINE.md` как D-NN, не чинить — это этапы 2+).

- [ ] **Step 4: Убедиться, что SQLite-прогон не сломан**

Run: `python3 manage.py test -v 1`
Expected: то же число тестов, `OK (expected failures=3)`.

- [ ] **Step 5: Обновить `docs/BASELINE.md`**

Таблицу baseline привести к виду «Набор | Тестов | SQLite | PostgreSQL», указать команду
прогона на PG и зафиксировать версию PostgreSQL.

- [ ] **Step 6: Commit**

```bash
git add config/settings_test.py docs/BASELINE.md tests/
git commit -m "test: run full suite on PostgreSQL"
```

---

### Task 4: Docker Compose dev-окружение

**Files:**
- Create: `docker-compose.yml`
- Create: `Dockerfile.dev`
- Create: `.dockerignore`
- Create: `.env.docker.example`

**Interfaces:**
- Produces: `docker compose up` поднимает postgres + redis + web + celery.

**Статус проверки:** на момент написания плана Docker отсутствовал, и файлы были
помечены как непроверенные запуском. Docker установлен позже, окружение
**поднято и проверено фактически**: `docker compose up --build` → 4 сервиса healthy,
`migrate` применил 46 миграций, 163 теста зелёные внутри контейнера на PostgreSQL,
`/api/health/` отвечает с хоста, порты слушают только `127.0.0.1`, Celery-воркер
принимает и исполняет задачу импорта студентов (проверено логами воркера и данными в БД).

- [ ] **Step 1: Написать `Dockerfile.dev`**

Python 3.11-slim, `libpq5` в рантайме, установка из `requirements.txt`,
non-root пользователь, `CMD` — `manage.py runserver` (это **dev**-образ; production-образ
без `runserver` делается на этапе 7, ТЗ п.37, 57).

- [ ] **Step 2: Написать `docker-compose.yml`**

Сервисы:
- `postgres`: `postgres:16-alpine`, healthcheck `pg_isready`, том `pgdata`;
- `redis`: `redis:7-alpine`, healthcheck `redis-cli ping`;
- `web`: сборка из `Dockerfile.dev`, `depends_on` с `condition: service_healthy`,
  `DJANGO_ENV=development`, `DB_ENGINE=postgresql`, порт 8000;
- `celery`: тот же образ, команда `celery -A config worker -l info`,
  `CELERY_TASK_ALWAYS_EAGER=False`.

- [ ] **Step 3: Написать `.dockerignore`**

`.git`, `__pycache__`, `*.pyc`, `db.sqlite3`, `media`, `staticfiles`, `.env`, `docs`, `tests`.

- [ ] **Step 4: Написать `.env.docker.example`** — переменные для compose с комментариями.

- [ ] **Step 5: Проверить синтаксис, если Docker доступен**

Run: `docker compose config >/dev/null && echo VALID`
Expected: `VALID`. Если Docker недоступен — зафиксировать это в коммите и в README,
а не выдавать за проверенное.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml Dockerfile.dev .dockerignore .env.docker.example
git commit -m "build: add docker compose dev environment (postgres, redis, web, celery)"
```

---

### Task 5: Репозиторная гигиена

**Files:**
- Modify: `.gitignore`
- Untrack: `db.sqlite3`, 95 файлов `*.pyc`

**Interfaces:**
- Consumes: раздел 6 `docs/BASELINE.md` («Отложено в этап 1»).

- [ ] **Step 1: Дополнить `.gitignore`**

К существующим Python-артефактам добавить: `db.sqlite3`, `db.sqlite3-journal`, `.env`,
`/media/`, `/staticfiles/`, `.DS_Store`, `.idea/`, `.vscode/`.

- [ ] **Step 2: Снять с отслеживания артефакты, не удаляя файлы с диска**

```bash
git rm -r --cached -q $(git ls-files | grep '\.pyc$')
git rm --cached -q db.sqlite3
```

`--cached` критичен: файлы остаются на диске, у разработчиков ничего не пропадает
(ТЗ п.56 — «не удалять production data без explicit migration»).

- [ ] **Step 3: Убедиться, что рабочие файлы на месте**

Run: `ls -la db.sqlite3 && git ls-files | grep -c '\.pyc$'`
Expected: файл существует; счётчик `.pyc` равен `0`.

- [ ] **Step 4: Прогнать тесты — ничего не должно сломаться**

Run: `python3 manage.py test -v 1`
Expected: без изменений.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: stop tracking db.sqlite3 and bytecode artifacts"
```

---

### Task 6: Команда аудита данных перед миграцией

**Files:**
- Create: `apps/core/management/commands/audit_db_data.py`
- Test: `tests/contract/test_audit_command.py`

**Interfaces:**
- Produces: `python3 manage.py audit_db_data [--fail-on-issues]`
  Печатает отчёт и, с флагом, завершается ненулевым кодом при найденных проблемах.

**Что проверяет** (только чтение, ТЗ п.15, 54, 55):
1. дубликаты `Student.email` без учёта регистра (блокируют будущий CI-UNIQUE);
2. дубликаты `(university_id, student_id)`;
3. выборы с `starts_at >= ends_at` (блокируют будущий CHECK-констрейнт);
4. дубликаты `(election_id, student_id)` в `VoteRecord`;
5. `Ballot`, чей `candidate.election_id` не совпадает с `ballot.election_id`;
6. `Candidate`, чей `university_id` не совпадает с университетом выборов;
7. сводка row counts по всем ключевым таблицам — для сверки до и после переноса.

- [ ] **Step 1: Написать падающий тест**

```python
class AuditCommandTest(TestCase):
    def test_reports_duplicate_emails(self):
        uni = make_university()
        make_student(uni, student_id="S-1", email="Dup@Kstu.kg")
        make_student(uni, student_id="S-2", email="dup@kstu.kg")
        out = StringIO()
        call_command("audit_db_data", stdout=out)
        self.assertIn("duplicate_emails", out.getvalue())
        self.assertIn("dup@kstu.kg", out.getvalue())
```

- [ ] **Step 2: Прогнать — убедиться, что падает**

Run: `python3 manage.py test tests.contract.test_audit_command -v 2`
Expected: FAIL — `Unknown command: 'audit_db_data'`.

- [ ] **Step 3: Реализовать команду**

Каждая проверка — отдельный метод, возвращающий список находок. Вывод группируется по
ключам (`duplicate_emails`, `duplicate_student_ids`, `invalid_election_window`,
`duplicate_vote_records`, `orphan_ballots`, `candidate_university_mismatch`, `row_counts`).
**Ничего не изменять и не удалять.** При находках печатать инструкцию, что делать руками.

- [ ] **Step 4: Прогнать тесты**

Run: `python3 manage.py test tests.contract.test_audit_command -v 2`
Expected: PASS.

- [ ] **Step 5: Прогнать команду на реальной локальной базе**

Run: `python3 manage.py audit_db_data`
Expected: отчёт по фактическим данным `db.sqlite3`; результат приложить к
`docs/SQLITE_TO_POSTGRES.md` в Task 7.

- [ ] **Step 6: Commit**

```bash
git add apps/core/management/commands/audit_db_data.py tests/contract/test_audit_command.py
git commit -m "feat: add audit_db_data command for pre-migration data checks"
```

---

### Task 7: Документ переноса SQLite → PostgreSQL

**Files:**
- Create: `docs/SQLITE_TO_POSTGRES.md`

**Interfaces:**
- Consumes: `audit_db_data` (Task 6), `config/settings_test.py` (Task 3).

- [ ] **Step 1: Описать порядок** — строго по ТЗ п.54:
      аудит данных → backup → создание БД → schema migrations → перенос данных →
      проверка sequences → сверка row counts → сверка FK → сверка `VoteRecord`/`Ballot` →
      переключение → откат.

- [ ] **Step 2: Дать исполняемые команды для каждого шага**, а не описание намерений.
      Перенос — через `dumpdata`/`loaddata` с `--natural-foreign`, с явным указанием,
      почему `contenttypes` и `auth.permission` исключаются.

- [ ] **Step 3: Раздел сверки** — таблица «объект → количество до → количество после»
      для universities, faculties, students, elections, candidates, VoteRecord, Ballot,
      AdminUser, UploadBatch, NewsArticle, FAQItem, StaticPage.
      Явно: **числа обязаны совпасть**, расхождение — стоп-сигнал.

- [ ] **Step 4: Раздел отката** — как вернуться на SQLite, если после переключения
      обнаружена проблема; что при этом происходит с голосами, поступившими в PostgreSQL
      (они будут потеряны при откате — это указать прямо, а не умолчать).

- [ ] **Step 5: Раздел «Перед переключением»** — чек-лист: аудит без находок, backup снят
      и проверен восстановлением, `DJANGO_ENV=production` выставлен, `DB_ENGINE=postgresql`,
      прогон тестов на PostgreSQL зелёный.

- [ ] **Step 6: Commit**

```bash
git add docs/SQLITE_TO_POSTGRES.md
git commit -m "docs: add SQLite to PostgreSQL migration procedure"
```

---

### Task 8: CI на GitHub Actions

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `requirements.txt` (Task 1), `config/settings_test.py` (Task 3).

- [ ] **Step 1: Написать workflow**

Триггеры: `push` и `pull_request`. Один job `test` на `ubuntu-latest`.
Сервисы: `postgres:16` и `redis:7` с healthcheck'ами.
Шаги: checkout → setup-python 3.11 → установка `uv` → `uv pip install --system -r requirements.txt`
→ `manage.py check` → `manage.py makemigrations --check --dry-run` (ТЗ п.69)
→ `manage.py migrate` → `manage.py test` **на PostgreSQL**.

- [ ] **Step 2: Проверить YAML локально**

Run: `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('VALID')"`
Expected: `VALID`.

- [ ] **Step 3: Проверить, что `makemigrations --check` проходит на текущем коде**

Run: `python3 manage.py makemigrations --check --dry-run`
Expected: `No changes detected` — иначе в репозитории есть несозданные миграции,
и это надо зафиксировать до включения CI.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run checks, migrations and tests on PostgreSQL + Redis"
```

---

### Task 9: Обновление README и roadmap

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-09-20-highload-roadmap.md`

- [ ] **Step 1: Добавить в README** разделы: локальная разработка на SQLite,
      локальная разработка через Docker Compose, прогон тестов на SQLite,
      прогон тестов на PostgreSQL, ссылки на `docs/SQLITE_TO_POSTGRES.md`,
      `docs/API_CONTRACT.md`, `docs/BASELINE.md`.
      **Никаких заявлений о производительности** (ТЗ п.123).

- [ ] **Step 2: Отметить этап 1 выполненным в roadmap.**

- [ ] **Step 3: Финальный прогон обоих наборов**

Run: `python3 manage.py test -v 1`
Run: `DJANGO_SETTINGS_MODULE=config.settings_test python3 manage.py test -v 1`
Expected: одинаковое число тестов, `OK (expected failures=3)` в обоих случаях.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/
git commit -m "docs: document local, docker and postgres workflows"
```

---

## Definition of Done этапа 1

- [ ] `DJANGO_ENV=production` + любой не-PostgreSQL движок → приложение падает на старте.
- [ ] Поведение по умолчанию (без новых переменных) не изменилось — живой деплой цел.
- [ ] Весь тестовый набор проходит на PostgreSQL с тем же результатом, что на SQLite.
- [ ] `requirements.txt` полностью запинен; один коммит → один набор версий.
- [ ] `docker-compose.yml` поднимает postgres + redis + web + celery
      (статус проверки запуском указан честно).
- [ ] `db.sqlite3` и `*.pyc` больше не отслеживаются Git, файлы на диске сохранены.
- [ ] `python3 manage.py audit_db_data` отрабатывает и ничего не меняет.
- [ ] `docs/SQLITE_TO_POSTGRES.md` содержит команды, сверку и процедуру отката.
- [ ] CI гоняет check, `makemigrations --check`, migrate и тесты на PostgreSQL.
