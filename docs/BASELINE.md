# Baseline и реестр дефектов

**Дата фиксации:** 2026-09-20
**Ветка:** `stage-0-api-contract` (от `main`, `c577e60`)
**Этап:** 0 — аудит и фиксация API-контракта

---

## 1. Baseline тестов

| Набор | Тестов | SQLite | PostgreSQL 16.15 |
|---|---|---|---|
| Существующие (`apps/`) | 12 | OK | OK |
| Contract-тесты (`tests/contract/`) | 368 | OK | OK |
| Тесты настроек (`tests/config/`) | 12 | OK | OK |
| Concurrency-тесты (`tests/concurrency/`) — с этапа 2 | 15 | пропускаются | OK |
| **Весь набор** | **428** | **OK, 25 skipped** | **OK, 1 skipped** |

**Expected failures: 0** (было 3 до этапа 2 — D-01, D-02, D-03 исправлены).

На SQLite пропускаются concurrency-тесты, семантика advisory-локов и тест DDL:
там нет advisory locks и другая модель блокировок, зелёный прогон ничего не доказывал бы.

Прогон на PostgreSQL добавлен на этапе 1 (ТЗ п.107). Расхождений между СУБД нет:
139 тестов этапа 0 дают одинаковый результат на обеих.

**Оговорка о существующем concurrency-тесте.** `apps/voting/tests.py::test_concurrency_race_condition_protection`
зелёный на PostgreSQL, но проходит он по «неправильной» причине: параллельные голоса
сериализуются глобальным `Election.objects.select_for_update()`, который этап 2 обязан
убрать (ТЗ п.7). После его удаления защита должна обеспечиваться UNIQUE-констрейнтом,
и этот же тест продолжит быть зелёным уже по правильной причине.

### Состав contract-тестов

| Файл | Тестов | Покрывает |
|---|---|---|
| `test_public_contract.py` | 22 | health, api root, университеты, факультеты, выборы, кандидаты, новости, FAQ, страницы |
| `test_student_auth_contract.py` | 24 | register, login, профиль, OTP identify/verify, оба пути монтирования |
| `test_voting_contract.py` | 21 | `cast`, `status`, все `error.code`, тайна голосования на уровне API |
| `test_admin_elections_contract.py` | 26 | логин админа, CRUD выборов, start/finish/cancel, turnout, results, xlsx-экспорт, featured |
| `test_admin_crud_contract.py` | 34 | университеты, факультеты, студенты, импорт, кандидаты, пользователи, логи, контент |

### Что проверено запуском, а что нет

| Утверждение | Статус |
|---|---|
| `requirements.txt` ставит рабочий набор | **проверено**: чистый venv из lock-файла, 267 тестов зелёные на обеих СУБД |
| Процедура `SQLITE_TO_POSTGRES.md` | **проверена целиком** на реальной dev-базе (125 объектов), см. сам документ |
| Шаги CI (`install → check → makemigrations --check → migrate → audit → test`) | **проверены** в чистом `python:3.11-slim` против compose-сервисов, включая буквальную команду `uv pip install --system` |
| Раннер GitHub Actions (`checkout`, `setup-python`, `setup-uv`, блок `services`) | **не проверен**: требует пуша в репозиторий |
| Concurrency при высоком параллелизме | **проверено** при 100 и 200 одновременных соединениях, 0 deadlock'ов |
| Docker-окружение | **проверено**: 4 сервиса, миграции, тесты, HTTP, Celery-воркер |
| Поведение при недоступном Redis | **проверено** с реально остановленным контейнером |
| Число SQL на горячих endpoint'ах | **измерено до и после**, см. `docs/PERFORMANCE.md`; ни один не растёт с данными |
| Планы запросов (`EXPLAIN ANALYZE`) | **измерены до и после на 200 000 студентов**, см. `docs/PERFORMANCE.md` раздел 3 |
| Компромисс по trigram-индексам | **измерен в обе стороны** (поиск против скорости импорта), решение обосновано цифрами |
| Эффект кэширования | **измерен** холодный против горячего, см. `docs/PERFORMANCE.md` раздел 4 |
| Работа при полностью очищенном Redis | **проверена** тестом ТЗ п.114 и вживую с остановленным контейнером |
| Production-образ | **собран и запущен**: non-root, health, 11 проверок, graceful shutdown |
| Агрегация метрик по воркерам gunicorn | **проверена**: 40 запросов через 4 воркера дают ровно 40.0 |
| Отсутствие student×candidate в телеметрии | **проверено** обходом всего реестра метрик и логов |
| Производительность (RPS, latency) | **не измерялась** — этап 10 |
| Процедура миграции на production-объёме | **не выполнялась** — нет доступа и нет таких данных |

