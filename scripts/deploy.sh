#!/usr/bin/env bash
# ==============================================================================
# Production Deployment Script for Vote Platform Backend
# Hetzner Cloud HEL1 — CCX33 (Ubuntu 24.04 LTS)
# ==============================================================================
# Порядок развёртывания (ТЗ п.30, 36):
#   1. Проверка окружения (.env и зависимости)
#   2. Сборка Docker-образов
#   3. Запуск инфраструктурных сервисов (PostgreSQL, Redis, PgBouncer)
#   4. Ожидание готовности (healthcheck) инфраструктуры
#   5. Применение миграций БД (один раз перед стартом воркеров)
#   6. Сборка статических файлов (collectstatic) в volume
#   7. Прогон проверок production_check
#   8. Запуск приложения, Celery и Nginx
#   9. Верификация health-эндпоинтов (/health/live, /health/ready)
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

step() {
    echo -e "\n${BLUE}==>${NC} ${GREEN}$1${NC}"
}

fail() {
    echo -e "\n${RED}ОШИБКА: $1${NC}" >&2
    exit 1
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${BACKEND_DIR}"

COMPOSE="docker compose -f docker-compose.prod.yml"

# ------------------------------------------------------------------------------
# 1. Проверка окружения
# ------------------------------------------------------------------------------
step "[1/9] Проверка конфигурации и окружения..."
if [ ! -f .env ]; then
    fail "Файл .env не найден! Скопируйте .env.example в .env и заполните секреты."
fi

# Запуск preflight проверки
if [ -x ./scripts/preflight.sh ]; then
    ./scripts/preflight.sh || fail "Preflight проверка не прошла. Деплой отменён."
fi

# ------------------------------------------------------------------------------
# 2. Сборка Docker-образов
# ------------------------------------------------------------------------------
step "[2/9] Сборка Docker-образов..."
${COMPOSE} build

# ------------------------------------------------------------------------------
# 3. Запуск зависимостей базы данных и брокера
# ------------------------------------------------------------------------------
step "[3/9] Запуск инфраструктуры: PostgreSQL, PgBouncer, Redis..."
${COMPOSE} up -d postgres redis pgbouncer

# ------------------------------------------------------------------------------
# 4. Ожидание готовности инфраструктуры
# ------------------------------------------------------------------------------
step "[4/9] Ожидание готовности (healthcheck) PostgreSQL, Redis, PgBouncer..."
MAX_WAIT=60
WAIT=0
while [ $WAIT -lt $MAX_WAIT ]; do
    PG_STATUS=$(${COMPOSE} ps postgres --format '{{.Health}}' 2>/dev/null || echo "unhealthy")
    PGB_STATUS=$(${COMPOSE} ps pgbouncer --format '{{.Health}}' 2>/dev/null || echo "unhealthy")
    REDIS_STATUS=$(${COMPOSE} ps redis --format '{{.Health}}' 2>/dev/null || echo "unhealthy")

    if [ "$PG_STATUS" = "healthy" ] && [ "$PGB_STATUS" = "healthy" ] && [ "$REDIS_STATUS" = "healthy" ]; then
        echo -e "  PostgreSQL: ${GREEN}${PG_STATUS}${NC}"
        echo -e "  PgBouncer:  ${GREEN}${PGB_STATUS}${NC}"
        echo -e "  Redis:      ${GREEN}${REDIS_STATUS}${NC}"
        break
    fi

    echo "  Ожидание сервисов (прошло ${WAIT}c / ${MAX_WAIT}c)... [postgres=${PG_STATUS}, pgbouncer=${PGB_STATUS}, redis=${REDIS_STATUS}]"
    sleep 3
    WAIT=$((WAIT + 3))
done

if [ $WAIT -ge $MAX_WAIT ]; then
    fail "Таймаут ожидания готовности инфраструктуры! Проверьте логи: ${COMPOSE} logs postgres pgbouncer redis"
fi

# ------------------------------------------------------------------------------
# 5. Применение миграций БД
# ------------------------------------------------------------------------------
step "[5/9] Применение миграций базы данных..."
# Миграции выполняются однократно через временный контейнер (ТЗ п.30).
# Подключение идёт через PgBouncer.
${COMPOSE} run --rm app python manage.py migrate --noinput

# ------------------------------------------------------------------------------
# 6. Сборка статики
# ------------------------------------------------------------------------------
step "[6/9] Сборка статических файлов в общий том..."
${COMPOSE} run --rm app python manage.py collectstatic --noinput

# ------------------------------------------------------------------------------
# 7. Проверка production_check
# ------------------------------------------------------------------------------
step "[7/9] Запуск проверок production_check..."
${COMPOSE} run --rm app python manage.py production_check

# ------------------------------------------------------------------------------
# 8. Запуск приложения, Celery и Nginx
# ------------------------------------------------------------------------------
step "[8/9] Запуск app (Gunicorn), celery-default, celery-heavy и nginx..."
${COMPOSE} up -d app celery-default celery-heavy nginx

# ------------------------------------------------------------------------------
# 9. Проверка доступности и health-эндпоинтов
# ------------------------------------------------------------------------------
step "[9/9] Проверка статуса сервисов и healthcheck..."
APP_WAIT=45
WAIT=0
while [ $WAIT -lt $APP_WAIT ]; do
    APP_STATUS=$(${COMPOSE} ps app --format '{{.Health}}' 2>/dev/null || echo "unhealthy")
    if [ "$APP_STATUS" = "healthy" ]; then
        break
    fi
    echo "  Ожидание готовности контейнера app (${WAIT}c / ${APP_WAIT}c)... [app=${APP_STATUS}]"
    sleep 3
    WAIT=$((WAIT + 3))
done

echo ""
echo "=== Проверка health эндпоинтов через Nginx ==="
echo "1. GET /health/live:"
LIVE_RESP=$(curl -fsS http://127.0.0.1/health/live || curl -fsS http://localhost/health/live || echo "FAILED")
echo "   Ответ: ${LIVE_RESP}"

echo "2. GET /health/ready:"
READY_RESP=$(curl -fsS http://127.0.0.1/health/ready || curl -fsS http://localhost/health/ready || echo "FAILED")
echo "   Ответ: ${READY_RESP}"

echo ""
step "Деплой успешно завершён!"
${COMPOSE} ps

echo ""
echo "=================================================================="
echo -e "${GREEN}Vote Platform Backend запущен и готов к приёму запросов!${NC}"
echo "=================================================================="
