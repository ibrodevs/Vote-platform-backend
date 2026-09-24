# Этап 4 — Устранение N+1 на горячих endpoint'ах: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development
> или superpowers:executing-plans. Шаги отмечаются чекбоксами.

**Goal:** Сделать число SQL-запросов на горячих endpoint'ах постоянным — не зависящим
от количества выборов, кандидатов и студентов (ТЗ п.48: O(1) round trips).

**Architecture:** Три приёма, по убыванию предпочтительности. `annotate(Count(...))` —
когда нужно только число: база считает сама, строки не едут по сети.
`prefetch_related` — когда нужны сами связанные объекты. `select_related` — для
FK в одну сторону. Агрегация результатов голосования переводится с `1+N`
подсчётов на один `GROUP BY candidate_id`.

**Tech Stack:** Django ORM 5.2, PostgreSQL 16.

**Spec:** roadmap, этап 4; ТЗ п.25, 26, 27, 28, 29, 30, 48, 51, 93.

---

## Global Constraints

Полный список — в roadmap. Критично здесь:

1. **Ответы не меняются ни на байт.** Оптимизация запросов не имеет права поменять
   форму JSON, порядок элементов или значения. Contract-тесты — арбитр.
2. **Скрытые результаты остаются скрытыми (ТЗ п.51).** Правило
   «не FINISHED и `results_visible_to_admin_before_finish == False` → 403»
   должно пережить рефакторинг агрегации. Отдельный тест.
3. **Никакого единого счётчика (ТЗ п.30).** Запрещено добавлять
   `election.vote_count += 1` или `ElectionStats.total_votes` — это возвращает
   сериализацию всех голосов через одну строку, ровно то, что убирал этап 2.
4. **Тайна голосования.** Агрегация идёт по `Ballot` и только по `candidate_id`;
   ни один новый запрос не должен соединять `Student` с `Candidate`.

---

## Измеренный baseline (2026-09-20, PostgreSQL)

Реальные SQL без служебных `SAVEPOINT`/advisory. Кэш личности прогрет.

| Endpoint | 2 выборов × 3 кандидата, 5 студентов | 5 × 10, 20 студентов | Растёт с |
|---|---|---|---|
| `GET /elections/available/?all=true` | 12 | **62** | выборы × кандидаты |
| `GET /admin/students/` | 14 | **44** | студенты |
| `GET /admin/elections/` | 7 | 17 | выборы |
| `GET /admin/elections/{id}/results/` | 8 | 15 | кандидаты |
| `POST /admin/elections/{id}/results/export/` | 8 | 15 | кандидаты |
| `GET /elections/{id}/` | 5 | 12 | кандидаты |
| `GET /admin/universities/` | 6 | 9 | университеты |
| `GET /elections/recent/` | 3 | 3 | — уже константа |
| `GET /admin/elections/{id}/turnout/` | 4 | 4 | — уже константа |

**Почему `recent/` уже хорош, а `admin/elections/` нет.** Оба используют
`ElectionSerializer` с `get_candidates_count() -> obj.candidates.count()`.
Но `recent/` делает `prefetch_related('candidates')`, а `.count()` на
предзагруженном менеджере Django отдаёт из кэша, без запроса. В админском
списке prefetch нет — и каждый объект стоит отдельного `COUNT`.

**Почему `admin/students/` хуже всех.** Вьюха делает `prefetch_related('vote_records')`,
но сериализатор вызывает `obj.vote_records.exists()`, `.count()` и
`.order_by('-voted_at').first()`. `exists()` и `order_by()` **не используют**
prefetch-кэш — они всегда идут в базу. Prefetch есть, пользы нет.

---

## Целевые бюджеты

| Endpoint | Цель | Обоснование |
|---|---|---|
| `GET /elections/available/` | ≤ 4 | ТЗ п.25 |
| `GET /elections/{id}/` | ≤ 4 | ТЗ п.48 |
| `GET /admin/elections/` | ≤ 4 | постоянное |
| `GET /admin/students/` | ≤ 4 | постоянное |
| `GET /admin/universities/` | ≤ 4 | постоянное |
| `GET /admin/elections/{id}/results/` | ≤ 5 | один `GROUP BY` (ТЗ п.27) |
| `POST .../results/export/` | ≤ 5 | то же |

Главное требование — не абсолютное число, а **отсутствие роста**: значения
при масштабе 5×10×20 обязаны совпадать со значениями при 2×3×5.

---

## File Structure

- Create `tests/contract/test_query_budget.py` — бюджеты всех горячих endpoint'ов
  на двух масштабах; главный тест — «число не изменилось при росте данных».
- Modify `apps/elections/serializers.py` — `candidates_count` из аннотации.
- Modify `apps/elections/views.py` — аннотации, prefetch, агрегация результатов.
- Create `apps/elections/aggregates.py` — единая функция подсчёта результатов,
  чтобы `results/` и `results/export/` не разъезжались.
- Modify `apps/universities/serializers.py` — `students_count`, `active_elections_count`.
- Modify `apps/students/serializers.py` — `has_voted`, `voted_at`, `votes_count`.
- Modify `apps/students/views.py` — аннотации вместо prefetch.
- Modify `apps/candidates/views.py` — `select_related` там, где сериализатор
  читает `election.title` и `university.name`.

---

### Task 1: Тесты бюджета запросов (сначала красные)

**Files:** Create `tests/contract/test_query_budget.py`

**Interfaces:**
- Produces: `real_sql(captured)` — фильтр служебных запросов;
  `QueryBudgetTestCase.assertBudget(label, fn, limit)`;
  `assertDoesNotGrow(fn_small, fn_large)`

