# Vote Platform Backend — High-load Roadmap (разбивка на этапы)

> Это **roadmap**, а не implementation plan. Он делит ТЗ (128 пунктов) на 13 этапов.
> Для каждого этапа перед его началом пишется отдельный детальный план в
> `docs/superpowers/plans/YYYY-MM-DD-stageN-<name>.md` по skill `superpowers:writing-plans`.

**Спека:** `ТЗ для backend оптимизации.docx` (High-load оптимизация Vote Platform Backend)
**Цель:** архитектура, горизонтально масштабируемая до 20–40k aggregate RPS, без изменения
бизнес-смысла, правил голосования и API-контракта для фронтенда.

---

## Global Constraints (действуют на каждом этапе)

Эти правила неявно входят в требования **любой** задачи любого этапа. Изменение,
нарушающее хотя бы одно, откатывается, даже если оно повышает RPS (ТЗ п.84, 127).

1. **Тайна голосования (п.3).** Никогда не создавать связей `Student→Candidate`, `Student→Ballot`,
   `VoteRecord→Candidate`, `VoteRecord→Ballot`. `Ballot` не содержит student/JWT/email/телефон/IP.
2. **Никакой корреляции через телеметрию (п.4).** Не логировать `student_id` и `candidate_id` вместе,
   не логировать тело `POST /vote`, `Authorization`, OTP, пароли. Ни в логах, ни в метриках,
   ни в трейсах, ни на reverse proxy.
3. **Атомарность голоса.** 1 `VoteRecord` + 1 `Ballot` в одной транзакции PostgreSQL.
   HTTP-успех — только после фактического COMMIT.
4. **Защита от двойного голоса — на уровне БД.** `UNIQUE (election_id, student_id)`,
   а не Python-проверка. Redis никогда не является source of truth для принятого голоса.
5. **Голос не уходит в очередь.** Core vote commit остаётся синхронным. Celery — только
   для imports/exports/notifications/maintenance/analytics.
6. **Обратная совместимость API.** Не переименовывать endpoints (`/api/v1/...`), поля JSON,
   `error.code`; не менять типы полей и успешные HTTP-статусы без причины.
7. **Stateless.** Никакого состояния в RAM процесса или локальной ФС. Shared state —
   PostgreSQL / Redis / object storage.
8. **Никаких неподтверждённых заявлений о производительности.** Любая цифра RPS — со ссылкой
   на benchmark с зафиксированным окружением (п.108).
9. **Приоритет:** CORRECTNESS → VOTE INTEGRITY → SECRET BALLOT → SECURITY → PERFORMANCE → OPERABILITY.

---

## Текущее состояние (аудит от 2026-09-20)

Подтверждённые дефекты, с которых стартуем:

| Область | Факт | Пункт ТЗ |
|---|---|---|
| `apps/voting/services.py` | `Election.objects.select_for_update()` на каждый голос — глобальная сериализация | 7 |
| `apps/voting/services.py` | `VoteRecord.objects.select_for_update().filter(...).exists()` — check-then-insert | 6 |
| `apps/voting/services.py` | `IntegrityError` ловится внутри `atomic()` без savepoint → broken transaction | 10 |
| `apps/voting/services.py` | два `logger.info` подряд: participation(student_id) + ballot(candidate_id) → коррелируемо по времени | 4 |
| `apps/voting/models.py` | `Index(fields=['election','student'])` дублирует `unique_together` | 14 |
| `apps/voting/models.py` | `VoteRecord.__str__` печатает `student.student_id`; `Ballot.__str__` — кандидата | 4 |
| `apps/core/authentication.py` | `Student.objects.select_related('university').get(...)` на **каждый** запрос | 18 |
| `apps/core/authentication.py` | нет проверки `is_active`, нет `auth_version`, нет механизма revoke | 19 |
| `apps/core/authentication.py` | `AuthenticationFailed(f"...{str(e)}")` — утечка internal exception | 65 |
| `config/settings.py` | hardcoded fallback `SECRET_KEY` (скомпрометирован — лежит в Git) | 32, 33 |
| `config/settings.py` | `ALLOWED_HOSTS = ['*']`, `CORS_ALLOW_ALL_ORIGINS = True`, `X_FRAME_OPTIONS='ALLOWALL'` | 32, 97 |
| `config/settings.py` | `DEBUG` по умолчанию `True`; `DB_ENGINE` по умолчанию `sqlite` | 12, 102 |
| `config/settings.py` | `CELERY_TASK_ALWAYS_EAGER` по умолчанию `True` | 40 |
| `config/settings.py` | `DEMO_OTP_CODE = '123456'` в коде, без гарантии отключения в prod | 34 |
| `Dockerfile` | `CMD python manage.py runserver`, root-пользователь, single-stage | 37, 57 |
| `requirements.txt` | только `>=` без lock; нет `psycopg`, нет gunicorn | 12, 68 |
| репозиторий | `db.sqlite3` закоммичен; нет `docs/`, `loadtests/`, `.github/`, docker-compose | 55, 56 |
| тесты | 12 тестов в 4 файлах, ни одного concurrency-теста, всё на SQLite | 70–76, 107 |

