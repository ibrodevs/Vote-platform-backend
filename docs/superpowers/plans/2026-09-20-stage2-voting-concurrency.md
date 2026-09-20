# Этап 2 — Голосование: корректность и конкуррентность: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Убрать глобальную сериализацию голосов через одну строку `Election`, не создав
при этом гонки между голосованием и завершением выборов, и доказать это concurrency-тестами
на PostgreSQL.

**Architecture:** Вместо `SELECT ... FOR UPDATE` на строке выборов вводятся PostgreSQL
advisory transaction locks: голоса берут **shared** блокировку по `election_id` и потому
идут параллельно, а операции смены состояния (start/finish/cancel/delete) берут **exclusive**
и потому ждут завершения уже начатых голосов и не пускают новые в критическую секцию.
Защита от двойного голоса переносится с Python-проверки на уже существующий
`UNIQUE (election_id, student_id)`: `INSERT` выполняется внутри savepoint, `IntegrityError`
превращается в `AlreadyVoted`, транзакция при этом не остаётся в broken state.

**Tech Stack:** Django 5.2.17, PostgreSQL 16 (`pg_advisory_xact_lock`,
`pg_advisory_xact_lock_shared`), psycopg 3.

**Spec:** roadmap, этап 2; ТЗ п.5, 6, 7, 8, 9, 10, 11, 16, 17, 52, 53, 66, 71, 72–76, 89, 106.

---

## Global Constraints

Полный список — в roadmap. Критично для этого этапа:

1. **Тайна голосования нерушима.** Ни одной новой связи `Student ↔ Candidate/Ballot`,
   ни в схеме, ни в логах, ни в исключениях, ни в тестовых утилитах.
2. **Атомарность.** Успешный голос = ровно 1 `VoteRecord` + 1 `Ballot` в одной транзакции.
   Отклонённый голос не оставляет ни одной строки.
3. **Источник истины — PostgreSQL.** Никаких Python- или Redis-локов вместо
   database transaction lock (ТЗ п.8).
4. **Ядро голосования остаётся синхронным** — никакой очереди (ТЗ п.11).
5. **Contract-тесты этапа 0 остаются зелёными.** Любое изменение кода ошибки или статуса —
   только осознанно, с обновлением `docs/API_CONTRACT.md` и явной записью в отчёт.
6. **Короткие транзакции** (ТЗ п.89): внутри транзакции голосования нет HTTP-запросов,
   Redis, файловых операций, тяжёлой сериализации.
7. **SQLite остаётся рабочим для локальной разработки.** Advisory locks там отсутствуют —
   helper обязан деградировать в no-op, а concurrency-тесты пропускаться с явной причиной.

---

## Исходные условия (проверено 2026-09-20)

| Факт | Значение | Следствие |
|---|---|---|
| `UNIQUE (election_id, student_id)` | **уже есть** в БД (`unique_together`) | новый констрейнт не нужен; нужно начать на него опираться |
| `voting_vote_electio_fe882d_idx` | дублирует UNIQUE-индекс | удалить (ТЗ п.14) |
| `apps/voting/services.py:44` | `Election.objects.select_for_update()` | убрать из hot path |
| `apps/voting/services.py:67` | `VoteRecord...select_for_update().exists()` | заменить на INSERT + savepoint |
| `apps/voting/services.py:80` | `IntegrityError` внутри `atomic()` без savepoint | транзакция остаётся broken |
| `apps/voting/services.py:96-97` | два коррелируемых `logger.info` | заменить на `vote_accepted election_id=...` |
| Дефекты к исправлению здесь | D-01, D-02, D-03, D-07 | по реестру `docs/BASELINE.md` |
| Тестовый набор | 163, OK, 3 expected failures | после этапа: expected failures = 0 |

---

## File Structure

- Create `apps/core/db_locks.py` — advisory-локи, единственное место, знающее про `pg_*`.
- Create `tests/contract/test_db_locks.py` — поведение хелперов и деградация на SQLite.
- Modify `apps/voting/services.py` — новый `cast_secret_ballot`, безопасное логирование.
- Modify `apps/voting/models.py` — `UniqueConstraint` с именем, снятие лишнего индекса,
  безопасные `__str__`, комментарии-инварианты (ТЗ п.106).