- [ ] **Step 1: Написать тесты на целевые бюджеты и на отсутствие роста.**
- [ ] **Step 2: Прогнать — большинство падает** с текущими числами из baseline.
- [ ] **Step 3: Commit** (красные тесты фиксируют цель).

---

### Task 2: `ElectionSerializer.candidates_count` через аннотацию

**Files:** `apps/elections/serializers.py`, `apps/elections/views.py`

**Проектное решение:** `annotate(Count('candidates'))` вместо `prefetch_related`.
Prefetch тоже убрал бы N+1, но потянул бы по сети все строки кандидатов ради
одного числа. На списке из 50 выборов по 20 кандидатов это 1000 лишних строк.

Сериализатор читает аннотацию, а при её отсутствии откатывается на `.count()` —
иначе любой вызов сериализатора вне подготовленного queryset'а упадёт.

- [ ] **Step 1–4:** написать, применить к `AdminElectionListCreateView`,
      `AdminFeaturedElectionsManageView` и `PublicRecentElectionsView`; прогнать.
- [ ] **Step 5: Commit**

---

### Task 3: `StudentAvailableElectionsView` — худший случай

**Files:** `apps/elections/views.py`

Сейчас 62 запроса. Причины: нет `select_related('university')`,
нет `prefetch_related('candidates')` (а `ElectionStudentSerializer` разворачивает
вложенных кандидатов), и `candidates.university` дёргается на каждого кандидата.

- [ ] **Step 1: Добавить `select_related('university')` и
      `prefetch_related('candidates__university')`.**
- [ ] **Step 2: Прогнать** — бюджет и contract-тесты.
- [ ] **Step 3: То же для `StudentElectionDetailView`.**
- [ ] **Step 4: Commit**

---

### Task 4: Результаты одним `GROUP BY` (ТЗ п.27)

**Files:** Create `apps/elections/aggregates.py`, modify `apps/elections/views.py`

Сейчас: `for candidate: Ballot.objects.filter(...).count()` — классический `1+N`.
Становится: один `values('candidate_id').annotate(Count('id'))`.

**Почему отдельный модуль:** `results/` и `results/export/` считают одно и то же
двумя копиями кода. Они уже разъехались — в `turnout/` знаменатель берётся из
`VoteRecord`, а в `results/` из `Ballot`. Одна функция исключает расхождение.

**Interfaces:**
- `election_results(election) -> dict` — `total_eligible`, `total_voted`,
  `turnout_percent`, `candidates[]`
- `results_are_visible(election) -> bool` — правило ТЗ п.51 в одном месте

- [ ] **Step 1: Тест, что скрытые результаты остаются скрытыми.**
- [ ] **Step 2: Написать `aggregates.py`.**
- [ ] **Step 3: Перевести обе вьюхи на него.**
- [ ] **Step 4: Прогнать** — форма ответа и сортировка по убыванию голосов
      обязаны совпасть с прежними contract-тестами.
- [ ] **Step 5: Commit**

---

### Task 5: `StudentSerializer` — prefetch, который не работает

**Files:** `apps/students/serializers.py`, `apps/students/views.py`

`exists()`, `count()` и `order_by()` игнорируют prefetch-кэш. Заменяются на
аннотации: `Count('vote_records')` и `Max('vote_records__voted_at')`.
`has_voted` выводится из счётчика, `voted_at` — из максимума.

Prefetch убирается: он грузил строки, которыми никто не пользовался.

- [ ] **Step 1: Тест бюджета `GET /admin/students/`.**
- [ ] **Step 2: Аннотации во вьюхе, чтение аннотаций в сериализаторе с fallback.**
- [ ] **Step 3: Прогнать** — `has_voted`, `voted_at`, `votes_count` и фильтр
      `?voted=` обязаны вести себя как раньше.
- [ ] **Step 4: Commit**

---

### Task 6: `UniversitySerializer`

**Files:** `apps/universities/serializers.py`, `apps/universities/views.py`

`students_count` и `active_elections_count` — через `Count` с `filter=Q(...)`.
Два условных счётчика в одном запросе, а не два запроса на объект.

- [ ] **Step 1–3:** тест, аннотации, прогон.
- [ ] **Step 4: Commit**

---

### Task 7: Пагинация и аудит остальных списков (ТЗ п.93)

- [ ] **Step 1: Перечислить все list-endpoint'ы и их пагинацию.**
- [ ] **Step 2: Задать максимальный размер страницы**, чтобы `?page_size=1000000`
      не выгружал всю таблицу.
- [ ] **Step 3: Тест, что `page_size` ограничен сверху.**
- [ ] **Step 4: Commit**

---

### Task 8: Документация и финальное измерение

- [ ] **Step 1: Повторить измерение на тех же двух масштабах.**
- [ ] **Step 2: Таблица «до/после» в `docs/PERFORMANCE.md`** — первый раздел
      этого документа.
- [ ] **Step 3: Обновить `BASELINE.md` и roadmap.**
- [ ] **Step 4: Прогон в трёх средах.**
- [ ] **Step 5: Commit**

---

## Definition of Done этапа 4

- [ ] Число SQL на каждом горячем endpoint'е **не растёт** при увеличении
      количества выборов, кандидатов и студентов — доказано тестом на двух масштабах.
- [ ] `results/` и `results/export/` считают голоса одним `GROUP BY`.
- [ ] Обе вьюхи результатов используют общий код — расхождение знаменателя устранено.
- [ ] Скрытые результаты остаются скрытыми.
- [ ] Ни одного нового счётчика-строки (ТЗ п.30).
- [ ] Все list-endpoint'ы имеют ограниченный сверху размер страницы.
- [ ] Contract-тесты не изменились: ответы те же.
- [ ] `docs/PERFORMANCE.md` содержит измеренную таблицу до/после.
