# API Contract — Vote Platform Backend

**Зафиксировано:** 2026-09-20, ветка `stage-0-api-contract`, коммит-база `c577e60`.
**Статус:** baseline перед high-load рефакторингом (ТЗ п.2, 49, 121).

Этот документ описывает **фактическое** поведение API на момент фиксации, а не желаемое.
Каждое утверждение здесь подкреплено тестом в `tests/contract/`. Если код и документ
расходятся — прав тест; документ обновляется вместе с ним.

**Правило совместимости (ТЗ п.49):** не переименовывать endpoints, не удалять и не
переименовывать поля ответа, не менять типы полей, не менять успешные HTTP-статусы,
не менять `error.code`. Новые поля добавлять можно.

---

## 1. Формат ошибок — жёсткий контракт

Все ошибки (и из `custom_exception_handler`, и написанные во views вручную) имеют вид:

```json
{"error": {"code": "<string>", "message": "<string>", "details": <any|null>}}
```

Фронтенд `lib/api.ts` читает ровно `data.error.code` и `data.error.message` и заворачивает
их в `ApiError`. **Переименование любого кода ломает фронтенд.**

### Реестр кодов

| `error.code` | HTTP | Где возникает |
|---|---|---|
| `already_voted` | 400 | `POST /voting/cast/` — у студента уже есть `VoteRecord` в этих выборах |
| `election_not_active` | 400 | `POST /voting/cast/` — статус ≠ ACTIVE **или** время вне `[starts_at, ends_at]` |
| `election_not_found` | 400 | `POST /voting/cast/` — выборов с таким id нет (**400**, не 404) |
| `ineligible_student` | 400 | `POST /voting/cast/` — университет студента ≠ университет выборов |
| `invalid_candidate` | 400 | `POST /voting/cast/` — кандидат не принадлежит этим выборам |
| `voting_error` | 400 | базовый код `VotingError`, если подкласс не задал свой |
| `email_already_exists` | 400 | `POST .../register/` |
| `registration_closed` | 403 | `POST .../register/` — `university.is_registration_open == False` |
| `university_not_found` | 404 | register, identify, toggle-registration |
| `student_not_found` | 404 | `POST .../identify/` |
| `phone_mismatch` | 400 | `POST .../identify/` — не совпали последние 9 цифр |
| `invalid_credentials` | 400 | `POST .../login/` — и неверный пароль, и несуществующий email, и `is_active=False` |
| `invalid_session` | 400 | `POST .../verify/` — нет `StudentAuthSession` с таким `request_id` |
| `already_verified` | 400 | `POST .../verify/` — сессия уже использована |
| `code_expired` | 400 | `POST .../verify/` — `expires_at` в прошлом |
| `invalid_code` | 400 | `POST .../verify/` — код не совпал |
| `too_many_attempts` | 429 | `POST .../verify/` — `attempts >= SMS_MAX_ATTEMPTS` |
| `not_found` | 404 | общий код для «объект не найден» в 12 местах |
| `forbidden` | 403 | доступ ограничен своим университетом / роль не позволяет (9 мест) |
| `no_candidates` | 400 | `POST /admin/elections/<id>/start/` без кандидатов |
| `active_election` | 400 | задуман для `DELETE /admin/elections/<id>/` активных выборов — **см. дефект D-02: сейчас не отдаётся** |
| `results_hidden` | 403 | results и results/export до завершения при выключенном флаге |
| `file_required` | 400 | `POST .../students/upload/` без файла |
| `missing_university` | 400 | `toggle-registration` без id и без вуза у админа |
| `missing_id` | 400 | `PATCH /admin/elections/featured/` без id |
| `internal_server_error` | 500 | необработанное исключение; **`message` сейчас содержит `str(exc)`** — утечка внутренностей, см. ТЗ п.65 |

---

## 2. Аутентификация

Единый заголовок: `Authorization: Bearer <token>`. Обрабатывается
`apps.core.authentication.CombinedJWTAuthentication`, которая различает два типа токенов.

### Студенческий JWT

Выпускается `apps/students/views.py::create_student_token`, HS256 на `settings.SECRET_KEY`:

