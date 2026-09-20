# Production deployment

Требование ТЗ п.100. Документ описывает топологию, порядок развёртывания,
раскатку, откат и эксплуатацию.

**Статус проверки.** Production-образ собран и запущен: non-root, health-чеки
отвечают, все 11 проверок `production_check` проходят внутри контейнера,
SIGTERM доходит до gunicorn (graceful shutdown, код выхода 0). На реальной
инфраструктуре с TLS, managed-PostgreSQL и несколькими нодами **не разворачивалось**.

---

## 1. Топология

```
            Интернет
               │
        ┌──────▼──────┐   TLS, rate limit, реальный IP, статика и медиа
        │   Nginx     │   deploy/nginx.conf
        └──────┬──────┘
               │ keepalive
     ┌─────────┼─────────┐
┌────▼───┐ ┌───▼────┐ ┌──▼─────┐   Gunicorn, non-root, stateless
│ app-1  │ │ app-2  │ │ app-N  │   gunicorn.conf.py
└────┬───┘ └───┬────┘ └──┬─────┘
     └─────────┼─────────┘
          ┌────▼─────┐   transaction pooling
          │ PgBouncer│   десятки воркеров -> единицы соединений
          └────┬─────┘
          ┌────▼─────┐
          │PostgreSQL│   единственный источник истины
          └──────────┘
     ┌──────────────────┐
     │      Redis       │   кэш, брокер Celery. Не источник истины
     └──────────────────┘
  ┌──────────────┐  ┌──────────────┐
  │celery-default│  │ celery-heavy │   импорт и экспорт отдельно,
  └──────────────┘  └──────────────┘   чтобы не конкурировать с голосами
```

**Почему PgBouncer обязателен (ТЗ п.13).** Количество воркеров умножается
на количество реплик: 4 реплики × 4 воркера × 4 потока — это 64 потенциальных
соединения к PostgreSQL, и каждое стоит памяти. При `max_connections=100`
третья реплика упрётся в лимит. PgBouncer в transaction pooling возвращает
соединение в пул после каждой транзакции, поэтому десятки воркеров делят единицы.

**Обязательное следствие:** `DB_CONN_MAX_AGE=0`. Persistent-соединения со стороны
Django удерживают соединение пулера и уничтожают его смысл.

---

## 2. Перед первым развёртыванием

- [ ] Сгенерирован **новый** `DJANGO_SECRET_KEY` (ключ из репозитория
      скомпрометирован — им подписываются студенческие JWT):
      `python -c "import secrets; print(secrets.token_urlsafe(64))"`
- [ ] Заполнен `.env` по образцу `.env.example`; в Git он не попадает
- [ ] Выполнен перенос базы по [SQLITE_TO_POSTGRES.md](SQLITE_TO_POSTGRES.md)
- [ ] Получены TLS-сертификаты, положены в `deploy/certs/`
- [ ] Настроены резервные копии PostgreSQL (см. раздел 7)

---

## 3. Развёртывание

```bash
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d postgres redis pgbouncer

# Миграции — отдельным шагом, до запуска приложения.
# Индексы создаются CONCURRENTLY, поэтому запись не блокируется (ТЗ п.54).
docker compose -f docker-compose.prod.yml run --rm app python manage.py migrate

# Отказ здесь означает небезопасную конфигурацию — это правильное поведение
docker compose -f docker-compose.prod.yml run --rm app python manage.py production_check

docker compose -f docker-compose.prod.yml up -d app celery-default celery-heavy nginx

# После массовой загрузки данных карта видимости пуста, и Index Only Scan
# не работает: запросы падают обратно на чтение кучи (измерено: 10.6 мс
# против 0.88 мс)
docker compose -f docker-compose.prod.yml exec postgres \
  psql -U "$DB_USER" -d "$DB_NAME" -c "VACUUM ANALYZE;"
```

Проверка:

```bash
curl -fsS https://api.example.kg/health/live
curl -fsS https://api.example.kg/health/ready
```

---

## 4. Раскатка обновлений