### Команды

```bash
# SQLite (быстро, для локальной разработки)
python3 manage.py test
python3 manage.py test tests.contract
python3 manage.py test apps

# PostgreSQL (обязательно для критических integration/concurrency тестов, ТЗ п.107)
DJANGO_SETTINGS_MODULE=config.settings_test python3 manage.py test
```

```bash
# В Docker (PostgreSQL + Redis + Celery worker)
docker compose exec web python manage.py test
```

Прогон на PostgreSQL требует запущенного сервера и доступной роли; параметры
подключения переопределяются переменными `DB_NAME`, `DB_USER`, `DB_PASSWORD`,
`DB_HOST`, `DB_PORT`.

Все три способа дают одинаковый результат: 163 теста, OK, 3 expected failures.

---

## 2. Реестр дефектов

`expectedFailure` означает: тест описывает **намеренный** контракт и сейчас падает.
После исправления дефекта декоратор снимается, и тест начинает защищать поведение.

### D-01 — OTP verify не возвращает ответ (500) (ИСПРАВЛЕНО)

| | |
|---|---|
| **Файл** | `apps/students/views.py:139` (`StudentVerifyView.post`) |
| **Суть** | После `auth_session.is_verified = True; save()` функция заканчивается без `return Response(...)`. DRF бросает `AssertionError: Expected a Response... received NoneType` |
| **Последствие** | Весь вход по студенческому ID + SMS-код нерабочий. Фронтенд (`app/vote/[university_code]/verify/page.tsx`) показывает «Ошибка сервера (500)». Токен не выдаётся никогда |
| **Проверено** | прямым прогоном: `VERIFY RAISED AssertionError` |
| **Тест** | `test_verify_returns_student_token` (`@expectedFailure`) |
| **ТЗ** | п.66 — восстановление уже задуманной логики, менять фронтенд не требуется |
| **Этап** | 2 |
| **Статус** | **ИСПРАВЛЕНО на этапе 2.** Добавлен `return Response(build_student_auth_response(...))`. Тело ответа вынесено в общий хелпер, чтобы register/login/verify не разъезжались. Проверяет `test_verify_returns_student_token`. |

### D-02 — DELETE активных выборов сообщает об удалении, которого не было (ИСПРАВЛЕНО)

| | |
|---|---|
| **Файл** | `apps/elections/views.py:89` (`AdminElectionDetailView.perform_destroy`) |
| **Суть** | Метод возвращает `Response(400 active_election)`, но DRF `destroy()` возвращаемое значение игнорирует и всегда отдаёт 204. Выход через `return` при этом происходит **до** `instance.delete()` |
| **Последствие** | Клиент получает 204 при неудалённых выборах. Фронтенд убирает строку из таблицы, после перезагрузки она возвращается. Ошибка не показывается |
| **Проверено** | тест: статус 204, `Election.objects.filter(id=...).exists() is True` |
| **Уточнение** | Первоначальное предположение, что активные выборы **удаляются** вместе с голосами по CASCADE, тестом **опровергнуто**. Данные не теряются; дефект в ложном ответе |
| **Тесты** | `test_delete_active_election_is_rejected` (`@expectedFailure`), `test_delete_active_election_current_behaviour_lies_to_client` (фиксирует факт) |
| **ТЗ** | п.66 |
| **Этап** | 2 |
| **Статус** | **ИСПРАВЛЕНО на этапе 2.** `perform_destroy` поднимает `ElectionOperationDenied` вместо `return Response(...)`. Проверяют `test_delete_active_election_is_rejected` и `test_delete_active_election_returns_400_and_keeps_it`. |

### D-03 — XLSX-шаблон студентов недостижим (ИСПРАВЛЕНО)