```json
{
  "token_type": "student",
  "student_id": "<uuid>",
  "university_id": "<uuid>",
  "student_code": "<Student.student_id>",
  "exp": <unix, +7 дней>,
  "iat": <unix>
}
```

Распознаётся по `token_type == "student"`. Далее делается
`Student.objects.select_related('university').get(id=student_id)` — **запрос в БД на каждый
request** (ТЗ п.18, устраняется на этапе 3). `is_active` **не проверяется** (см. D-04).

### Админский JWT

`rest_framework_simplejwt`, выдаётся `POST /api/v1/auth/admin/login/`. В refresh-токен
дописываются `role` и `university_id`.

### Права

| Класс | Правило |
|---|---|
| `IsStudentAuthenticated` | `request.user.is_student` истинно; иначе **403** (не 401) |
| `IsAdminUserWithRole` | `super_admin` и `university_admin` — полный доступ; `observer` — только SAFE_METHODS |
| `IsNotObserver` | запрещает `observer` |
| `IsSuperAdmin` | только `super_admin` / `is_superuser` |
| `IsUniversityAdmin` | плюс проверка совпадения университета объекта |

---

## 3. Служебные endpoints

| Метод | Endpoint | Ответ |
|---|---|---|
| GET | `/`, `/api/` | `{status: "online", message, version, endpoints{}}` |
| GET | `/api/health/` | `{"status": "healthy", "service": "dobush-backend"}` |

Тяжёлых проверок нет — это фактически liveness-проба (ТЗ п.43 добавит `/health/live` и `/health/ready`).

---

## 4. Публичные endpoints

| Метод | Endpoint | Auth | Форма | Тест |
|---|---|---|---|---|
| GET | `/api/v1/universities/` | — | **голый массив** | `test_universities_list_is_bare_array` |
| GET | `/api/v1/universities/<code>/info/` | — | объект | `test_university_info_by_code` |
| GET | `/api/v1/universities/<uuid>/faculties/` | — | **пагинировано** | `test_university_faculties_public_is_paginated` |
| POST | `/api/v1/universities/<uuid>/faculties/` | admin | объект | — |
| GET | `/api/v1/elections/recent/` | — | **голый массив**, до 6 шт | `test_recent_elections_is_bare_array` |
| GET | `/api/v1/elections/public/` | — | алиас `recent/` | `test_elections_public_alias_matches_recent` |
| GET | `/api/v1/elections/<uuid>/` | — | объект + `has_voted`, `is_eligible` | `test_election_detail_anonymous` |
| GET | `/api/v1/elections/<uuid>/candidates/` | — | **голый массив**, сортировка `order, created_at` | `test_election_candidates_public_ordered` |
| GET | `/api/v1/candidates/<uuid>/` | — | объект | `test_candidate_public_detail` |
| GET | `/api/v1/news/` | — | **пагинировано** | `test_news_list_is_paginated` |
| GET | `/api/v1/news/recent/` | — | **голый массив** | `test_news_recent_is_bare_array` |
| GET | `/api/v1/news/<uuid>/` | — | объект | `test_news_detail` |
| GET | `/api/v1/faqs/` | — | **голый массив** | `test_faqs_list_is_bare_array` |
| GET | `/api/v1/pages/<slug>/` | — | объект | `test_static_page_by_slug` |

**University (публичный):** `id, name, name_ky, code, logo, is_active, is_registration_open, faculties[]`
Неактивные вузы из списка исключены. `faculties[] = {id, name, name_ky, code}`.

**Election (`ElectionSerializer`, используется в `recent/`):**
`id, university, university_details, title, title_ky, description, description_ky, status,
starts_at, ends_at, results_visible_to_admin_before_finish, is_featured, featured_order,
cover_image, cover_image_url, created_by, created_by_name, candidates_count, is_voting_open,
created_at, updated_at`

`cover_image` нормализуется в `to_representation`: абсолютный URL файла → иначе `cover_image_url`
→ иначе **пустая строка** (никогда `null`). Отменённые выборы исключены.

