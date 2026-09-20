# Baseline и реестр дефектов

**Дата фиксации:** 2026-09-20
**Ветка:** `stage-0-api-contract` (от `main`, `c577e60`)
**Этап:** 0 — аудит и фиксация API-контракта

---

## 1. Baseline тестов

| Набор | Тестов | SQLite | PostgreSQL 16.15 |
|---|---|---|---|
| Существующие (`apps/`) | 12 | OK | OK |
| Contract-тесты (`tests/contract/`) | 127 | OK, 3 expected failures | OK, 3 expected failures |
| Тесты настроек (`tests/config/`) — с этапа 1 | 10 | OK | OK |
| **Весь набор** | **149** | **OK, 3 expected failures** | **OK, 3 expected failures** |

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

### Команды

```bash
# SQLite (быстро, для локальной разработки)
python3 manage.py test
python3 manage.py test tests.contract
python3 manage.py test apps

# PostgreSQL (обязательно для критических integration/concurrency тестов, ТЗ п.107)
DJANGO_SETTINGS_MODULE=config.settings_test python3 manage.py test
```

Прогон на PostgreSQL требует запущенного сервера и доступной роли; параметры
подключения переопределяются переменными `DB_NAME`, `DB_USER`, `DB_PASSWORD`,
`DB_HOST`, `DB_PORT`.

---

## 2. Реестр дефектов

`expectedFailure` означает: тест описывает **намеренный** контракт и сейчас падает.
После исправления дефекта декоратор снимается, и тест начинает защищать поведение.

### D-01 — OTP verify не возвращает ответ (500)

| | |
|---|---|
| **Файл** | `apps/students/views.py:139` (`StudentVerifyView.post`) |
| **Суть** | После `auth_session.is_verified = True; save()` функция заканчивается без `return Response(...)`. DRF бросает `AssertionError: Expected a Response... received NoneType` |
| **Последствие** | Весь вход по студенческому ID + SMS-код нерабочий. Фронтенд (`app/vote/[university_code]/verify/page.tsx`) показывает «Ошибка сервера (500)». Токен не выдаётся никогда |
| **Проверено** | прямым прогоном: `VERIFY RAISED AssertionError` |
| **Тест** | `test_verify_returns_student_token` (`@expectedFailure`) |
| **ТЗ** | п.66 — восстановление уже задуманной логики, менять фронтенд не требуется |
| **Этап** | 2 |

### D-02 — DELETE активных выборов сообщает об удалении, которого не было

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

### D-03 — XLSX-шаблон студентов недостижим

| | |
|---|---|
| **Файл** | `apps/students/views.py:411` (`AdminStudentTemplateView.get`) |
| **Суть** | View читает `request.query_params.get('format')`, но DRF `URL_FORMAT_OVERRIDE` по умолчанию тоже равен `'format'`. Content negotiation срабатывает раньше, не находит рендерер `csv`/`xlsx` и отдаёт 404 |
| **Последствие** | `?format=csv` → 404, `?format=xlsx` → 404. Работает только вызов без параметра (отдаёт CSV). XLSX-ветка кода недостижима ни при каком входе |
| **Проверено** | `(none) → 200 text/csv`, `?format=csv → 404`, `?format=xlsx → 404`, `?format=json → 200 text/csv` |
| **Тесты** | `test_students_template_format_param_is_swallowed_by_drf` (факт), `test_students_template_xlsx_is_reachable` (`@expectedFailure`) |
| **Исправление** | переименовать параметр (например `kind`) или задать `URL_FORMAT_OVERRIDE = None`. Фронтенд endpoint не вызывает — риск нулевой |
| **Этап** | 2 |

### D-04 — JWT не проверяет `Student.is_active`, нет механизма отзыва

| | |
|---|---|
| **Файл** | `apps/core/authentication.py:50` |
| **Суть** | `Student.objects.select_related('university').get(id=student_id)` — без фильтра `is_active=True`. Деактивация студента никак не влияет на уже выданные токены (живут 7 дней) |
| **Последствие** | **Дыра в безопасности:** отчисленный или заблокированный студент продолжает голосовать. Отозвать токен невозможно в принципе |
| **Проверено** | тест: студент с `is_active=False` успешно голосует, `VoteRecord` создаётся |
| **Тест** | `test_deactivated_student_can_still_vote_with_old_token` (фиксирует факт) |
| **ТЗ** | п.18, 19 |
| **Этап** | 3 — вместе с `auth_version` и Redis principal cache |

### D-05 — OTP хранится и логируется в открытом виде

| | |
|---|---|
| **Файлы** | `apps/students/services.py:49-50`, `apps/students/models.py` (`StudentAuthSession.__str__`) |
| **Суть** | Код пишется в `logger.info` **и** в `print()` вместе с номером телефона и `student_id`. `__str__` модели тоже печатает код. В БД код хранится plaintext |
| **Дополнительно** | `MOCK_SMS` по умолчанию `True`, `DEMO_OTP_CODE = '123456'` захардкожен. В production без явного отключения **любой** OTP равен `123456` |
| **Наблюдение** | Коды видны прямо в выводе тестового прогона |
| **ТЗ** | п.34 |
| **Этап** | 8 |