- Create `apps/voting/migrations/0002_*.py`.
- Modify `apps/elections/models.py` — `CheckConstraint(starts_at < ends_at)`.
- Create `apps/elections/migrations/0003_*.py`.
- Create `apps/elections/services.py` — start/finish/cancel/delete под exclusive-локом.
- Modify `apps/elections/views.py` — views становятся тонкими, чинится D-02.
- Create `tests/concurrency/` — четыре обязательных теста ТЗ п.72–75 плюс failure-тесты.
- Modify `apps/students/views.py` — D-01.
- Modify `config/settings.py` — D-03 (`URL_FORMAT_OVERRIDE`).
- Modify `docs/API_CONTRACT.md`, `docs/BASELINE.md`.

---

### Task 1: Advisory locks

**Files:**
- Create: `apps/core/db_locks.py`
- Test: `tests/contract/test_db_locks.py`

**Interfaces:**
- Produces:
  - `advisory_lock_key(namespace: str, value) -> int` — стабильный знаковый int64
  - `election_vote_lock(election_id) -> None` — shared, для голосов
  - `election_state_lock(election_id) -> None` — exclusive, для смены состояния
  - `supports_advisory_locks() -> bool`

**Проектные решения:**
- Ключ — 64-битный: `blake2b(namespace + uuid_bytes, digest_size=8)`, знаковый.
  `hash()` не годится — он рандомизирован между процессами.
- Обе функции требуют открытой транзакции. Вызов вне `atomic()` — ошибка
  программиста: `pg_advisory_xact_lock` вне транзакции освободится немедленно
  и создаст ложное чувство защиты. Поэтому `RuntimeError`.
- На SQLite — no-op с предупреждением в лог. Иначе локальная разработка встанет.

- [ ] **Step 1: Написать падающий тест**

```python
def test_key_is_stable_across_calls(self):
    u = uuid.uuid4()
    self.assertEqual(advisory_lock_key("election", u), advisory_lock_key("election", u))

def test_key_fits_signed_bigint(self):
    k = advisory_lock_key("election", uuid.uuid4())
    self.assertGreaterEqual(k, -(2 ** 63))
    self.assertLess(k, 2 ** 63)
```

- [ ] **Step 2: Прогнать — убедиться, что падает**

Run: `python3 manage.py test tests.contract.test_db_locks -v 2`
Expected: `ModuleNotFoundError: apps.core.db_locks`.

- [ ] **Step 3: Реализовать `apps/core/db_locks.py`**

- [ ] **Step 4: Дописать тесты и прогнать на PostgreSQL**

`test_vote_lock_requires_transaction`, `test_state_lock_requires_transaction`,
`test_two_shared_locks_coexist`, `test_exclusive_blocks_shared`,
`test_different_elections_do_not_block`, `test_noop_on_sqlite`.

Run: `DJANGO_SETTINGS_MODULE=config.settings_test python3 manage.py test tests.contract.test_db_locks -v 2`
Expected: все PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/core/db_locks.py tests/contract/test_db_locks.py
git commit -m "feat: add PostgreSQL advisory transaction lock helpers"
```

---

### Task 2: Констрейнты и индексы

**Files:**
- Modify: `apps/voting/models.py`
- Modify: `apps/elections/models.py`
- Create: `apps/voting/migrations/0002_*.py`, `apps/elections/migrations/0003_*.py`
- Test: `tests/contract/test_db_constraints.py`

**Что делаем:**
1. `unique_together` → именованный `UniqueConstraint("election", "student",
   name="uniq_voterecord_election_student")`. Имя нужно, чтобы отличать причину
   `IntegrityError` от других нарушений.
2. Удалить `Index(fields=['election','student'])` — его полностью покрывает UNIQUE (ТЗ п.14).
3. `Election`: `CheckConstraint(starts_at__lt=ends_at, name="election_starts_before_ends")` (ТЗ п.16).

- [ ] **Step 1: Проверить данные перед констрейнтом**

Run: `docker compose exec -T web python manage.py audit_db_data --fail-on-issues`
Expected: без находок. При находках — **остановиться**, миграция их сломает.

- [ ] **Step 2: Написать падающий тест**

```python
def test_check_constraint_rejects_inverted_window(self):
    uni = make_university()
    now = timezone.now()
    with self.assertRaises(IntegrityError):
        Election.objects.create(university=uni, title="X", title_ky="X",
                                starts_at=now + timedelta(hours=1), ends_at=now)