---

## Карта этапов

Порядок соответствует приоритету из п.118 ТЗ (contract tests → PostgreSQL → корректность
голосования → auth → N+1 → индексы → Redis → app server → static/media → observability →
load tests → профилирование → повторная оптимизация только по измерениям).
Ожидаемые новые файлы из п.122 распределены по этапам ниже.

```
Этап 0  Аудит + contract tests          ─┐ фундамент, блокирует всё
Этап 1  PostgreSQL + Docker dev/test    ─┘ без него нет advisory locks и честных тестов
          │
Этап 2  Голосование: корректность и конкуррентность   ← ядро ТЗ
          │
   ┌──────┼──────┬──────────┐
Этап 3  Этап 4  Этап 5     (могут идти параллельно после 2)
 auth    N+1    индексы
   └──────┼──────┘
Этап 6  Redis-кэширование
          │
Этап 7  Production runtime и деплой
Этап 8  Security hardening
Этап 9  Observability
          │
Этап 10 Нагрузочное тестирование        ← первая настоящая цифра
          │
Этап 11 Профилирование и 2-я итерация   ← только по измерениям
          │
Этап 12 Документация и финальный отчёт
```

---

## Этап 0 — Аудит и фиксация API-контракта ✅ ВЫПОЛНЕН (2026-09-20)

> План: `2026-09-20-stage0-api-contract.md`. Результат: 127 contract-тестов,
> `docs/API_CONTRACT.md`, `docs/FRONTEND_USAGE.md`, `docs/BASELINE.md` (дефекты D-01…D-07).

**Пункты ТЗ:** 2, 49, 50, 121
**Зачем первым:** без зафиксированного контракта невозможно доказать, что рефакторинг ничего
не сломал. ТЗ прямо запрещает начинать рефакторинг раньше (п.2).

**Работы:**
- Полная карта backend: все endpoints, request/response schemas, HTTP-статусы, `error.code`,
  permission classes, модели и связи, lifecycle выборов (create → start → vote → finish → results),
  OTP/auth flow, импорт студентов, медиа, административные операции.
- Разбор фронтенда `ibrodevs/Vote-platform-frontend`: таблица «Frontend call → метод → endpoint →
  request → response → auth». Расхождения и явные баги фронта — задокументировать, но **не**
  использовать как повод менять backend-контракт.
- Прогон существующих 12 тестов, фиксация baseline (что зелёное, что падает).
- Написать **contract/regression tests**: по тесту на каждый публичный endpoint, проверяющие
  форму ответа, коды, поля, `error.code`.

**Файлы:** `docs/API_CONTRACT.md`, `docs/FRONTEND_USAGE.md`, `tests/contract/`
**Definition of Done:** contract-тесты зелёные на текущем коде; любой последующий этап
обязан оставлять их зелёными.
**Риск:** фронтенд может использовать недокументированные поля — поэтому таблица строится
по реальному коду фронта, а не по документации.

---

## Этап 1 — PostgreSQL как production-база + Docker dev/test окружение ✅ ВЫПОЛНЕН (2026-09-20)

> План: `2026-09-20-stage1-postgresql.md`. Результат: psycopg 3 + pinned requirements,
> fail-fast на не-PostgreSQL в production, весь набор (149 тестов) зелёный на PostgreSQL 16.15,
> docker-compose, `audit_db_data`, `docs/SQLITE_TO_POSTGRES.md`, CI на GitHub Actions, README.

**Пункты ТЗ:** 12, 13 (подготовка), 55, 56, 58, 68, 107
**Зачем здесь:** PostgreSQL advisory locks и честные concurrency-тесты физически невозможны
на SQLite. Этап 2 без этого не проверяем.

**Работы:**
- `psycopg` 3, PostgreSQL как единственный production-движок; `DB_ENGINE` больше не
  «sqlite по умолчанию». MySQL-ветка — решить: удалить или пометить unsupported.
- Docker Compose dev-окружение: PostgreSQL + Redis + Django + Celery worker, подъём одной командой.
- Перевод тестового прогона на PostgreSQL; критические integration/concurrency тесты — только PG.
- Reproducible dependencies: lock-стратегия (`uv lock` / `pip-tools` / pinned), один commit →
  один и тот же протестированный dependency set.
