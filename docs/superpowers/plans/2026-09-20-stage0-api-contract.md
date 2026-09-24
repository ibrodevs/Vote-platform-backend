# Этап 0 — Аудит и фиксация API-контракта: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Зафиксировать текущее поведение публичного API набором regression/contract-тестов и
документацией, чтобы любой последующий рефакторинг доказуемо не ломал контракт для фронтенда.

**Architecture:** Новый top-level пакет `tests/` с подпакетом `tests/contract/`, обнаруживаемый
стандартным `python manage.py test`. Общие фабрики данных и хелперы аутентификации — в
`tests/contract/factories.py` и `tests/contract/base.py`, чтобы каждый тестовый модуль описывал
только сам контракт. Документация контракта — в `docs/API_CONTRACT.md` (backend) и
`docs/FRONTEND_USAGE.md` (кто из фронтенда что вызывает). Найденные дефекты — в `docs/BASELINE.md`.

**Tech Stack:** Django 5.2.17, DRF, `rest_framework.test.APIClient`, PyJWT, SQLite (baseline;
переезд на PostgreSQL — этап 1).

**Spec:** `docs/superpowers/plans/2026-09-20-highload-roadmap.md` (этап 0) и ТЗ п.2, 49, 50, 121.

## Global Constraints

Полный список — в разделе «Global Constraints» roadmap. Для этого этапа критично:

- **Ничего не менять в поведении приложения.** Этап 0 — только тесты и документация.
  Единственные правки кода вне `tests/` и `docs/` — те, что перечислены в Task 9 явно, и ни одной больше.
- **Тесты фиксируют факт, а не желаемое.** Если endpoint сейчас ведёт себя странно, но фронтенд
  на это опирается — тест закрепляет текущее поведение.
- **Исключение — доказанные дефекты.** Там, где текущее поведение противоречит фронтенду
  (500 вместо ответа), тест пишется на **намеренный** контракт и помечается
  `@unittest.expectedFailure` со ссылкой на запись в `docs/BASELINE.md`. Так дефект зафиксирован,
  но не зацементирован. Когда дефект будет исправлен на этапе 2, `expectedFailure` снимается.
- **Не логировать и не печатать в тестах** `student_id` вместе с `candidate_id`.
- Тесты не должны зависеть от порядка выполнения и от реального времени вне `timezone.now()`.

## Объём кода в плане

Ниже для каждой задачи даны: точные файлы, интерфейсы, полный код общих модулей и
**полный перечень тестов с конкретными утверждениями** (имя теста → что именно проверяется →
ожидаемый статус и поля). Код каждого отдельного теста пишется по этому перечню — он
однозначен: endpoint, метод, вход, ожидаемый код, ожидаемые ключи.

---

## Инвентарь endpoints (результат аудита кода, 2026-09-20)

Всё, что смонтировано в `config/urls.py`. Столбец «FE» — вызывается ли из `lib/api.ts` фронтенда.

### Служебные
| Метод | Endpoint | View | Auth | FE |
|---|---|---|---|---|
| GET | `/` , `/api/` | `api_root` | — | нет |
| GET | `/api/health/` | `health_check` | — | нет |

### Публичные: университеты
| Метод | Endpoint | View | Auth | Пагинация | FE |
|---|---|---|---|---|---|
| GET | `/api/v1/universities/` | `UniversityPublicListView` | AllowAny | нет | `getUniversities` |
| GET | `/api/v1/universities/<code>/info/` | `UniversityPublicDetailByCodeView` | AllowAny | — | `getUniversityInfo` |
| GET | `/api/v1/universities/<uuid>/faculties/` | `UniversityFacultyListCreateView` | AllowAny (GET) | да (default) | `getUniversityFaculties` |
| POST | `/api/v1/universities/<uuid>/faculties/` | тот же | `IsAdminUserWithRole` | — | нет |

### Студенческая аутентификация
Смонтировано дважды: `/api/v1/auth/student/...` и `/api/v1/students/auth/...` — один и тот же `urls_auth`.
Фронтенд использует первый вариант; существующие тесты — второй. **Оба обязаны работать.**

| Метод | Endpoint | View | Auth | FE |
|---|---|---|---|---|
| POST | `.../identify/` | `StudentIdentifyView` | AllowAny | `studentIdentify` |
| POST | `.../verify/` | `StudentVerifyView` | AllowAny | `studentVerify` |
| POST | `.../register/` | `StudentRegisterView` | AllowAny | `studentRegister` |
| POST | `.../login/` | `StudentPasswordLoginView` | AllowAny | `studentPasswordLogin` |
| GET/PATCH | `.../me/` | `StudentProfileView` | `IsStudentAuthenticated` | `getStudentProfile` |

