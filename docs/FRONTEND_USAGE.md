# Карта использования API фронтендом

**Источник:** `ibrodevs/Vote-platform-frontend`, коммит `1aeb7ef`, файл `lib/api.ts`.
**Зафиксировано:** 2026-09-20. Требование ТЗ п.50.

Фронтенд — Next.js. **Все** обращения к бэкенду идут через единственный модуль `lib/api.ts`
(63 метода в экспорте `api`). Отдельных `fetch` в обход него в `app/` и `components/` нет,
поэтому этот файл и есть полное описание того, что фронтенд ждёт от бэкенда.

`API_BASE = process.env.NEXT_PUBLIC_API_URL || 'https://voteplatformbackend.pythonanywhere.com/api/v1'`
— все пути ниже даны относительно `/api/v1`.

---

## 1. Механика авторизации (`lib/api.ts::request`)

| Условие пути | Какой токен подставляется |
|---|---|
| содержит `/admin/` | `localStorage.admin_token` |
| `/auth/student/{register,login,identify,verify}/` | никакой — публичные |
| иначе | `sessionStorage.student_token`, при отсутствии — `admin_token` |

Заголовок всегда `Authorization: Bearer <token>`.

**Следствия для рефакторинга:**
- Изменение формата заголовка ломает оба клиента одновременно.
- `student_token` живёт в `sessionStorage` — закрытие вкладки разлогинивает. Значит короткий
  TTL токена ударит по UX сильнее, чем кажется.
- Правило «путь содержит `/admin/`» — строковое. Переименование любого админского пути так,
  что из него исчезнет `/admin/`, молча лишит запрос токена.

## 2. Обработка ошибок

```js
const err = data.error || {};
throw new ApiError(err.message || '...', err.code || 'request_failed', err.details);
```

