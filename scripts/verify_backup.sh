#!/usr/bin/env bash
# ==============================================================================
# Проверка бэкапа восстановлением во временную БД (ТЗ п.29, 47)
# ==============================================================================
# Восстанавливает дамп во временную базу, сверяет число строк в таблицах
# голосов и выборов с рабочей базой, проверяет целостность и удаляет
# временную базу за собой. Рабочая база не затрагивается.
#
# Запуск:
#   ./scripts/verify_backup.sh backups/vote_db-YYYYMMDD-HHMMSS.dump
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${BACKEND_DIR}"

DUMP="${1:?Укажите файл дампа}"
[ -f "$DUMP" ] || { echo "Файл не найден: $DUMP" >&2; exit 1; }

# Загрузка .env если есть
if [ -f .env ]; then
    export $(grep -E '^(DB_NAME|DB_USER|DB_PASSWORD)=' .env | xargs -d '\n' 2>/dev/null || grep -E '^(DB_NAME|DB_USER|DB_PASSWORD)=' .env || true)
fi

DB_NAME="${DB_NAME:-vote_db}"
DB_USER="${DB_USER:-vote_user}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
CHECK_DB="verify_restore_$(date +%s)"

USE_DOCKER=false
if command -v docker >/dev/null 2>&1 && docker compose -f docker-compose.prod.yml ps postgres 2>/dev/null | grep -q "postgres"; then
    USE_DOCKER=true
fi

run_sql() {
    local db="$1"
    local sql="$2"
    if [ "$USE_DOCKER" = true ]; then
        docker compose -f docker-compose.prod.yml exec -T postgres \
            psql --username="$DB_USER" --dbname="$db" --no-psqlrc --quiet --tuples-only --no-align -c "$sql"
    else
        psql --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" \
            --dbname="$db" --no-psqlrc --quiet --tuples-only --no-align -c "$sql"
    fi
}

cleanup() {
    run_sql "postgres" "DROP DATABASE IF EXISTS \"$CHECK_DB\";" >/dev/null 2>&1 || true
}
trap cleanup EXIT

TABLES="voting_voterecord voting_ballot students_student elections_election candidates_candidate universities_university"

echo "=== Проверка резервной копии: ${DUMP} ==="
echo "Временная проверочная база: ${CHECK_DB}"
run_sql "postgres" "CREATE DATABASE \"$CHECK_DB\";" >/dev/null

echo "Восстановление дампа во временную базу..."
if [ "$USE_DOCKER" = true ]; then
    docker compose -f docker-compose.prod.yml exec -T postgres \
        pg_restore --username="$DB_USER" --dbname="$CHECK_DB" --no-owner --no-privileges < "$DUMP" >/dev/null
else
    pg_restore --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" \
               --dbname="$CHECK_DB" --no-owner --no-privileges "$DUMP" >/dev/null
fi

echo ""
printf '%-32s %12s %12s  %s\n' "таблица" "рабочая БД" "из бэкапа" "итог"
FAILED=0
for table in $TABLES; do
    LIVE="$(run_sql "$DB_NAME" "SELECT count(*) FROM $table;" 2>/dev/null || echo "n/a")"
    REST="$(run_sql "$CHECK_DB" "SELECT count(*) FROM $table;" 2>/dev/null || echo "n/a")"
    LIVE=$(echo "$LIVE" | tr -d '[:space:]')
    REST=$(echo "$REST" | tr -d '[:space:]')

    if [ "$LIVE" = "$REST" ]; then
        printf '%-32s %12s %12s  %s\n' "$table" "$LIVE" "$REST" "OK"
    else
        printf '%-32s %12s %12s  %s\n' "$table" "$LIVE" "$REST" "РАСХОЖДЕНИЕ"
        FAILED=1
    fi
done

echo ""
echo "--- Проверка целостности связей в восстановленной копии ---"
ORPHANS="$(run_sql "$CHECK_DB" "
  SELECT count(*) FROM voting_ballot b
  WHERE NOT EXISTS (SELECT 1 FROM elections_election e WHERE e.id = b.election_id);" | tr -d '[:space:]')"

DUPES="$(run_sql "$CHECK_DB" "
  SELECT count(*) FROM (
    SELECT election_id, student_id FROM voting_voterecord
    GROUP BY election_id, student_id HAVING count(*) > 1
  ) d;" | tr -d '[:space:]')"

echo "Осиротевших бюллетеней: ${ORPHANS}"
echo "Дубликатов голосов (выборы, студент): ${DUPES}"

if [ "$ORPHANS" != "0" ] || [ "$DUPES" != "0" ]; then
    echo "ОШИБКА: восстановленная копия нарушает целостность данных!" >&2
    FAILED=1
fi

echo ""
if [ "$FAILED" -eq 0 ]; then
    echo "Бэкап пригоден: восстановление прошло успешно, данные согласованы."
    exit 0
else
    echo "ВНИМАНИЕ: проверка выявила расхождения. Разберитесь до использования бэкапа." >&2
    exit 1
fi
