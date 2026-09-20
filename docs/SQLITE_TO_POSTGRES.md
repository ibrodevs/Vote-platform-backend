# Перенос с SQLite на PostgreSQL

**Требование:** ТЗ п.12, 54, 55.
**Статус документа:** процедура **прогнана целиком на реальной dev-базе**
(3 университета, 19 студентов, 3 выборов, 6 кандидатов, 14 голосов, 125 объектов),
шаг за шагом по командам ниже. Результат прогона:

| Проверка | Результат |
|---|---|
| Аудит исходной базы | проблем не найдено |
| `dumpdata` | 111 КБ, 125 объектов |
| `migrate` + `loaddata` на чистой PostgreSQL | без ошибок |
| `row_counts` до и после | **совпали построчно** |
| `VoteRecord == Ballot` по каждым выборам | 1/1, 1/1, 12/12 — держится |
| Невалидированные FK | 0 |
| Отстающие последовательности | 0 |
| Ключевые констрейнты после переноса | оба на месте |
| Приложение на перенесённой базе | health, публичные списки и вход студента — 200 |

На **production-объёме** процедура не выполнялась: там на порядки больше строк,
и время `dumpdata`/`loaddata` придётся измерить отдельно. Для больших таблиц
может понадобиться перенос порциями вместо одного дампа.

---

## 0. Прежде чем начинать

Прочитать целиком, включая раздел «Откат». Наиболее опасный момент —
шаг 8: голоса, поданные в PostgreSQL после переключения, при откате на SQLite
**теряются**. Это не гипотеза, а прямое следствие того, что обратной репликации нет.

Поэтому переключение выполняется **только когда нет активных выборов**.
Проверить:

```bash
python manage.py shell -c "
from apps.elections.models import Election
active = Election.objects.filter(status='active')
print('активных выборов:', active.count())
for e in active: print(' ', e.id, e.title, e.starts_at, e.ends_at)
"
```

Если активные выборы есть — дождаться их завершения. Переносить базу под
идущим голосованием нельзя.

---

## 1. Аудит данных

```bash
python manage.py audit_db_data --fail-on-issues
```

Команда read-only. При находках она завершится ошибкой и напечатает, что именно
разобрать. **Ничего не удаляет автоматически** (ТЗ п.15: «Не удалять данные
автоматически. Если найдены duplicates — migration должна остановиться с понятной
инструкцией»).

Сохранить вывод — блок `row_counts` понадобится на шаге 6:

```bash
python manage.py audit_db_data > /tmp/audit_before.txt
```

## 2. Backup SQLite

```bash
cp db.sqlite3 "db.sqlite3.backup-$(date +%Y%m%d-%H%M%S)"
sqlite3 db.sqlite3 ".backup '/tmp/db.sqlite3.consistent'"   # согласованная копия
```

Проверить, что копия читается:

```bash
sqlite3 /tmp/db.sqlite3.consistent "select count(*) from voting_voterecord;"
```

Также сделать резервную копию медиа:

```bash
tar czf "media-backup-$(date +%Y%m%d).tar.gz" media/
```

## 3. Выгрузка данных

`contenttypes` и `auth.permission` исключаются: Django пересоздаёт их при
`migrate` на новой базе, и их выгрузка приводит к конфликтам первичных ключей
при загрузке.

```bash
python manage.py dumpdata \
  --natural-foreign --natural-primary \
  --exclude contenttypes \
  --exclude auth.permission \
  --exclude admin.logentry \
  --exclude sessions.session \
  --indent 2 \
  -o /tmp/dump.json

ls -lh /tmp/dump.json
```

## 4. Создание базы PostgreSQL

```bash
createdb vote_db
psql -d vote_db -c "CREATE USER vote_user WITH PASSWORD 'СМЕНИТЬ';"
psql -d vote_db -c "GRANT ALL PRIVILEGES ON DATABASE vote_db TO vote_user;"
psql -d vote_db -c "ALTER DATABASE vote_db OWNER TO vote_user;"
```

Пароль задать реальный и положить в секрет-хранилище, **не в Git** (ТЗ п.33).

## 5. Схема и загрузка данных

```bash
export DJANGO_ENV=production
export DB_ENGINE=postgresql
export DB_NAME=vote_db
export DB_USER=vote_user
export DB_PASSWORD='...'
export DB_HOST=127.0.0.1
export DB_PORT=5432

python manage.py migrate                 # только схема, база пустая
python manage.py loaddata /tmp/dump.json
```

Если `loaddata` падает на конкретной модели — не подгонять данные вслепую:
прочитать ошибку, вернуться к шагу 1 и разобрать причину на SQLite.

## 6. Сверка

