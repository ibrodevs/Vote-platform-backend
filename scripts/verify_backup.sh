#!/usr/bin/env bash
# Проверка бэкапа восстановлением (ТЗ п.47).
#
# Написать «делаем бэкапы» недостаточно. Копия, из которой никто никогда
# не восстанавливался, — это предположение, а не резервная копия.
#
# Скрипт восстанавливает дамп во ВРЕМЕННУЮ базу, сверяет число строк
# по ключевым таблицам и удаляет временную базу за собой. Рабочая база
# при этом не затрагивается.
#
#   ./scripts/verify_backup.sh backups/vote_db-20260923-120000.dump
#
# Запускать периодически — ТЗ п.47 требует именно регулярного restore test.

set -euo pipefail

DUMP="${1:?Укажите файл дампа}"
DB_NAME="${DB_NAME:-vote_db}"
DB_USER="${DB_USER:-vote_user}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
CHECK_DB="verify_restore_$(date +%s)"

PSQL=(psql --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" --no-psqlrc --quiet --tuples-only --no-align)

cleanup() {
  "${PSQL[@]}" --dbname=postgres --command="DROP DATABASE IF EXISTS \"$CHECK_DB\";" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Таблицы, расхождение по которым означает потерю голосов. Проверяются
# в первую очередь: остальное восстановимо, голоса — нет.
TABLES="voting_voterecord voting_ballot students_student elections_election candidates_candidate universities_university"

echo "=== Проверка ${DUMP} ==="
echo "Временная база: ${CHECK_DB}"
"${PSQL[@]}" --dbname=postgres --command="CREATE DATABASE \"$CHECK_DB\";" >/dev/null

echo "Восстанавливаю..."
pg_restore --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" \
           --dbname="$CHECK_DB" --no-owner --no-privileges "$DUMP" >/dev/null

echo
printf '%-32s %12s %12s  %s\n' "таблица" "рабочая" "из бэкапа" "итог"
FAILED=0
for table in $TABLES; do
  LIVE="$("${PSQL[@]}" --dbname="$DB_NAME"  --command="SELECT count(*) FROM $table;" 2>/dev/null || echo "n/a")"
  REST="$("${PSQL[@]}" --dbname="$CHECK_DB" --command="SELECT count(*) FROM $table;" 2>/dev/null || echo "n/a")"
  if [ "$LIVE" = "$REST" ]; then
    printf '%-32s %12s %12s  %s\n' "$table" "$LIVE" "$REST" "OK"
  else
    # Расхождение не всегда ошибка: база могла измениться после снятия дампа.
    # Но оно обязано быть замечено человеком, а не пройти молча.
    printf '%-32s %12s %12s  %s\n' "$table" "$LIVE" "$REST" "РАСХОЖДЕНИЕ"
    FAILED=1
  fi
done

echo
echo "--- Целостность голосов в восстановленной копии ---"
ORPHANS="$("${PSQL[@]}" --dbname="$CHECK_DB" --command="
  SELECT count(*) FROM voting_ballot b
  WHERE NOT EXISTS (SELECT 1 FROM elections_election e WHERE e.id = b.election_id);")"
DUPES="$("${PSQL[@]}" --dbname="$CHECK_DB" --command="
  SELECT count(*) FROM (
    SELECT election_id, student_id FROM voting_voterecord
    GROUP BY election_id, student_id HAVING count(*) > 1
  ) d;")"
echo "осиротевших бюллетеней: ${ORPHANS}"
echo "дублей (выборы, студент): ${DUPES}"
if [ "$ORPHANS" != "0" ] || [ "$DUPES" != "0" ]; then
  echo "ОШИБКА: восстановленная копия непригодна." >&2
  FAILED=1
fi

echo
if [ "$FAILED" -eq 0 ]; then
  echo "Бэкап пригоден: восстановление прошло, данные сошлись."
else
  echo "Проверка выявила расхождения — разберитесь до того, как полагаться на эту копию." >&2
  exit 1
fi
