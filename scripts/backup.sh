#!/usr/bin/env bash
# ==============================================================================
# Резервная копия базы PostgreSQL (ТЗ п.29, 47)
# ==============================================================================
# Формат: custom (-Fc) со сжатием.
# Автоматически определяет запуск в Docker Compose или на хосте.
# Поддерживает отправку на внешнее хранилище (S3 / Hetzner Storage Box).
#
# Запуск:
#   ./scripts/backup.sh
#   BACKUP_DIR=/mnt/backups ./scripts/backup.sh
#   S3_BACKUP_BUCKET=s3://my-vote-backups ./scripts/backup.sh
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${BACKEND_DIR}"

load_backup_env() {
    local env_file="${1:-${BACKEND_DIR}/.env}"
    if [ -f "$env_file" ]; then
        get_val() {
            grep -E "^${1}=" "$env_file" 2>/dev/null | cut -d '=' -f2- | tr -d '"' | tr -d "'" | tr -d '\r' | xargs || true
        }
        local val
        val="$(get_val DB_NAME)"; if [ -n "$val" ]; then DB_NAME="$val"; fi
        val="$(get_val DB_USER)"; if [ -n "$val" ]; then DB_USER="$val"; fi
        val="$(get_val DB_PASSWORD)"; if [ -n "$val" ]; then DB_PASSWORD="$val"; fi
        val="$(get_val DB_HOST)"; if [ -n "$val" ]; then DB_HOST="$val"; fi
        val="$(get_val DB_PORT)"; if [ -n "$val" ]; then DB_PORT="$val"; fi
        val="$(get_val BACKUP_DIR)"; if [ -n "$val" ]; then BACKUP_DIR="$val"; fi
        val="$(get_val S3_BACKUP_BUCKET)"; if [ -n "$val" ]; then S3_BACKUP_BUCKET="$val"; fi
        val="$(get_val RETENTION_DAYS)"
        if [ -z "$val" ]; then val="$(get_val BACKUP_RETENTION_DAYS)"; fi
        if [ -n "$val" ]; then RETENTION_DAYS="$val"; fi
    fi
}

# Режим тестирования парсинга конфигурации
if [ "${1:-}" = "--print-config" ]; then
    load_backup_env "${2:-${BACKEND_DIR}/.env}"
    echo "DB_NAME=${DB_NAME:-vote_db}"
    echo "DB_USER=${DB_USER:-vote_user}"
    echo "DB_HOST=${DB_HOST:-127.0.0.1}"
    echo "DB_PORT=${DB_PORT:-5432}"
    echo "BACKUP_DIR=${BACKUP_DIR:-./backups}"
    echo "S3_BACKUP_BUCKET=${S3_BACKUP_BUCKET:-}"
    echo "RETENTION_DAYS=${RETENTION_DAYS:-14}"
    exit 0
fi

load_backup_env "${BACKEND_DIR}/.env"

DB_NAME="${DB_NAME:-vote_db}"
DB_USER="${DB_USER:-vote_user}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
S3_BACKUP_BUCKET="${S3_BACKUP_BUCKET:-}"

# Минимальный правдоподобный размер дампа (схема + таблицы > 10 КБ)
MIN_BYTES="${MIN_BYTES:-10240}"

STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"
TARGET="$BACKUP_DIR/${DB_NAME}-${STAMP}.dump"

echo "=== Снятие резервной копии базы данных ==="
echo "База: ${DB_NAME}, Назначение: ${TARGET}"

# Определение способа запуска: через Docker Compose или напрямую
if command -v docker >/dev/null 2>&1 && docker compose -f docker-compose.prod.yml ps postgres 2>/dev/null | grep -q "postgres"; then
    echo "Используется контейнер docker compose postgres..."
    docker compose -f docker-compose.prod.yml exec -T postgres \
        pg_dump --format=custom --compress=6 --no-owner --no-privileges \
                --username="${DB_USER}" --dbname="${DB_NAME}" > "$TARGET"