**Election (`ElectionStudentSerializer`, используется в `available/` и детали):**
`id, university, university_name, university_name_ky, title, title_ky, description,
description_ky, status, starts_at, ends_at, candidates[]`
В detail-вьюхе к этому добавляются `has_voted` и `is_eligible` (для анонима — `false` и `null`).

**Candidate (публичный):** `id, election, election_title, university, university_name, full_name,
photo, photo_url, faculty, course, position, position_ky, short_bio, short_bio_ky, program,
program_ky, order`

**Статусы выборов:** `draft`, `scheduled`, `active`, `finished`, `cancelled`.

---

## 5. Студенческая аутентификация

Смонтировано **дважды**, оба пути обязаны работать:
`/api/v1/auth/student/...` (использует фронтенд) и `/api/v1/students/auth/...`
(используют существующие тесты). Тест: `test_both_auth_mount_points_work`.

### `POST .../register/` → **201**

Запрос: `{full_name, university_id, faculty?, course (1..6), group, email, password (≥6)}`

Ответ:
```json
{
  "student_token": "<jwt>",
  "student": {"id","student_id","full_name","email","photo","group","faculty","course"},
  "university": {"id","name","name_ky","code"}
}
```
`student.photo` при регистрации всегда `null`. `student_id` генерируется как `STU-XXXXXXXX`.
Ошибки: `university_not_found` 404, `registration_closed` 403, `email_already_exists` 400.

### `POST .../login/` → **200**

Запрос: `{email, password}`. Ответ — **та же структура**, что у register.
Ошибка: `invalid_credentials` 400 одинаково при неверном пароле, несуществующем email
и деактивированном студенте.

### `GET/PATCH .../me/` → **200**

Ответ: `{student{...}, university{...}}` — те же наборы ключей.
PATCH принимает `multipart` с `photo` и/или `full_name`, возвращает обновлённый профиль.
Без токена — **403**.

### `POST .../identify/` → **200**

Запрос: `{university_code, student_id, phone_number}`.
Ответ: `{request_id, message, expires_in_seconds}` + `demo_code` **только при `DEBUG=True`**.
Сверка телефона — по последним 9 цифрам.
Ошибки: `university_not_found` 404, `student_not_found` 404, `phone_mismatch` 400.

### `POST .../verify/` — **нерабочий (D-01)**

Намеренный контракт (его ждёт фронтенд): 200 и `{student_token, student, university}`.
Фактически view не возвращает `Response` → DRF бросает `AssertionError` → **500**.
Пути ошибок при этом работают: `invalid_session`, `already_verified`, `code_expired`,
`invalid_code` (400), `too_many_attempts` (429).

---

## 6. Голосование

### `POST /api/v1/voting/cast/` → **200** (не 201)

Auth: студенческий токен. Запрос: `{election_id, candidate_id}`.
Успех: `{"success": true, "message": "Ваш голос успешно и анонимно принят"}`.

Все бизнес-ошибки — **400** с конвертом `error`: `already_voted`, `election_not_active`,
`election_not_found`, `ineligible_student`, `invalid_candidate`.
Без токена или с админским токеном — **403**.

Проверки идут в порядке: существование выборов → статус ACTIVE → окно времени →
университет студента → кандидат принадлежит выборам → INSERT `VoteRecord` → INSERT `Ballot`.
Успешный голос создаёт ровно 1 `VoteRecord` и 1 `Ballot`; отклонённая попытка — ни одного.

### `GET /api/v1/voting/status/<election_id>/` → **200**

Ответ: `{has_voted: bool, voted_at: datetime|null}`.
Несуществующие выборы дают **200 с `has_voted: false`**, а не 404.
Без токена — 403.

---

## 7. Админские endpoints

### Аутентификация

| Метод | Endpoint | Ответ |
|---|---|---|
| POST | `/api/v1/auth/admin/login/` | `{access, refresh, user{...}}` |
| POST | `/api/v1/auth/admin/refresh/` | SimpleJWT `TokenRefreshView` |
| GET | `/api/v1/auth/admin/me/` | объект `AdminUser` |
| GET/POST | `/api/v1/auth/admin/users/` | **пагинировано**, только `IsSuperAdmin` |
| GET/PATCH/DELETE | `/api/v1/auth/admin/users/<uuid>/` | только `IsSuperAdmin` |
| GET | `/api/v1/auth/admin/logs/` | **пагинировано**, только `IsSuperAdmin` |