- `.gitignore`: `db.sqlite3`, `.env`, logs, dev-медиа; удалить `db.sqlite3` из индекса Git
  (без удаления данных у разработчиков).
- `docs/SQLITE_TO_POSTGRES.md`: backup → создание БД → schema migration → перенос данных →
  проверка sequences / row counts / FK / количества `VoteRecord` и `Ballot` → switch → rollback.
- Команда проверки данных перед миграцией (duplicate emails и т.п. — **без** автоудаления).

**Файлы:** `requirements*.txt`/lock, `docker-compose.yml`, `config/settings.py`,
`.gitignore`, `docs/SQLITE_TO_POSTGRES.md`, management command для data audit
**Definition of Done:** `docker compose up` поднимает окружение; весь тестовый набор
(включая contract-тесты этапа 0) зелёный на PostgreSQL.

---

## Этап 2 — Голосование: корректность и конкуррентность ⭐ ядро ✅ ВЫПОЛНЕН (2026-09-20)

> План: `2026-09-20-stage2-voting-concurrency.md`. Результат: advisory-локи вместо
> глобального row lock, защита от дубля на UNIQUE-констрейнте, savepoints, 15 concurrency-
> и failure-тестов на PostgreSQL, 0 deadlock'ов, исправлены D-01, D-02, D-03, D-07, D-09.
> 223 теста, expected failures = 0.

**Пункты ТЗ:** 5, 6, 7, 8, 9, 10, 11, 16, 17, 52, 53, 66, 71, 72, 73, 74, 75, 76, 89, 106
**Зачем:** это главная ценность проекта. Всё остальное — производительность вокруг него.

**Работы:**
- `apps/core/db_locks.py`: reusable helpers `shared advisory transaction lock(election_id)` и
  `exclusive advisory transaction lock(election_id)`. Никаких Python/Redis-локов.
- Переписать `cast_secret_ballot` по алгоритму п.9: BEGIN → shared lock → проверки
  (ACTIVE, окно времени, университет из authenticated identity, кандидат принадлежит выборам) →
  INSERT `VoteRecord` → при UNIQUE VIOLATION rollback + `AlreadyVoted` → INSERT `Ballot` → COMMIT.
  Убрать `select_for_update()` на `Election` и на `VoteRecord` из hot path.
- Корректные savepoint-границы для `IntegrityError` (сейчас транзакция остаётся broken).
- Exclusive lock на `start / finish / cancel / delete election` и на критические изменения
  кандидатов активных выборов.
- DB-констрейнты: `UNIQUE (election_id, student_id)` как формальное ограничение,
  `starts_at < ends_at` (с предварительной проверкой существующих данных).
- Убрать коррелируемый audit-лог; оставить `vote_accepted election_id=<uuid>` без student/candidate.
- Исправить `__str__` моделей, чтобы не печатали student/candidate.
- Починить DRF lifecycle-баги (п.66): `perform_destroy`, возвращающий `Response`, который DRF
  игнорирует → удаление активных выборов должно реально отдавать 400/409, а не ложный 204.
- Комментарии-инварианты рядом с voting service (п.106).

**Тесты (обязательный объём этапа):**
- Unit: успешный голос, дубль, чужой университет, чужой кандидат, неактивные выборы,
  до `starts_at`, после `ends_at`, cancelled, finished, невалидный JWT, неактивный студент.
- Structural secret-ballot: автоматический assert, что у `Ballot` нет FK на Student/VoteRecord,
  у `VoteRecord` нет FK на Candidate/Ballot; что ни один admin API не отдаёт Student+Candidate вместе.
- Concurrency #1: один студент, 100–1000 параллельных запросов → ровно 1 VoteRecord и 1 Ballot.
- Concurrency #2: 1000+ уникальных студентов, 10 кандидатов → все проходят, без сериализации.
- Concurrency #3: параллельные `POST /vote` + `finish election` → после COMMIT finish
  ни один новый голос не принят, никаких partial records.
- Concurrency #4: один студент одновременно голосует за A и за B → 1 VoteRecord, 1 Ballot.
- Failure: Redis недоступен, обрыв PostgreSQL, исключение между VoteRecord и Ballot,
  убитый worker, дубликаты запросов, client timeout.

**Файлы:** `apps/core/db_locks.py`, `apps/voting/{services,models,views}.py`,
миграции, `apps/elections/views.py`, `tests/concurrency/`
**Definition of Done:** все 4 concurrency-теста зелёные на PostgreSQL; 0 unexpected deadlocks;
contract-тесты этапа 0 не изменились.

---

## Этап 3 — Аутентификация без DB-запроса на каждый request ✅ ВЫПОЛНЕН (2026-09-20)

