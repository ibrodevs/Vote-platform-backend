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

**И обязательно заявите схему явно:** `DB_BEHIND_PGBOUNCER=True`. Django не видит
разницы между пулером и настоящим PostgreSQL, поэтому сам определить это не может.
Без явного заявления `production_check` не пропустит деплой — и это не формальность.

Этап 11 измерил цену ошибки на профиле записи голосов, одна и та же нагрузка,
всё остальное идентично:

| Конфигурация | p95 | Не уложились в темп |
|---|---|---|
| `DB_CONN_MAX_AGE=0` **без** пулера | **364 мс** | 847 |
| `DB_CONN_MAX_AGE=60` без пулера | **13 мс** | 18 |

Разница в 28 раз. Причина: без пулера и с нулевым `CONN_MAX_AGE` Django закрывает
соединение после каждого HTTP-запроса, и PostgreSQL на каждый следующий заново
порождает backend-процесс. В профилировщике приложения это видно как стеки внутри
`psycopg.connect`, в базе — как загрузка CPU, не соответствующая объёму запросов.

Если пулера нет, работоспособны обе схемы, но пара должна быть согласованной:

| Схема | `DB_BEHIND_PGBOUNCER` | `DB_CONN_MAX_AGE` |
|---|---|---|
| С PgBouncer (рекомендуется, ТЗ п.13) | `True` | `0` |
| Прямое подключение | `False` | `60` |

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
| `DB_BEHIND_PGBOUNCER` | **True** | заявляет схему; без этого деплой не пройдёт проверку |
| `DB_CONN_MAX_AGE` | **0** | обязательно при transaction pooling |

Формула: `реплики × WEB_CONCURRENCY × GUNICORN_THREADS` ≤ `MAX_CLIENT_CONN`,
а к самой базе уходит не больше `DEFAULT_POOL_SIZE`.

**Эти числа — отправная точка, а не результат измерения.** Правильные значения
определяются нагрузочным тестированием этапа 10 (ТЗ п.38).

---

## 7. Резервное копирование

Требование ТЗ п.47. Полная процедура, включая восстановление на момент
времени и действия при инцидентах — **[docs/RUNBOOK.md](RUNBOOK.md)**.
Здесь только то, что нужно настроить при развёртывании.

```bash
# Ежедневный дамп. Скрипт отказывается считать успехом пустой файл
# или файл, который не читается pg_restore.
BACKUP_DIR=/mnt/backups ./scripts/backup.sh

# ПРОВЕРКА ВОССТАНОВЛЕНИЕМ — обязательна и регулярна.
# Копия, из которой никто не восстанавливался, — это предположение,
# а не резервная копия.
./scripts/verify_backup.sh /mnt/backups/vote_db-<дата>.dump

# Восстановление. Уничтожает текущую базу, поэтому требует подтверждения
# и само снимает страховочную копию перед разрушением.
./scripts/restore.sh /mnt/backups/vote_db-<дата>.dump
```

cron:

```cron
15 3 * * * cd /srv/vote-platform && BACKUP_DIR=/mnt/backups ./scripts/backup.sh >> /var/log/vote-backup.log 2>&1
30 4 * * 0 cd /srv/vote-platform && ./scripts/verify_backup.sh "$(ls -t /mnt/backups/*.dump | head -1)" >> /var/log/vote-restore-test.log 2>&1
```

**Копии хранить не на том же диске, что база.** Отказ диска не должен
уносить и данные, и их резервную копию.

**WAL archiving обязателен.** Ежедневный дамп теряет всё, что произошло
после него; в день выборов это потерянные голоса. Настройка `wal_level`,
`archive_mode`, `archive_command` и процедура PITR — в
[RUNBOOK](RUNBOOK.md#13-wal-archiving-и-pitr).

Вся цепочка — бэкап, проверка, восстановление, подтверждение целостности —
прогнана 2026-09-23 на реальных данных, включая разрушающий шаг.
Зафиксированный вывод в RUNBOOK.

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