**AdminUser:** `id, email, full_name, role, university, university_details, is_active, created_at`.
`password` — write-only, в ответе отсутствует. Сериализатор принимает `university_id`
как алиас `university`. Для ролей `university_admin` и `observer` университет обязателен.
Роли: `super_admin`, `university_admin`, `observer`.

### Выборы

| Метод | Endpoint | Ответ |
|---|---|---|
| GET/POST | `/api/v1/admin/elections/` | **пагинировано** / 201 |
| GET/PATCH/DELETE | `/api/v1/admin/elections/<uuid>/` | объект / 204 |
| POST | `.../start/` | `{success, message, status: "active"}` |
| POST | `.../finish/` | `{success, message, status: "finished"}` |
| POST | `.../cancel/` | `{success, message, status: "cancelled"}` |
| GET | `.../turnout/` | см. ниже |
| GET | `.../results/` | см. ниже |
| POST | `.../results/export/` | xlsx-файл |
| GET | `/api/v1/admin/elections/featured/` | голый массив, `IsSuperAdmin` |
| PATCH | `/api/v1/admin/elections/<uuid>/featured/` | объект Election, `IsSuperAdmin` |

Фильтры списка: `status`, `university`, `is_featured`; поиск по `title, title_ky, description`;
сортировка по `starts_at, created_at, title, featured_order` (по умолчанию `-created_at`).
Админ вуза видит только свои выборы; для чужих start/finish/cancel → 403 `forbidden`.
`start` без кандидатов → 400 `no_candidates`.
`DELETE` активных выборов → **204, но ничего не удалено** (D-02).

**turnout:** `{election_id, election_title, status, starts_at, ends_at, total_eligible,
total_voted, turnout_percent}`.
`total_eligible` = активные студенты вуза, `total_voted` = `VoteRecord` этих выборов,
процент округлён до 2 знаков.

**results:** `{election_id, election_title, university_name, total_eligible, total_voted,
turnout_percent, candidates[]}`, где элемент =
`{candidate_id, full_name, photo, photo_url, faculty, course, position, votes, percent}`,
отсортирован по `votes` убывающе. Здесь `total_voted` считается по `Ballot` (в turnout — по `VoteRecord`).

Результаты скрыты, пока `status != finished` и `results_visible_to_admin_before_finish == False`
→ 403 `results_hidden`. То же правило у экспорта. **Оптимизация не должна это ослабить (ТЗ п.51).**

**export:** `Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`,
`Content-Disposition: attachment; filename="results_<election_id>.xlsx"`. Метод — **POST**.

### Университеты

| Метод | Endpoint | Права |
|---|---|---|
| GET/POST | `/api/v1/admin/universities/` | GET `IsAdminUserWithRole`, POST `IsSuperAdmin` |
| GET/PATCH/DELETE | `/api/v1/admin/universities/<uuid>/` | DELETE `IsSuperAdmin` |
| POST | `/api/v1/admin/universities/toggle-registration/` | `{all: true}` — только `IsSuperAdmin` |
| POST | `/api/v1/admin/universities/<uuid>/toggle-registration/` | +`IsNotObserver` |
| GET/POST | `/api/v1/admin/universities/<uuid>/faculties/` | `IsAdminUserWithRole` |
| GET/PATCH/DELETE | `/api/v1/admin/universities/<uuid>/faculties/<uuid>/` | `IsAdminUserWithRole` |

**University (админский):** `id, name, name_ky, code, logo, is_active, is_registration_open,
created_at, students_count, active_elections_count, faculties[]`.
`faculties_input: ["ФИТ", ...]` — write-only, создаёт/синхронизирует факультеты, в ответе отсутствует.

`toggle-registration` по id → `{id, name, is_registration_open, message}`;
с `{all: true}` → `{all, is_registration_open, message}`.
Без `is_registration_open` в теле значение инвертируется.

### Студенты