Приложение stateless (ТЗ п.39): любой инстанс обслуживает любой запрос,
sticky sessions не нужны. Поэтому раскатка — простая поочерёдная замена.

```bash
docker compose -f docker-compose.prod.yml build app
docker compose -f docker-compose.prod.yml up -d --no-deps --scale app=2 app
```

**Почему `stop_grace_period: 45s`.** SIGTERM доходит до gunicorn (проверено),
тот перестаёт принимать соединения и ждёт завершения текущих запросов до
`GUNICORN_GRACEFUL_TIMEOUT`. Grace period контейнера обязан превышать этот
таймаут, иначе Docker убьёт процесс посреди транзакции голосования (ТЗ п.44).

**Миграции и раскатка.** Во время поочерёдной замены одновременно работают
старая и новая версии кода. Миграция обязана быть совместимой с обеими:
добавление поля — да, удаление или переименование — нет. Такие изменения
разбиваются на два релиза.

---

## 5. Откат

```bash
docker compose -f docker-compose.prod.yml up -d --no-deps app  # предыдущий образ
```

**Миграции автоматически не откатываются.** Если релиз содержал миграцию,
откат кода без отката схемы может не заработать. Поэтому миграции и делаются
совместимыми в обе стороны — тогда откат кода безопасен сам по себе.

---

## 6. Пулы соединений

| Параметр | Значение | Обоснование |
|---|---|---|
| `max_connections` PostgreSQL | 200 | каждое соединение стоит памяти |
| PgBouncer `DEFAULT_POOL_SIZE` | 25 | реальных соединений к базе |
| PgBouncer `MAX_CLIENT_CONN` | 1000 | сколько клиентов примет пулер |
| `WEB_CONCURRENCY` | 4 на реплику | отправная точка, уточняется бенчмарком |
| `GUNICORN_THREADS` | 4 | воркер ждёт базу, а не считает |
| `DB_CONN_MAX_AGE` | **0** | обязательно при transaction pooling |

Формула: `реплики × WEB_CONCURRENCY × GUNICORN_THREADS` ≤ `MAX_CLIENT_CONN`,
а к самой базе уходит не больше `DEFAULT_POOL_SIZE`.

**Эти числа — отправная точка, а не результат измерения.** Правильные значения
определяются нагрузочным тестированием этапа 10 (ТЗ п.38).

---

## 7. Резервное копирование

Требование ТЗ п.47. Раздел будет дополнен на этапе 12 — здесь минимум,
без которого нельзя запускаться.

```bash
# Ежедневный дамп
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U "$DB_USER" -Fc "$DB_NAME" > "backup-$(date +%F).dump"

# ПРОВЕРКА восстановлением — обязательна. Бэкап, который не восстанавливали,
# бэкапом не является.
createdb restore_test
pg_restore -d restore_test "backup-$(date +%F).dump"
psql -d restore_test -c "SELECT count(*) FROM voting_voterecord;"
dropdb restore_test
```

Для PITR нужен `archive_mode=on` и архивация WAL — настраивается на уровне
PostgreSQL или managed-сервиса.

---

## 8. Эксплуатация

```bash
# Состояние
docker compose -f docker-compose.prod.yml ps
curl -fsS https://api.example.kg/health/ready | jq

# Проверка конфигурации
docker compose -f docker-compose.prod.yml exec app python manage.py production_check

# Целостность данных выборов
docker compose -f docker-compose.prod.yml exec app python manage.py audit_db_data

# Планы горячих запросов
docker compose -f docker-compose.prod.yml exec app python manage.py explain_hot_queries
```

**Отозвать токены студента:**

```python
from apps.students.models import Student
from apps.students.services_auth import revoke_student_tokens
revoke_student_tokens(Student.objects.get(student_id="..."))
```

---

## 9. Чего здесь ещё нет

| Что | Этап |
|---|---|
| Метрики, structured logging, трейсинг | 9 |
| Нагрузочные тесты и обоснованные числа воркеров | 10 |
| Read replica, HA, полная процедура восстановления | 12 |

Никаких утверждений о пропускной способности этот документ не содержит
и не должен содержать до появления результатов этапа 10 (ТЗ п.85, 123).