> План: `2026-09-20-stage3-auth.md`. Результат: 0 SQL на аутентификацию при попадании
> в Redis, `auth_version` с мгновенным отзывом токенов, fallback проверен с реально
> остановленным Redis, исправлены D-04 и auth-часть D-06. 263 теста.

**Пункты ТЗ:** 18, 19, 20 (в части auth), 65, 67
**Зависит от:** этап 1 (Redis в окружении).

**Работы:**
- Быстрый auth path: локальная криптопроверка JWT → Redis principal cache → при miss PostgreSQL
  и запись в кэш. В Redis только `student_id`, `student_code`, `university_id`, `full_name`
  (если реально нужен), `is_active`, `auth_version` — не сериализовать Django-модель.
- `Student.auth_version` + claim в JWT; инкремент при деактивации/смене credentials/security reset
  с инвалидацией кэша → мгновенный revoke.
- Обратная совместимость: старые токены без `auth_version` обрабатываются в течение migration period.
- Redis-фейл не ломает авторизацию: короткие таймауты, fallback на PostgreSQL.
- Добавить отсутствующую проверку `is_active`.
- Безопасные ошибки: generic message + `request_id`, без `str(e)`; проверить timing/error behaviour
  login-эндпоинта.

**Файлы:** `apps/core/authentication.py`, `apps/core/cache_keys.py` (первая версия),
`apps/students/models.py` + миграция, `apps/core/exceptions.py`
**Definition of Done:** тест подтверждает **0 SQL-запросов** на authenticated request при Redis hit;
тест revoke: после инкремента `auth_version` старый токен немедленно невалиден; тест fallback при
выключенном Redis.

---

## Этап 4 — Устранение N+1 на hot endpoints ✅ ВЫПОЛНЕН (2026-09-20)

> План: `2026-09-20-stage4-n-plus-one.md`. Результат: все горячие endpoint'ы стали
> константными по числу SQL (available 62→3, students 44→3, results 30→5).
> Устранено расхождение знаменателя между turnout и results. Пагинация ограничена
> сверху. Измерения — в `docs/PERFORMANCE.md`.

**Пункты ТЗ:** 25, 26, 27, 28, 29, 51, 93
**Зависит от:** этап 0 (contract-тесты фиксируют, что ответы не изменились).

**Работы:**
- `StudentAvailableElectionsView`: `select_related` / `prefetch_related` / `annotate`,
  бюджет ~2–4 SQL независимо от количества выборов и кандидатов.
- Сериализаторы: заменить `obj.candidates.count()` на `annotate(Count(...))`, читаемый сериализатором.
- Results endpoint: один aggregate `GROUP BY candidate_id` вместо `1 + N` `.count()`.
- Turnout: без `COUNT(*)` по гигантской таблице на каждый запрос и **без** глобального
  counter row (см. Global Constraint / п.30).
- Сохранить правило скрытых результатов: при не-FINISHED и `results_visible_to_admin_before_finish == False`
  результаты не отдаются — оптимизация не должна случайно их раскрыть.
- Пагинация на всех потенциально больших admin-списках, разумный max page size.

**Файлы:** `apps/elections/{views,serializers}.py`, `apps/voting/views.py`, `apps/students/views.py`
**Definition of Done:** `assertNumQueries`-тесты на бюджет запросов; количество SQL не растёт
с числом объектов; contract-тесты зелёные.

---

## Этап 5 — Индексы и schema performance ✅ ВЫПОЛНЕН (2026-09-20)

> План: `2026-09-20-stage5-indexes.md`. Результат: три индекса по планам EXPLAIN
> на 200 000 студентов (login 29.6→0.04 мс, identify 8.7→0.04 мс, COUNT избирателей
> 12.9→0.88 мс), UNIQUE(LOWER(email)) с guard'ом в миграции, ограничение длины поиска,
> CREATE INDEX CONCURRENTLY. Trigram отвергнут по измеренному компромиссу. 311 тестов.

**Пункты ТЗ:** 14, 15, 54, 94
**Зависит от:** этап 4 (сначала исправляем запросы, потом индексируем то, что осталось).

**Работы:**
- `EXPLAIN (ANALYZE, BUFFERS)` по каждому hot query; индексы **только** там, где реально используются.
- Убрать дублирующий индекс `(election_id, student_id)` — UNIQUE уже его создаёт.
- `Ballot`: `WHERE election_id`, `WHERE election_id AND candidate_id`, `GROUP BY candidate_id`.
- `Election`: `university_id`, `status`, `starts_at`, `ends_at`. `Candidate`: `election_id`, `order`.
- `Student`: `university_id + student_id`, `email`, `is_active`; разобрать текущие `__iexact`
  (functional index по `LOWER(...)` или нормализованные колонки).