```

- [ ] **Step 3: Прогнать — падает** (констрейнта нет, объект создаётся).

- [ ] **Step 4: Изменить модели и сгенерировать миграции**

Run: `python3 manage.py makemigrations voting elections`

- [ ] **Step 5: Применить и прогнать тесты на PostgreSQL**

Run: `docker compose exec -T web python manage.py migrate`
Run: `docker compose exec -T web python manage.py test tests.contract.test_db_constraints -v 2`

- [ ] **Step 6: Убедиться, что лишний индекс исчез**

```bash
docker compose exec -T web python manage.py shell -c "
from django.db import connection
with connection.cursor() as c:
    c.execute(\"SELECT indexname FROM pg_indexes WHERE tablename='voting_voterecord'\")
    for r in c.fetchall(): print(r[0])"
```
Expected: `voting_vote_electio_fe882d_idx` отсутствует, UNIQUE на месте.

- [ ] **Step 7: Commit**

---

### Task 3: Переписать `cast_secret_ballot`

**Files:**
- Modify: `apps/voting/services.py`
- Modify: `apps/voting/models.py` (`__str__`, комментарии-инварианты)

**Interfaces:**
- Consumes: `election_vote_lock` из Task 1, именованный UNIQUE из Task 2.
- Produces: та же сигнатура `cast_secret_ballot(student, election_id, candidate_id) -> bool`
  и те же коды ошибок — контракт не меняется.

**Алгоритм (ТЗ п.9):**

```
BEGIN
  shared advisory lock(election_id)
  election = SELECT ... WHERE id = %s              # без FOR UPDATE
  проверить status == ACTIVE
  проверить starts_at <= now <= ends_at
  проверить election.university_id == student.university_id
  candidate = SELECT ... WHERE id=%s AND election_id=%s
  SAVEPOINT
    INSERT VoteRecord(election, student)
  ON UNIQUE VIOLATION -> ROLLBACK TO SAVEPOINT -> raise AlreadyVoted
  INSERT Ballot(election, candidate)
COMMIT
```

- [ ] **Step 1: Убедиться, что текущие тесты голосования зелёные** (точка отсчёта)

Run: `docker compose exec -T web python manage.py test tests.contract.test_voting_contract apps.voting -v 1`

- [ ] **Step 2: Переписать сервис**

Ключевые моменты:
- `select_for_update()` удалён в обоих местах;
- `IntegrityError` ловится внутри вложенного `transaction.atomic()` (savepoint);
- `university_id` берётся **только** из аутентифицированного `student` (ТЗ п.53);
- логирование выносится за пределы транзакции и не содержит пары student+candidate.

- [ ] **Step 3: Заменить логирование**

Было — два коррелируемых сообщения. Стало:

```python
logger.info("vote_accepted election_id=%s", election_id)
```

Ни `student_id`, ни `candidate_id` (ТЗ п.4).

- [ ] **Step 4: Починить `__str__` моделей**

`VoteRecord.__str__` → `f"Участие в выборах {self.election_id}"`,
`Ballot.__str__` → `f"Бюллетень в выборах {self.election_id}"`.
Ни студента, ни кандидата: `__str__` попадает в админку, логи и трейсбеки.

- [ ] **Step 5: Добавить комментарии-инварианты (ТЗ п.106)**

Над `cast_secret_ballot` и над моделями:

```
DO NOT add student relation to Ballot
DO NOT add candidate relation to VoteRecord
DO NOT replace database uniqueness with cache
DO NOT move core vote commit to asynchronous queue
DO NOT reintroduce SELECT FOR UPDATE on Election in the vote path
```

- [ ] **Step 6: Прогнать оба набора**

Run: `docker compose exec -T web python manage.py test -v 1`
Expected: без регрессий, число тестов прежнее.

- [ ] **Step 7: Commit**

---

### Task 4: Exclusive-лок на смену состояния выборов + D-02, D-07

**Files:**
- Create: `apps/elections/services.py`
- Modify: `apps/elections/views.py`
- Test: `tests/contract/test_election_lifecycle.py`

**Interfaces:**
- Produces:
  - `start_election(election, *, actor) -> Election`
  - `finish_election(election, *, actor) -> Election`
  - `cancel_election(election, *, actor) -> Election`
  - `delete_election(election, *, actor) -> None`
  - исключение `ElectionStateError(message, code)`

**Изменения контракта — осознанные, требуют записи в `API_CONTRACT.md`:**

| Что | Было | Стало | Почему |
|---|---|---|---|
| `DELETE` активных выборов | 204, ничего не удалено | 400 `active_election` | D-02, ТЗ п.66 — восстановление задуманной логики |
| `start` завершённых/отменённых | 200, выборы переоткрываются | 400 `invalid_status_transition` | D-07, ТЗ п.8, 52 — голосование поверх готовых результатов недопустимо |

Окно времени при `start` **намеренно не валидируется**: выборы с окном в прошлом
безвредны, потому что голосование всё равно проверяет `starts_at <= now <= ends_at`
(ТЗ п.52). Блокировать это значило бы запретить админу заранее настроенное расписание.

- [ ] **Step 1: Написать тесты на новое поведение**

Включая снятие `@expectedFailure` с `test_delete_active_election_is_rejected`
и удаление `test_delete_active_election_current_behaviour_lies_to_client`
(он фиксировал дефект, которого больше нет).

- [ ] **Step 2: Прогнать — падают.**

- [ ] **Step 3: Реализовать `apps/elections/services.py`**

Каждая операция: `with transaction.atomic(): election_state_lock(election.id); ...`.
Разрешённые переходы:

```
draft, scheduled -> active
active           -> finished, cancelled
draft, scheduled -> cancelled
finished         -> (ничего)
cancelled        -> (ничего)
```

- [ ] **Step 4: Переписать views на вызов сервисов**

`perform_destroy` больше не возвращает `Response` — он **поднимает** DRF-исключение,
которое обработчик превратит в 400 с нужным кодом. Возврат `Response` из
`perform_destroy` DRF игнорирует — это и была причина D-02.

- [ ] **Step 5: Прогнать** — все тесты, включая contract.

- [ ] **Step 6: Commit**

---

### Task 5: Concurrency-тесты (ТЗ п.72–75)

**Files:**
- Create: `tests/concurrency/__init__.py`
- Create: `tests/concurrency/base.py` — раннер потоков с закрытием соединений
- Create: `tests/concurrency/test_vote_concurrency.py`

**Interfaces:**
- Produces: `run_concurrently(fn, n, max_workers=30) -> (results, errors)`

**Почему нужен свой раннер:** каждый поток открывает собственное соединение с
PostgreSQL и обязан закрыть его в `finally`, иначе `max_connections` исчерпается,
а тестовую базу нельзя будет удалить в teardown. Эта же ошибка уже ловилась
на этапе 1 в `apps/voting/tests.py`.

Все тесты — `TransactionTestCase` и **пропускаются не на PostgreSQL** с явной
причиной: advisory locks на SQLite отсутствуют, зелёный прогон там ничего не доказывает.

| Тест | ТЗ | Сценарий | Ожидание |
|---|---|---|---|
| `test_single_student_many_requests` | 72 | 1 студент, 100 параллельных попыток | `VoteRecord == 1`, `Ballot == 1`, ровно 1 успех, остальные `AlreadyVoted` |
| `test_many_students_vote_in_parallel` | 73 | 1000 студентов, 10 кандидатов | 1000 успехов, `VoteRecord == 1000`, `Ballot == 1000`, сумма по кандидатам == 1000 |
| `test_votes_and_finish_are_serialized` | 74 | параллельно голоса + `finish` | после коммита finish новых голосов нет; `VoteRecord == Ballot`; частичных записей нет |
| `test_same_student_two_candidates` | 75 | 1 студент, одновременно за A и за B | `VoteRecord == 1`, `Ballot == 1` |
| `test_no_serialization_on_election_row` | 7 | голоса разных студентов | ни один не ждёт row lock на `Election` |

- [ ] **Step 1: Написать `base.py` с раннером.**
- [ ] **Step 2: Написать тест 1, прогнать на PostgreSQL.**
- [ ] **Step 3: Написать тесты 2–5, прогнать.**
- [ ] **Step 4: Проверить отсутствие deadlock'ов (ТЗ п.88)**

```bash
docker compose exec -T web python manage.py shell -c "
from django.db import connection
with connection.cursor() as c:
    c.execute('SELECT deadlocks FROM pg_stat_database WHERE datname=current_database()')
    print('deadlocks:', c.fetchone()[0])"
```
Expected: `0`.

- [ ] **Step 5: Commit**

---

### Task 6: Failure-тесты (ТЗ п.76)

**Files:**
- Create: `tests/concurrency/test_vote_failures.py`

| Тест | Сценарий | Ожидание |
|---|---|---|
| `test_exception_between_record_and_ballot_rolls_back_both` | исключение после `VoteRecord`, до `Ballot` | 0 `VoteRecord`, 0 `Ballot` |
| `test_ballot_failure_rolls_back_vote_record` | `Ballot.objects.create` бросает | 0 `VoteRecord` |
| `test_duplicate_after_integrity_error_creates_no_ballot` | повторный голос | `Ballot` не создаётся (ТЗ п.10) |
| `test_transaction_usable_after_integrity_error` | после `AlreadyVoted` соединение живо | следующий запрос выполняется |
| `test_redis_unavailable_does_not_block_voting` | Redis недоступен | голосование работает (ТЗ п.20) |

- [ ] **Step 1: Написать тесты.**
- [ ] **Step 2: Прогнать на PostgreSQL.**
- [ ] **Step 3: Commit**

---

### Task 7: Структурные тесты тайны голосования (ТЗ п.71)

**Files:**
- Create: `tests/contract/test_secret_ballot_structure.py`

| Тест | Проверяет |
|---|---|
| `test_ballot_has_no_student_fk` | ни одно поле `Ballot` не ведёт к `Student` |
| `test_ballot_has_no_voterecord_fk` | и к `VoteRecord` |
| `test_vote_record_has_no_candidate_fk` | ни одно поле `VoteRecord` не ведёт к `Candidate` |
| `test_no_model_links_student_and_candidate` | обход **всех** моделей проекта: нет модели с FK и на `Student`, и на `Candidate` |
| `test_no_serializer_exposes_student_and_candidate` | обход всех сериализаторов |
| `test_vote_logging_never_pairs_student_and_candidate` | `assertLogs` при успешном голосе |

Последние три — новые и сильнее прежних: они ловят не конкретные поля,
а само появление связи в любом месте проекта.

- [ ] **Step 1–3:** написать, прогнать, закоммитить.

---

### Task 8: D-01 — OTP verify возвращает токен

**Files:**
- Modify: `apps/students/views.py`
- Modify: `tests/contract/test_student_auth_contract.py` (снять `@expectedFailure`)

- [ ] **Step 1: Снять `@expectedFailure`, прогнать — падает с 500.**
- [ ] **Step 2: Дописать `return Response(...)`** той же формы, что у login:
      `{student_token, student, university}`, статус 200.
      Формирование тела вынести в общий хелпер, чтобы login, register и verify
      не разъезжались.
- [ ] **Step 3: Прогнать — PASS.**
- [ ] **Step 4: Commit**

---

### Task 9: D-03 — шаблон студентов в xlsx

**Files:**
- Modify: `config/settings.py`
- Modify: `tests/contract/test_admin_crud_contract.py`

**Решение:** `URL_FORMAT_OVERRIDE = '_format'`. Параметр `?format=` перестаёт
перехватываться content negotiation и доходит до view, а возможность DRF
запросить рендерер сохраняется под именем `?_format=`. Это уже, чем отключать
override совсем, и не ломает отладку через браузерный API.

- [ ] **Step 1: Снять `@expectedFailure` с `test_students_template_xlsx_is_reachable`,
      заменить `test_students_template_format_param_is_swallowed_by_drf` на тест
      нового поведения. Прогнать — падает.**
- [ ] **Step 2: Добавить `URL_FORMAT_OVERRIDE` в `REST_FRAMEWORK`.**
- [ ] **Step 3: Прогнать весь набор** — убедиться, что смена override ничего не задела.
- [ ] **Step 4: Commit**

---

### Task 10: Документация и финальная проверка

**Files:**
- Modify: `docs/API_CONTRACT.md`, `docs/BASELINE.md`,
  `docs/superpowers/plans/2026-09-20-highload-roadmap.md`

- [ ] **Step 1: Обновить `API_CONTRACT.md`** — новый код `invalid_status_transition`,
      изменившееся поведение `DELETE` активных выборов, рабочий OTP verify,
      рабочий `?format=xlsx`, новый `?_format`.
- [ ] **Step 2: Обновить `BASELINE.md`** — D-01, D-02, D-03, D-07 помечены исправленными
      с указанием проверяющего теста; expected failures теперь 0.
- [ ] **Step 3: Финальный прогон в трёх средах.**
- [ ] **Step 4: Проверить deadlocks и отсутствие `select_for_update` в hot path:**

```bash
grep -rn "select_for_update" apps/voting/
```
Expected: пусто.

- [ ] **Step 5: Commit**

---

## Definition of Done этапа 2

- [ ] `select_for_update` отсутствует в пути голосования.
- [ ] Голоса разных студентов не сериализуются друг с другом.
- [ ] `finish` корректно синхронизирован с параллельными голосами.
- [ ] Двойной голос закрыт констрейнтом БД, а не Python-проверкой.
- [ ] `IntegrityError` обрабатывается через savepoint; `Ballot` при дубле не создаётся.
- [ ] Все 4 concurrency-теста ТЗ зелёные на PostgreSQL, 0 unexpected deadlocks.
- [ ] Логи и `__str__` не позволяют связать студента с кандидатом.
- [ ] D-01, D-02, D-03, D-07 исправлены, expected failures = 0.
- [ ] Contract-тесты зелёные; все изменения контракта задокументированы.
