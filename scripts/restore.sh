#!/usr/bin/env bash
# ==============================================================================
# Восстановление базы данных из дампа (ТЗ п.1, 29, 47)
# ==============================================================================
# ВНИМАНИЕ: ЭТА ОПЕРАЦИЯ ПОЛНОСТЬЮ ЗАМЕНЯЕТ ТЕКУЩУЮ БАЗУ ДАННЫХ.
#
# Порядок выполнения:
#   1. Валидация входного дампа (pg_restore --list)
#   2. Явное подтверждение от пользователя (или CONFIRM=yes)
#   3. Остановка пишущих сервисов (app, celery-default, celery-heavy)
#   4. Создание страховочной копии текущей базы (pre-restore dump)
#   5. Валидация страховочной копии (при ошибке — НЕМЕДЛЕННАЯ ОСТАНОВКА)
#   6. Отключение активных соединений к базе
#   7. DROP DATABASE (отдельным вызовом psql)
#   8. CREATE DATABASE (отдельным вызовом psql)
#   9. Восстановление данных из дампа
#  10. Проверка миграций (migrate --check)
#  11. Проверка целостности данных (audit_db_data)
#  12. Запуск остановленных сервисов
#  13. Healthcheck приложения
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
[ -f "$DUMP" ] || { echo "ОШИБКА: Файл не найден: $DUMP" >&2; exit 1; }

# Загрузка переменных окружения из .env если файл существует
if [ -f .env ]; then
    export $(grep -E '^(DB_NAME|DB_USER|DB_PASSWORD)=' .env | xargs -d '\n' 2>/dev/null || grep -E '^(DB_NAME|DB_USER|DB_PASSWORD)=' .env || true)
fi

DB_NAME="${DB_NAME:-vote_db}"
DB_USER="${DB_USER:-vote_user}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"

COMPOSE="docker compose -f docker-compose.prod.yml"

USE_DOCKER=false
if command -v docker >/dev/null 2>&1 && ${COMPOSE} ps postgres 2>/dev/null | grep -q "postgres"; then
    USE_DOCKER=true
fi

echo "=================================================================="
echo " Восстановление PostgreSQL базы данных Vote Platform"
echo " База назначения: ${DB_NAME}"
echo " Файл дампа:      ${DUMP}"
echo " Режим работы:    $([ "$USE_DOCKER" = true ] && echo "Docker Compose" || echo "Direct Host")"
echo "=================================================================="

# ------------------------------------------------------------------------------
# 1. Валидация входного дампа
# ------------------------------------------------------------------------------
echo "==> [1/13] Валидация входного дампа..."
if command -v pg_restore >/dev/null 2>&1; then
    pg_restore --list "$DUMP" >/dev/null || { echo "ОШИБКА: Файл не является валидным pg_dump -Fc дампом: $DUMP" >&2; exit 1; }
elif [ "$USE_DOCKER" = true ]; then
    ${COMPOSE} exec -T postgres pg_restore --list < "$DUMP" >/dev/null || { echo "ОШИБКА: Файл не является валидным pg_dump -Fc дампом: $DUMP" >&2; exit 1; }
fi
echo "    Дамп валиден и доступен для чтения."

# ------------------------------------------------------------------------------
# 2. Подтверждение пользователя
# ------------------------------------------------------------------------------
echo "==> [2/13] Проверка подтверждения..."
if [ "${CONFIRM:-}" != "yes" ]; then
    printf 'Для подтверждения введите точное имя базы данных (%s): ' "$DB_NAME"
    read -r answer
    if [ "$answer" != "$DB_NAME" ]; then
        echo "Отменено пользователем." >&2
        exit 1
    fi
fi

# ------------------------------------------------------------------------------
# 3. Остановка пишущих сервисов (writers)
# ------------------------------------------------------------------------------
echo "==> [3/13] Остановка пишущих сервисов (app, celery-default, celery-heavy)..."
if [ "$USE_DOCKER" = true ]; then
    ${COMPOSE} stop app celery-default celery-heavy
    echo "    Сервисы app, celery-default, celery-heavy остановлены."
else
    echo "    ВНИМАНИЕ: Direct Host режим. Убедитесь, что фоновые воркеры и web-сервер остановлены!"
fi

# ------------------------------------------------------------------------------
# 4. Создание обязательной страховочной копии текущей базы
# ------------------------------------------------------------------------------
SAFETY="/tmp/pre-restore-${DB_NAME}-$(date +%Y%m%d-%H%M%S).dump"
echo "==> [4/13] Создание страховочной копии текущего состояния базы -> ${SAFETY}..."

if [ "$USE_DOCKER" = true ]; then
    if ! ${COMPOSE} exec -T postgres pg_dump --format=custom --compress=6 \
        --username="$DB_USER" --dbname="$DB_NAME" > "$SAFETY"; then
        echo "ОШИБКА: Не удалось создать страховочный дамп! ВОССТАНОВЛЕНИЕ ПРЕРВАНО." >&2
        rm -f "$SAFETY"
        exit 1
    fi
else
    if ! pg_dump --format=custom --compress=6 --no-owner --no-privileges \
        --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" \
        --dbname="$DB_NAME" --file="$SAFETY"; then
        echo "ОШИБКА: Не удалось создать страховочный дамп! ВОССТАНОВЛЕНИЕ ПРЕРВАНО." >&2
        rm -f "$SAFETY"
        exit 1
    fi
fi

# Проверка размера страховочного дампа
SAFETY_SIZE="$(wc -c < "$SAFETY" | tr -d ' ')"
if [ "$SAFETY_SIZE" -lt 1024 ]; then
    echo "ОШИБКА: Страховочный дамп пуст или слишком мал (${SAFETY_SIZE} Б). ВОССТАНОВЛЕНИЕ ПРЕРВАНО." >&2
    rm -f "$SAFETY"
    exit 1