Читаются ровно `error.code`, `error.message`, `error.details`. Конверт и коды —
жёсткий контракт (реестр в [API_CONTRACT.md](API_CONTRACT.md#1-формат-ошибок--жёсткий-контракт)).

Особые случаи в клиенте:
- `204` → возвращается `{}` без парсинга тела.
- `Content-Type` с `spreadsheetml`, `octet-stream` или `csv` → ответ читается как `Blob`.
  Это касается `exportElectionResults`; при `!response.ok` бросается `export_failed`.
- Тело, которое не парсится как JSON, при `!ok` → `ApiError('Ошибка сервера (<status>)', 'server_error')`.
  **Поэтому 500 от D-01 приходит студенту как «Ошибка сервера (500)».**

## 3. Толерантность к пагинации

Во всех 22 местах потребления списков фронтенд пишет
`Array.isArray(res) ? res : (res?.results || [])`.

Значит переход «голый массив → пагинированный» обратно совместим, и наоборот.
Это единственная вольность, которую контракт допускает; менять форму без необходимости
всё равно нельзя (ТЗ п.49).

## 4. Таблица вызовов

`Auth`: `—` публичный, `S` студенческий токен, `A` админский токен.

### Университеты и факультеты
| Frontend call | Method | Endpoint | Request | Response | Auth |
|---|---|---|---|---|---|
| `getUniversities` | GET | `/universities/` | — | массив University | — |
| `getUniversityInfo` | GET | `/universities/{code}/info/` | — | University | — |
| `getUniversityFaculties` | GET | `/universities/{id}/faculties/` | — | пагинированные Faculty | — |

### Студенческая аутентификация
| Frontend call | Method | Endpoint | Request | Response | Auth |
|---|---|---|---|---|---|
| `studentRegister` | POST | `/auth/student/register/` | `{full_name, university_id, faculty?, course, group, email, password}` | `{student_token, student, university}` 201 | — |
| `studentPasswordLogin` | POST | `/auth/student/login/` | `{email, password}` | `{student_token, student, university}` | — |
| `getStudentProfile` | GET | `/auth/student/me/` | — | `{student, university}` | S |
| `studentIdentify` | POST | `/auth/student/identify/` | `{university_code, student_id, phone_number}` | `{request_id, message, expires_in_seconds}` | — |
| `studentVerify` | POST | `/auth/student/verify/` | `{request_id, code}` | `{student_token, student, university}` — **не работает, D-01** | — |

### Выборы и голосование
| Frontend call | Method | Endpoint | Request | Response | Auth |
|---|---|---|---|---|---|
| `getRecentElections` | GET | `/elections/recent/` | — | массив Election | — |
| `getAvailableElections` | GET | `/elections/available/[?all=true]` | — | массив Election + `has_voted` | S |
| `getElectionDetail` | GET | `/elections/{id}/` | — | Election + `has_voted`, `is_eligible` | S/— |
| `getElectionCandidates` | GET | `/elections/{id}/candidates/` | — | массив Candidate | — |
| `getCandidateDetails` | GET | `/candidates/{id}/` | — | Candidate | — |
| `castVote` | POST | `/voting/cast/` | `{election_id, candidate_id}` | `{success, message}` 200 | S |
| `getVotingStatus` | GET | `/voting/status/{id}/` | — | `{has_voted, voted_at?}` | S |

### Админ: аутентификация и пользователи
| Frontend call | Method | Endpoint | Request | Response | Auth |
|---|---|---|---|---|---|
| `adminLogin` | POST | `/auth/admin/login/` | `{email, password}` | `{access, refresh, user}` | — |
| `adminMe` | GET | `/auth/admin/me/` | — | AdminUser | A |
| `getAdminUsers` | GET | `/auth/admin/users/[?university&role]` | — | пагинированные AdminUser | A |
| `createAdminUser` | POST | `/auth/admin/users/` | `{email, password?, full_name, role, university_id?}` | AdminUser 201 | A |
| `updateAdminUser` | PATCH | `/auth/admin/users/{id}/` | частичный AdminUser | AdminUser | A |
| `deleteAdminUser` | DELETE | `/auth/admin/users/{id}/` | — | 204 | A |

### Админ: университеты
| Frontend call | Method | Endpoint | Request | Response | Auth |
|---|---|---|---|---|---|
| `getAdminUniversities` | GET | `/admin/universities/` | — | пагинированные University | A |
| `createAdminUniversity` | POST | `/admin/universities/` | University + `faculties_input?` | University 201 | A |
| `updateAdminUniversity` | PATCH | `/admin/universities/{id}/` | частичный | University | A |
| `deleteAdminUniversity` | DELETE | `/admin/universities/{id}/` | — | 204 | A |
| `toggleStudentRegistration` | POST | `/admin/universities/[{id}/]toggle-registration/` | `{university_id?, is_registration_open?}` | `{id, name, is_registration_open, message}` | A |
| `createAdminFaculty` | POST | `/admin/universities/{id}/faculties/` | `{name, name_ky?, code?}` | Faculty 201 | A |
| `deleteAdminFaculty` | DELETE | `/admin/universities/{uid}/faculties/{fid}/` | — | 204 | A |

### Админ: студенты
| Frontend call | Method | Endpoint | Request | Response | Auth |
|---|---|---|---|---|---|
| `getAdminStudents` | GET | `/admin/students/` или `/admin/universities/{id}/students/` | query `page, search, faculty, course, only_registered, voted` | пагинированные Student | A |
| `uploadStudents` | POST | `/admin/universities/{id}/students/upload/` | `FormData{file}` | `{batch_id, message, file_name}` 202 | A |
| `getBatchStatus` | GET | `/admin/upload-batches/{id}/status/` | — | UploadBatch | A |

### Админ: выборы
| Frontend call | Method | Endpoint | Request | Response | Auth |
|---|---|---|---|---|---|
| `getAdminElections` | GET | `/admin/elections/[?status&university]` | — | пагинированные Election | A |
| `createElection` | POST | `/admin/elections/` | Election | Election 201 | A |
| `updateElection` | PATCH | `/admin/elections/{id}/` | частичный | Election | A |
| `deleteElection` | DELETE | `/admin/elections/{id}/` | — | 204 — **лжёт для активных, D-02** | A |
| `startElection` | POST | `/admin/elections/{id}/start/` | — | `{success, message, status}` | A |
| `finishElection` | POST | `/admin/elections/{id}/finish/` | — | `{success, message, status}` | A |
| `cancelElection` | POST | `/admin/elections/{id}/cancel/` | — | `{success, message, status}` | A |
| `getElectionTurnout` | GET | `/admin/elections/{id}/turnout/` | — | turnout | A |
| `getElectionResults` | GET | `/admin/elections/{id}/results/` | — | results | A |
| `exportElectionResults` | POST | `/admin/elections/{id}/results/export/` | — | **Blob** xlsx | A |
| `getAdminFeaturedElections` | GET | `/admin/elections/featured/` | — | массив Election | A |
| `updateElectionFeatured` | PATCH | `/admin/elections/{id}/featured/` | JSON или FormData `{is_featured, featured_order, cover_image}` | Election | A |

### Админ: кандидаты
| Frontend call | Method | Endpoint | Request | Response | Auth |
|---|---|---|---|---|---|
| `getAdminCandidates` | GET | `/admin/elections/{id}/candidates/` | — | массив Candidate | A |
| `createCandidate` | POST | `/admin/elections/{id}/candidates/` | JSON или FormData | Candidate 201 | A |
| `updateCandidate` | PATCH | `/admin/candidates/{id}/` | JSON или FormData | Candidate | A |
| `deleteCandidate` | DELETE | `/admin/candidates/{id}/` | — | 204 | A |
| `reorderCandidates` | POST | `/admin/elections/{id}/candidates/reorder/` | `{ordered_ids: []}` | `{success, message}` | A |

### Контент
| Frontend call | Method | Endpoint | Response | Auth |
|---|---|---|---|---|
| `getNews` | GET | `/news/[?category&search]` | пагинированные NewsArticle | — |
| `getRecentNews` | GET | `/news/recent/` | массив | — |
| `getNewsDetail` | GET | `/news/{id}/` | NewsArticle | — |
| `getAdminNews` | GET | `/admin/content/news/[?category&search]` | пагинированные | A |
| `createAdminNews` | POST | `/admin/content/news/` | NewsArticle 201 | A |
| `updateAdminNews` | PATCH | `/admin/content/news/{id}/` | NewsArticle | A |
| `deleteAdminNews` | DELETE | `/admin/content/news/{id}/` | 204 | A |
| `getFaqs` | GET | `/faqs/` | массив FAQItem | — |
| `getAdminFaqs` | GET | `/admin/content/faqs/` | FAQItem | A |
| `createAdminFaq` | POST | `/admin/content/faqs/` | FAQItem 201 | A |
| `updateAdminFaq` | PATCH | `/admin/content/faqs/{id}/` | FAQItem | A |
| `deleteAdminFaq` | DELETE | `/admin/content/faqs/{id}/` | 204 | A |
| `getStaticPage` | GET | `/pages/{slug}/` | StaticPage | — |
| `getAdminStaticPages` | GET | `/admin/content/pages/` | массив StaticPage | A |
| `updateAdminStaticPage` | PATCH | `/admin/content/pages/{slug}/` | StaticPage | A |

## 5. Медиа

`getMediaUrl(path)` берёт `NEXT_PUBLIC_API_URL`, срезает суффикс `/api/v1` и приклеивает путь,
если тот не начинается с `http`/`data:`. То есть фронтенд ожидает, что медиа лежат
**на том же origin**, что и API.

Это прямое ограничение для ТЗ п.31 (вынос статики в object storage/CDN): либо бэкенд
продолжает отдавать абсолютные URL в тех же полях (тогда `getMediaUrl` вернёт их как есть —
безопасный путь), либо медиа остаются на том же домене за реверс-прокси.
**Отдавать относительные пути к чужому домену нельзя — фронтенд соберёт битый URL.**

## 6. Endpoints, которые фронтенд не использует

`/`, `/api/`, `/api/health/`, `/api/v1/auth/admin/refresh/`, `/api/v1/auth/admin/logs/`,
`/api/v1/admin/students/template/`, `/api/v1/admin/students/{id}/`,
`/api/v1/elections/public/`, второй монтаж `/api/v1/students/auth/...`.

Они всё равно покрыты contract-тестами: неиспользуемость фронтендом не означает,
что их можно молча сломать (ими могут пользоваться админы напрямую, скрипты, Postman).

## 7. Расхождения и дефекты со стороны фронтенда

Согласно ТЗ п.50 — фиксируются, но **не служат основанием менять backend-контракт**.

1. **OTP-вход существует в UI, но нерабочий.** Страницы
   `app/vote/[university_code]/login/page.tsx` → `.../verify/page.tsx` реализуют вход по
   студенческому ID и SMS-коду и ожидают `student_token` от `/auth/student/verify/`.
   Из-за D-01 студент получает «Ошибка сервера (500)». Чинится на бэкенде (ТЗ п.66 —
   восстановление уже заложенной логики), фронтенд менять не нужно.
2. **Ошибка удаления выборов не видна пользователю.** `deleteElection` при 204 считает
   операцию успешной. Из-за D-02 активные выборы остаются в БД, но пропадают из таблицы
   до перезагрузки. После исправления D-02 фронтенд сам покажет `error.message`.
3. **`getAdminUsers`, `getAdminFaqs`, `getAdminStaticPages`, `getUniversityFaculties`
   типизированы как `any[]`,** хотя часть из них возвращает пагинированный объект.
   Ошибки в рантайме нет — потребители применяют `Array.isArray(...) ? ... : res.results`.
   Это неточность типов фронтенда, а не контракта.
4. **`getMediaUrl` предполагает общий origin с API** — см. раздел 5.