- DB-level case-insensitive UNIQUE на email (там, где email задан) + предварительная команда
  поиска дубликатов; при найденных дубликатах миграция **останавливается** с инструкцией,
  ничего не удаляя автоматически.
- Admin search по миллионам строк: bounded queries, при необходимости `pg_trgm`/GIN — но только после EXPLAIN.
- Safe migration strategy: `CREATE INDEX CONCURRENTLY` для больших таблиц, кастомный SQL — задокументировать.

**Файлы:** миграции всех приложений, `docs/PERFORMANCE.md` (раздел EXPLAIN), management command для email-аудита
**Definition of Done:** для каждого hot query в `docs/PERFORMANCE.md` есть query + индекс +
EXPLAIN ANALYZE + expected rows + время; ни одного лишнего индекса.

---

## Этап 6 — Redis-кэширование ✅ ВЫПОЛНЕН (2026-09-20)

> План: `2026-09-20-stage6-caching.md`. Результат: положительный кэш статуса
> (1→0 SQL), кэш явки и итогов завершённых выборов, явная инвалидация,
> заголовки Cache-Control, обязательный тест ТЗ п.114. Отрицательный статус
> и итоги незавершённых выборов не кэшируются — обоснование в PERFORMANCE.md.

**Пункты ТЗ:** 20, 21, 22, 23, 24, 30, 51 (cache keys), 96, 113, 114
**Зависит от:** этапы 3, 4, 5.

**Работы:**
- `apps/core/cache_keys.py`: неймспейс `voteplatform:v1:...`, helper, никаких ad-hoc имён по проекту.
- Vote status: positive cache `vote-status:{election_id}:{student_id}` через
  `transaction.on_commit(...)`; на miss — PostgreSQL. Negative cache — крайне осторожно,
  `has_voted=false` надолго не кэшируем.
- Election cache для часто читаемых данных; но статус ACTIVE/FINISHED при `POST /vote`
  проверяется консистентно в транзакции PostgreSQL, а не по stale Redis.
- Turnout: короткий кэш (задержка в несколько секунд допустима), без hot counter row.
  Финальный turnout после завершения — точный из PostgreSQL.
- Final results после FINISHED — долгий кэш, source of truth всегда PostgreSQL.
  Раздельные ключи для `turnout` и `results`.
- Явная инвалидация при admin update (Election / Candidate / University / deactivate Student);
  TTL — только дополнительная защита.
- Redis memory policy: для каждого namespace TTL, размер элемента, max key count, eviction.
- `Cache-Control` / `ETag` для public GET; `private/no-store` для vote status, profile, auth, admin.

**Файлы:** `apps/core/cache_keys.py`, `apps/core/cache.py`, views/serializers, settings
**Definition of Done:** обязательный тест п.114 — после полной очистки Redis все подтверждённые
голоса в PostgreSQL корректны; тест: при выключенном Redis голосование продолжает работать.

---

## Этап 7 — Production runtime и деплой ✅ ВЫПОЛНЕН (2026-09-20)

> План: `2026-09-20-stage7-production.md`. Результат: `production_check` (11 проверок),
> fail-fast на старте, security-заголовки, gunicorn.conf.py, health live/ready,
> production Dockerfile (собран и запущен, non-root, graceful shutdown проверен),
> docker-compose.prod.yml с PgBouncer, Nginx, .env.example, DEPLOY_PRODUCTION.md.
> Исправлены D-06 и D-10. 385 тестов.

**Пункты ТЗ:** 13 (PgBouncer), 31, 32, 33, 37, 38, 39, 40, 41, 42, 43, 44, 45, 57, 59, 60, 95, 101, 102, 103
**Зависит от:** этап 1.

**Работы:**
- Production settings: `DEBUG=False`, отсутствие fallback `SECRET_KEY` (startup fails),
  `ALLOWED_HOSTS` из env без `*`, CORS origins из env без `ALLOW_ALL`, CSRF / `SECURE_PROXY_SSL_HEADER` /
  `SECURE_SSL_REDIRECT` / cookie secure / HSTS / `X_FRAME_OPTIONS` — с учётом API за reverse proxy,
  не ломая фронтенд.
- Ротация секретов: текущий закоммиченный `SECRET_KEY` считается скомпрометированным.
  В Git — ни одного реального пароля; полный `.env.example` с группами
  (DJANGO / DATABASE / REDIS / CELERY / SECURITY / CORS / MEDIA / OBSERVABILITY / GUNICORN) и комментариями.
- Startup validation (п.102) + `python manage.py production_check` (п.103): fail fast при
  `DEBUG=True`, отсутствии секрета, выбранном SQLite, wildcard hosts, включённом demo OTP;
  проверка Redis, Celery config, storage, migration status.