| Метод | Endpoint | Форма |
|---|---|---|
| GET/POST | `/api/v1/admin/students/` | **пагинировано** |
| GET/PATCH/DELETE | `/api/v1/admin/students/<uuid>/` | объект |
| GET | `/api/v1/admin/students/template/` | CSV; `?format=...` даёт 404 (D-03) |
| GET/POST | `/api/v1/admin/universities/<uuid>/students/` | **пагинировано** |
| POST | `/api/v1/admin/universities/<uuid>/students/upload/` | **202** |
| GET | `/api/v1/admin/upload-batches/<uuid>/status/` | объект |

**Student (админский):** `id, university, university_name, university_code, student_id,
full_name, phone_number, email, photo, faculty, group, course, is_active, has_voted,
voted_at, votes_count, created_at`.

Фильтры: `faculty`, `course`, `is_active`, `only_registered=true`, `voted=true|false`;
поиск по `student_id, full_name, phone_number, email, faculty`;
сортировка по `full_name, student_id, course, created_at` (по умолчанию `-created_at`).
Админ вуза видит только своих студентов.

**upload** → 202 `{batch_id, message, file_name}`; без файла → 400 `file_required`.
**UploadBatch:** `id, university, university_name, uploaded_by, uploaded_by_name, file_name,
total_rows, success_count, error_count, errors_detail, status, created_at`.
Статусы: `processing`, `completed`, `failed`.

### Кандидаты

| Метод | Endpoint | Форма |
|---|---|---|
| GET/POST | `/api/v1/admin/elections/<uuid>/candidates/` | **голый массив** (`pagination_class = None`) |
| POST | `/api/v1/admin/elections/<uuid>/candidates/reorder/` | `{success, message}` |
| GET/PATCH/DELETE | `/api/v1/admin/candidates/<uuid>/` | объект / 204 |

**Candidate (админский)** = публичный + `created_at`. `university` проставляется из выборов
автоматически и доступен только на чтение.
Валидация: `short_bio`, `short_bio_ky`, `program`, `program_ky` — не длиннее **100 символов**.
`reorder` принимает `{ordered_ids: [uuid, ...]}` и выставляет `order` по индексу.

### Контент

| Метод | Endpoint | Права | Форма |
|---|---|---|---|
| CRUD | `/api/v1/admin/content/news/[<uuid>/]` | `CanManageNews` | пагинировано |
| CRUD | `/api/v1/admin/content/faqs/[<uuid>/]` | `IsSuperAdmin` | — |
| GET | `/api/v1/admin/content/pages/` | `IsSuperAdmin` | **голый массив** |
| GET/PATCH | `/api/v1/admin/content/pages/<slug>/` | `IsSuperAdmin` | объект |

Категории новостей: `official`, `elections`, `tech`, `students`.

---

## 8. Пагинация

По умолчанию `PageNumberPagination`, `PAGE_SIZE = 20`, конверт `{count, next, previous, results}`.

Не пагинированы (`pagination_class = None`): `/universities/`, `/faqs/`,
`/admin/elections/<id>/candidates/`, `/admin/content/pages/`.
Возвращают голый массив, будучи `APIView`: `/elections/recent/`, `/elections/public/`,
`/elections/available/`, `/elections/<id>/candidates/`, `/news/recent/`,
`/admin/elections/featured/`.

Фронтенд везде пишет `Array.isArray(res) ? res : res.results`, поэтому переход
list → paginated обратно совместим. Но менять без необходимости нельзя (ТЗ п.49).

---

## 9. Медиа

`photo`, `logo`, `cover_image` отдаются абсолютным URL через `request.build_absolute_uri()`.
При отсутствии файла: `photo` → `photo_url` или `null`, `cover_image` → `cover_image_url`
или `""`. Сейчас файлы раздаёт сам Django (`django.views.static.serve` в `config/urls.py`) —
на этапе 7 это уходит в object storage/CDN **с сохранением тех же URL** (ТЗ п.31).

---

## 10. Известные дефекты

Полный реестр — в [BASELINE.md](BASELINE.md). Кратко: **D-01** (OTP verify → 500),
**D-02** (DELETE активных выборов лжёт о результате), **D-03** (xlsx-шаблон недостижим),
**D-04** (JWT не проверяет `is_active`).
