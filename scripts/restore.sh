#!/usr/bin/env bash
# Восстановление базы из дампа (ТЗ п.47).
#
# ЭТА КОМАНДА УНИЧТОЖАЕТ ТЕКУЩУЮ БАЗУ. Поэтому она требует явного
# подтверждения и не запускается по недосмотру.
#
#   ./scripts/restore.sh backups/vote_db-20260923-120000.dump
#   CONFIRM=yes ./scripts/restore.sh <файл>     # без вопроса, для runbook
#
# Перед восстановлением остановите приложение и Celery: восстановление
# в базу, куда продолжают писать, даёт смесь старых и новых данных.

set -euo pipefail

DUMP="${1:?Укажите файл дампа}"
DB_NAME="${DB_NAME:-vote_db}"
DB_USER="${DB_USER:-vote_user}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"

PSQL=(psql --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" --no-psqlrc --quiet)

[ -f "$DUMP" ] || { echo "Файл не найден: $DUMP" >&2; exit 1; }
pg_restore --list "$DUMP" >/dev/null || { echo "Это не дамп pg_dump -Fc: $DUMP" >&2; exit 1; }

echo "Будет ПОЛНОСТЬЮ ЗАМЕНЕНА база ${DB_NAME} на ${DB_HOST}:${DB_PORT}"
echo "Источник: ${DUMP}"
if [ "${CONFIRM:-}" != "yes" ]; then
  printf 'Введите имя базы для подтверждения: '
  read -r answer
  [ "$answer" = "$DB_NAME" ] || { echo "Отменено." >&2; exit 1; }
fi

# Страховочная копия текущего состояния. Восстановление из неверного
# дампа — обычная ошибка, и откатить её должно быть чем.
SAFETY="/tmp/pre-restore-${DB_NAME}-$(date +%Y%m%d-%H%M%S).dump"
echo "Снимаю страховочную копию текущей базы -> ${SAFETY}"
pg_dump --format=custom --no-owner --no-privileges \
        --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" \
        --dbname="$DB_NAME" --file="$SAFETY" || echo "предупреждение: страховочная копия не снята"

echo "Отключаю оставшиеся соединения..."
"${PSQL[@]}" --dbname=postgres --command="
  SELECT pg_terminate_backend(pid) FROM pg_stat_activity
  WHERE datname = '$DB_NAME' AND pid <> pg_backend_pid();" >/dev/null

echo "Пересоздаю базу..."
"${PSQL[@]}" --dbname=postgres --command="DROP DATABASE IF EXISTS \"$DB_NAME\";" >/dev/null
"${PSQL[@]}" --dbname=postgres --command="CREATE DATABASE \"$DB_NAME\";" >/dev/null

echo "Восстанавливаю..."
pg_restore --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" \
           --dbname="$DB_NAME" --no-owner --no-privileges "$DUMP"

echo
echo "Восстановление завершено. Страховочная копия: ${SAFETY}"
echo "Обязательный следующий шаг:"
echo "  python manage.py migrate --check"
echo "  python manage.py verify_election_integrity"
