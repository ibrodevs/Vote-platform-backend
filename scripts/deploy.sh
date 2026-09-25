#!/usr/bin/env bash
# ==============================================================================
# Production Deployment Script for Vote Platform Backend
# Hetzner Cloud HEL1 — CCX33 (Ubuntu 24.04 LTS)
# ==============================================================================
# Порядок развёртывания (ТЗ п.3, 4, 10, 14, 30, 36):
#   1. Проверка окружения (.env, preflight)
#   2. Генерация актуальных конфигураций Nginx (домен, admin IP allowlist)
#   3. Сборка Docker-образов
#   4. Запуск зависимостей: PostgreSQL, PgBouncer, Redis
#   5. Ожидание готовности (healthcheck) инфраструктуры
#   6. Применение миграций БД (однократно до запуска воркеров)
#   7. Сборка статических файлов (collectstatic) в volume
#   8. Прогон проверок production_check
#   9. Запуск приложения (Gunicorn), Celery и Nginx
#  10. Верификация health-эндпоинтов:
#        - bootstrap: HTTP over IP (http://127.0.0.1/health/ready)
#        - production: HTTPS over domain (https://${API_DOMAIN}/health/ready)
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
step "[1/10] Проверка конфигурации и запуск preflight..."
if [ ! -f .env ]; then
    fail "Файл .env не найден! Скопируйте .env.example в .env и заполните секреты."
fi

# Безопасное считывание параметров для деплоя
get_env() {
    grep -E "^${1}=" .env | cut -d '=' -f2- | tr -d '"' | tr -d "'" | tr -d '\r' | xargs || true
}

DEPLOYMENT_STAGE="$(get_env DEPLOYMENT_STAGE)"
DEPLOYMENT_STAGE="${DEPLOYMENT_STAGE:-bootstrap}"
API_DOMAIN="$(get_env API_DOMAIN)"
ADMIN_ALLOWED_IP="$(get_env ADMIN_ALLOWED_IP)"
NGINX_CONF_FILE="$(get_env NGINX_CONF_FILE)"
NGINX_CONF_FILE="${NGINX_CONF_FILE:-http.conf}"