### Выборы: студент / публика
| Метод | Endpoint | View | Auth | FE |
|---|---|---|---|---|
| GET | `/api/v1/elections/recent/` | `PublicRecentElectionsView` | AllowAny | `getRecentElections` |
| GET | `/api/v1/elections/public/` | `PublicRecentElectionsView` | AllowAny | нет |
| GET | `/api/v1/elections/available/` | `StudentAvailableElectionsView` | `IsStudentAuthenticated` | `getAvailableElections` |
| GET | `/api/v1/elections/<uuid>/` | `StudentElectionDetailView` | AllowAny | `getElectionDetail` |
| GET | `/api/v1/elections/<uuid>/candidates/` | `StudentElectionCandidatesListView` | AllowAny | `getElectionCandidates` |
| GET | `/api/v1/candidates/<uuid>/` | `CandidatePublicDetailView` | AllowAny | `getCandidateDetails` |

### Голосование
| Метод | Endpoint | View | Auth | FE |
|---|---|---|---|---|
| POST | `/api/v1/voting/cast/` | `CastVoteView` | `IsStudentAuthenticated` | `castVote` |
| GET | `/api/v1/voting/status/<uuid>/` | `VoteStatusView` | `IsStudentAuthenticated` | `getVotingStatus` |

### Админ: аутентификация и пользователи
| Метод | Endpoint | View | Auth | FE |
|---|---|---|---|---|
| POST | `/api/v1/auth/admin/login/` | `AdminLoginView` | AllowAny | `adminLogin` |
| POST | `/api/v1/auth/admin/refresh/` | `TokenRefreshView` | AllowAny | нет |
| GET | `/api/v1/auth/admin/me/` | `AdminMeView` | `IsAdminUserWithRole` | `adminMe` |
| GET/POST | `/api/v1/auth/admin/users/` | `AdminUsersListView` | `IsSuperAdmin` | `getAdminUsers`, `createAdminUser` |
| GET/PATCH/DELETE | `/api/v1/auth/admin/users/<uuid>/` | `AdminUserDetailView` | `IsSuperAdmin` | `updateAdminUser`, `deleteAdminUser` |
| GET | `/api/v1/auth/admin/logs/` | `AdminActionLogsListView` | `IsSuperAdmin` | нет |

### Админ: университеты, студенты, выборы, кандидаты, контент
| Метод | Endpoint | Auth | FE |
|---|---|---|---|
| GET/POST | `/api/v1/admin/universities/` | GET `IsAdminUserWithRole` / POST `IsSuperAdmin` | `getAdminUniversities`, `createAdminUniversity` |
| GET/PATCH/DELETE | `/api/v1/admin/universities/<uuid>/` | DELETE `IsSuperAdmin`, иначе `IsAdminUserWithRole` | `updateAdminUniversity`, `deleteAdminUniversity` |
| POST | `/api/v1/admin/universities/toggle-registration/` | `IsAdminUserWithRole`+`IsNotObserver` | `toggleStudentRegistration` |
| POST | `/api/v1/admin/universities/<uuid>/toggle-registration/` | то же | `toggleStudentRegistration` |
| GET/POST | `/api/v1/admin/universities/<uuid>/faculties/` | `IsAdminUserWithRole` | `createAdminFaculty` |
| GET/PATCH/DELETE | `/api/v1/admin/universities/<uuid>/faculties/<uuid>/` | `IsAdminUserWithRole` | `deleteAdminFaculty` |
| GET/POST | `/api/v1/admin/universities/<uuid>/students/` | `IsAdminUserWithRole` | `getAdminStudents` |
| POST | `/api/v1/admin/universities/<uuid>/students/upload/` | +`IsNotObserver` | `uploadStudents` |
| GET/POST | `/api/v1/admin/students/` | `IsAdminUserWithRole` | `getAdminStudents` |
| GET/PATCH/DELETE | `/api/v1/admin/students/<uuid>/` | `IsAdminUserWithRole` | нет |
| GET | `/api/v1/admin/students/template/` | `IsAdminUserWithRole` | нет |
| GET | `/api/v1/admin/upload-batches/<uuid>/status/` | `IsAdminUserWithRole` | `getBatchStatus` |
| GET/POST | `/api/v1/admin/elections/` | `IsAdminUserWithRole` | `getAdminElections`, `createElection` |
| GET/PATCH/DELETE | `/api/v1/admin/elections/<uuid>/` | `IsAdminUserWithRole` | `updateElection`, `deleteElection` |
| POST | `/api/v1/admin/elections/<uuid>/{start,finish,cancel}/` | +`IsNotObserver` | `startElection`… |
| GET | `/api/v1/admin/elections/<uuid>/turnout/` | `IsAdminUserWithRole` | `getElectionTurnout` |
| GET | `/api/v1/admin/elections/<uuid>/results/` | `IsAdminUserWithRole` | `getElectionResults` |
| POST | `/api/v1/admin/elections/<uuid>/results/export/` | `IsAdminUserWithRole` | `exportElectionResults` |
| GET | `/api/v1/admin/elections/featured/` | `IsSuperAdmin` | `getAdminFeaturedElections` |
| PATCH | `/api/v1/admin/elections/<uuid>/featured/` | `IsSuperAdmin` | `updateElectionFeatured` |
| GET/POST | `/api/v1/admin/elections/<uuid>/candidates/` | `IsAdminUserWithRole`, пагинации нет | `getAdminCandidates`, `createCandidate` |
| POST | `/api/v1/admin/elections/<uuid>/candidates/reorder/` | +`IsNotObserver` | `reorderCandidates` |
| GET/PATCH/DELETE | `/api/v1/admin/candidates/<uuid>/` | `IsAdminUserWithRole` | `updateCandidate`, `deleteCandidate` |
| GET | `/api/v1/news/`, `/news/recent/`, `/news/<uuid>/` | AllowAny | `getNews`, `getRecentNews`, `getNewsDetail` |
| GET | `/api/v1/faqs/` | AllowAny, пагинации нет | `getFaqs` |
| GET | `/api/v1/pages/<slug>/` | AllowAny | `getStaticPage` |
| CRUD | `/api/v1/admin/content/news/[<uuid>/]` | `CanManageNews` | `getAdminNews`… |
| CRUD | `/api/v1/admin/content/faqs/[<uuid>/]` | `IsSuperAdmin` | `getAdminFaqs`… |
| GET | `/api/v1/admin/content/pages/` | `IsSuperAdmin`, пагинации нет | `getAdminStaticPages` |
| GET/PATCH | `/api/v1/admin/content/pages/<slug>/` | `IsSuperAdmin` | `updateAdminStaticPage` |