fi

# ------------------------------------------------------------------------------
# 5. Валидация страховочной копии
# ------------------------------------------------------------------------------
echo "==> [5/13] Проверка целостности страховочной копии..."
SAFETY_VALID=false
if command -v pg_restore >/dev/null 2>&1; then
    if pg_restore --list "$SAFETY" >/dev/null 2>&1; then
        SAFETY_VALID=true
    fi
elif [ "$USE_DOCKER" = true ]; then
    if ${COMPOSE} exec -T postgres pg_restore --list < "$SAFETY" >/dev/null 2>&1; then
        SAFETY_VALID=true
    fi
fi

if [ "$SAFETY_VALID" != true ]; then
    echo "ОШИБКА: Страховочная копия повреждена и не читается pg_restore! ВОССТАНОВЛЕНИЕ ПРЕРВАНО." >&2
    rm -f "$SAFETY"
    exit 1
fi
echo "    Страховочная копия успешно создана и верифицирована (${SAFETY_SIZE} Б)."

# ------------------------------------------------------------------------------
# 6. Отключение активных клиентских соединений
# ------------------------------------------------------------------------------
echo "==> [6/13] Принудительное закрытие активных соединений с базой ${DB_NAME}..."
TERMINATE_SQL="SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$DB_NAME' AND pid <> pg_backend_pid();"

if [ "$USE_DOCKER" = true ]; then
    ${COMPOSE} exec -T postgres psql --username="$DB_USER" --dbname="postgres" -c "$TERMINATE_SQL" >/dev/null 2>&1 || true
else
    psql --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" --dbname="postgres" -c "$TERMINATE_SQL" >/dev/null 2>&1 || true
fi

# ------------------------------------------------------------------------------
# 7. Удаление старой базы данных (DROP DATABASE отдельным вызовом)
# ------------------------------------------------------------------------------
echo "==> [7/13] Удаление старой базы данных (DROP DATABASE)..."
DROP_CMD="DROP DATABASE IF EXISTS \"$DB_NAME\";"

if [ "$USE_DOCKER" = true ]; then
    ${COMPOSE} exec -T postgres psql --username="$DB_USER" --dbname="postgres" -c "$DROP_CMD"
else
    psql --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" --dbname="postgres" -c "$DROP_CMD"
fi

# ------------------------------------------------------------------------------
# 8. Создание чистой базы данных (CREATE DATABASE отдельным вызовом)
# ------------------------------------------------------------------------------
echo "==> [8/13] Создание новой пустой базы данных (CREATE DATABASE)..."
CREATE_CMD="CREATE DATABASE \"$DB_NAME\";"

if [ "$USE_DOCKER" = true ]; then
    ${COMPOSE} exec -T postgres psql --username="$DB_USER" --dbname="postgres" -c "$CREATE_CMD"
else
    psql --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" --dbname="postgres" -c "$CREATE_CMD"
fi

# ------------------------------------------------------------------------------
# 9. Восстановление данных из целевого дампа
# ------------------------------------------------------------------------------
echo "==> [9/13] Восстановление данных из дампа..."
if [ "$USE_DOCKER" = true ]; then
    ${COMPOSE} exec -T postgres pg_restore --username="$DB_USER" --dbname="$DB_NAME" --no-owner --no-privileges < "$DUMP"
else
    pg_restore --host="$DB_HOST" --port="$DB_PORT" --username="$DB_USER" \
               --dbname="$DB_NAME" --no-owner --no-privileges "$DUMP"
fi
echo "    Данные успешно загружены."

# ------------------------------------------------------------------------------
# 10. Проверка миграций базы данных
# ------------------------------------------------------------------------------
echo "==> [10/13] Проверка статуса миграций..."
if [ "$USE_DOCKER" = true ]; then
    ${COMPOSE} run --rm app python manage.py migrate --check
else
    python manage.py migrate --check
fi
echo "    Миграции актуальны."

# ------------------------------------------------------------------------------
# 11. Проверка целостности данных (integrity checks)
# ------------------------------------------------------------------------------
echo "==> [11/13] Проверка целостности данных..."
if [ "$USE_DOCKER" = true ]; then
    ${COMPOSE} run --rm app python manage.py audit_db_data
else
    python manage.py audit_db_data
fi
echo "    Целостность данных подтверждена."

# ------------------------------------------------------------------------------
# 12. Запуск остановленных сервисов
# ------------------------------------------------------------------------------
echo "==> [12/13] Запуск сервисов приложения..."
if [ "$USE_DOCKER" = true ]; then
    ${COMPOSE} start app celery-default celery-heavy
fi

# ------------------------------------------------------------------------------
# 13. Проверка здоровья восстановленного сервиса
# ------------------------------------------------------------------------------
echo "==> [13/13] Проверка healthcheck приложения..."
if [ "$USE_DOCKER" = true ]; then
    sleep 3
    READY_STATUS="unknown"
    for i in {1..10}; do
        if curl -fsS http://127.0.0.1/health/ready >/dev/null 2>&1 || curl -fsS http://localhost/health/ready >/dev/null 2>&1; then
            READY_STATUS="ready"
            break
        fi
        sleep 2
    done
    if [ "$READY_STATUS" = "ready" ]; then
        echo "    /health/ready отвечает OK."
    else
        echo "    ПРЕДУПРЕЖДЕНИЕ: /health/ready не ответил сразу. Проверьте логи: ${COMPOSE} logs app"
    fi
fi

echo ""
echo "=================================================================="
echo "Восстановление успешно завершено!"
echo "Страховочная копия сохранена в: ${SAFETY}"
echo "=================================================================="
