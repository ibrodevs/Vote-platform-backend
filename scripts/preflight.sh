#!/usr/bin/env bash
# ==============================================================================
# Preflight Verification Script for Vote Platform Backend
# Hetzner Cloud HEL1 — CCX33 (Ubuntu 24.04 LTS)
# ==============================================================================
# Проверяет готовность сервера и конфигурации к запуску production-деплоя.
# НЕ выводит секреты в консоль.
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ERRORS=0
WARNINGS=0

pass() {
    echo -e "  [${GREEN}OK${NC}] $1"
}

warn() {
    echo -e "  [${YELLOW}WARN${NC}] $1"
    WARNINGS=$((WARNINGS + 1))
}

fail() {
    echo -e "  [${RED}FAIL${NC}] $1"
    ERRORS=$((ERRORS + 1))
}

info() {
    echo -e "${BLUE}==>${NC} $1"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${BACKEND_DIR}"

echo "=================================================================="
echo " Vote Platform Backend: Preflight System Verification"
echo "=================================================================="

# ------------------------------------------------------------------------------
# 1. Проверка Docker и Docker Compose
# ------------------------------------------------------------------------------
info "Проверка Docker окружения..."

if command -v docker >/dev/null 2>&1; then
    pass "Docker CLI установлен: $(docker --version)"
    if docker info >/dev/null 2>&1; then
        pass "Docker daemon доступен и отвечает"
    else
        fail "Docker daemon не запущен или текущий пользователь не входит в группу docker"
    fi
else
    fail "Docker не установлен. Установите Docker: https://docs.docker.com/engine/install/ubuntu/"
fi

if docker compose version >/dev/null 2>&1; then
    pass "Docker Compose v2 доступен: $(docker compose version)"
else
    fail "Docker Compose v2 не найден (требуется docker compose v2.x)"
fi

# ------------------------------------------------------------------------------
# 2. Проверка конфигурации .env
# ------------------------------------------------------------------------------
info "Проверка файла конфигурации (.env)..."

ENV_FILE="${BACKEND_DIR}/.env"
if [ -f "${ENV_FILE}" ]; then
    pass "Файл .env найден"
else
    fail "Файл .env отсутствует! Скопируйте шаблон: cp .env.example .env и задайте секреты"
fi

# Загружаем переменные из .env безопасно для проверок
if [ -f "${ENV_FILE}" ]; then
    get_env() {
        grep -E "^${1}=" "${ENV_FILE}" | cut -d '=' -f2- | tr -d '"' | tr -d "'" | tr -d '\r' | xargs || true
    }

    DJANGO_ENV_VAL="$(get_env DJANGO_ENV)"
    STAGE_VAL="$(get_env DEPLOYMENT_STAGE)"
    SECRET_KEY_VAL="$(get_env DJANGO_SECRET_KEY)"
    ALLOWED_HOSTS_VAL="$(get_env DJANGO_ALLOWED_HOSTS)"
    CORS_VAL="$(get_env DJANGO_CORS_ALLOWED_ORIGINS)"
    DB_PASS_VAL="$(get_env DB_PASSWORD)"
    REDIS_PASS_VAL="$(get_env REDIS_PASSWORD)"
    REDIS_URL_VAL="$(get_env REDIS_URL)"
    CELERY_BROKER_VAL="$(get_env CELERY_BROKER_URL)"
    DB_BEHIND_PG_VAL="$(get_env DB_BEHIND_PGBOUNCER)"
    DB_CONN_AGE_VAL="$(get_env DB_CONN_MAX_AGE)"

    # DJANGO_ENV
    if [ "${DJANGO_ENV_VAL}" = "production" ]; then
        pass "DJANGO_ENV=production"
    else
        fail "DJANGO_ENV должен быть 'production' (получено '${DJANGO_ENV_VAL}')"
    fi

    # DJANGO_SECRET_KEY
    LEAKED_KEY="vote-platform-secret-key-34e8bb-midnight-011c42"
    if [ -z "${SECRET_KEY_VAL}" ]; then
        fail "DJANGO_SECRET_KEY не задан!"
    elif [ "${SECRET_KEY_VAL}" = "${LEAKED_KEY}" ]; then
        fail "DJANGO_SECRET_KEY содержит скомпрометированный ключ из репозитория! Смените немедленно"
    elif [ "${#SECRET_KEY_VAL}" -lt 32 ]; then
        fail "DJANGO_SECRET_KEY короче 32 символов (текущая длина: ${#SECRET_KEY_VAL})"
    else
        pass "DJANGO_SECRET_KEY задан и имеет надёжную длину (${#SECRET_KEY_VAL} симв.)"
    fi

    # Пароли БД и Redis
    if [ -z "${DB_PASS_VAL}" ]; then
        fail "DB_PASSWORD не задан"
    elif [ "${#DB_PASS_VAL}" -lt 16 ]; then
        warn "DB_PASSWORD короче 16 символов"
    else
        pass "DB_PASSWORD задан"
    fi

    if [ -z "${REDIS_PASS_VAL}" ]; then
        fail "REDIS_PASSWORD не задан"
    elif [ "${#REDIS_PASS_VAL}" -lt 16 ]; then
        warn "REDIS_PASSWORD короче 16 символов"
    else
        pass "REDIS_PASSWORD задан"
    fi

    # Проверка на незаменённые плейсхолдеры в URL
    if [[ "${REDIS_URL_VAL}" == *"<REDIS_PASSWORD>"* ]] || [[ "${REDIS_URL_VAL}" == *"пароль"* ]]; then
        fail "REDIS_URL содержит незаменённый плейсхолдер пароля"
    else
        pass "REDIS_URL сконфигурирован"
    fi

    if [[ "${CELERY_BROKER_VAL}" == *"<REDIS_PASSWORD>"* ]] || [[ "${CELERY_BROKER_VAL}" == *"пароль"* ]]; then
        fail "CELERY_BROKER_URL содержит незаменённый плейсхолдер пароля"
    else
        pass "CELERY_BROKER_URL сконфигурирован"
    fi

    # ALLOWED_HOSTS
    if [ -z "${ALLOWED_HOSTS_VAL}" ]; then
        fail "DJANGO_ALLOWED_HOSTS пуст! Укажите IP сервера или домен"
    elif [[ "${ALLOWED_HOSTS_VAL}" == *"*"* ]]; then
        fail "DJANGO_ALLOWED_HOSTS содержит wildcard '*' (запрещено в production)"
    else
        pass "DJANGO_ALLOWED_HOSTS: ${ALLOWED_HOSTS_VAL}"
    fi

    # CORS
    if [ -z "${CORS_VAL}" ]; then
        fail "DJANGO_CORS_ALLOWED_ORIGINS пуст! Фронтенд не сможет отправлять запросы"
    elif [[ "${CORS_VAL}" == *"*"* ]]; then
        fail "DJANGO_CORS_ALLOWED_ORIGINS содержит wildcard '*' (запрещено)"
    else
        pass "DJANGO_CORS_ALLOWED_ORIGINS: ${CORS_VAL}"
    fi

    # PgBouncer пара
    if [ "${DB_BEHIND_PG_VAL}" = "True" ] && [ "${DB_CONN_AGE_VAL}" = "0" ]; then
        pass "DB_BEHIND_PGBOUNCER=True и DB_CONN_MAX_AGE=0 (корректная пара для transaction pooling)"
    else
        fail "Неверная конфигурация PgBouncer! Требуется DB_BEHIND_PGBOUNCER=True и DB_CONN_MAX_AGE=0"
    fi

    # Deployment stage
    if [ "${STAGE_VAL}" = "bootstrap" ]; then
        pass "Режим: DEPLOYMENT_STAGE=bootstrap (проверка по IP over HTTP)"
    elif [ "${STAGE_VAL}" = "production" ]; then
        pass "Режим: DEPLOYMENT_STAGE=production (боевой режим с TLS)"
    else
        warn "Нестандартный DEPLOYMENT_STAGE: '${STAGE_VAL}' (рекомендуется 'bootstrap' или 'production')"
    fi
fi

# ------------------------------------------------------------------------------
# 3. Проверка аппаратных ресурсов (Hetzner CCX33: 8 CPU, 32GB RAM, 240GB NVMe)
# ------------------------------------------------------------------------------
info "Проверка аппаратных ресурсов сервера..."

# RAM
TOTAL_MEM_KB=0
if [ -f /proc/meminfo ]; then
    TOTAL_MEM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
    TOTAL_MEM_GB=$((TOTAL_MEM_KB / 1024 / 1024))
    if [ "${TOTAL_MEM_GB}" -ge 28 ]; then
        pass "Оперативная память: ${TOTAL_MEM_GB} GB (соответствует CCX33 32 GB)"
    elif [ "${TOTAL_MEM_GB}" -ge 14 ]; then
        warn "Оперативная память: ${TOTAL_MEM_GB} GB (меньше ожидаемых 32 GB для CCX33)"
    else
        fail "Оперативная память: ${TOTAL_MEM_GB} GB (недостаточно для CCX33 production стека)"
    fi
elif command -v sysctl >/dev/null 2>&1; then
    # macOS fallback
    TOTAL_MEM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
    TOTAL_MEM_GB=$((TOTAL_MEM_BYTES / 1024 / 1024 / 1024))
    pass "Оперативная память (хост): ${TOTAL_MEM_GB} GB"
fi

# Диск
DISK_AVAIL_KB=$(df -k "${BACKEND_DIR}" | awk 'NR==2 {print $4}')
DISK_AVAIL_GB=$((DISK_AVAIL_KB / 1024 / 1024))
if [ "${DISK_AVAIL_GB}" -ge 20 ]; then
    pass "Доступно свободного места на диске: ${DISK_AVAIL_GB} GB"
elif [ "${DISK_AVAIL_GB}" -ge 5 ]; then
    warn "Доступно места на диске: ${DISK_AVAIL_GB} GB (рекомендуется минимум 20 GB)"
else
    fail "Критически мало места на диске: ${DISK_AVAIL_GB} GB!"
fi

# Swap
if [ -f /proc/swaps ]; then
    SWAP_COUNT=$(grep -v Filename /proc/swaps | wc -l || echo 0)
    if [ "${SWAP_COUNT}" -gt 0 ]; then
        SWAP_KB=$(awk 'NR>1 {sum += $3} END {print sum}' /proc/swaps)
        SWAP_MB=$((SWAP_KB / 1024))
        pass "Swap настроен: ${SWAP_MB} MB"
    else
        warn "Swap не обнаружен. Рекомендуется настроить 2-4 GB swapfile (ТЗ п.20) как страховку от мгновенного OOM"
    fi
fi

# ------------------------------------------------------------------------------
# 4. Проверка портов
# ------------------------------------------------------------------------------
info "Проверка сетевых портов..."

check_port_free() {
    local port=$1
    if command -v ss >/dev/null 2>&1; then
        if ss -tuln | grep -q ":${port} "; then
            return 1
        fi
    elif command -v netstat >/dev/null 2>&1; then
        if netstat -tuln 2>/dev/null | grep -q ":${port} "; then
            return 1
        fi
    fi
    return 0
}

# ------------------------------------------------------------------------------
# 5. Проверка синтаксиса Docker Compose
# ------------------------------------------------------------------------------
info "Валидация docker-compose.prod.yml..."

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    if docker compose -f docker-compose.prod.yml config -q 2>/dev/null; then
        pass "docker-compose.prod.yml валиден"
    else
        fail "Ошибка в docker-compose.prod.yml! Запустите: docker compose -f docker-compose.prod.yml config"
    fi
fi

# ------------------------------------------------------------------------------
# Итог
# ------------------------------------------------------------------------------
echo "=================================================================="
if [ "${ERRORS}" -eq 0 ]; then
    echo -e "${GREEN}✓ Все критические проверки пройдены successfully!${NC}"
    if [ "${WARNINGS}" -gt 0 ]; then
        echo -e "${YELLOW}  (Обнаружено ${WARNINGS} предупреждений — ознакомьтесь выше)${NC}"
    fi
    echo "Сервер готов к запуску: ./scripts/deploy.sh"
    exit 0
else
    echo -e "${RED}✗ Обнаружено ${ERRORS} критических проблем!${NC}"
    echo "Исправьте указанные ошибки перед запуском деплоя."
    exit 1
fi