```bash
python manage.py audit_db_data > /tmp/audit_after.txt
diff /tmp/audit_before.txt /tmp/audit_after.txt && echo "СОВПАЛО"
```

Блок `row_counts` обязан совпасть построчно:

| Объект | До | После |
|---|---|---|
| universities | | |
| faculties | | |
| admin_users | | |
| students | | |
| upload_batches | | |
| elections | | |
| candidates | | |
| vote_records | | |
| ballots | | |
| news_articles | | |
| faq_items | | |
| static_pages | | |

**Любое расхождение — стоп.** Не переключаться, разбираться.

Отдельно проверить инвариант голосования — число участий и число бюллетеней
по каждым выборам:

```bash
python manage.py shell -c "
from apps.elections.models import Election
from apps.voting.models import VoteRecord, Ballot
for e in Election.objects.all():
    v = VoteRecord.objects.filter(election=e).count()
    b = Ballot.objects.filter(election=e).count()
    print(f'{e.id} {e.title[:30]:30} VoteRecord={v} Ballot={b} {\"OK\" if v==b else \"РАСХОЖДЕНИЕ\"}')
"
```

### Последовательности

Все первичные ключи в проекте — `UUIDField` с `default=uuid.uuid4`, автоинкрементных
последовательностей для них нет. Проверить остаётся только служебные таблицы Django:

```bash
psql -d vote_db -c "
SELECT sequencename, last_value FROM pg_sequences WHERE schemaname='public';
"
```

Если какая-то последовательность отстала от максимума в таблице, поправить:

```bash
python manage.py sqlsequencereset auth contenttypes | psql -d vote_db
```

### Внешние ключи

```bash
psql -d vote_db -c "
SELECT conrelid::regclass AS table, conname
FROM pg_constraint WHERE contype='f' AND NOT convalidated;
"
```

Пустой результат — все FK валидны.

## 7. Прогон тестов на новой базе

```bash
DJANGO_SETTINGS_MODULE=config.settings_test python manage.py test
```

Ожидается тот же результат, что задокументирован в [BASELINE.md](BASELINE.md):
149 тестов, OK, 3 expected failures.

## 8. Переключение

Чек-лист перед переключением — все пункты обязаны выполняться одновременно:

- [ ] нет активных выборов (раздел 0);
- [ ] `audit_db_data --fail-on-issues` проходит;
- [ ] backup SQLite снят **и проверен чтением**;
- [ ] `row_counts` до и после совпали;
- [ ] `VoteRecord == Ballot` по каждым выборам;
- [ ] тесты на PostgreSQL зелёные;
- [ ] `DJANGO_SECRET_KEY` задан новым значением (старый закоммичен и скомпрометирован, ТЗ п.33);
- [ ] переменные окружения выставлены на целевом сервере;
- [ ] медиа-файлы доступны на новой площадке.

Переключение:

1. Перевести приложение в режим обслуживания (или остановить приём трафика).
2. Повторить шаги 3–6 на **свежем** дампе — данные могли измениться с первого прогона.
3. Выставить `DJANGO_ENV=production` и `DB_ENGINE=postgresql`.
4. Перезапустить приложение. При неверной конфигурации оно **не стартует**:
   `ImproperlyConfigured` (ТЗ п.12) — это ожидаемое поведение, а не поломка.
5. Проверить `/api/health/` и вход администратора.
6. Снять режим обслуживания.

## 9. Откат

**Важно:** голоса, поданные в PostgreSQL после переключения, при откате теряются —
обратной синхронизации нет. Поэтому откат допустим только если после переключения
голосование не начиналось.

```bash
python manage.py shell -c "
from apps.voting.models import VoteRecord
from django.utils import timezone
from datetime import timedelta
new = VoteRecord.objects.filter(voted_at__gte=timezone.now()-timedelta(hours=24)).count()
print('голосов за последние 24ч в PostgreSQL:', new)
"
```

Если `0` — откат безопасен:

```bash
unset DJANGO_ENV
export DB_ENGINE=sqlite
cp db.sqlite3.backup-<timestamp> db.sqlite3
# перезапустить приложение
```

Если не `0` — откатываться нельзя без переноса этих голосов обратно.
Сначала выгрузить их (`dumpdata apps.voting`), затем принимать решение осознанно.

## 10. После переключения

- Удалить `db.sqlite3` с production-сервера, чтобы к нему нельзя было случайно вернуться.
- Настроить резервное копирование PostgreSQL: ежедневные бэкапы, WAL archiving / PITR,
  **проверенную процедуру восстановления** (ТЗ п.47 — этап 12).
- Убедиться, что `DJANGO_ENV=production` выставлен постоянно, а не только в текущей сессии.
