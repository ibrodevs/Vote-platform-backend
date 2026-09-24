#!/usr/bin/env bash
# ==============================================================================
# Восстановление базы данных из дампа (ТЗ п.29, 47)
# ==============================================================================
# ВНИМАНИЕ: ЭТА ОПЕРАЦИЯ ПОЛНОСТЬЮ ЗАМЕНЯЕТ ТЕКУЩУЮ БАЗУ ДАННЫХ.
# Требует подтверждения перед выполнением.
# Автоматически создаёт страховочную копию перед перезаписью.
#
# Запуск:
#   ./scripts/restore.sh backups/vote_db-YYYYMMDD-HHMMSS.dump
#   CONFIRM=yes ./scripts/restore.sh <файл>
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${BACKEND_DIR}"

DUMP="${1:?Укажите файл дампа: ./scripts/restore.sh <dump_file>}"
[ -f "$DUMP" ] || { echo "Файл не найден: $DUMP" >&2; exit 1; }

# Загрузка .env если есть
if [ -f .env ]; then
    export $(grep -E '^(DB_NAME|DB_USER|DB_PASSWORD)=' .env | xargs -d '\n' 2>/dev/null || grep -E '^(DB_NAME|DB_USER|DB_PASSWORD)=' .env || true)
fi

DB_NAME="${DB_NAME:-vote_db}"
DB_USER="${DB_USER:-vote_user}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"

USE_DOCKER=false
if command -v docker >/dev/null 2>&1 && docker compose -f docker-compose.prod.yml ps postgres 2>/dev/null | grep -q "postgres"; then
    USE_DOCKER=true
fi

# Проверка валидности дампа
if command -v pg_restore >/dev/null 2>&1; then
    pg_restore --list "$DUMP" >/dev/null || { echo "Файл не является валидным pg_dump -Fc дампом: $DUMP" >&2; exit 1; }
fi

echo "=================================================================="
echo " ВНИМАНИЕ: БУДЕТ ПОЛНОСТЬЮ ПЕРЕЗАПИСАНА БАЗА ${DB_NAME}"
echo " Источник восстановления: ${DUMP}"
echo "=================================================================="

if [ "${CONFIRM:-}" != "yes" ]; then
    printf 'Для подтверждения введите точное имя базы данных (%s): ' "$DB_NAME"
    read -r answer
    if [ "$answer" != "$DB_NAME" ]; then
        echo "Отменено пользователем." >&2
        exit 1
    fi
fi

# Страховочная копия текущего состояния базы
SAFETY="/tmp/pre-restore-${DB_NAME}-$(date +%Y%m%d-%H%M%S).dump"
echo "Создание страховочной копии текущей базы -> ${SAFETY}"
if [ "$USE_DOCKER" = true ]; then
    docker compose -f docker-compose.prod.yml exec -T postgres \
        pg_dump --format=custom --username="$DB_USER" --dbname="$DB_NAME" > "$SAFETY" || echo "Предупреждение: не удалось снять страховочную копию"
else
    pg_dump --format=custom --no-owner --no-privileges \
            --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" \
            --dbname="$DB_NAME" --file="$SAFETY" || echo "Предупреждение: не удалось снять страховочную копию"
fi

echo "Остановка активных клиентских соединений к базе..."
TERMINATE_SQL="SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$DB_NAME' AND pid <> pg_backend_pid();"
DROP_SQL="DROP DATABASE IF EXISTS \"$DB_NAME\"; CREATE DATABASE \"$DB_NAME\";"

if [ "$USE_DOCKER" = true ]; then
    docker compose -f docker-compose.prod.yml exec -T postgres \
        psql --username="$DB_USER" --dbname="postgres" -c "$TERMINATE_SQL" >/dev/null 2>&1 || true
    echo "Пересоздание пустой базы данных ${DB_NAME}..."
    docker compose -f docker-compose.prod.yml exec -T postgres \
        psql --username="$DB_USER" --dbname="postgres" -c "$DROP_SQL" >/dev/null

    echo "Восстановление структуры и данных..."
    docker compose -f docker-compose.prod.yml exec -T postgres \
        pg_restore --username="$DB_USER" --dbname="$DB_NAME" --no-owner --no-privileges < "$DUMP"
else
    psql --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" --dbname="postgres" -c "$TERMINATE_SQL" >/dev/null 2>&1 || true
    echo "Пересоздание пустой базы данных ${DB_NAME}..."
    psql --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" --dbname="postgres" -c "$DROP_SQL" >/dev/null

    echo "Восстановление структуры и данных..."
    pg_restore --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" \
               --dbname="$DB_NAME" --no-owner --no-privileges "$DUMP"
fi

echo ""
echo "=================================================================="
echo "Восстановление успешно завершено!"
echo "Страховочная копия сохранена в: ${SAFETY}"
echo ""
echo "Обязательные последующие шаги проверки:"
echo "  1. docker compose -f docker-compose.prod.yml run --rm app python manage.py migrate --check"
echo "  2. docker compose -f docker-compose.prod.yml run --rm app python manage.py audit_db_data"
echo "  3. ./scripts/verify_backup.sh ${DUMP}"
echo "=================================================================="