- Gunicorn вместо `runserver`; `gunicorn.conf.py`; workers/threads/timeouts из env
  (`WEB_CONCURRENCY`, `GUNICORN_THREADS`, `GUNICORN_TIMEOUT`, `GUNICORN_GRACEFUL_TIMEOUT`,
  `GUNICORN_MAX_REQUESTS`, `GUNICORN_MAX_REQUESTS_JITTER`). WSGI vs ASGI — **по benchmark**, не по моде (п.38).
- PgBouncer в transaction pooling mode, `DB_CONN_MAX_AGE` и пр. из env, документация по pool sizing.
- Static/media из Django hot path убрать: object storage / S3-совместимое / CDN либо Nginx;
  URL для фронтенда остаются прежними.
- Celery: `CELERY_TASK_ALWAYS_EAGER=False` в prod, реальные workers, очереди
  `default / imports / notifications / maintenance`; retries только для идемпотентных задач.
- Импорт студентов (п.41): batch/bulk, chunked validation, тяжёлое — в worker,
  request только создаёт upload batch; метрики processed/success/errors/rows-per-sec/duration.
- Excel export (п.42): изолировать от voting workers, контракт сохранить.
- Health: сохранить текущий endpoint + добавить `/health/live` и `/health/ready`
  с жёсткими короткими таймаутами; Redis outage не обязан делать приложение unready при наличии DB fallback.
- Graceful shutdown, backpressure (лучше честный 503, чем 60-секундное ожидание; но никогда 503
  после успешного commit), короткие connect/socket timeouts для PostgreSQL/Redis/upstream.
- Dockerfile production: multi-stage, non-root, зависимости отдельно от исходников, корректный
  SIGTERM, collectstatic strategy, без `runserver`.
- Пример Nginx/HAProxy: keep-alive, upstream keepalive, timeouts, request size limits, real client IP,
  TLS termination, health checks; **не логировать** `Authorization` и тело vote-запроса.
- Trusted proxy chain: не доверять произвольному `X-Forwarded-For`; правила edge/CDN-кэширования
  (никогда не кэшировать profile / vote status / POST vote / admin / authenticated private).

**Файлы:** `config/settings/` (split), `apps/core/system_checks.py`, `apps/core/health.py`,
`gunicorn.conf.py`, `Dockerfile`, `docker-compose.prod.yml`, `deploy/nginx.conf`,
`.env.example`, `config/celery.py`, `apps/students/tasks.py`
**Definition of Done:** `production_check` падает на каждой небезопасной конфигурации;
контейнер стартует под non-root с Gunicorn; фронтенд продолжает работать.

---

## Этап 8 — Security hardening ✅ ВЫПОЛНЕН (2026-09-20)

> План: `2026-09-20-stage8-security.md`. Результат: D-05 закрыт (OTP хэшируется,
> не логируется), гонки OTP закрыты атомарным инкрементом и условным UPDATE,
> rate limiting с ключом по студенту для голосования — университет за одним
> NAT не блокируется, путь Django admin из окружения. 411 тестов.

**Пункты ТЗ:** 34, 35, 36, 67, 97, 98
**Зависит от:** этап 7 (settings-инфраструктура), этап 3 (auth).
**Важно:** rate limiting должен быть конфигурируемым, иначе он исказит нагрузочные тесты этапа 10.

**Работы:**
- OTP: хранить hash, а не plaintext; никогда не выводить в `__str__`, логи, ошибки, APM;
  demo OTP только при `DEBUG=True`/development, production startup это гарантирует.
- OTP race (п.35): `attempts` обновлять атомарно (`F`-expression / подходящая row lock);
  один OTP нельзя успешно использовать дважды при двух параллельных verify.
- Rate limiting с разными policies: строгий на login / register / OTP request / OTP verify /
  password endpoints. Для `/vote` лимит по authenticated student/token, **не** только по IP —
  5000 студентов одного университета за одним NAT IP не должны блокировать друг друга.
  Volumetric abuse — на уровне infrastructure/WAF.
- Пароли: безопасный Django hashing, никаких plaintext, хэш не попадает в логи.
- Security headers: `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`
  (убрать `ALLOWALL`), HSTS — не ломая фронтенд.
- Django admin: strong auth, rate limit, отдельный path, по возможности VPN/IP-ограничение,
  без слома административного workflow.

**Файлы:** `apps/students/{models,services,views}.py`, `apps/core/throttling.py`,
`config/settings/`, `config/urls.py`
**Definition of Done:** тест на параллельный OTP verify; тест, что NAT-сценарий не блокируется;
тест, что OTP не появляется ни в одном лог-выводе.

---

## Этап 9 — Observability ✅ ВЫПОЛНЕН (2026-09-20)