### D-06 — Необработанные исключения отдают `str(exc)` наружу

| | |
|---|---|
| **Файл** | `apps/core/exceptions.py:35` |
| **Суть** | Ветка 500 формирует `{"error": {"code": "internal_server_error", "message": str(exc)}}` |
| **Последствие** | Внутренности (SQL, пути, значения) уходят клиенту. Тот же класс проблемы в `authentication.py:67`: `AuthenticationFailed(f"Недействительный токен: {str(e)}")` |
| **ТЗ** | п.65 |
| **Этап** | 3 (auth) и 7 (общий обработчик) |

### D-07 — `start_election` не проверяет ни текущий статус, ни окно времени

| | |
|---|---|
| **Файл** | `apps/elections/views.py:120` |
| **Суть** | Проверяется только наличие кандидатов. Можно перевести в ACTIVE уже завершённые или отменённые выборы; `starts_at`/`ends_at` не валидируются и могут быть в прошлом |
| **Последствие** | Завершённые выборы переоткрываются, голосование возобновляется поверх готовых результатов |
| **Наблюдение** | покрыто contract-тестами как текущее поведение; как дефект — на этапе 2 вместе с exclusive advisory lock |
| **ТЗ** | п.8, 17, 52 |
| **Этап** | 2 |

---

## 3. Наблюдения по производительности (без изменений на этапе 0)

Подтверждено чтением кода; количественные замеры — этап 10.

| Место | Проблема | ТЗ | Этап |
|---|---|---|---|
| `apps/voting/services.py:44` | `Election.objects.select_for_update()` — глобальная сериализация всех голосов одних выборов через одну строку | 7 | 2 |
| `apps/voting/services.py:67` | `VoteRecord...select_for_update().exists()` — check-then-insert вместо DB-констрейнта | 6 | 2 |
| `apps/voting/services.py:80` | `IntegrityError` перехвачен внутри `atomic()` без savepoint → транзакция в broken state, а следом выполняется `Ballot.objects.create()` | 10 | 2 |
| `apps/voting/services.py:96` | два соседних `logger.info`: participation со `student.id` и ballot с `candidate_id`, один `election_id` — корреляция восстанавливается по времени | 4 | 2 |
| `apps/voting/models.py` | `Index(fields=['election','student'])` дублирует индекс от `unique_together` | 14 | 5 |
| `apps/voting/models.py` | `VoteRecord.__str__` печатает `student.student_id`, `Ballot.__str__` — кандидата | 4 | 2 |
| `apps/core/authentication.py:50` | SELECT `Student` на **каждый** authenticated request | 18 | 3 |
| `apps/elections/serializers.py:26` | `obj.candidates.count()` в `SerializerMethodField` → N+1 на списках | 26 | 4 |
| `apps/elections/views.py:245` | results: `for candidate: Ballot.objects.filter(...).count()` → 1+N | 27 | 4 |
| `apps/elections/views.py:310` | xlsx-экспорт: та же 1+N, плюс CPU/RAM в web-воркере | 27, 42 | 4, 7 |
| `apps/elections/views.py:404` | `StudentAvailableElectionsView` → `ElectionStudentSerializer` с вложенными кандидатами → N+1 | 25 | 4 |
| `apps/universities/serializers.py:30` | `students_count`, `active_elections_count` через `.count()` на каждый объект списка | 26 | 4 |
| `apps/students/views.py:170` | `Student.objects.filter(email__iexact=...).exists()` перед INSERT — гонка при параллельной регистрации | 15 | 5 |
| `apps/students/views.py:126` | `attempts += 1; save()` — неатомарный инкремент при параллельных verify | 35 | 8 |
| `apps/students/views.py:373` | `file_obj.read()` целиком в память, затем передача байтов в Celery-задачу | 41 | 7 |

## 4. Наблюдения по безопасности и конфигурации

| Место | Проблема | ТЗ | Этап |
|---|---|---|---|
| `config/settings.py:11` | рабочий `SECRET_KEY` захардкожен как fallback и закоммичен → считать скомпрометированным | 32, 33 | 7 |
| `config/settings.py:12` | `DEBUG` по умолчанию `True` | 32, 102 | 7 |
| `config/settings.py:15` | `ALLOWED_HOSTS = ['*']` без возможности переопределить | 32 | 7 |
| `config/settings.py:~200` | `CORS_ALLOW_ALL_ORIGINS = True`, `CORS_ALLOW_CREDENTIALS = True` | 32 | 7 |
| `config/settings.py` | `X_FRAME_OPTIONS = 'ALLOWALL'` | 97 | 8 |
| `config/settings.py:70` | `DB_ENGINE` по умолчанию `sqlite`, prod ничем не защищён | 12, 102 | 1, 7 |
| `config/settings.py` | `CELERY_TASK_ALWAYS_EAGER` по умолчанию `True` — импорт Excel выполняется в web-воркере | 40 | 7 |
| `config/urls.py:57` | медиа и статика раздаются `django.views.static.serve` | 31 | 7 |
| `Dockerfile:24` | `CMD python manage.py runserver`, root-пользователь, single-stage | 37, 57 | 7 |
| `requirements.txt` | только `>=`, нет lock; нет `psycopg`, нет gunicorn | 12, 68 | 1 |
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