| | |
|---|---|
| **Файл** | `apps/students/views.py:411` (`AdminStudentTemplateView.get`) |
| **Суть** | View читает `request.query_params.get('format')`, но DRF `URL_FORMAT_OVERRIDE` по умолчанию тоже равен `'format'`. Content negotiation срабатывает раньше, не находит рендерер `csv`/`xlsx` и отдаёт 404 |
| **Последствие** | `?format=csv` → 404, `?format=xlsx` → 404. Работает только вызов без параметра (отдаёт CSV). XLSX-ветка кода недостижима ни при каком входе |
| **Проверено** | `(none) → 200 text/csv`, `?format=csv → 404`, `?format=xlsx → 404`, `?format=json → 200 text/csv` |
| **Тесты** | `test_students_template_format_param_is_swallowed_by_drf` (факт), `test_students_template_xlsx_is_reachable` (`@expectedFailure`) |
| **Исправление** | переименовать параметр (например `kind`) или задать `URL_FORMAT_OVERRIDE = None`. Фронтенд endpoint не вызывает — риск нулевой |
| **Этап** | 2 |
| **Статус** | **ИСПРАВЛЕНО на этапе 2.** `URL_FORMAT_OVERRIDE = '_format'`. Проверяют `test_students_template_xlsx_is_reachable` и `test_drf_format_override_still_available_under_new_name`. |

### D-04 — JWT не проверяет `Student.is_active`, нет механизма отзыва (ИСПРАВЛЕНО)

| | |
|---|---|
| **Файл** | `apps/core/authentication.py:50` |
| **Суть** | `Student.objects.select_related('university').get(id=student_id)` — без фильтра `is_active=True`. Деактивация студента никак не влияет на уже выданные токены (живут 7 дней) |
| **Последствие** | **Дыра в безопасности:** отчисленный или заблокированный студент продолжает голосовать. Отозвать токен невозможно в принципе |
| **Проверено** | тест: студент с `is_active=False` успешно голосует, `VoteRecord` создаётся |
| **Тест** | `test_deactivated_student_can_still_vote_with_old_token` (фиксирует факт) |
| **ТЗ** | п.18, 19 |
| **Этап** | 3 — вместе с `auth_version` и Redis principal cache |
| **Статус** | **ИСПРАВЛЕНО на этапе 3.** Добавлена проверка `is_active` и механизм `auth_version`: деактивация и смена пароля немедленно обесценивают выданные токены. Проверяют `tests/contract/test_token_revocation.py` (14 тестов) и `test_deactivated_student_cannot_vote`. |

### D-08 — тесты отправляли задачи Celery в реальный брокер (ИСПРАВЛЕНО на этапе 1)

| | |
|---|---|
| **Файл** | `config/settings.py` (блок Celery) |
| **Суть** | Django не переводит Celery в eager-режим под тестами. При `CELERY_TASK_ALWAYS_EAGER=False` (docker-compose, CI) тест `test_student_upload_returns_202_batch_id` отправлял задачу в **реальный** брокер |
| **Последствие** | Живой воркер получал задачу и искал `UploadBatch` в реальной базе вместо тестовой → `Batch ... not found`. Тест оставался зелёным (он проверяет только 202), но прогон трогал чужие данные и зависел от доступности Redis |
| **Обнаружено** | в логах воркера при первом реальном запуске docker-compose: лишняя задача с временем прогона тестов |
| **Исправление** | `if TESTING: CELERY_TASK_ALWAYS_EAGER = True` в `config/settings.py` |
| **Проверено** | счётчик задач воркера не меняется за полный прогон (до фикса рос на 1) |
| **Тесты** | `tests/config/test_settings_celery.py` (2 теста) |

### D-05 — OTP хранится и логируется в открытом виде (ИСПРАВЛЕНО)

| | |
|---|---|
| **Файлы** | `apps/students/services.py:49-50`, `apps/students/models.py` (`StudentAuthSession.__str__`) |
| **Суть** | Код пишется в `logger.info` **и** в `print()` вместе с номером телефона и `student_id`. `__str__` модели тоже печатает код. В БД код хранится plaintext |
| **Дополнительно** | `MOCK_SMS` по умолчанию `True`, `DEMO_OTP_CODE = '123456'` захардкожен. В production без явного отключения **любой** OTP равен `123456` |
| **Наблюдение** | Коды видны прямо в выводе тестового прогона |
| **ТЗ** | п.34 |
| **Этап** | 8 |
| **Статус** | **ИСПРАВЛЕНО на этапе 8.** Код хранится хэшем (`code_hash`), не логируется, не печатается, отсутствует в `__str__` и в ответе при `DEBUG=False`. Миграция гасит открытые сессии явно. Проверяет `tests/contract/test_otp_security.py` (14 тестов). |

### D-06 — Необработанные исключения отдают `str(exc)` наружу (ИСПРАВЛЕНО)

