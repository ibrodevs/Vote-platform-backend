#!/usr/bin/env bash
# Резервная копия базы (ТЗ п.47).
#
# Формат custom (-Fc), а не plain SQL: он сжат, восстанавливается
# параллельно и позволяет восстановить отдельные таблицы.
#
#   ./scripts/backup.sh                      # в ./backups
#   BACKUP_DIR=/mnt/backups ./scripts/backup.sh
#
# Скрипт отказывается считать успехом пустой или подозрительно маленький
# файл: молча созданный нулевой дамп — худший вид бэкапа, потому что он
# выглядит как сделанный.

set -euo pipefail

DB_NAME="${DB_NAME:-vote_db}"
DB_USER="${DB_USER:-vote_user}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

# Минимальный правдоподобный размер дампа. База со схемой и без данных
# уже весит десятки килобайт; всё, что меньше, — признак сбоя.
MIN_BYTES="${MIN_BYTES:-10240}"

STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"
TARGET="$BACKUP_DIR/${DB_NAME}-${STAMP}.dump"

echo "Снимаю дамп ${DB_NAME} с ${DB_HOST}:${DB_PORT} -> ${TARGET}"
pg_dump --format=custom --compress=6 --no-owner --no-privileges \
        --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" \
        --dbname="$DB_NAME" --file="$TARGET"

SIZE="$(wc -c < "$TARGET" | tr -d ' ')"
if [ "$SIZE" -lt "$MIN_BYTES" ]; then
  echo "ОШИБКА: дамп ${SIZE} Б, меньше порога ${MIN_BYTES} Б. Бэкап НЕ создан." >&2
  rm -f "$TARGET"
  exit 1
fi

# Содержимое дампа читается заголовком: файл, который pg_restore не понимает,
# бэкапом не является, каким бы большим он ни был.
if ! pg_restore --list "$TARGET" > /dev/null 2>&1; then
  echo "ОШИБКА: pg_restore не может прочитать ${TARGET}. Бэкап НЕ создан." >&2
  rm -f "$TARGET"
  exit 1
fi

echo "Готово: ${TARGET} (${SIZE} Б)"

if [ "$RETENTION_DAYS" -gt 0 ]; then
  echo "Удаляю копии старше ${RETENTION_DAYS} дней"
  find "$BACKUP_DIR" -name "${DB_NAME}-*.dump" -type f -mtime "+${RETENTION_DAYS}" -print -delete || true
fi

echo
echo "Бэкап не считается сделанным, пока из него не восстановились."
echo "Проверка: ./scripts/verify_backup.sh ${TARGET}"