> План: `2026-09-20-stage9-observability.md`. Результат: JSON-логи с request_id
> и шаблоном маршрута, метрики Prometheus с проверенной multiprocess-агрегацией,
> запрет student×candidate в телеметрии проверяется обходом всего реестра.
> Документация — `docs/OBSERVABILITY.md`.

**Пункты ТЗ:** 61, 62, 63, 64
**Зависит от:** этап 7. **Нужен до этапа 10** — иначе нагрузочный тест нечем интерпретировать.

**Работы:**
- Structured JSON logging: `request_id`, method, route, status, `duration_ms`, instance —
  без sensitive data. Запрещено: `Authorization`, password, OTP, vote choice, полное тело vote-запроса.
- Метрики: HTTP RPS / latency p50 p95 p99 / status codes / active requests;
  vote attempts, successful votes, already_voted, vote failures (в секунду);
  DB query duration, pool usage, errors, lock wait time, deadlocks;
  Redis hit/miss, latency, errors; Celery queue depth, task duration, failures.
- Privacy метрик (п.63): никогда `student_id × candidate_id`; `candidate_id` как label —
  только если не создаёт privacy/cardinality проблем. `successful_votes_total{election_id=...}` допустимо.
- Tracing: sampling (при 40k RPS полный трейс невозможен), без Authorization / vote body / OTP / PII.

**Файлы:** `apps/core/logging.py`, `apps/core/middleware.py`, `apps/core/metrics.py`, settings
**Definition of Done:** тест-ассерт, что в логах и метриках отсутствуют запрещённые поля.

---

## Этап 10 — Нагрузочное тестирование ✅ ВЫПОЛНЕН (2026-09-21)

> План: `2026-09-21-stage10-load-testing.md`. Результат: стенд k6 с 4 профилями,
> spike и soak; реальные измерения на 8 ядрах: ~150 RPS чтение, ~81 durable
> запись/с, 0 deadlock'ов, целостность подтверждена после каждого прогона.
> Цифры 20–40k RPS НЕ измерялись — нужна настоящая инфраструктура.

**Пункты ТЗ:** 48, 77, 78, 79, 80, 81, 82, 85, 86, 87, 88, 90, 91, 92, 108, 109, 110, 111, 112, 115, 116
**Зависит от:** этапы 2–9.

**Работы:**
- `loadtests/` в репозитории, k6 (предпочтительно) или Locust.
- Management command — генератор synthetic данных: 100k и 1M студентов, несколько университетов,
  активные выборы, 10–20 кандидатов, токены. Никаких реальных персональных данных.
- Профиль A — public/cached read: ramp 1k → 5k → 10k → 20k → 40k RPS.
- Профиль B — authenticated read: подтвердить, что Redis auth cache действительно убирает
  PostgreSQL-запрос на каждом request.
- Профиль C — mixed realistic (55% available elections / 15% detail / 15% vote status /
  10% POST vote / 5% прочее), mix конфигурируемый.
- Профиль D — **отдельно** vote write: 40k HTTP RPS ≠ 40k durable vote writes/sec.
  Определить реальный max sustainable votes/sec при p95/p99, error rate, WAL, IOPS, CPU, lock waits.
- Soak 30–60 мин (memory/connection leak, latency drift, Celery backlog),
  spike 2k → 20k → 40k (без cascading failure), recovery (возврат к норме без ручного рестарта).
- Проверить, что генератор нагрузки сам не стал бутылочным горлышком; при необходимости распределённый.
- Network bandwidth: средний размер ответа, ingress/egress Gbit/s. gzip/Brotli — на edge, не в Django CPU.
- **Обязательная post-test валидация** (п.87): `COUNT(VoteRecord)` / `COUNT(Ballot)` соответствуют
  ожидаемым, нет дублей `(election, student)`, нет orphan ballot, нет partial vote.
  Нагрузка без валидации целостности не считается валидным benchmark.
- `python manage.py verify_election_integrity <election_id>` — проверка без сопоставления
  студента с кандидатом.
- Фиксация окружения benchmark (п.108): commit SHA, версии Django/Python/PostgreSQL/Redis,
  количество нод, CPU/RAM/сеть, настройки PgBouncer, размер датасета, длительность, request mix.
- Целевые SLO (п.85): cached read p95 < 200–250 мс, authenticated read p95 < 300 мс,
  vote p95 < 500 мс, unexpected 5xx < 0.1%; 0 unexpected deadlocks.

**Файлы:** `loadtests/k6/`, management commands (`generate_test_data`, `clear_test_data`,
`warm_cache`, `verify_election_integrity`), `docs/LOAD_TESTING.md`
**Definition of Done:** есть реальные результаты прогонов 20k и 40k сценариев + отчёт о
целостности БД после каждого.

---