| | |
|---|---|
| **Файл** | `apps/core/exceptions.py:35` |
| **Суть** | Ветка 500 формирует `{"error": {"code": "internal_server_error", "message": str(exc)}}` |
| **Последствие** | Внутренности (SQL, пути, значения) уходят клиенту. Тот же класс проблемы в `authentication.py:67`: `AuthenticationFailed(f"Недействительный токен: {str(e)}")` |
| **ТЗ** | п.65 |
| **Этап** | 3 (auth) и 7 (общий обработчик) |
| **Статус** | **ИСПРАВЛЕНО на этапе 7.** Обработчик 500 отдаёт generic-сообщение и `request_id`; подробности только в лог. Проверяет `tests/contract/test_error_handling.py`. |

### D-07 — `start_election` не проверяет ни текущий статус, ни окно времени (ИСПРАВЛЕНО)

| | |
|---|---|
| **Файл** | `apps/elections/views.py:120` |
| **Суть** | Проверяется только наличие кандидатов. Можно перевести в ACTIVE уже завершённые или отменённые выборы; `starts_at`/`ends_at` не валидируются и могут быть в прошлом |
| **Последствие** | Завершённые выборы переоткрываются, голосование возобновляется поверх готовых результатов |
| **Наблюдение** | покрыто contract-тестами как текущее поведение; как дефект — на этапе 2 вместе с exclusive advisory lock |
| **ТЗ** | п.8, 17, 52 |
| **Этап** | 2 |
| **Статус** | **ИСПРАВЛЕНО на этапе 2.** Переходы из терминальных статусов запрещены, новый код `invalid_status_transition`. Проверяют тесты в `tests/contract/test_election_lifecycle.py`. |

---

### D-09 — `FOR UPDATE` на выборах блокировал любую вставку с FK (ИСПРАВЛЕНО на этапе 2)

| | |
|---|---|
| **Файл** | `apps/voting/services.py` (прежняя редакция) |
| **Суть** | `Election.objects.select_for_update()` брал `FOR UPDATE` на строке выборов на всю транзакцию голосования. В PostgreSQL этот режим конфликтует не только с другими `FOR UPDATE`, но и с `FOR KEY SHARE`, который берётся при вставке **любой** строки с внешним ключом на эти выборы |
| **Последствие** | Сериализовались не только голоса, но и любые параллельные вставки `VoteRecord`, `Ballot`, `Candidate`, ссылающиеся на те же выборы. Масштаб проблемы был больше, чем описано в ТЗ п.7 |
| **Обнаружено** | прямым замером при написании regression-стража: `INSERT` с FK при удерживаемом `FOR UPDATE` — ЗАБЛОКИРОВАН |
| **Статус** | **ИСПРАВЛЕНО на этапе 2** вместе с основным рефакторингом. Защищено двумя стражами в `tests/concurrency/test_no_row_lock.py`, каждый проверен на способность падать |

## 3. Наблюдения по производительности (без изменений на этапе 0)

Подтверждено чтением кода; количественные замеры — этап 10.

| Место | Проблема | ТЗ | Этап |
|---|---|---|---|
| ~~`apps/voting/services.py:44`~~ | ~~`select_for_update()`~~ — **устранено на этапе 2** | 7 | ✅ 2 |
| ~~`apps/voting/services.py:67`~~ | ~~check-then-insert~~ — **устранено на этапе 2**, защиту даёт UNIQUE | 6 | ✅ 2 |
| ~~`apps/voting/services.py:80`~~ | ~~broken state~~ — **устранено на этапе 2**, INSERT в savepoint | 10 | ✅ 2 |
| ~~`apps/voting/services.py:96`~~ | ~~коррелируемые логи~~ — **устранено на этапе 2**: `vote_accepted election_id=...` | 4 | ✅ 2 |
| ~~`apps/voting/models.py`~~ | ~~дублирующий индекс~~ — **удалён на этапе 2** | 14 | ✅ 2 |
| ~~`apps/voting/models.py`~~ | ~~`__str__` раскрывали стороны~~ — **исправлено на этапе 2** | 4 | ✅ 2 |
| ~~`apps/core/authentication.py:50`~~ | ~~SELECT на каждый запрос~~ — **устранено на этапе 3**: 0 SQL при попадании в Redis | 18 | ✅ 3 |
| ~~`apps/elections/serializers.py:26`~~ | ~~N+1 на списках~~ — **устранено на этапе 4**: annotate(Count) | 26 | ✅ 4 |
| ~~`apps/elections/views.py:245`~~ | ~~1+N подсчётов~~ — **устранено на этапе 4**: один GROUP BY | 27 | ✅ 4 |
| `apps/elections/views.py:310` | 1+N ~~устранена на этапе 4~~; CPU/RAM в web-воркере остаётся | 27, 42 | ✅ 4 / 7 |
| ~~`apps/elections/views.py:404`~~ | ~~62 запроса~~ — **устранено на этапе 4**: 3 запроса, не растёт | 25 | ✅ 4 |
| ~~`apps/universities/serializers.py:30`~~ | ~~два COUNT на объект~~ — **устранено на этапе 4** | 26 | ✅ 4 |
| ~~`apps/students/views.py:170`~~ | ~~гонка при регистрации~~ — **закрыта на этапе 5**: UNIQUE(LOWER(email)) | 15 | ✅ 5 |
| ~~`apps/students/views.py:126`~~ | ~~неатомарный инкремент~~ — **исправлено на этапе 8**: `F('attempts') + 1` и условный UPDATE для `is_verified` | 35 | ✅ 8 |
| `apps/students/views.py:373` | `file_obj.read()` целиком в память, затем передача байтов в Celery-задачу | 41 | 7 |