validate_domain() {
    local domain="$1"
    if [[ ! "${domain}" =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$ ]] || [[ "${domain}" =~ [\/:\;[:space:]\$\`\\] ]] || [[ "${domain}" == *".."* ]]; then
        return 1
    fi
    return 0
}

validate_ip_or_cidr() {
    local ip="$1"
    if [[ "${ip}" =~ [^a-fA-F0-9.:/] ]] || [ -z "${ip}" ]; then
        return 1
    fi
    local ipv4_cidr_regex="^([0-9]{1,3}\.){3}[0-9]{1,3}(/([0-9]|[1-2][0-9]|3[0-2]))?$"
    local ipv6_cidr_regex="^([0-9a-fA-F]{0,4}:){1,7}[0-9a-fA-F]{0,4}(/([0-9]|[1-9][0-9]|1[0-1][0-9]|12[0-8]))?$"

    if [[ "${ip}" =~ $ipv4_cidr_regex ]]; then
        local base_ip="${ip%%/*}"
        IFS='.' read -r o1 o2 o3 o4 <<< "$base_ip"
        if [ "$o1" -le 255 ] && [ "$o2" -le 255 ] && [ "$o3" -le 255 ] && [ "$o4" -le 255 ]; then
            return 0
        fi
        return 1
    elif [[ "${ip}" =~ $ipv6_cidr_regex ]] && [[ "${ip}" == *":"* ]]; then
        return 0
    fi
    return 1
}

# Запуск preflight проверки (ТЗ п.14)
if [ -x ./scripts/preflight.sh ]; then
    ./scripts/preflight.sh || fail "Preflight проверка не прошла. Деплой отменён."
fi

# Ранняя проверка production-требований до запуска Docker (fail-fast)
if [ "${DEPLOYMENT_STAGE}" = "production" ]; then
    if [ -z "${API_DOMAIN}" ]; then
        fail "В режиме DEPLOYMENT_STAGE=production переменная API_DOMAIN обязательна!"
    fi
    if ! validate_domain "${API_DOMAIN}"; then
        fail "API_DOMAIN содержит недопустимые символы: '${API_DOMAIN}'"
    fi
    if [ -z "${ADMIN_ALLOWED_IP}" ]; then
        fail "В режиме DEPLOYMENT_STAGE=production переменная ADMIN_ALLOWED_IP обязательна для защиты панели управления Django!"
    fi
    if ! validate_ip_or_cidr "${ADMIN_ALLOWED_IP}"; then
        fail "ADMIN_ALLOWED_IP содержит некорректный IP/CIDR адрес: '${ADMIN_ALLOWED_IP}'"
    fi
    if [ "${NGINX_CONF_FILE}" != "https.conf" ]; then
        fail "В режиме DEPLOYMENT_STAGE=production требуется NGINX_CONF_FILE=https.conf (получено: '${NGINX_CONF_FILE}')"
    fi
    if [ ! -s deploy/certs/fullchain.pem ] || [ ! -s deploy/certs/privkey.pem ]; then
        fail "Отсутствуют TLS-сертификаты в deploy/certs/ (fullchain.pem и privkey.pem обязательны в production)!"
    fi
fi

# ------------------------------------------------------------------------------
# 2. Подготовка конфигураций Nginx (Domain & Admin Allowlist)
# ------------------------------------------------------------------------------
step "[2/10] Подготовка конфигураций Nginx..."

# Настройка IP allowlist для Django Admin (ТЗ п.10, 11, 12, 13)
mkdir -p deploy/nginx
if [ -n "${ADMIN_ALLOWED_IP}" ]; then
    if ! validate_ip_or_cidr "${ADMIN_ALLOWED_IP}"; then
        fail "Недопустимый ADMIN_ALLOWED_IP: '${ADMIN_ALLOWED_IP}'"
    fi
    echo "  Настройка ограничения доступа к Django Admin по IP: ${ADMIN_ALLOWED_IP}..."
    cat << EOF > deploy/nginx/admin_ips.conf
# Auto-generated by deploy.sh from ADMIN_ALLOWED_IP
allow ${ADMIN_ALLOWED_IP};
deny all;
EOF
elif [ "${DEPLOYMENT_STAGE}" = "production" ]; then
    fail "В режиме DEPLOYMENT_STAGE=production переменная ADMIN_ALLOWED_IP обязательна!"
else
    cat << 'EOF' > deploy/nginx/admin_ips.conf
# IP allowlist для доступа к Django Admin (Bootstrap Mode — открыт для начальной настройки)
EOF
fi

# Генерация https.conf из шаблона при наличии API_DOMAIN (ТЗ п.4, 10)
if [ -n "${API_DOMAIN}" ] && [ -f deploy/nginx/templates/https.conf.template ]; then
    if ! validate_domain "${API_DOMAIN}"; then
        fail "API_DOMAIN содержит недопустимые символы: '${API_DOMAIN}'"
    fi
    echo "  Генерация deploy/nginx/conf.d/https.conf для домена: ${API_DOMAIN}..."
    mkdir -p deploy/nginx/conf.d
    sed "s|\${API_DOMAIN}|${API_DOMAIN}|g" deploy/nginx/templates/https.conf.template > deploy/nginx/conf.d/https.conf
fi

# ------------------------------------------------------------------------------
# 3. Сборка Docker-образов
# ------------------------------------------------------------------------------
step "[3/10] Сборка Docker-образов..."
${COMPOSE} build

# ------------------------------------------------------------------------------
# 4. Запуск зависимостей базы данных и брокера
# ------------------------------------------------------------------------------
step "[4/10] Запуск инфраструктуры: PostgreSQL, PgBouncer, Redis..."
${COMPOSE} up -d postgres redis pgbouncer

# ------------------------------------------------------------------------------
# 5. Ожидание готовности инфраструктуры
# ------------------------------------------------------------------------------
step "[5/10] Ожидание готовности (healthcheck) PostgreSQL, Redis, PgBouncer..."
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

    echo "  Ожидание готовности сервисов (${WAIT}c / ${MAX_WAIT}c)... [postgres=${PG_STATUS}, pgbouncer=${PGB_STATUS}, redis=${REDIS_STATUS}]"
    sleep 3
    WAIT=$((WAIT + 3))
done

if [ $WAIT -ge $MAX_WAIT ]; then
    fail "Таймаут ожидания готовности инфраструктуры! Проверьте логи: ${COMPOSE} logs postgres pgbouncer redis"
fi

# ------------------------------------------------------------------------------
# 6. Применение миграций БД
# ------------------------------------------------------------------------------
step "[6/10] Применение миграций базы данных..."
# Миграции выполняются однократно через временный контейнер (ТЗ п.30).
${COMPOSE} run --rm app python manage.py migrate --noinput

# ------------------------------------------------------------------------------
# 7. Сборка статики
# ------------------------------------------------------------------------------
step "[7/10] Сборка статических файлов в общий том..."
${COMPOSE} run --rm app python manage.py collectstatic --noinput

# ------------------------------------------------------------------------------
# 8. Проверка production_check
# ------------------------------------------------------------------------------
step "[8/10] Запуск проверок production_check..."
${COMPOSE} run --rm app python manage.py production_check

# ------------------------------------------------------------------------------
# 9. Запуск приложения, Celery и Nginx
# ------------------------------------------------------------------------------
step "[9/10] Запуск app (Gunicorn), celery-default, celery-heavy и nginx..."
${COMPOSE} up -d app celery-default celery-heavy nginx

# ------------------------------------------------------------------------------
# 10. Проверка доступности и health-эндпоинтов
# ------------------------------------------------------------------------------
step "[10/10] Проверка статуса сервисов и верификация health-эндпоинтов..."
APP_WAIT=45
WAIT=0
while [ $WAIT -lt $APP_WAIT ]; do
    APP_STATUS=$(${COMPOSE} ps app --format '{{.Health}}' 2>/dev/null || echo "unhealthy")
    NGINX_STATUS=$(${COMPOSE} ps nginx --format '{{.Health}}' 2>/dev/null || echo "unhealthy")
    if [ "$APP_STATUS" = "healthy" ] && [ "$NGINX_STATUS" = "healthy" ]; then
        break
    fi
    echo "  Ожидание готовности контейнеров (${WAIT}c / ${APP_WAIT}c)... [app=${APP_STATUS}, nginx=${NGINX_STATUS}]"
    sleep 3
    WAIT=$((WAIT + 3))
done

echo ""
echo "=== Проверка Nginx internal healthcheck ==="
NGINX_HEALTH=$(${COMPOSE} exec -T nginx wget -qO- http://127.0.0.1/nginx-health 2>/dev/null || echo "FAILED")
echo "  /nginx-health: ${NGINX_HEALTH}"
if [ "${NGINX_HEALTH}" != "ok" ]; then
    fail "Внутренний healthcheck Nginx не ответил 'ok'!"
fi

echo ""
if [ "${DEPLOYMENT_STAGE}" = "bootstrap" ]; then
    echo "=== Режим BOOTSTRAP (HTTP over IP) ==="
    echo "1. GET http://127.0.0.1/health/live:"
    LIVE_RESP=$(curl -fsS http://127.0.0.1/health/live 2>/dev/null || echo "FAILED")
    echo "   Ответ: ${LIVE_RESP}"

    echo "2. GET http://127.0.0.1/health/ready:"
    READY_RESP=$(curl -fsS http://127.0.0.1/health/ready 2>/dev/null || echo "FAILED")
    echo "   Ответ: ${READY_RESP}"

    if [ "${LIVE_RESP}" = "FAILED" ] || [ "${READY_RESP}" = "FAILED" ]; then
        fail "Bootstrap healthcheck завершился ошибкой! Проверьте логи: ${COMPOSE} logs app nginx"
    fi
else
    echo "=== Режим PRODUCTION (HTTPS over Domain) ==="
    if [ -z "${API_DOMAIN}" ]; then
        fail "В режиме DEPLOYMENT_STAGE=production переменная API_DOMAIN обязательна в .env!"
    fi

    echo "1. GET https://${API_DOMAIN}/health/live (строгая проверка TLS):"
    LIVE_RESP=$(curl -fsS "https://${API_DOMAIN}/health/live" 2>/dev/null || echo "FAILED")
    echo "   Ответ: ${LIVE_RESP}"

    echo "2. GET https://${API_DOMAIN}/health/ready (строгая проверка TLS):"
    READY_RESP=$(curl -fsS "https://${API_DOMAIN}/health/ready" 2>/dev/null || echo "FAILED")
    echo "   Ответ: ${READY_RESP}"

    if [ "${LIVE_RESP}" = "FAILED" ] || [ "${READY_RESP}" = "FAILED" ]; then
        fail "Production HTTPS healthcheck не прошёл проверку на домене https://${API_DOMAIN}! Проверьте DNS-записи и TLS-сертификаты."
    fi
fi

echo ""
step "Деплой успешно завершён!"
${COMPOSE} ps

echo ""
echo "=================================================================="
echo -e "${GREEN}Vote Platform Backend успешно развёрнут и верифицирован!${NC}"
echo "=================================================================="