### Формат ошибок (жёсткий контракт)

`apps/core/exceptions.py::custom_exception_handler` и ручные ответы во views дают единый конверт:

```json
{"error": {"code": "<string>", "message": "<string>", "details": <any|null>}}
```

Фронтенд (`lib/api.ts`) читает ровно `data.error.code` и `data.error.message`. **Переименование
любого `error.code` ломает фронтенд.** Полный перечень кодов фиксируется в Task 2.

---

## File Structure

- Create `tests/__init__.py` — пустой, делает `tests` пакетом для discovery.
- Create `tests/contract/__init__.py` — пустой.
- Create `tests/contract/factories.py` — фабрики доменных объектов. Единственное место,
  где тесты знают, как собрать University/Student/Election/Candidate/AdminUser.
- Create `tests/contract/base.py` — `ContractTestCase` с `APIClient`, хелперами
  аутентификации и ассертами на форму ответа.
- Create `tests/contract/test_public_contract.py` — публичные GET-endpoints.
- Create `tests/contract/test_student_auth_contract.py` — регистрация/логин/профиль/OTP.
- Create `tests/contract/test_voting_contract.py` — `cast` и `status`, все `error.code`.
- Create `tests/contract/test_admin_elections_contract.py` — жизненный цикл выборов, turnout, results, export.
- Create `tests/contract/test_admin_crud_contract.py` — университеты, студенты, кандидаты, контент, пользователи.
- Create `docs/API_CONTRACT.md` — карта endpoints, схемы, коды ошибок.
- Create `docs/FRONTEND_USAGE.md` — таблица вызовов фронтенда по ТЗ п.50.
- Create `docs/BASELINE.md` — baseline тестов и реестр найденных дефектов.

---

### Task 1: Каркас contract-тестов (фабрики + базовый TestCase)

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/contract/__init__.py`
- Create: `tests/contract/factories.py`
- Create: `tests/contract/base.py`
- Test: сам каркас проверяется smoke-тестом в `tests/contract/test_public_contract.py` (Task 3)

**Interfaces:**
- Produces:
  - `make_university(code: str = "test-uni", **kw) -> University`
  - `make_faculty(university, name: str = "ФИТ", **kw) -> Faculty`
  - `make_student(university, *, student_id="S-0001", email=None, password=None, **kw) -> Student`
  - `make_admin(*, email="admin@test.kg", password="adminpass123", role="super_admin", university=None) -> AdminUser`
  - `make_election(university, *, status=Election.Status.ACTIVE, starts_at=None, ends_at=None, **kw) -> Election`
  - `make_candidate(election, *, full_name="Кандидат", order=0, **kw) -> Candidate`
  - `student_token(student) -> str` — JWT того же формата, что выдаёт `create_student_token`
  - `ContractTestCase.as_student(student) -> None` — ставит `Authorization: Bearer <student jwt>`
  - `ContractTestCase.as_admin(admin, password) -> None` — логинится через `/api/v1/auth/admin/login/`
  - `ContractTestCase.as_anonymous() -> None` — снимает заголовок
  - `ContractTestCase.assertErrorEnvelope(response, code: str | None = None) -> dict`
  - `ContractTestCase.assertKeys(payload: dict, expected: set[str])` — точное совпадение набора ключей

- [ ] **Step 1: Создать пакеты**

```bash
mkdir -p tests/contract && touch tests/__init__.py tests/contract/__init__.py
```

- [ ] **Step 2: Написать `tests/contract/factories.py`**

```python
"""Фабрики доменных объектов для contract-тестов.

Единственное место, знающее, как собрать валидный объект каждой модели.
Тесты не создают модели напрямую — иначе изменение схемы правит десятки файлов.
"""
from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.utils import timezone

from apps.accounts.models import AdminUser
from apps.candidates.models import Candidate
from apps.elections.models import Election
from apps.students.models import Student
from apps.universities.models import Faculty, University