## Этап 11 — Профилирование и вторая итерация оптимизации ✅ ВЫПОЛНЕН (2026-09-23)

> План: `2026-09-23-stage11-profiling.md`. Результат: `pg_stat_statements` + команда
> `pg_hot_statements`, бюджет 9 round trips на голос зафиксирован тестом, найдено и
> устранено открытие соединения с PostgreSQL на каждый запрос (p95 записи 364 → 13 мс),
> проверка `check_conn_max_age`, `docs/PROFILING.md`. Переписывание `cast_secret_ballot`
> отклонено: измерения показали, что обмен с базой больше не ограничитель.

**Пункты ТЗ:** 83, 84, 117, 119, 120, 127
**Зависит от:** этап 10. Ничего не делаем без измерений.

**Работы:**
- Найти оставшийся bottleneck: app CPU / PostgreSQL CPU / WAL / disk IOPS / network / Redis.
- Если ORM остаётся database-roundtrip bottleneck — допустима PostgreSQL-specific реализация
  `cast_secret_ballot` (CTE, database function, минимизация round trips), но: все существующие
  тесты зелёные, бизнес-правила в одном service boundary, никакого raw SQL по views,
  на любой raw SQL — integration-тесты.
- Не вводить sharding заранее; архитектура лишь должна позволять будущий shard по university/election.
- Не переписывать на Go/Rust и не дробить на микросервисы без доказательств.
- Цикл: измерить → найти → изменить → correctness → concurrency → load → снова измерить.
  Изменение, ломающее инвариант голосования, откатывается.

**Definition of Done:** повторный benchmark, зафиксированный оставшийся ограничитель.

---

## Этап 12 — Документация, HA и финальный отчёт

**Пункты ТЗ:** 46, 47, 90, 99, 100, 104, 105, 116, 123, 124, 125, 126
**Зависит от:** все предыдущие.

**Работы:**
- Read replica readiness (п.46): critical reads (POST vote, vote status сразу после голоса,
  admin start/finish) — только primary; replica — там, где допустима eventual consistency.
- Backup (п.47): daily backups, WAL archiving / PITR, **процедура восстановления**,
  верификация бэкапа, периодический restore test.
- HA (п.99): 2 LB, N app-нод, Redis HA, PostgreSQL primary + standby, object storage/CDN;
  падение одной ноды не роняет сервис; никаких sticky sessions.
- Code structure (п.104–105): тонкие views, бизнес-логика в services, concurrency в отдельных
  helpers, кэш в отдельном модуле; type hints для voting services, auth, cache helpers, locking.
- `docs/ARCHITECTURE.md`, `docs/DEPLOY_PRODUCTION.md` (PostgreSQL, PgBouncer, Redis, реплики Django,
  Celery, Nginx/LB, media storage, env vars, migrations, collectstatic, health checks,
  rolling deployment, rollback, backups, monitoring, load testing).
- `docs/PERFORMANCE.md`: таблица before/after (GET elections, GET detail, GET vote status,
  POST vote; DB queries/request, p50/p95/p99, max sustained RPS, error rate, CPU, DB CPU, Redis hit rate).
- README: local development, PostgreSQL, Redis, Celery, migrations, tests, concurrency tests,
  load tests, ссылки на production docs. Никаких «supports 40k RPS» без ссылки на benchmark.
- CI (п.69) — GitHub Actions: install deps, PostgreSQL + Redis, migrations, `django check`,
  тесты, concurrency-тесты разумного размера, lint, `makemigrations --check`.
  *(Поднимается сразу после этапа 1 и пополняется на каждом этапе; финализируется здесь.)*
- Финальный отчёт (п.125): что найдено, что изменено по файлам, миграции, подтверждение
  API-совместимости, подтверждение инвариантов тестами, число пройденных тестов, реальные
  результаты нагрузки, оставшийся bottleneck, рекомендация по количеству реплик.
- Пройтись по чек-листу Definition of Done (п.126) — 28 пунктов, все должны выполняться одновременно.

---

## Как работаем дальше

Роль (п.1): Senior Backend / Database / Performance / DevOps Engineer. Требование п.128 —
работать непосредственно с репозиторием, а не выдавать рекомендации, — выполняется через
эти этапы: каждый заканчивается рабочим, протестированным кодом в репозитории.

1. Перед каждым этапом — отдельный детальный план по `superpowers:writing-plans`
   в `docs/superpowers/plans/`, с bite-sized задачами и TDD-циклом.
2. Каждый этап — своя ветка, частые коммиты, зелёный CI на выходе.
3. Contract-тесты этапа 0 и concurrency-тесты этапа 2 прогоняются на **каждом** последующем этапе.
4. Этап считается закрытым только по своему Definition of Done, а не «код написан».