else
    echo "Используется локальный pg_dump (${DB_HOST}:${DB_PORT})..."
    pg_dump --format=custom --compress=6 --no-owner --no-privileges \
            --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" \
            --dbname="$DB_NAME" --file="$TARGET"
fi

SIZE="$(wc -c < "$TARGET" | tr -d ' ')"
if [ "$SIZE" -lt "$MIN_BYTES" ]; then
    echo "ОШИБКА: дамп ${SIZE} Б, меньше порога ${MIN_BYTES} Б. Бэкап НЕ создан." >&2
    rm -f "$TARGET"
    exit 1
fi

# Проверка читаемости дампа через pg_restore
if command -v pg_restore >/dev/null 2>&1; then
    if ! pg_restore --list "$TARGET" > /dev/null 2>&1; then
        echo "ОШИБКА: pg_restore не может прочитать ${TARGET}. Бэкап повреждён!" >&2
        rm -f "$TARGET"
        exit 1
    fi
elif command -v docker >/dev/null 2>&1 && docker compose -f docker-compose.prod.yml ps postgres 2>/dev/null | grep -q "postgres"; then
    if ! docker compose -f docker-compose.prod.yml exec -T postgres pg_restore --list < "$TARGET" > /dev/null 2>&1; then
        echo "ОШИБКА: pg_restore в контейнере не может прочитать ${TARGET}. Бэкап повреждён!" >&2
        rm -f "$TARGET"
        exit 1
    fi
fi

echo "Успешно: ${TARGET} (${SIZE} Б)"

# ------------------------------------------------------------------------------
# Копирование на внешнее хранилище (ТЗ п.8, 29)
# ------------------------------------------------------------------------------
if [ -n "${S3_BACKUP_BUCKET}" ]; then
    echo "==> Копирование дампа на внешнее хранилище: ${S3_BACKUP_BUCKET}..."
    UPLOAD_OK=false

    if command -v aws >/dev/null 2>&1; then
        if aws s3 cp "$TARGET" "${S3_BACKUP_BUCKET}/$(basename "$TARGET")"; then
            UPLOAD_OK=true
            echo "    [OK] Дамп успешно выгружен в ${S3_BACKUP_BUCKET}/$(basename "$TARGET")"
        else
            echo "ОШИБКА: Команда 'aws s3 cp' завершилась сбоем при выгрузке в ${S3_BACKUP_BUCKET}!" >&2
        fi
    elif command -v rclone >/dev/null 2>&1; then
        if rclone copy "$TARGET" "${S3_BACKUP_BUCKET}"; then
            UPLOAD_OK=true
            echo "    [OK] Дамп успешно выгружен через rclone в ${S3_BACKUP_BUCKET}"
        else
            echo "ОШИБКА: Команда 'rclone copy' завершилась сбоем при выгрузке в ${S3_BACKUP_BUCKET}!" >&2
        fi
    else
        echo "ОШИБКА: S3_BACKUP_BUCKET=${S3_BACKUP_BUCKET} задан, но утилиты aws-cli и rclone отсутствуют на сервере!" >&2
    fi

    if [ "$UPLOAD_OK" != true ]; then
        echo "ОШИБКА: Выгрузка резервной копии на внешнее хранилище НЕ удалась. Локальный дамп сохранён: ${TARGET}." >&2
        echo "Резервная копия НЕ считается выполненной. Завершение с ошибкой." >&2
        exit 1
    fi
fi

# ------------------------------------------------------------------------------
# Ротация локальных копий
# ------------------------------------------------------------------------------
if [ "$RETENTION_DAYS" -gt 0 ]; then
    echo "Удаление локальных копий старше ${RETENTION_DAYS} дней..."
    find "$BACKUP_DIR" -name "${DB_NAME}-*.dump" -type f -mtime "+${RETENTION_DAYS}" -print -delete 2>/dev/null || true
fi

echo
echo "Бэкап не считается проверенным, пока из него не восстановились."
echo "Проверка: ./scripts/verify_backup.sh ${TARGET}"