### D-10 — короткий SECRET_KEY для HMAC SHA256 (ИСПРАВЛЕНО)

| | |
|---|---|
| **Обнаружено** | предупреждение PyJWT при работе в docker: `InsecureKeyLengthWarning: The HMAC key is 21 bytes long, which is below the minimum recommended length of 32 bytes for SHA256` |
| **Суть** | dev-ключ `dev-only-insecure-key` короче 32 байт. Тот же класс проблемы касается и production-ключа: `DJANGO_SECRET_KEY` используется для подписи студенческих JWT, и его длина — часть стойкости подписи |
| **Последствие** | короткий ключ снижает стоимость перебора подписи токена |
| **Этап** | 7 — вместе с ротацией секретов и startup-валидацией: проверка длины `DJANGO_SECRET_KEY` добавляется в `production_check` |
| **Статус** | **ИСПРАВЛЕНО на этапе 7.** `production_check` проверяет длину `SECRET_KEY` (минимум 32 байта) и отвергает ключ из репозитория. |

## 4. Наблюдения по безопасности и конфигурации

| Место | Проблема | ТЗ | Этап |
|---|---|---|---|
| ~~`config/settings.py:11`~~ | fallback остался только для разработки; в production отсутствие ключа **валит старт** | 32, 33 | ✅ 7 |
| ~~`config/settings.py:12`~~ | в production `DEBUG=True` **валит старт** | 32, 102 | ✅ 7 |
| ~~`config/settings.py:15`~~ | из окружения; wildcard в production **валит старт** | 32 | ✅ 7 |
| ~~`config/settings.py:~200`~~ | в production обязателен явный список origin'ов | 32 | ✅ 7 |
| ~~`config/settings.py`~~ | `DENY` в production | 97 | ✅ 7 |
| `config/settings.py:70` | `DB_ENGINE` по умолчанию `sqlite`, prod ничем не защищён | 12, 102 | 1, 7 |
| ~~`config/settings.py`~~ | в production `False`; очереди разделены | 40 | ✅ 7 |
| `config/urls.py:57` | медиа и статика раздаются `django.views.static.serve` | 31 | 7 |
| ~~`Dockerfile:24`~~ | multi-stage, non-root, gunicorn — **проверено запуском** | 37, 57 | ✅ 7 |
| ~~`requirements.txt`~~ | полный pin, psycopg 3, gunicorn | 12, 68 | ✅ 1, 7 |
| репозиторий | `db.sqlite3` отслеживается Git | 56 | 1 |
| `apps/elections/views.py:22` | `get_client_ip` безусловно доверяет `X-Forwarded-For` (продублировано в 4 файлах) | 60 | 7 |

---

## 5. Что этап 0 **не** менял

`git diff --stat main -- apps/ config/` пуст. Добавлены только `tests/` и `docs/`.
Все дефекты зафиксированы, ни один не исправлен: исправления идут этапами 2, 3, 7, 8
по порядку приоритета из ТЗ п.118.

---

## 6. Отложено в этап 1 (репозиторная гигиена)

- В `main` отслеживаются **95** файлов `*.pyc` (`__pycache__/` во всех приложениях и `config/`).
  Этап 0 добавил минимальный `.gitignore` (только `__pycache__`, `*.py[cod]`, venv, логи),
  чтобы новые артефакты не попадали в коммиты, но **не удалял** ранее отслеженные 95 файлов —
  это отдельная операция этапа 1 вместе с `db.sqlite3` и `.env` (ТЗ п.56).
- `db.sqlite3` отслеживается Git — удаление из индекса на этапе 1, после того как
  будет готов путь миграции на PostgreSQL (`docs/SQLITE_TO_POSTGRES.md`).