def make_university(code="test-uni", **kw):
    defaults = {
        "name": "Тестовый университет",
        "name_ky": "Сыноо университети",
        "code": code,
        "is_active": True,
        "is_registration_open": True,
    }
    defaults.update(kw)
    return University.objects.create(**defaults)
```

Остальные фабрики — по тому же шаблону, сигнатуры из блока **Interfaces**.
`make_student` хэширует пароль через `make_password`, если он передан.
`make_election` по умолчанию: `starts_at = now - 1h`, `ends_at = now + 1h`, `status = ACTIVE`.
`student_token` повторяет payload из `apps/students/views.py::create_student_token`
(`token_type='student'`, `student_id`, `university_id`, `student_code`, `exp`, `iat`,
HS256 на `settings.SECRET_KEY`) — **импортировать функцию из views нельзя**: тест должен
ломаться, если формат токена изменят молча.

- [ ] **Step 3: Написать `tests/contract/base.py`**

```python
class ContractTestCase(TestCase):
    """База для contract-тестов: клиент, аутентификация, ассерты формы ответа."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def as_student(self, student):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {student_token(student)}")

    def as_admin(self, admin, password="adminpass123"):
        res = self.client.post(
            "/api/v1/auth/admin/login/",
            {"email": admin.email, "password": password},
            format="json",
        )
        assert res.status_code == 200, f"admin login failed: {res.status_code} {res.data}"
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")
        return res.data

    def as_anonymous(self):
        self.client.credentials()

    def assertErrorEnvelope(self, response, code=None):
        """Проверяет конверт {"error": {"code", "message", "details"}} — контракт lib/api.ts."""
        self.assertIn("error", response.data, f"нет конверта error: {response.data}")
        err = response.data["error"]
        self.assertIn("code", err)
        self.assertIn("message", err)
        self.assertTrue(err["message"], "message не должен быть пустым")
        if code is not None:
            self.assertEqual(err["code"], code)
        return err

    def assertKeys(self, payload, expected):
        self.assertEqual(set(payload.keys()), set(expected))
```

- [ ] **Step 4: Проверить, что discovery видит пакет**

Run: `python3 manage.py test tests -v 1`
Expected: `Ran 0 tests` и `OK` — пакет найден, тестов пока нет.

- [ ] **Step 5: Commit**

```bash
git add tests/ && git commit -m "test: add contract test scaffolding (factories, base case)"
```

---

### Task 2: Документ API-контракта

**Files:**
- Create: `docs/API_CONTRACT.md`

**Interfaces:**
- Consumes: инвентарь endpoints из шапки этого плана.
- Produces: справочник, на который ссылаются `docs/FRONTEND_USAGE.md` и все последующие этапы.

- [ ] **Step 1: Перенести инвентарь endpoints** из шапки плана в `docs/API_CONTRACT.md`,
      разбив по разделам (служебные, публичные, студент-auth, выборы, голосование, админ).

- [ ] **Step 2: Для каждого не-CRUD endpoint задокументировать точную форму запроса и ответа.**
      Минимум: `POST /voting/cast/`, `GET /voting/status/<id>/`, `POST .../register/`,
      `POST .../login/`, `GET .../me/`, `GET /elections/available/`, `GET /elections/<id>/`,
      `POST /admin/elections/<id>/{start,finish,cancel}/`, `GET .../turnout/`, `GET .../results/`,
      `POST .../results/export/`, `POST .../toggle-registration/`, `POST .../students/upload/`.

- [ ] **Step 3: Собрать полную таблицу `error.code`** — grep по репозиторию:

```bash
grep -rhno '"code": "[a-z_0-9]*"' apps/ | sed 's/.*"code": "//;s/"//' | sort -u
```

      Для каждого кода указать: HTTP-статус, endpoint, когда возникает.
      Отметить, что переименование кода ломает фронтенд.

- [ ] **Step 4: Зафиксировать, какие списки пагинированы, а какие — голый массив.**
      Отметить, что `lib/api.ts` обрабатывает обе формы (`Array.isArray(res) ? res : res.results`),
      поэтому переход list→paginated обратно совместим, но менять без нужды нельзя.

- [ ] **Step 5: Commit**

```bash
git add docs/API_CONTRACT.md && git commit -m "docs: add API contract map"
```

---

### Task 3: Contract-тесты публичных endpoints

**Files:**
- Create: `tests/contract/test_public_contract.py`

**Interfaces:**
- Consumes: `make_university`, `make_faculty`, `make_election`, `make_candidate`, `ContractTestCase`.

**Перечень тестов:**

| Тест | Проверяет |
|---|---|
| `test_health_endpoint` | `GET /api/health/` → 200, `{"status": "healthy", "service": "dobush-backend"}` |
| `test_api_root_lists_endpoints` | `GET /api/` → 200, есть ключи `status`, `version`, `endpoints` |
| `test_universities_list_is_bare_array` | `GET /api/v1/universities/` → 200, тип `list` (не пагинирован), элемент содержит `id,name,name_ky,code,logo,is_active,is_registration_open,faculties` |
| `test_universities_list_excludes_inactive` | неактивный вуз не попадает в выдачу |
| `test_university_info_by_code` | `GET /api/v1/universities/<code>/info/` → 200, те же поля |
| `test_university_info_unknown_code_404` | → 404, `error.code == "not_found"` |
| `test_university_faculties_public` | `GET /api/v1/universities/<uuid>/faculties/` → 200, элемент `{id,name,name_ky,code}` |
| `test_recent_elections_is_bare_array` | `GET /api/v1/elections/recent/` → 200, тип `list`, элемент содержит `candidates_count`, `is_voting_open`, `university_details` |
| `test_recent_elections_excludes_cancelled` | отменённые выборы не попадают |
| `test_elections_public_alias_matches_recent` | `/elections/public/` возвращает то же, что `/elections/recent/` |
| `test_election_detail_anonymous` | `GET /api/v1/elections/<uuid>/` → 200, есть `candidates`, `has_voted is False`, `is_eligible is None` |
| `test_election_detail_not_found` | → 404, `error.code == "not_found"` |
| `test_election_candidates_public` | `GET /api/v1/elections/<uuid>/candidates/` → 200, список, порядок по `order` |
| `test_election_candidates_unknown_election_404` | → 404, `error.code == "not_found"` |
| `test_candidate_public_detail` | `GET /api/v1/candidates/<uuid>/` → 200, поля `CandidatePublicSerializer` |
| `test_news_faqs_pages_public` | `GET /news/`, `/news/recent/`, `/faqs/`, `/pages/<slug>/` → 200 и ожидаемая форма |

- [ ] **Step 1: Написать тесты по таблице (сначала падающие — файла ещё нет)**

Образец, задающий стиль для остальных:

```python
class PublicUniversitiesContractTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university(code="kstu", name="КГТУ")
        make_faculty(self.uni, name="ФИТ")

    def test_universities_list_is_bare_array(self):
        res = self.client.get("/api/v1/universities/")
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.data, list)  # НЕ пагинировано — контракт getUniversities()
        self.assertKeys(res.data[0], {
            "id", "name", "name_ky", "code", "logo",
            "is_active", "is_registration_open", "faculties",
        })
```

- [ ] **Step 2: Прогнать и убедиться, что тесты действительно исполняются**

Run: `python3 manage.py test tests.contract.test_public_contract -v 2`
Expected: все PASS. Любой FAIL здесь — расхождение между планом и реальным кодом:
разобраться и поправить **тест** (не приложение), потому что этап 0 фиксирует факт.

- [ ] **Step 3: Commit**

```bash
git add tests/contract/test_public_contract.py
git commit -m "test: pin public API contract"
```

---

### Task 4: Contract-тесты студенческой аутентификации

**Files:**
- Create: `tests/contract/test_student_auth_contract.py`

**Interfaces:**
- Consumes: `make_university`, `make_student`, `ContractTestCase`.

**Перечень тестов:**

| Тест | Проверяет |
|---|---|
| `test_register_returns_token_student_and_university` | `POST /api/v1/auth/student/register/` → 201; верхний уровень ровно `{student_token, student, university}`; `student` = `{id,student_id,full_name,email,photo,group,faculty,course}`; `university` = `{id,name,name_ky,code}` |
| `test_register_duplicate_email_400` | повтор → 400, `error.code == "email_already_exists"` |
| `test_register_unknown_university_404` | → 404, `error.code == "university_not_found"` |
| `test_register_when_registration_closed_403` | `is_registration_open=False` → 403, `error.code == "registration_closed"` |
| `test_register_validation_error_envelope` | `course=99` → 400 и конверт `error` |
| `test_login_returns_same_shape_as_register` | `POST .../login/` → 200, набор ключей совпадает с register |
| `test_login_wrong_password_400` | → 400, `error.code == "invalid_credentials"` |
| `test_login_unknown_email_400_same_code` | тот же код — не раскрывает существование аккаунта |
| `test_login_inactive_student_400` | `is_active=False` → 400, `invalid_credentials` |
| `test_profile_get_requires_student_token` | без токена → 403 (`IsStudentAuthenticated`) |
| `test_profile_get_shape` | → 200, `{student, university}`, те же ключи |
| `test_profile_patch_updates_full_name` | PATCH `full_name` → 200 и новое значение |
| `test_both_auth_mount_points_work` | `/api/v1/auth/student/login/` и `/api/v1/students/auth/login/` дают одинаковый результат |
| `test_identify_returns_request_id_and_expiry` | `POST .../identify/` → 200, ключи `request_id`, `message`, `expires_in_seconds` (+`demo_code` при DEBUG) |
| `test_identify_unknown_university_404` | → 404, `university_not_found` |
| `test_identify_unknown_student_404` | → 404, `student_not_found` |
| `test_identify_phone_mismatch_400` | → 400, `phone_mismatch` |
| `test_verify_returns_student_token` | **`@unittest.expectedFailure`** — намеренный контракт: 200 и `{student_token, student, university}`. Сейчас view не возвращает Response → 500. См. `docs/BASELINE.md` дефект **D-01** |
| `test_verify_invalid_session_400` | несуществующий `request_id` → 400, `invalid_session` (этот путь работает) |
| `test_verify_expired_code_400` | истёкший → 400, `code_expired` |
| `test_verify_wrong_code_400` | неверный код → 400, `invalid_code` |

- [ ] **Step 1: Написать тесты по таблице**

Дефектный кейс оформляется так — тест описывает намерение фронтенда, а не текущий 500:

```python
@unittest.expectedFailure
def test_verify_returns_student_token(self):
    """D-01: StudentVerifyView не возвращает Response → 500.

    Фронтенд (app/vote/[university_code]/verify/page.tsx) ожидает
    {student_token, student, university}. Снять expectedFailure после
    исправления на этапе 2.
    """
    identify = self.client.post("/api/v1/auth/student/identify/", {...}, format="json")
    res = self.client.post("/api/v1/auth/student/verify/", {
        "request_id": identify.data["request_id"],
        "code": identify.data["demo_code"],
    }, format="json")
    self.assertEqual(res.status_code, 200)
    self.assertIn("student_token", res.data)
```

- [ ] **Step 2: Прогнать**

Run: `python3 manage.py test tests.contract.test_student_auth_contract -v 2`
Expected: все PASS, ровно один `expected failure` (D-01).

- [ ] **Step 3: Commit**

```bash
git add tests/contract/test_student_auth_contract.py
git commit -m "test: pin student auth contract, record OTP verify defect D-01"
```

---

### Task 5: Contract-тесты голосования

**Files:**
- Create: `tests/contract/test_voting_contract.py`

**Interfaces:**
- Consumes: `make_university`, `make_student`, `make_election`, `make_candidate`, `ContractTestCase`.

**Перечень тестов:**

| Тест | Проверяет |
|---|---|
| `test_cast_vote_success_shape` | `POST /api/v1/voting/cast/` → **200** (не 201), тело ровно `{"success": true, "message": <str>}` |
| `test_cast_vote_requires_student_auth` | без токена → 403 |
| `test_cast_vote_admin_token_rejected` | админский JWT → 403 (`IsStudentAuthenticated`) |
| `test_cast_vote_already_voted` | второй раз → 400, `error.code == "already_voted"` |
| `test_cast_vote_election_not_active` | FINISHED → 400, `election_not_active` |
| `test_cast_vote_before_starts_at` | окно не наступило → 400, `election_not_active` |
| `test_cast_vote_after_ends_at` | окно закрыто → 400, `election_not_active` |
| `test_cast_vote_cancelled_election` | CANCELLED → 400, `election_not_active` |
| `test_cast_vote_other_university` | чужой вуз → 400, `ineligible_student` |
| `test_cast_vote_candidate_from_other_election` | чужой кандидат → 400, `invalid_candidate` |
| `test_cast_vote_unknown_election` | несуществующие выборы → 400, `election_not_found` |
| `test_cast_vote_malformed_body_400` | без `candidate_id` → 400 и конверт `error` |
| `test_vote_status_before_and_after` | `GET /voting/status/<id>/` → 200, `{has_voted, voted_at}`; до голоса `False/None`, после — `True` и непустой `voted_at` |
| `test_vote_status_requires_student_auth` | без токена → 403 |
| `test_vote_creates_exactly_one_record_and_one_ballot` | после успеха `VoteRecord.count()==1` и `Ballot.count()==1` |
| `test_ballot_carries_no_student_reference` | у `Ballot` нет поля, ссылающегося на студента — дублирует структурный инвариант на уровне API-теста |

- [ ] **Step 1: Написать тесты по таблице**

- [ ] **Step 2: Прогнать**

Run: `python3 manage.py test tests.contract.test_voting_contract -v 2`
Expected: все PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/contract/test_voting_contract.py
git commit -m "test: pin voting API contract and error codes"
```

---

### Task 6: Contract-тесты админского жизненного цикла выборов

**Files:**
- Create: `tests/contract/test_admin_elections_contract.py`

**Interfaces:**
- Consumes: `make_admin`, `make_university`, `make_election`, `make_candidate`, `make_student`,
  `ContractTestCase.as_admin`.

**Перечень тестов:**

| Тест | Проверяет |
|---|---|
| `test_admin_login_returns_access_refresh_user` | `POST /api/v1/auth/admin/login/` → 200, ключи `access`, `refresh`, `user`; `user` содержит `role`, `university_details` |
| `test_admin_login_wrong_password` | → 400 и конверт `error` |
| `test_admin_me` | `GET /auth/admin/me/` → 200, поля `AdminUserSerializer` |
| `test_elections_list_is_paginated` | `GET /admin/elections/` → 200, ключи `count,next,previous,results` |
| `test_election_create_shape` | POST → 201, поля `ElectionSerializer`, `candidates_count == 0`, `cover_image == ""` |
| `test_election_detail_patch` | PATCH `title` → 200 и новое значение |
| `test_start_election_returns_success_status` | `POST .../start/` → 200, `{success, message, status}`; `status == "active"` |
| `test_start_election_without_candidates_400` | → 400, `error.code == "no_candidates"` |
| `test_finish_election` | → 200, `status == "finished"` |
| `test_cancel_election` | → 200, `status == "cancelled"` |
| `test_lifecycle_endpoints_404_for_unknown_id` | start/finish/cancel на чужой uuid → 404, `not_found` |
| `test_lifecycle_endpoints_403_for_foreign_university_admin` | админ чужого вуза → 403, `forbidden` |
| `test_turnout_shape` | `GET .../turnout/` → 200, ключи `election_id,election_title,status,starts_at,ends_at,total_eligible,total_voted,turnout_percent` |
| `test_turnout_counts_votes` | после 1 голоса при 2 активных студентах → `total_voted == 1`, `turnout_percent == 50.0` |
| `test_results_hidden_before_finish` | ACTIVE и флаг False → 403, `error.code == "results_hidden"` |
| `test_results_visible_when_flag_enabled` | флаг True → 200 |
| `test_results_shape_after_finish` | → 200, ключи `election_id,election_title,university_name,total_eligible,total_voted,turnout_percent,candidates`; элемент `candidates` = `{candidate_id,full_name,photo,photo_url,faculty,course,position,votes,percent}` |
| `test_results_sorted_by_votes_desc` | лидер первым |
| `test_results_export_returns_xlsx` | `POST .../results/export/` → 200, `Content-Type` содержит `spreadsheetml`, заголовок `attachment; filename="results_<id>.xlsx"` |
| `test_results_export_hidden_before_finish_403` | → 403, `results_hidden` |
| `test_delete_active_election_is_rejected` | **`@unittest.expectedFailure`** — намеренный контракт: 400 и `error.code == "active_election"`. Сейчас `perform_destroy` возвращает `Response`, который DRF игнорирует → **204 и выборы реально удаляются**. Дефект **D-02** |
| `test_delete_draft_election_204` | черновик удаляется корректно → 204 |
| `test_featured_list_requires_superadmin` | админ вуза → 403 |
| `test_featured_patch_toggles_flag` | PATCH `is_featured=true` → 200 и флаг выставлен |

- [ ] **Step 1: Написать тесты по таблице**

Дефект D-02 оформляется так:

```python
@unittest.expectedFailure
def test_delete_active_election_is_rejected(self):
    """D-02: perform_destroy возвращает Response, который DRF игнорирует.

    Ожидаемое поведение (уже заложенное в коде намерение): 400 active_election.
    Фактическое: 204 и активные выборы удаляются вместе с голосами (CASCADE).
    Снять expectedFailure после исправления на этапе 2.
    """
    res = self.client.delete(f"/api/v1/admin/elections/{self.election.id}/")
    self.assertEqual(res.status_code, 400)
    self.assertErrorEnvelope(res, "active_election")
```

- [ ] **Step 2: Прогнать**

Run: `python3 manage.py test tests.contract.test_admin_elections_contract -v 2`
Expected: все PASS, ровно один `expected failure` (D-02).

- [ ] **Step 3: Commit**

```bash
git add tests/contract/test_admin_elections_contract.py
git commit -m "test: pin admin election lifecycle contract, record delete defect D-02"
```

---

### Task 7: Contract-тесты остального админского CRUD

**Files:**
- Create: `tests/contract/test_admin_crud_contract.py`

**Перечень тестов:**

| Тест | Проверяет |
|---|---|
| `test_admin_universities_list` | → 200, пагинировано, элемент содержит `students_count`, `active_elections_count`, `faculties` |
| `test_create_university_requires_superadmin` | админ вуза POST → 403 |
| `test_create_university_with_faculties_input` | `faculties_input: ["ФИТ","ИЭФ"]` → 201 и 2 факультета в ответе |
| `test_delete_university_requires_superadmin` | → 403 для не-superadmin |
| `test_toggle_registration_by_id` | `POST /admin/universities/<id>/toggle-registration/` → 200, ключи `id,name,is_registration_open,message` |
| `test_toggle_registration_all_requires_superadmin` | `{"all": true}` от админа вуза → 403, `forbidden` |
| `test_admin_students_list_paginated` | `GET /admin/students/` → 200, `count,next,previous,results`; элемент содержит `has_voted`, `voted_at`, `votes_count` |
| `test_admin_students_scoped_to_own_university` | админ вуза видит только своих |
| `test_admin_students_filter_voted` | `?voted=true` отдаёт только проголосовавших |
| `test_admin_students_search` | `?search=<имя>` фильтрует |
| `test_student_upload_returns_202_batch_id` | `POST .../students/upload/` с CSV → 202, ключи `batch_id,message,file_name` |
| `test_student_upload_without_file_400` | → 400, `file_required` |
| `test_batch_status_shape` | `GET /admin/upload-batches/<id>/status/` → 200, поля `UploadBatchSerializer` |
| `test_students_template_csv_and_xlsx` | `?format=csv` → `text/csv`; `?format=xlsx` → spreadsheetml |
| `test_admin_candidates_list_not_paginated` | `GET /admin/elections/<id>/candidates/` → 200, тип `list` |
| `test_create_candidate_inherits_university` | POST → 201, `university` = вуз выборов |
| `test_candidate_bio_length_validation` | `short_bio` > 100 символов → 400 и конверт `error` |
| `test_reorder_candidates` | POST `ordered_ids` → 200, `{success, message}`, порядок применён |
| `test_admin_users_crud_superadmin_only` | список/создание/удаление доступны только superadmin |
| `test_admin_logs_list` | `GET /auth/admin/logs/` → 200, пагинировано |
| `test_admin_news_faq_pages_crud` | создание/чтение/обновление новостей, FAQ и страниц отдают ожидаемые статусы и поля |

- [ ] **Step 1: Написать тесты по таблице**

- [ ] **Step 2: Прогнать**

Run: `python3 manage.py test tests.contract.test_admin_crud_contract -v 2`
Expected: все PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/contract/test_admin_crud_contract.py
git commit -m "test: pin admin CRUD contract"
```

---

### Task 8: Карта использования API фронтендом

**Files:**
- Create: `docs/FRONTEND_USAGE.md`

**Interfaces:**
- Consumes: `lib/api.ts` фронтенда (`ibrodevs/Vote-platform-frontend`), `docs/API_CONTRACT.md`.

- [ ] **Step 1: Построить таблицу по ТЗ п.50** — колонки:
      `Frontend call` | `HTTP method` | `Endpoint` | `Request` | `Response` | `Auth`.
      Источник — экспорт `api` из `lib/api.ts` (около 60 методов).

- [ ] **Step 2: Зафиксировать механику авторизации фронтенда** (`lib/api.ts::request`):
      `student_token` в `sessionStorage`, `admin_token` в `localStorage`; для путей,
      содержащих `/admin/`, берётся админский токен; для `register/login/identify/verify`
      токен не шлётся; иначе — студенческий, при его отсутствии админский.
      **Следствие:** любое изменение формата `Authorization` ломает оба клиента сразу.

- [ ] **Step 3: Зафиксировать обработку ошибок фронтендом** — `ApiError(err.message, err.code, err.details)`
      из `data.error`. Отсюда прямое требование: конверт и коды неизменны.

- [ ] **Step 4: Зафиксировать толерантность к пагинации** — фронтенд везде пишет
      `Array.isArray(res) ? res : res.results`, поэтому list↔paginated обратно совместимо.

- [ ] **Step 5: Отдельным разделом «Расхождения и дефекты»** записать замеченное со стороны
      фронтенда, **не меняя backend-контракт** (ТЗ п.50): страницы
      `app/vote/[university_code]/login` и `.../verify` реализуют OTP-вход, который сейчас
      не может работать из-за D-01.

- [ ] **Step 6: Commit**

```bash
git add docs/FRONTEND_USAGE.md && git commit -m "docs: map frontend API usage"
```

---

### Task 9: Baseline, реестр дефектов и полный прогон

**Files:**
- Create: `docs/BASELINE.md`
- Modify: `docs/superpowers/plans/2026-09-20-highload-roadmap.md` (отметить этап 0 выполненным)

**Interfaces:**
- Consumes: результаты Task 1–8.
- Produces: `docs/BASELINE.md` с идентификаторами дефектов **D-01…D-NN**, на которые
  ссылаются `expectedFailure`-тесты и планы этапов 2+.

- [ ] **Step 1: Зафиксировать baseline существующих тестов**

Run: `python3 manage.py test apps -v 1`
Expected: `Ran 12 tests ... OK` (SQLite). Записать в `docs/BASELINE.md`.

- [ ] **Step 2: Полный прогон всего набора**

Run: `python3 manage.py test -v 1`
Expected: все PASS + ровно 2 `expected failures` (D-01, D-02). Записать итоговые числа.

- [ ] **Step 3: Заполнить реестр дефектов.** Для каждого: ID, файл и строка, суть,
      последствие, пункт ТЗ, этап исправления, есть ли `expectedFailure`-тест.
      Минимум — дефекты, подтверждённые аудитом кода и прогоном:
      D-01 (OTP verify → 500), D-02 (удаление активных выборов → ложный 204),
      плюс наблюдения по производительности и безопасности из таблицы в roadmap.

- [ ] **Step 4: Убедиться, что приложение не изменено**

Run: `git diff --stat HEAD -- apps/ config/`
Expected: пустой вывод. Этап 0 не трогает приложение.

- [ ] **Step 5: Commit**

```bash
git add docs/BASELINE.md docs/superpowers/plans/
git commit -m "docs: record stage 0 baseline and defect registry"
```

---

## Definition of Done этапа 0

- [ ] `python3 manage.py test` зелёный: 12 существующих + новые contract-тесты, ровно 2 expected failures.
- [ ] `docs/API_CONTRACT.md` покрывает все смонтированные endpoints и все `error.code`.
- [ ] `docs/FRONTEND_USAGE.md` содержит таблицу по ТЗ п.50 для всех вызовов `lib/api.ts`.
- [ ] `docs/BASELINE.md` содержит baseline и пронумерованный реестр дефектов.
- [ ] `git diff HEAD -- apps/ config/` пуст — поведение приложения не тронуто.
